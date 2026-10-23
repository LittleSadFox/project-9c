"""Streaming upload, ingest job, and reprocess."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.clock import utc_now
from app.config import Settings
from app.errors import AppError
from app.jobs.context import JobContext
from app.jobs.queue import JobQueue
from app.media.tool import MediaError, MediaTool
from app.repo import boulders as boulders_repo
from app.repo import sessions as sessions_repo
from app.repo import settings as settings_repo
from app.repo import videos as videos_repo
from app.storage import LibraryPaths, move_into, safe_ext

STAGE_JOB = {"proxy": "ingest", "pose": "pose", "detect": "detect"}


def stream_to_file(
    chunks: Iterator[bytes], dest: Path, max_bytes: int
) -> tuple[str, int]:
    """Write chunks to dest. Bound memory to one chunk. Return sha256 and size."""
    hasher = hashlib.sha256()
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as out:
            for chunk in chunks:
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise AppError("too_large", 413, "The file is too large.")
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise AppError("not_video", 415, "This file is not a video.")
    return hasher.hexdigest(), written


async def stream_to_file_async(
    chunks: AsyncIterator[bytes], dest: Path, max_bytes: int
) -> tuple[str, int]:
    hasher = hashlib.sha256()
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as out:
            async for chunk in chunks:
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise AppError("too_large", 413, "The file is too large.")
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise AppError("not_video", 415, "This file is not a video.")
    return hasher.hexdigest(), written


def parse_filename(filename: str) -> tuple[str, str]:
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise AppError("bad_filename", 400, "The filename is missing.")
    suffix = Path(name).suffix
    ext = safe_ext(suffix) if suffix else "mp4"
    return name, ext


def content_length(raw: str | None, max_bytes: int) -> int:
    if raw is None or raw == "":
        raise AppError("missing_length", 400, "Content-Length is required.")
    try:
        size = int(raw)
    except ValueError as exc:
        raise AppError("missing_length", 400, "Content-Length is required.") from exc
    if size < 0:
        raise AppError("missing_length", 400, "Content-Length is required.")
    if size > max_bytes:
        raise AppError("too_large", 413, "The file is too large.")
    return size


async def upload_video(
    *,
    conn: sqlite3.Connection,
    queue: JobQueue,
    paths: LibraryPaths,
    media: MediaTool,
    settings: Settings,
    chunks: AsyncIterator[bytes],
    raw_length: str | None,
    filename: str,
    boulder_id: str | None,
    session_id: str | None,
    last_modified: str | None,
) -> dict[str, Any]:
    max_bytes = int(settings.max_upload_gb * (1024**3))
    content_length(raw_length, max_bytes)
    original_name, ext = parse_filename(filename)
    tmp = paths.tmp / f"{uuid4().hex}.part"
    digest, size = await stream_to_file_async(chunks, tmp, max_bytes)
    existing = videos_repo.find_by_sha256(conn, digest)
    if existing is not None:
        tmp.unlink(missing_ok=True)
        raise AppError(
            "duplicate_video",
            409,
            "This video is already in the library.",
            {"existing_video_id": existing["id"]},
        )
    try:
        probe = media.probe(tmp)
    except MediaError as exc:
        tmp.unlink(missing_ok=True)
        raise AppError("not_video", 415, "This file is not a video.") from exc
    boulder = None
    if boulder_id:
        boulder = boulders_repo.get(conn, boulder_id)
        if boulder is None:
            tmp.unlink(missing_ok=True)
            raise AppError("not_found", 404, "The boulder is not here.")
    recorded_at = _recorded_at(last_modified, probe.get("recorded_at"))
    if session_id:
        session = sessions_repo.get(conn, session_id)
        if session is None:
            tmp.unlink(missing_ok=True)
            raise AppError("not_found", 404, "The session is not here.")
    else:
        day = recorded_at[:10]
        gym = str(boulder["gym"]) if boulder and boulder.get("gym") else None
        session = sessions_repo.get_or_create_for_day(conn, day, gym)
        session_id = str(session["id"])
    video = videos_repo.insert(
        conn,
        original_name=original_name,
        original_ext=ext,
        sha256=digest,
        size_bytes=size,
        boulder_id=boulder_id,
        session_id=session_id,
        duration_s=_as_float(probe.get("duration_s")),
        src_fps=_as_float(probe.get("fps")),
        is_vfr=1 if probe.get("is_vfr") else 0,
        src_width=_as_int(probe.get("width")),
        src_height=_as_int(probe.get("height")),
        rotation=_as_int(probe.get("rotation")),
        codec=str(probe.get("codec") or "") or None,
        recorded_at=recorded_at,
    )
    dest = paths.original_path(str(video["id"]), ext)
    move_into(tmp, dest)
    try:
        job = queue.enqueue("ingest", entity_type="video", entity_id=str(video["id"]))
    except sqlite3.IntegrityError as exc:
        raise AppError("job_conflict", 409, "An ingest job is already running.") from exc
    return {"video": video, "job_id": str(job["id"])}


def reprocess(
    conn: sqlite3.Connection, queue: JobQueue, video_id: str, from_stage: str
) -> dict[str, Any]:
    video = videos_repo.get(conn, video_id)
    if video is None:
        raise AppError("not_found", 404, "The video is not here.")
    kind = STAGE_JOB.get(from_stage)
    if kind is None:
        raise AppError("bad_stage", 400, "from_stage must be proxy, pose, or detect.")
    if kind == "ingest":
        videos_repo.update(conn, video_id, {"ingest_status": "pending", "error": None})
    elif kind == "pose":
        videos_repo.update(conn, video_id, {"pose_status": "queued", "error": None})
    else:
        videos_repo.update(conn, video_id, {"detect_status": "queued", "error": None})
    try:
        job = queue.enqueue(kind, entity_type="video", entity_id=video_id)
    except sqlite3.IntegrityError as exc:
        raise AppError("job_conflict", 409, "A job of this kind is already running.") from exc
    return {"job_id": str(job["id"])}


def make_ingest_handler(
    paths: LibraryPaths, media: MediaTool, queue: JobQueue
) -> Any:
    def handle_ingest(ctx: JobContext) -> None:
        from app.repo import jobs as jobs_repo

        job = jobs_repo.get_job(ctx.conn, ctx.job_id)
        if job is None or not job.get("entity_id"):
            return
        video_id = str(job["entity_id"])
        video = videos_repo.get(ctx.conn, video_id, include_deleted=True)
        if video is None:
            raise AppError("not_found", 404, "The video is not here.")
        ctx.check_cancel()
        videos_repo.update(ctx.conn, video_id, {"ingest_status": "running", "error": None})
        prefs = settings_repo.get_all(ctx.conn)
        if hasattr(media, "proxy_fps"):
            media.proxy_fps = float(prefs.get("proxy_fps") or 30)  # type: ignore[attr-defined]
        if hasattr(media, "proxy_long_side"):
            media.proxy_long_side = int(prefs.get("proxy_long_side") or 1280)  # type: ignore[attr-defined]
        original = paths.original_path(video_id, str(video["original_ext"]))
        try:
            ctx.progress(0.05, "Probe original")
            src_info = media.probe(original)
            ctx.check_cancel()
            ctx.progress(0.15, "Make proxy")
            proxy = paths.proxy_path(video_id)
            media.make_proxy(original, proxy)
            ctx.check_cancel()
            ctx.progress(0.75, "Probe proxy")
            proxy_info = media.probe(proxy)
            ctx.progress(0.8, "Thumbnails")
            media.thumbnails(proxy, paths.thumb_dir(video_id))
            n_frames = _as_int(proxy_info.get("n_frames"))
            fps = _as_float(proxy_info.get("fps")) or float(prefs.get("proxy_fps") or 30)
            duration = _as_float(proxy_info.get("duration_s"))
            if n_frames is None and duration is not None:
                n_frames = int(round(duration * fps))
            videos_repo.update(
                ctx.conn,
                video_id,
                {
                    "duration_s": _as_float(src_info.get("duration_s")) or duration,
                    "src_fps": _as_float(src_info.get("fps")),
                    "is_vfr": 1 if src_info.get("is_vfr") else 0,
                    "src_width": _as_int(src_info.get("width")),
                    "src_height": _as_int(src_info.get("height")),
                    "rotation": _as_int(src_info.get("rotation")),
                    "codec": str(src_info.get("codec") or "") or video.get("codec"),
                    "proxy_fps": fps,
                    "proxy_width": _as_int(proxy_info.get("width")),
                    "proxy_height": _as_int(proxy_info.get("height")),
                    "n_frames": n_frames,
                    "ingest_status": "done",
                    "error": None,
                },
            )
            ctx.progress(0.95, "Queue pose")
            videos_repo.update(ctx.conn, video_id, {"pose_status": "queued"})
            try:
                queue.enqueue("pose", entity_type="video", entity_id=video_id)
            except sqlite3.IntegrityError:
                pass
        except MediaError as exc:
            videos_repo.update(
                ctx.conn,
                video_id,
                {"ingest_status": "failed", "error": exc.message},
            )
            raise
        except Exception:
            videos_repo.update(
                ctx.conn,
                video_id,
                {"ingest_status": "failed", "error": "Ingest failed."},
            )
            raise

    return handle_ingest


def _recorded_at(last_modified: str | None, probed: object) -> str:
    for raw in (probed, last_modified):
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = _parse_time(raw.strip())
        if parsed:
            return parsed
    return utc_now()


def _parse_time(raw: str) -> str | None:
    if raw.isdigit():
        try:
            return (
                datetime.fromtimestamp(int(raw), UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (OSError, OverflowError, ValueError):
            return None
    cleaned = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
