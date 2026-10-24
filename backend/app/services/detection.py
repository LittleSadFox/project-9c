"""Detect job: floor line, events, and attempt proposals."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import numpy as np

from app.core.cuts import build_proposals
from app.core.events import detect_events, thresholds_from_settings
from app.core.halpe26 import N_KEYPOINTS
from app.core.scene import auto_floor_line
from app.db import immediate
from app.errors import AppError
from app.jobs.context import JobContext
from app.jobs.queue import JobQueue
from app.pose.store import pose_path, read_pose
from app.repo import events as events_repo
from app.repo import jobs as jobs_repo
from app.repo import models as models_repo
from app.repo import proposals as proposals_repo
from app.repo import scene as scene_repo
from app.repo import settings as settings_repo
from app.repo import videos as videos_repo
from app.repo.util import new_id
from app.storage import LibraryPaths


def _require_video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = videos_repo.get(conn, video_id)
    if row is None:
        raise AppError("not_found", 404, "The video is not here.")
    return row


def enqueue_detect(
    conn: sqlite3.Connection,
    video_id: str,
    queue: JobQueue | None = None,
) -> dict[str, Any] | None:
    """Queue a compute-lane detect job. No-op for a reviewed video."""
    _require_video(conn, video_id)
    with immediate(conn):
        row = conn.execute(
            "SELECT review_status FROM videos WHERE id = ? AND deleted_at IS NULL",
            (video_id,),
        ).fetchone()
        if row is None:
            raise AppError("not_found", 404, "The video is not here.")
        if str(row["review_status"]) == "reviewed":
            return None
        existing = conn.execute(
            """
            SELECT * FROM jobs
            WHERE kind = 'detect' AND entity_id = ? AND status IN ('queued', 'running')
            """,
            (video_id,),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        job_id = new_id()
        job = jobs_repo.insert_job(
            conn,
            job_id=job_id,
            kind="detect",
            lane="compute",
            entity_type="video",
            entity_id=video_id,
        )
        videos_repo.update(conn, video_id, {"detect_status": "queued", "error": None}, commit=False)
    if queue is not None:
        queue.notify()
    return job


def load_raw_climber_track(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video: dict[str, Any],
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """Read the Phase 1 B raw climber track. E later switches this to get_effective_track."""
    video_id = str(video["id"])
    run = conn.execute(
        """
        SELECT * FROM pose_runs
        WHERE video_id = ? AND status = 'done'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    if run is None:
        raise AppError("pose_pending", 409, "Wait for pose to finish.")
    run_d = dict(run)
    climber_id = run_d.get("climber_track_id")
    if climber_id is None:
        n = int(video.get("n_frames") or 0)
        empty_k = np.zeros((n, N_KEYPOINTS, 2), dtype=np.float32)
        empty_s = np.zeros((n, N_KEYPOINTS), dtype=np.float32)
        return run_d, empty_k, empty_s
    track = conn.execute(
        "SELECT track_id FROM pose_tracks WHERE run_id = ? AND track_id = ?",
        (run_d["id"], int(climber_id)),
    ).fetchone()
    if track is None:
        raise AppError("not_found", 404, "The climber track is not here.")
    dest = pose_path(paths.pose, video_id, str(run_d["id"]))
    if not dest.is_file():
        raise AppError("not_found", 404, "The pose file is not here.")
    arrays = read_pose(dest)
    n_frames = int(video.get("n_frames") or arrays.get("n_frames") or 0)
    keypoints = np.zeros((n_frames, N_KEYPOINTS, 2), dtype=np.float32)
    scores = np.zeros((n_frames, N_KEYPOINTS), dtype=np.float32)
    mask = arrays["track_id"] == int(climber_id)
    frames = arrays["frame"][mask]
    rows = arrays["keypoints"][mask]
    for frame, row in zip(frames, rows, strict=False):
        index = int(frame)
        if 0 <= index < n_frames:
            keypoints[index] = row[:, :2]
            if row.shape[-1] >= 3:
                scores[index] = row[:, 2]
            else:
                scores[index] = 1.0
    return run_d, keypoints, scores


def _decode_json(raw: object) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    return json.loads(raw)


def _encode_json(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def ensure_scene_marks(
    conn: sqlite3.Connection,
    video: dict[str, Any],
    keypoints: np.ndarray,
    scores: np.ndarray,
    *,
    fps: float,
) -> dict[str, Any]:
    video_id = str(video["id"])
    row = scene_repo.get(conn, video_id)
    if row is not None and row.get("floor_line"):
        return row
    width = float(video.get("proxy_width") or 1280)
    line = auto_floor_line(
        keypoints,
        scores,
        fps=fps,
        frame_width=width,
    )
    return scene_repo.upsert(
        conn,
        video_id=video_id,
        floor_line=_encode_json(line.tolist()),
        top_zone=row.get("top_zone") if row else None,
        start_holds=row.get("start_holds") if row else None,
        ref_points=row.get("ref_points") if row else None,
        source="auto" if row is None or row.get("source") == "auto" else str(row["source"]),
    )


def run_detect_for_video(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Write events and proposals for one video. Caller holds no transaction yet."""
    video = _require_video(conn, video_id)
    if str(video.get("review_status")) == "reviewed":
        videos_repo.update(conn, video_id, {"detect_status": "done"})
        return {"proposals": 0, "events": 0, "skipped": "reviewed"}
    fps = float(video.get("proxy_fps") or 30.0)
    n_frames = int(video.get("n_frames") or 0)
    run, keypoints, scores = load_raw_climber_track(conn, paths, video)
    prefs = settings_repo.get_all(conn)
    thresholds = thresholds_from_settings(prefs)
    scene = ensure_scene_marks(conn, video, keypoints, scores, fps=fps)
    floor = _decode_json(scene.get("floor_line"))
    if floor is None:
        width = float(video.get("proxy_width") or 1280)
        floor = auto_floor_line(keypoints, scores, fps=fps, frame_width=width)
    top_zone = _decode_json(scene.get("top_zone"))
    events, spans = detect_events(
        keypoints,
        scores,
        floor,
        fps=fps,
        top_zone=top_zone,
        thresholds=thresholds,
    )
    proposals = build_proposals(
        spans,
        fps=fps,
        n_frames=n_frames or int(keypoints.shape[0]),
        pre_roll_s=float(prefs.get("pre_roll_s") or 1.5),
        post_roll_s=float(prefs.get("post_roll_s") or 1.0),
    )
    model_id = models_repo.active_event_id(conn)
    detect_run = run_id or str(run.get("id") or new_id())
    with immediate(conn):
        fresh = conn.execute(
            "SELECT review_status FROM videos WHERE id = ? AND deleted_at IS NULL",
            (video_id,),
        ).fetchone()
        if fresh is None:
            raise AppError("not_found", 404, "The video is not here.")
        if str(fresh["review_status"]) == "reviewed":
            videos_repo.update(conn, video_id, {"detect_status": "done"}, commit=False)
            return {"proposals": 0, "events": 0, "skipped": "reviewed"}
        events_repo.delete_rule_for_video(conn, video_id)
        proposals_repo.supersede_pending(conn, video_id)
        for event in events:
            events_repo.insert(
                conn,
                video_id=video_id,
                run_id=detect_run,
                frame=event.frame,
                kind=event.kind,
                confidence=event.confidence,
                source=event.source,
                model_version_id=model_id,
            )
        for proposal in proposals:
            proposals_repo.insert(
                conn,
                video_id=video_id,
                start_frame=proposal.start_frame,
                end_frame=proposal.end_frame,
                outcome_guess=proposal.outcome_guess,
                confidence=proposal.confidence,
                model_version_id=model_id,
            )
        videos_repo.update(conn, video_id, {"detect_status": "done", "error": None}, commit=False)
    return {"proposals": len(proposals), "events": len(events), "run_id": detect_run}


def handle_detect_job(ctx: JobContext) -> dict[str, Any]:
    job = jobs_repo.get_job(ctx.conn, ctx.job_id)
    if job is None or not job.get("entity_id"):
        raise RuntimeError("The detect job has no video id.")
    video_id = str(job["entity_id"])
    from app.services.pose_service import _paths_from_conn

    paths = _paths_from_conn(ctx.conn)
    videos_repo.update(ctx.conn, video_id, {"detect_status": "running", "error": None})
    ctx.progress(0.1, "Detect events")
    try:
        result = run_detect_for_video(ctx.conn, paths, video_id, run_id=ctx.job_id)
        ctx.progress(1.0, "Done")
        return result
    except Exception as exc:
        videos_repo.update(
            ctx.conn,
            video_id,
            {"detect_status": "failed", "error": str(exc)},
        )
        raise
