"""Manual attempts, ratings, and the cut job."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.clock import utc_now
from app.errors import AppError
from app.jobs.context import JobContext
from app.jobs.queue import JobQueue
from app.learning.feedback import log_feedback
from app.media.tool import MediaError, MediaTool
from app.repo import attempts as attempts_repo
from app.repo import trash as trash_repo
from app.repo import videos as videos_repo
from app.repo.util import new_id
from app.storage import LibraryPaths, move_into


def list_attempts(
    conn: sqlite3.Connection,
    *,
    boulder_id: str | None,
    video_id: str | None,
    outcome: str | None,
    rated: bool | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total = attempts_repo.list_attempts(
        conn,
        boulder_id=boulder_id,
        video_id=video_id,
        outcome=outcome,
        rated=rated,
        limit=limit,
        offset=offset,
    )
    enriched = [_with_video_media(conn, row) for row in items]
    return {"items": enriched, "total": total}


def get_attempt(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any]:
    row = attempts_repo.get(conn, attempt_id)
    if row is None:
        raise AppError("not_found", 404, "The attempt is not here.")
    return _with_video_media(conn, row)


def create_attempt(
    conn: sqlite3.Connection,
    queue: JobQueue,
    video_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    video = _require_ready_video(conn, video_id)
    start = int(data["start_frame"])
    end = int(data["end_frame"])
    _validate_span(start, end, int(video["n_frames"]))
    from app.db import immediate
    from app.repo import models as models_repo

    with immediate(conn):
        attempt = attempts_repo.insert(
            conn,
            video_id=video_id,
            boulder_id=video.get("boulder_id"),
            start_frame=start,
            end_frame=end,
            outcome=str(data["outcome"]),
            commit=False,
        )
        log_feedback(
            conn,
            kind="cut.missed",
            entity_type="attempt",
            entity_id=str(attempt["id"]),
            video_id=video_id,
            before={"proposal_id": None},
            after={"start_frame": start, "end_frame": end, "outcome": data["outcome"]},
            model_version_id=models_repo.active_event_id(conn),
        )
    job = request_cut(conn, queue, str(attempt["id"]))
    row = _with_video_media(conn, attempt)
    row["job_id"] = job["id"] if job else None
    return row


def patch_attempt(
    conn: sqlite3.Connection,
    queue: JobQueue,
    attempt_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    attempt = attempts_repo.get(conn, attempt_id)
    if attempt is None:
        raise AppError("not_found", 404, "The attempt is not here.")
    video = videos_repo.get(conn, str(attempt["video_id"]))
    if video is None:
        raise AppError("not_found", 404, "The video is not here.")
    updates: dict[str, Any] = {}
    start = int(fields["start_frame"]) if "start_frame" in fields else int(attempt["start_frame"])
    end = int(fields["end_frame"]) if "end_frame" in fields else int(attempt["end_frame"])
    frames_changed = "start_frame" in fields or "end_frame" in fields
    if frames_changed:
        n_frames = int(video["n_frames"] or 0)
        _validate_span(start, end, n_frames)
        updates["start_frame"] = start
        updates["end_frame"] = end
        updates["clip_version"] = int(attempt["clip_version"]) + 1
        updates["clip_status"] = "pending"
        log_feedback(
            conn,
            kind="cut.adjust",
            entity_type="attempt",
            entity_id=attempt_id,
            video_id=str(attempt["video_id"]),
            before={"start_frame": attempt["start_frame"], "end_frame": attempt["end_frame"]},
            after={"start_frame": start, "end_frame": end},
        )
    if "outcome" in fields and fields["outcome"] != attempt["outcome"]:
        updates["outcome"] = fields["outcome"]
        log_feedback(
            conn,
            kind="outcome.correct",
            entity_type="attempt",
            entity_id=attempt_id,
            video_id=str(attempt["video_id"]),
            before={"outcome": attempt["outcome"]},
            after={"outcome": fields["outcome"]},
        )
    ratings_touched = False
    for key in ("proximity", "exertion", "notes"):
        if key in fields:
            updates[key] = fields[key]
            if key in {"proximity", "exertion"}:
                ratings_touched = True
    if ratings_touched:
        updates["rated_at"] = utc_now()
    row = attempts_repo.update(conn, attempt_id, updates) or attempt
    job_id = None
    if frames_changed:
        job = request_cut(conn, queue, attempt_id)
        job_id = job["id"] if job else None
    out = _with_video_media(conn, row)
    out["job_id"] = job_id
    return out


def delete_attempt(conn: sqlite3.Connection, paths: LibraryPaths, attempt_id: str) -> None:
    attempt = attempts_repo.get(conn, attempt_id)
    if attempt is None:
        raise AppError("not_found", 404, "The attempt is not here.")
    trash_id = new_id()
    trash_dir = paths.trash_item_dir(trash_id)
    trash_dir.mkdir(parents=True, exist_ok=True)
    clip = paths.clip_path(attempt_id, int(attempt["clip_version"]))
    move_into(clip, trash_dir / clip.name)
    trash_repo.insert(
        conn,
        kind="attempt",
        entity_id=attempt_id,
        payload=json.dumps({"row": dict(attempt)}),
        path=str(trash_dir.relative_to(paths.root)),
        trash_id=trash_id,
    )
    attempts_repo.soft_delete(conn, attempt_id)
    log_feedback(
        conn,
        kind="cut.delete",
        entity_type="attempt",
        entity_id=attempt_id,
        video_id=str(attempt["video_id"]),
        before={"start_frame": attempt["start_frame"], "end_frame": attempt["end_frame"]},
    )


def resolve_clip(conn: sqlite3.Connection, paths: LibraryPaths, attempt_id: str) -> tuple[Any, ...]:
    attempt = attempts_repo.get(conn, attempt_id)
    if attempt is None:
        raise AppError("not_found", 404, "The attempt is not here.")
    path = paths.clip_path(attempt_id, int(attempt["clip_version"]))
    if not path.is_file():
        raise AppError("not_found", 404, "The clip is not here.")
    return path, attempt


def extract_frame_bytes(
    conn: sqlite3.Connection,
    paths: LibraryPaths,
    media: MediaTool,
    video_id: str,
    frame: int,
    source: str,
) -> bytes:
    from app.services.library import resolve_video_file

    if source not in {"proxy", "original"}:
        raise AppError("bad_source", 400, "source must be proxy or original.")
    video = videos_repo.get(conn, video_id)
    if video is None:
        raise AppError("not_found", 404, "The video is not here.")
    path = resolve_video_file(conn, paths, video_id, source)
    index = int(frame)
    if index < 0:
        raise AppError("bad_frame", 400, "n must be 0 or greater.")
    if source == "original":
        src_fps = float(video.get("src_fps") or video.get("proxy_fps") or 30)
        proxy_fps = float(video.get("proxy_fps") or src_fps or 30)
        index = int(round(index * src_fps / proxy_fps))
    try:
        return media.extract_frame(path, index)
    except MediaError as exc:
        raise AppError("no_frame", 404, "The frame is not in this file.") from exc


def make_cut_handler(paths: LibraryPaths, media: MediaTool) -> Any:
    def handle_cut(ctx: JobContext) -> None:
        from app.repo import jobs as jobs_repo

        job = jobs_repo.get_job(ctx.conn, ctx.job_id)
        if job is None or not job.get("entity_id"):
            return
        attempt_id = str(job["entity_id"])
        attempt = attempts_repo.get(ctx.conn, attempt_id, include_deleted=True)
        if attempt is None:
            raise AppError("not_found", 404, "The attempt is not here.")
        video = videos_repo.get(ctx.conn, str(attempt["video_id"]), include_deleted=True)
        if video is None:
            raise AppError("not_found", 404, "The video is not here.")
        fps = float(video.get("proxy_fps") or video.get("src_fps") or 30)
        start_s = int(attempt["start_frame"]) / fps
        end_s = (int(attempt["end_frame"]) + 1) / fps
        src = paths.original_path(str(video["id"]), str(video["original_ext"]))
        dest = paths.clip_path(attempt_id, int(attempt["clip_version"]))
        attempts_repo.update(ctx.conn, attempt_id, {"clip_status": "running"})
        ctx.check_cancel()
        ctx.progress(0.2, "Cut clip")
        try:
            media.cut_clip(src, dest, start_s, end_s)
        except MediaError as exc:
            attempts_repo.update(ctx.conn, attempt_id, {"clip_status": "failed"})
            raise AppError("cut_failed", 500, exc.message) from exc
        attempts_repo.update(ctx.conn, attempt_id, {"clip_status": "done"})
        ctx.progress(1.0, "Done")

    return handle_cut


def _require_ready_video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    video = videos_repo.get(conn, video_id)
    if video is None:
        raise AppError("not_found", 404, "The video is not here.")
    if video["ingest_status"] != "done" or video.get("n_frames") is None:
        raise AppError("ingest_pending", 409, "Wait for ingest to finish.")
    return video


def _validate_span(start: int, end: int, n_frames: int) -> None:
    if start < 0 or end < 0 or end <= start:
        raise AppError("bad_span", 400, "end_frame must be greater than start_frame.")
    if n_frames and end >= n_frames:
        raise AppError("bad_span", 400, "The frames are outside the video.")


def request_cut(
    conn: sqlite3.Connection, queue: JobQueue, attempt_id: str
) -> dict[str, Any] | None:
    try:
        return queue.enqueue("cut", entity_type="attempt", entity_id=attempt_id)
    except sqlite3.IntegrityError:
        from app.repo import jobs as jobs_repo

        for row in jobs_repo.list_jobs(conn, "active"):
            if row.get("kind") == "cut" and row.get("entity_id") == attempt_id:
                return row
        return None


def _with_video_media(conn: sqlite3.Connection, attempt: dict[str, Any]) -> dict[str, Any]:
    video = videos_repo.get(conn, str(attempt["video_id"]), include_deleted=True)
    fps = None
    if video is not None:
        fps = video.get("proxy_fps") or video.get("src_fps")
    out = dict(attempt)
    out["fps"] = fps
    return out
