"""Pose job and pose read use cases. Services own transactions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from app.clock import utc_now
from app.config import Settings
from app.core.climber import coverage, person_at_xy, select_climber, vertical_travel
from app.core.edits import apply_edits_to_arrays, confirmed_frames
from app.core.halpe26 import EDGES, N_KEYPOINTS, NAMES
from app.core.pose_checks import flag_frames
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
from app.jobs.queue import JobQueue
from app.learning.feedback import log_feedback
from app.media.frames import FrameReader
from app.pose.estimator import PoseEstimator, make_estimator
from app.pose.store import (
    edits_hash,
    effective_cache_key,
    effective_path,
    pose_path,
    read_effective,
    read_pose,
    tracks_to_arrays,
    write_effective,
    write_pose,
)
from app.repo import jobs as jobs_repo
from app.repo import models as models_repo
from app.repo import pose_edits as pose_edits_repo
from app.storage import LibraryPaths


@dataclass
class PoseRuntime:
    settings: Settings | None = None
    paths: LibraryPaths | None = None
    estimator: PoseEstimator | None = None
    estimators: dict[str, PoseEstimator] = field(default_factory=dict)


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
    _RUNTIME.estimators = {}
    if estimator is not None:
        bound_mode = str(getattr(estimator, "mode", "balanced"))
        _RUNTIME.estimators[bound_mode] = estimator


def current_runtime() -> PoseRuntime:
    return _RUNTIME


def current_estimator(*, mode: str = "balanced") -> PoseEstimator:
    cached = _RUNTIME.estimators.get(mode)
    if cached is not None:
        _RUNTIME.estimator = cached
        return cached
    bound = _RUNTIME.estimator
    if bound is not None and str(getattr(bound, "mode", mode)) == mode:
        _RUNTIME.estimators[mode] = bound
        return bound
    settings = _RUNTIME.settings
    if settings is None:
        raise AppError("pose_not_ready", 500, "The pose estimator is not configured.")
    estimator = make_estimator(
        pose_backend=settings.pose_backend,
        models_dir=settings.models_dir,
        device=settings.device,
        mode=mode,
    )
    _RUNTIME.estimators[mode] = estimator
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
    conn: sqlite3.Connection,
    video_id: str,
    status: str,
    error: str | None = None,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        "UPDATE videos SET pose_status = ?, error = ? WHERE id = ?",
        (status, error, video_id),
    )
    if commit:
        conn.commit()


def _rollback_quiet(conn: sqlite3.Connection) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        return


def _remove_pose_artifacts(dest: Path | None) -> None:
    if dest is None:
        return
    for path in (dest, dest.with_name(dest.name + ".tmp")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _insert_pose_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    video_id: str,
    device_name: object,
    provider: object,
    mode: str,
    det_every: int,
    climber_id: int | None,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pose_runs (
            id, video_id, model_version_id, device, provider, mode, det_every,
            fps_measured, climber_track_id, status, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            run_id,
            video_id,
            str(device_name),
            provider,
            mode,
            det_every,
            climber_id,
            status,
            utc_now(),
        ),
    )


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
    total = n_frames if n_frames and n_frames > 0 else 0
    stride = max(int(det_every), 1)
    for index, frame in frames:
        if ctx is not None:
            ctx.check_cancel()
            seen = index + 1
            denom = total if total > 0 else seen
            ctx.progress(min(1.0, seen / denom), f"Frame {seen} of {denom}")
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
    mode = str(_setting(ctx.conn, "pose_mode", "balanced"))
    estimator = current_estimator(mode=mode)
    settings = _RUNTIME.settings
    fps = float(video.get("proxy_fps") or 30.0)
    n_frames = int(video.get("n_frames") or 0)
    det_every = int(_setting(ctx.conn, "det_every", 5))
    _set_pose_status(ctx.conn, video_id, "running")
    run_id: str | None = None
    dest: Path | None = None
    climber_id: int | None = None
    device_name: object = settings.device if settings else "cpu"
    provider: object = None
    try:
        if frames is None:
            proxy = paths.proxies / f"{video_id}.mp4"
            with FrameReader(proxy) as reader:
                if n_frames > 0:
                    reader.check_count(n_frames)
                else:
                    n_frames = reader.check_count(None)
                    fps = fps or reader.fps or 30.0
                tracks, climber_id = process_frames(
                    reader.iter_frames(),
                    estimator,
                    fps=fps,
                    det_every=det_every,
                    ctx=ctx,
                    n_frames=n_frames or None,
                )
        else:
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
        device_name = getattr(estimator, "device_name", device_name)
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
        ctx.conn.execute("BEGIN")
        _insert_pose_run(
            ctx.conn,
            run_id=run_id,
            video_id=video_id,
            device_name=device_name,
            provider=provider,
            mode=mode,
            det_every=det_every,
            climber_id=climber_id,
            status="done",
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
        _set_pose_status(ctx.conn, video_id, "done", commit=False)
        ctx.conn.commit()
        from app.services.detection import enqueue_detect

        enqueue_detect(ctx.conn, video_id)
        return {"run_id": run_id, "climber_track_id": climber_id, "n_tracks": len(tracks)}
    except Exception as exc:
        _rollback_quiet(ctx.conn)
        _remove_pose_artifacts(dest)
        if run_id is not None:
            _insert_pose_run(
                ctx.conn,
                run_id=run_id,
                video_id=video_id,
                device_name=device_name,
                provider=provider,
                mode=mode,
                det_every=det_every,
                climber_id=climber_id,
                status="failed",
            )
        _set_pose_status(ctx.conn, video_id, "failed", str(exc))
        raise


def _latest_run(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM pose_runs
        WHERE video_id = ? AND status = 'done'
        ORDER BY created_at DESC, rowid DESC
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


def _load_raw_arrays(paths: LibraryPaths, video_id: str, run: dict[str, Any]) -> dict[str, Any]:
    raw = pose_path(paths.pose, video_id, str(run["id"]))
    if not raw.is_file():
        raise AppError("not_found", 404, "The pose file is not here.")
    return read_pose(raw)


def _require_track(conn: sqlite3.Connection, run_id: str, track_id: int) -> None:
    row = conn.execute(
        "SELECT track_id FROM pose_tracks WHERE run_id = ? AND track_id = ?",
        (run_id, int(track_id)),
    ).fetchone()
    if row is None:
        raise AppError("not_found", 404, "The track is not here.")


def _pose_job_active(conn: sqlite3.Connection, video_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM jobs
        WHERE entity_id = ? AND kind = 'pose' AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    return row is not None


def _begin_pose_edit_tx(conn: sqlite3.Connection, video_id: str) -> None:
    """Lock and check the pose job in the same transaction as the write."""
    conn.execute("BEGIN IMMEDIATE")
    if _pose_job_active(conn, video_id):
        conn.rollback()
        raise AppError("pose_busy", 409, "A pose job is running.")


def _enqueue_detect(conn: sqlite3.Connection, queue: JobQueue | None, video_id: str) -> str | None:
    """Re-queue detection after a climber change. D owns the detect job."""
    from app.services.detection import enqueue_detect

    job = enqueue_detect(conn, video_id, queue)
    if job is None:
        return None
    job_id = job.get("id") or job.get("job_id")
    return None if job_id is None else str(job_id)


def _drop_effective(paths: LibraryPaths, video_id: str, run_id: str) -> None:
    dest = effective_path(pose_path(paths.pose, video_id, run_id))
    dest.unlink(missing_ok=True)


def get_effective_track(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
) -> dict[str, Any]:
    """Return pose arrays with climber edits applied.

    Cache key is raw track version + edits hash. A pose re-run writes a new
    NPZ, so this never serves a stale track.
    """
    _video(conn, video_id)
    run = _latest_run(conn, video_id)
    climber_id = run.get("climber_track_id")
    raw = pose_path(paths.pose, video_id, str(run["id"]))
    if not raw.is_file():
        raise AppError("not_found", 404, "The pose file is not here.")
    edits = pose_edits_repo.list_active(conn, video_id)
    key = effective_cache_key(raw, edits, climber_track_id=climber_id)
    cached = read_effective(raw, key)
    if cached is not None:
        cached["climber_track_id"] = climber_id
        return cached
    data = apply_edits_to_arrays(read_pose(raw), edits, climber_id=climber_id)
    write_effective(raw, data, hash_value=key)
    return data


def get_pose_summary(
    conn: sqlite3.Connection, paths: LibraryPaths, video_id: str
) -> dict[str, Any]:
    video = _video(conn, video_id)
    run = _latest_run(conn, video_id)
    tracks = _track_rows(conn, str(run["id"]))
    arrays = _load_raw_arrays(paths, video_id, run)
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
    if effective:
        arrays = get_effective_track(conn, paths, video_id)
    else:
        arrays = _load_raw_arrays(paths, video_id, run)
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
            int(frame): kpt
            for frame, kpt in zip(arrays["frame"][mask], arrays["keypoints"][mask], strict=True)
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
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    _video(conn, video_id)
    _latest_run(conn, video_id)
    arrays = get_effective_track(conn, paths, video_id)
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
    hit_track_id = None
    if x is not None and y is not None:
        hit_track_id = person_at_xy(
            arrays["frame"],
            arrays["track_id"],
            arrays["bbox"],
            int(frame),
            float(x),
            float(y),
        )
    return {"frame": int(frame), "persons": persons, "hit_track_id": hit_track_id}


def _climber_values(
    arrays: dict[str, Any],
    *,
    track_id: int | None,
    frame: int,
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if track_id is None:
        return []
    mask = arrays["track_id"] == int(track_id)
    by_frame = {
        int(frame_i): kpt
        for frame_i, kpt in zip(arrays["frame"][mask], arrays["keypoints"][mask], strict=True)
    }
    row = by_frame.get(int(frame))
    if row is None:
        return []
    wanted = {int(point["kpt"]) for point in points} if points else set(range(N_KEYPOINTS))
    values: list[dict[str, Any]] = []
    for kpt in sorted(wanted):
        if kpt < 0 or kpt >= N_KEYPOINTS:
            continue
        values.append(
            {
                "kpt": kpt,
                "x": round(float(row[kpt, 0]), 3),
                "y": round(float(row[kpt, 1]), 3),
                "score": round(float(row[kpt, 2]), 4),
            }
        )
    return values


def _range_frames(
    arrays: dict[str, Any],
    *,
    track_id: int | None,
    start: int,
    end: int,
) -> list[list[list[float]] | None]:
    frames_out: list[list[list[float]] | None] = []
    if track_id is None:
        return [None] * (end - start + 1)
    mask = arrays["track_id"] == int(track_id)
    by_frame = {
        int(frame_i): kpt
        for frame_i, kpt in zip(arrays["frame"][mask], arrays["keypoints"][mask], strict=True)
    }
    for frame in range(start, end + 1):
        row = by_frame.get(frame)
        frames_out.append(None if row is None else _triplet(row))
    return frames_out


def set_climber(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    queue: JobQueue | None,
    video_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Reassign the climber track. Logs climber.reassign and enqueues detect."""
    _video(conn, video_id)
    run = _latest_run(conn, video_id)
    old_id = run.get("climber_track_id")
    track_id = data.get("track_id")
    if track_id is not None:
        new_id = int(track_id)
        _require_track(conn, str(run["id"]), new_id)
    elif data.get("frame") is not None and data.get("x") is not None and data.get("y") is not None:
        arrays = get_effective_track(conn, paths, video_id)
        hit = person_at_xy(
            arrays["frame"],
            arrays["track_id"],
            arrays["bbox"],
            int(data["frame"]),
            float(data["x"]),
            float(data["y"]),
        )
        if hit is None:
            raise AppError("not_found", 404, "No person is at that point.")
        new_id = int(hit)
    else:
        raise AppError("bad_climber", 400, "Send track_id or frame, x, and y.")
    _begin_pose_edit_tx(conn, video_id)
    try:
        conn.execute(
            "UPDATE pose_runs SET climber_track_id = ? WHERE id = ?",
            (new_id, str(run["id"])),
        )
        conn.execute(
            """
            UPDATE pose_tracks
            SET is_climber = CASE WHEN track_id = ? THEN 1 ELSE 0 END
            WHERE run_id = ?
            """,
            (new_id, str(run["id"])),
        )
        log_feedback(
            conn,
            kind="climber.reassign",
            entity_type="video",
            entity_id=video_id,
            video_id=video_id,
            before={"climber_track_id": old_id},
            after={"climber_track_id": new_id},
            model_version_id=models_repo.active_event_id(conn),
        )
        conn.commit()
    except Exception:
        _rollback_quiet(conn)
        raise
    _drop_effective(paths, video_id, str(run["id"]))
    job_id = _enqueue_detect(conn, queue, video_id)
    return {"climber_track_id": new_id, "job_id": job_id}


def list_edits(
    conn: sqlite3.Connection,
    video_id: str,
    *,
    start: int | None = None,
    end: int | None = None,
) -> dict[str, Any]:
    _video(conn, video_id)
    _latest_run(conn, video_id)
    items = pose_edits_repo.list_active(conn, video_id, start=start, end=end)
    return {
        "items": [
            {
                "id": str(item["id"]),
                "kind": str(item["kind"]),
                "frame": int(item["frame"]),
                "range_start": item.get("range_start"),
                "range_end": item.get("range_end"),
                "points": item.get("points") or [],
                "created_at": item.get("created_at"),
            }
            for item in items
        ],
        "total": len(items),
    }


def create_edit(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    video = _video(conn, video_id)
    run = _latest_run(conn, video_id)
    kind = str(data["kind"])
    frame = int(data["frame"])
    n_frames = int(video.get("n_frames") or 0)
    raw_range = data.get("range")
    if raw_range is None:
        start, end = frame, frame
    else:
        if len(raw_range) != 2:
            raise AppError("bad_range", 400, "range must be [start, end].")
        start, end = int(raw_range[0]), int(raw_range[1])
    if end < start:
        raise AppError("bad_range", 400, "end must be greater than or equal to start.")
    if start < 0 or (n_frames and end >= n_frames):
        raise AppError("bad_range", 400, "The range is outside the proxy frames.")
    if frame < start or frame > end:
        raise AppError("bad_range", 400, "frame must lie inside the range.")
    points = list(data.get("points") or [])
    if kind == "move" and not points:
        raise AppError("bad_edit", 400, "A move edit needs points.")
    before_arrays = get_effective_track(conn, paths, video_id)
    before_values = _climber_values(
        before_arrays,
        track_id=run.get("climber_track_id"),
        frame=frame,
        points=points,
    )
    _begin_pose_edit_tx(conn, video_id)
    try:
        row = pose_edits_repo.insert_edit(
            conn,
            video_id=video_id,
            kind=kind,
            frame=frame,
            range_start=start,
            range_end=end,
            points=points,
        )
        feedback_kind = "pose.confirm" if kind == "confirm" else "pose.edit"
        after: dict[str, Any] = {
            "edit_id": str(row["id"]),
            "kind": kind,
            "frame": frame,
            "range_start": start,
            "range_end": end,
            "points": [
                {
                    "kpt": int(point["kpt"]),
                    "x": None if point.get("x") is None else float(point["x"]),
                    "y": None if point.get("y") is None else float(point["y"]),
                }
                for point in points
            ],
        }
        log_feedback(
            conn,
            kind=feedback_kind,
            entity_type="pose_edit",
            entity_id=str(row["id"]),
            video_id=video_id,
            before={"frame": frame, "values": before_values},
            after=after,
            model_version_id=run.get("model_version_id"),
        )
        conn.commit()
    except Exception:
        _rollback_quiet(conn)
        raise
    _drop_effective(paths, video_id, str(run["id"]))
    arrays = get_effective_track(conn, paths, video_id)
    return {
        "edit_id": str(row["id"]),
        "start": start,
        "end": end,
        "frames": _range_frames(
            arrays,
            track_id=run.get("climber_track_id"),
            start=start,
            end=end,
        ),
    }


def delete_edit(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    video_id: str,
    edit_id: str,
) -> None:
    _video(conn, video_id)
    run = _latest_run(conn, video_id)
    _begin_pose_edit_tx(conn, video_id)
    try:
        row = pose_edits_repo.get_edit(conn, video_id, edit_id)
        if row is None or row.get("undone_at") is not None:
            conn.rollback()
            raise AppError("not_found", 404, "The edit is not here.")
        pose_edits_repo.undo_edit(conn, video_id, edit_id)
        conn.commit()
    except AppError:
        raise
    except Exception:
        _rollback_quiet(conn)
        raise
    _drop_effective(paths, video_id, str(run["id"]))
    get_effective_track(conn, paths, video_id)


def review_queue(conn: sqlite3.Connection, paths: LibraryPaths, video_id: str) -> dict[str, Any]:
    _video(conn, video_id)
    run = _latest_run(conn, video_id)
    arrays = get_effective_track(conn, paths, video_id)
    climber_id = run.get("climber_track_id")
    edits = pose_edits_repo.list_active(conn, video_id)
    confirmed = confirmed_frames(edits)
    if climber_id is None:
        return {"items": [], "total": 0}
    mask = arrays["track_id"] == int(climber_id)
    flags = flag_frames(
        arrays["frame"][mask],
        arrays["keypoints"][mask],
        confirmed=confirmed,
    )
    return {"items": flags, "total": len(flags)}
