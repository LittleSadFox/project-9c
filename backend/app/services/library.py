"""Boulder, session, video, settings, and trash use cases."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from app.errors import AppError
from app.learning.feedback import log_feedback
from app.repo import attempts as attempts_repo
from app.repo import boulders as boulders_repo
from app.repo import sessions as sessions_repo
from app.repo import settings as settings_repo
from app.repo import trash as trash_repo
from app.repo import videos as videos_repo
from app.storage import LibraryPaths, move_into, safe_join

VIDEO_PATCH_FIELDS = frozenset(
    {"boulder_id", "session_id", "recorded_at", "notes", "review_status"}
)
BOULDER_PATCH_FIELDS = frozenset(
    {"name", "gym", "grade", "color", "sector", "set_date", "status", "notes"}
)
SESSION_PATCH_FIELDS = frozenset({"date", "gym", "notes"})


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    return settings_repo.get_all(conn)


def patch_settings(conn: sqlite3.Connection, updates: dict[str, Any]) -> dict[str, Any]:
    unknown = set(updates) - settings_repo.ALLOWED_KEYS
    if unknown:
        raise AppError("bad_settings", 400, f"Unknown settings: {sorted(unknown)}.")
    return settings_repo.put_many(conn, updates)


def create_boulder(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    return boulders_repo.insert(conn, **data)


def get_boulder(conn: sqlite3.Connection, boulder_id: str) -> dict[str, Any]:
    row = boulders_repo.get(conn, boulder_id)
    if row is None:
        raise AppError("not_found", 404, "The boulder is not here.")
    return row


def list_boulders(
    conn: sqlite3.Connection,
    *,
    status: str | None,
    gym: str | None,
    q: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total = boulders_repo.list_boulders(
        conn, status=status, gym=gym, q=q, limit=limit, offset=offset
    )
    return {"items": items, "total": total}


def patch_boulder(
    conn: sqlite3.Connection, boulder_id: str, fields: dict[str, Any]
) -> dict[str, Any]:
    get_boulder(conn, boulder_id)
    cleaned = {key: value for key, value in fields.items() if key in BOULDER_PATCH_FIELDS}
    if "status" in cleaned and cleaned["status"] not in {"active", "archived"}:
        raise AppError("bad_status", 400, "status must be active or archived.")
    row = boulders_repo.update(conn, boulder_id, cleaned)
    assert row is not None
    return row


def delete_boulder(conn: sqlite3.Connection, boulder_id: str) -> None:
    get_boulder(conn, boulder_id)
    if boulders_repo.video_count(conn, boulder_id) > 0:
        raise AppError("boulder_has_videos", 409, "This boulder still has videos.")
    boulders_repo.delete(conn, boulder_id)


def create_session(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    return sessions_repo.insert(conn, **data)


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = sessions_repo.get(conn, session_id)
    if row is None:
        raise AppError("not_found", 404, "The session is not here.")
    return row


def list_sessions(
    conn: sqlite3.Connection,
    *,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total = sessions_repo.list_sessions(
        conn, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    return {"items": items, "total": total}


def patch_session(
    conn: sqlite3.Connection, session_id: str, fields: dict[str, Any]
) -> dict[str, Any]:
    get_session(conn, session_id)
    cleaned = {key: value for key, value in fields.items() if key in SESSION_PATCH_FIELDS}
    row = sessions_repo.update(conn, session_id, cleaned)
    assert row is not None
    return row


def list_videos(
    conn: sqlite3.Connection,
    *,
    boulder_id: str | None,
    session_id: str | None,
    review_status: str | None,
    status: str | None,
    q: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    items, total = videos_repo.list_videos(
        conn,
        boulder_id=boulder_id,
        session_id=session_id,
        review_status=review_status,
        status=status,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


def get_video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = videos_repo.get(conn, video_id)
    if row is None:
        raise AppError("not_found", 404, "The video is not here.")
    row["pending_proposals"] = videos_repo.pending_proposal_count(conn, video_id)
    row["attempts"] = videos_repo.attempt_count(conn, video_id)
    return row


def patch_video(conn: sqlite3.Connection, video_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    from app.db import immediate
    from app.repo import models as models_repo

    get_video(conn, video_id)
    cleaned = {key: value for key, value in fields.items() if key in VIDEO_PATCH_FIELDS}
    if "boulder_id" in cleaned and cleaned["boulder_id"]:
        get_boulder(conn, str(cleaned["boulder_id"]))
    if "session_id" in cleaned and cleaned["session_id"]:
        get_session(conn, str(cleaned["session_id"]))
    if cleaned.get("review_status") == "reviewed":
        with immediate(conn):
            locked = videos_repo.get(conn, video_id)
            if locked is None:
                raise AppError("not_found", 404, "The video is not here.")
            pending = videos_repo.pending_proposal_count(conn, video_id)
            if pending:
                raise AppError(
                    "review_blocked",
                    409,
                    "This video still has pending proposals.",
                    {"pending_proposals": pending},
                )
            if str(locked.get("review_status")) != "reviewed":
                log_feedback(
                    conn,
                    kind="review.complete",
                    entity_type="video",
                    entity_id=video_id,
                    video_id=video_id,
                    before={"review_status": locked["review_status"]},
                    after={"review_status": "reviewed"},
                    model_version_id=models_repo.active_event_id(conn),
                )
            row = videos_repo.update(conn, video_id, cleaned, commit=False)
    else:
        row = videos_repo.update(conn, video_id, cleaned)
    assert row is not None
    row["pending_proposals"] = videos_repo.pending_proposal_count(conn, video_id)
    row["attempts"] = videos_repo.attempt_count(conn, video_id)
    return row


def delete_video(conn: sqlite3.Connection, paths: LibraryPaths, video_id: str) -> None:
    from app.repo.util import new_id

    video = get_video(conn, video_id)
    attempts = attempts_repo.list_for_video(conn, video_id)
    trash_id = new_id()
    trash_dir = paths.trash_item_dir(trash_id)
    trash_dir.mkdir(parents=True, exist_ok=True)
    original = paths.original_path(video_id, str(video["original_ext"]))
    proxy = paths.proxy_path(video_id)
    thumbs = paths.thumb_dir(video_id)
    clip_names: list[str] = []
    move_into(original, trash_dir / f"original.{video['original_ext']}")
    move_into(proxy, trash_dir / "proxy.mp4")
    move_into(thumbs, trash_dir / "thumbs")
    for attempt in attempts:
        if attempt.get("deleted_at"):
            continue
        clip = paths.clip_path(str(attempt["id"]), int(attempt["clip_version"]))
        dest = trash_dir / "clips" / clip.name
        move_into(clip, dest)
        if dest.exists():
            clip_names.append(clip.name)
    payload = {
        "row": {key: video[key] for key in video if key not in {"pending_proposals", "attempts"}},
        "attempts": [
            {"id": a["id"], "clip_version": a["clip_version"]}
            for a in attempts
            if not a.get("deleted_at")
        ],
        "clips": clip_names,
    }
    trash_repo.insert(
        conn,
        kind="video",
        entity_id=video_id,
        payload=json.dumps(payload),
        path=str(trash_dir.relative_to(paths.root)),
        trash_id=trash_id,
    )
    attempts_repo.soft_delete_for_video(conn, video_id)
    videos_repo.soft_delete(conn, video_id)


def list_trash(conn: sqlite3.Connection) -> dict[str, Any]:
    items = trash_repo.list_items(conn)
    return {"items": items, "total": len(items)}


def restore_trash(conn: sqlite3.Connection, paths: LibraryPaths, trash_id: str) -> dict[str, Any]:
    item = trash_repo.get(conn, trash_id)
    if item is None:
        raise AppError("not_found", 404, "The trash item is not here.")
    payload = json.loads(item["payload"] or "{}")
    trash_dir = _resolve_trash_dir(paths, item.get("path"))
    if item["kind"] == "video":
        row = payload.get("row") or {}
        video_id = str(item["entity_id"])
        ext = str(row.get("original_ext") or "mp4")
        move_into(trash_dir / f"original.{ext}", paths.original_path(video_id, ext))
        move_into(trash_dir / "proxy.mp4", paths.proxy_path(video_id))
        move_into(trash_dir / "thumbs", paths.thumb_dir(video_id))
        clips_dir = trash_dir / "clips"
        if clips_dir.is_dir():
            for clip in clips_dir.iterdir():
                move_into(clip, paths.clips / clip.name)
        videos_repo.restore(conn, video_id)
        attempt_ids = [
            str(entry["id"])
            for entry in (payload.get("attempts") or [])
            if isinstance(entry, dict) and entry.get("id")
        ]
        attempts_repo.restore_for_video(conn, video_id, attempt_ids)
    elif item["kind"] == "attempt":
        attempt_id = str(item["entity_id"])
        version = int((payload.get("row") or {}).get("clip_version") or 1)
        clip_name = f"{attempt_id}_v{version}.mp4"
        src = trash_dir / clip_name
        if not src.exists() and trash_dir.is_dir():
            matches = list(trash_dir.glob(f"{attempt_id}_v*.mp4"))
            src = matches[0] if matches else src
        move_into(src, paths.clip_path(attempt_id, version))
        attempts_repo.restore(conn, attempt_id)
    else:
        raise AppError("bad_trash", 400, "Unknown trash kind.")
    if trash_dir.exists():
        shutil.rmtree(trash_dir, ignore_errors=True)
    trash_repo.delete(conn, trash_id)
    return item


def empty_trash(conn: sqlite3.Connection, paths: LibraryPaths) -> None:
    items = trash_repo.list_items(conn)
    targets: list[tuple[dict[str, Any], Path]] = []
    for item in items:
        target = _resolve_trash_dir(paths, item.get("path"))
        targets.append((item, target))
    for item, target in targets:
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        if item["kind"] == "video":
            videos_repo.hard_delete(conn, str(item["entity_id"]))
        elif item["kind"] == "attempt":
            attempts_repo.hard_delete(conn, str(item["entity_id"]))
    trash_repo.delete_all(conn)


def _resolve_trash_dir(paths: LibraryPaths, stored: object) -> Path:
    """Resolve a stored trash path. The result must sit strictly inside trash/."""
    if stored is None or not str(stored).strip():
        raise AppError("bad_path", 400, "The path is not allowed.")
    raw = str(stored).strip().replace("\\", "/")
    if Path(raw).is_absolute():
        raise AppError("bad_path", 400, "The path is not allowed.")
    parts = [part for part in Path(raw).parts if part not in {"", "."}]
    if parts and parts[0] == "trash":
        parts = parts[1:]
    if not parts:
        raise AppError("bad_path", 400, "The path is not allowed.")
    candidate = safe_join(paths.trash, *parts)
    trash_root = paths.trash.resolve()
    resolved = candidate.resolve()
    if resolved == trash_root:
        raise AppError("bad_path", 400, "The path is not allowed.")
    try:
        resolved.relative_to(trash_root)
    except ValueError as exc:
        raise AppError("bad_path", 400, "The path is not allowed.") from exc
    return candidate


def resolve_video_file(
    conn: sqlite3.Connection, paths: LibraryPaths, video_id: str, kind: str
) -> Path:
    video = get_video(conn, video_id)
    if kind == "original":
        path = paths.original_path(video_id, str(video["original_ext"]))
    elif kind == "proxy":
        path = paths.proxy_path(video_id)
    else:
        raise AppError("bad_source", 400, "source must be proxy or original.")
    if not path.is_file():
        raise AppError("not_found", 404, "The media file is not here.")
    return path


def resolve_thumb(conn: sqlite3.Connection, paths: LibraryPaths, video_id: str, index: int) -> Path:
    get_video(conn, video_id)
    path = paths.thumb_path(video_id, index)
    if not path.is_file():
        raise AppError("not_found", 404, "The thumbnail is not here.")
    return path


def require_video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    return get_video(conn, video_id)
