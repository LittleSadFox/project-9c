"""Pose job and pose read use cases. Services own transactions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.clock import utc_now
from app.config import Settings
from app.core.climber import coverage, select_climber, vertical_travel
from app.core.halpe26 import EDGES, N_KEYPOINTS, NAMES
from app.core.smoothing import smooth_track
from app.core.tracking import (
    Track,
    Tracker,
    boxes_from_people,
    empty_boxes,
    empty_keypoints,
    empty_scores,
)
from app.errors import AppError
from app.jobs.context import JobContext
from app.media.frames import FrameReader
from app.pose.estimator import PoseEstimator, make_estimator
from app.pose.store import (
    edits_hash,
    pose_path,
    read_effective,
    read_pose,
    tracks_to_arrays,
    write_pose,
)
from app.repo import jobs as jobs_repo
from app.storage import LibraryPaths


@dataclass
class PoseRuntime:
    settings: Settings | None = None
    paths: LibraryPaths | None = None
    estimator: PoseEstimator | None = None


_RUNTIME = PoseRuntime()


def bind_pose_runtime(
    *,
    settings: Settings | None,
    paths: LibraryPaths | None,
    estimator: PoseEstimator | None,
) -> None:
    """Store app dependencies for the compute-lane pose handler."""
    _RUNTIME.settings = settings
    _RUNTIME.paths = paths
    _RUNTIME.estimator = estimator


def current_runtime() -> PoseRuntime:
    return _RUNTIME


def current_estimator() -> PoseEstimator:
    if _RUNTIME.estimator is not None:
        return _RUNTIME.estimator
    settings = _RUNTIME.settings
    if settings is None:
        raise AppError("pose_not_ready", 500, "The pose estimator is not configured.")
    estimator = make_estimator(
        pose_backend=settings.pose_backend,
        models_dir=settings.models_dir,
        device=settings.device,
    )
    _RUNTIME.estimator = estimator
    return estimator


def _paths_from_conn(conn: sqlite3.Connection) -> LibraryPaths:
    if _RUNTIME.paths is not None:
        return _RUNTIME.paths
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        raise AppError("pose_not_ready", 500, "The library database is not open.")
    file = Path(row["file"] if isinstance(row, sqlite3.Row) else row[2])
    return LibraryPaths(file.parent)


def _video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM videos WHERE id = ? AND deleted_at IS NULL",
        (video_id,),
    ).fetchone()
    if row is None:
        raise AppError("not_found", 404, "The video is not here.")
    return dict(row)


def _setting(conn: sqlite3.Connection, key: str, default: Any) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(str(row["value"]))


def _set_pose_status(
    conn: sqlite3.Connection, video_id: str, status: str, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE videos SET pose_status = ?, error = ? WHERE id = ?",
        (status, error, video_id),
    )
    conn.commit()


def process_frames(
    frames: Iterable[tuple[int, object]],
    estimator: PoseEstimator,
    *,
    fps: float,
    det_every: int = 5,
    ctx: JobContext | None = None,
    n_frames: int | None = None,
) -> tuple[list[Track], int | None]:
    """Detect, pose, track, pick the climber, and smooth that track."""
    tracker = Tracker()
    last_boxes: np.ndarray | None = None
    frame_list = list(frames)
    total = n_frames if n_frames and n_frames > 0 else max(len(frame_list), 1)
    stride = max(int(det_every), 1)
    for index, frame in frame_list:
        if ctx is not None:
            ctx.check_cancel()
            ctx.progress((index + 1) / total, f"Frame {index + 1} of {total}")
        run_detector = index % stride == 0 or last_boxes is None
        if run_detector:
            boxes = np.asarray(estimator.detect(frame, frame_index=index), dtype=np.float32)
            if boxes.size == 0 or boxes.reshape(-1, 4).shape[0] == 0:
                last_boxes = None
                tracker.update(index, empty_boxes(), empty_keypoints(), empty_scores())
                continue
            boxes = boxes.reshape(-1, 4)
        else:
            assert last_boxes is not None
            boxes = last_boxes
        result = estimator.pose(frame, boxes, frame_index=index)
        keypoints = np.asarray(result["keypoints"], dtype=np.float32)
        scores = np.asarray(result["scores"], dtype=np.float32)
        used_boxes = np.asarray(result.get("boxes", boxes), dtype=np.float32).reshape(-1, 4)
        if keypoints.size == 0:
            last_boxes = None
            tracker.update(index, empty_boxes(), empty_keypoints(), empty_scores())
            continue
        last_boxes = boxes_from_people(keypoints, scores, fallback=used_boxes)
        tracker.update(index, used_boxes, keypoints, scores)

    tracks = tracker.finalize()
    climber_id = select_climber(tracks)
    if climber_id is not None and fps > 0:
        for track in tracks:
            if track.track_id != climber_id or len(track.keypoints) < 2:
                continue
            kpts = np.stack(track.keypoints)
            scores = np.stack(track.scores)
            smooth_k, smooth_s = smooth_track(kpts, scores, fps)
            track.keypoints = [smooth_k[i] for i in range(smooth_k.shape[0])]
            track.scores = [smooth_s[i] for i in range(smooth_s.shape[0])]
    return tracks, climber_id


def handle_pose_job(
    ctx: JobContext, frames: Iterable[tuple[int, object]] | None = None
) -> dict[str, Any]:
    """Compute-lane pose handler. A's ingest enqueues kind=pose."""
    job = jobs_repo.get_job(ctx.conn, ctx.job_id)
    if job is None or not job.get("entity_id"):
        raise RuntimeError("The pose job has no video id.")
    video_id = str(job["entity_id"])
    paths = _paths_from_conn(ctx.conn)
    video = _video(ctx.conn, video_id)
    estimator = current_estimator()
    settings = _RUNTIME.settings
    fps = float(video.get("proxy_fps") or 30.0)
    n_frames = int(video.get("n_frames") or 0)
    det_every = int(_setting(ctx.conn, "det_every", 5))
    mode = str(_setting(ctx.conn, "pose_mode", "balanced"))
    _set_pose_status(ctx.conn, video_id, "running")
    try:
        if frames is None:
            proxy = paths.proxies / f"{video_id}.mp4"
            with FrameReader(proxy) as reader:
                if n_frames > 0:
                    reader.check_count(n_frames)
                else:
                    n_frames = reader.check_count(None)
                    fps = fps or reader.fps or 30.0
                frames = list(reader.iter_frames())
        tracks, climber_id = process_frames(
            frames,
            estimator,
            fps=fps,
            det_every=det_every,
            ctx=ctx,
            n_frames=n_frames or None,
        )
        run_id = str(uuid4())
        arrays = tracks_to_arrays(tracks)
        device_name = getattr(estimator, "device_name", settings.device if settings else "cpu")
        provider = getattr(estimator, "provider", None)
        model_version = getattr(estimator, "model_version", None)
        dest = pose_path(paths.pose, video_id, run_id)
        write_pose(
            dest,
            frame=arrays["frame"],
            track_id=arrays["track_id"],
            keypoints=arrays["keypoints"],
            bbox=arrays["bbox"],
            meta={
                "n_frames": n_frames,
                "fps": fps,
                "climber_track_id": climber_id,
                "run_id": run_id,
                "provider": provider,
                "model_version": model_version,
                "det_every": det_every,
                "mode": mode,
                "device": device_name,
                "edits_hash": edits_hash([]),
            },
        )
        now = utc_now()
        ctx.conn.execute(
            """
            INSERT INTO pose_runs (
                id, video_id, model_version_id, device, provider, mode, det_every,
                fps_measured, climber_track_id, status, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, 'done', ?)
            """,
            (run_id, video_id, str(device_name), provider, mode, det_every, climber_id, now),
        )
        for track in tracks:
            ctx.conn.execute(
                """
                INSERT INTO pose_tracks (
                    id, run_id, track_id, first_frame, last_frame, coverage,
                    vertical_travel, is_climber
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    track.track_id,
                    track.first_frame,
                    track.last_frame,
                    coverage(track),
                    vertical_travel(track),
                    1 if track.track_id == climber_id else 0,
                ),
            )
        _set_pose_status(ctx.conn, video_id, "done")
        return {"run_id": run_id, "climber_track_id": climber_id, "n_tracks": len(tracks)}
    except Exception as exc:
        _set_pose_status(ctx.conn, video_id, "failed", str(exc))
        raise


def _latest_run(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM pose_runs
        WHERE video_id = ? AND status = 'done'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    if row is None:
        raise AppError("not_found", 404, "Pose is not ready.")
    return dict(row)


def _track_rows(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT track_id, first_frame, last_frame, coverage, vertical_travel, is_climber
        FROM pose_tracks
        WHERE run_id = ?
        ORDER BY track_id
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_run_arrays(
    paths: LibraryPaths, video_id: str, run: dict[str, Any], *, effective: bool
) -> dict[str, Any]:
    raw = pose_path(paths.pose, video_id, str(run["id"]))
    if not raw.is_file():
        raise AppError("not_found", 404, "The pose file is not here.")
    if effective:
        cached = read_effective(raw, edits_hash([]))
        if cached is not None:
            return cached
    return read_pose(raw)


def get_pose_summary(
    conn: sqlite3.Connection, paths: LibraryPaths, video_id: str
) -> dict[str, Any]:
    video = _video(conn, video_id)
    run = _latest_run(conn, video_id)
    tracks = _track_rows(conn, str(run["id"]))
    arrays = _load_run_arrays(paths, video_id, run, effective=False)
    fps = float(video.get("proxy_fps") or arrays.get("fps") or 0.0)
    n_frames = int(video.get("n_frames") or arrays.get("n_frames") or 0)
    return {
        "run_id": str(run["id"]),
        "model_version": arrays.get("model_version") or None,
        "provider": run.get("provider") or arrays.get("provider") or None,
        "fps": fps,
        "n_frames": n_frames,
        "keypoint_names": list(NAMES),
        "edges": [list(edge) for edge in EDGES],
        "climber_track_id": run.get("climber_track_id"),
        "tracks": [
            {
                "track_id": int(row["track_id"]),
                "first_frame": int(row["first_frame"]),
                "last_frame": int(row["last_frame"]),
                "coverage": row.get("coverage"),
                "vertical_travel": row.get("vertical_travel"),
            }
            for row in tracks
        ],
    }


def _triplet(values: np.ndarray) -> list[list[float]]:
    out: list[list[float]] = []
    for item in values.reshape(N_KEYPOINTS, 3):
        out.append([round(float(item[0]), 3), round(float(item[1]), 3), round(float(item[2]), 4)])
    return out


def get_keypoints(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
    *,
    track: str = "climber",
    start: int | None = None,
    end: int | None = None,
    effective: bool = True,
) -> dict[str, Any]:
    video = _video(conn, video_id)
    run = _latest_run(conn, video_id)
    arrays = _load_run_arrays(paths, video_id, run, effective=effective)
    fps = float(video.get("proxy_fps") or arrays.get("fps") or 0.0)
    n_frames = int(video.get("n_frames") or arrays.get("n_frames") or 0)
    climber_id = run.get("climber_track_id")
    if track in {None, "", "climber"}:
        track_id = climber_id
    else:
        try:
            track_id = int(track)
        except ValueError as exc:
            raise AppError("bad_track", 400, "track must be climber or a track id.") from exc
    start_i = 0 if start is None else int(start)
    end_i = max(n_frames - 1, 0) if end is None else int(end)
    if end_i < start_i:
        raise AppError("bad_range", 400, "end must be greater than or equal to start.")
    frames_out: list[list[list[float]] | None] = []
    if track_id is None:
        frames_out = [None] * (end_i - start_i + 1)
    else:
        mask = arrays["track_id"] == int(track_id)
        by_frame = {
            int(frame): arrays["keypoints"][index]
            for index, frame in enumerate(arrays["frame"][mask])
        }
        for frame in range(start_i, end_i + 1):
            row = by_frame.get(frame)
            frames_out.append(None if row is None else _triplet(row))
    return {
        "run_id": str(run["id"]),
        "fps": fps,
        "start": start_i,
        "end": end_i,
        "frames": frames_out,
    }


def get_persons(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
    *,
    frame: int,
) -> dict[str, Any]:
    _video(conn, video_id)
    run = _latest_run(conn, video_id)
    arrays = _load_run_arrays(paths, video_id, run, effective=True)
    persons: list[dict[str, Any]] = []
    for index, stored_frame in enumerate(arrays["frame"]):
        if int(stored_frame) != int(frame):
            continue
        persons.append(
            {
                "track_id": int(arrays["track_id"][index]),
                "bbox": [round(float(v), 3) for v in arrays["bbox"][index]],
                "keypoints": _triplet(arrays["keypoints"][index]),
            }
        )
    return {"frame": int(frame), "persons": persons}
