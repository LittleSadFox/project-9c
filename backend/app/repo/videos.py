"""SQL for videos."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id

SORTS = {
    "recorded_at": "COALESCE(recorded_at, created_at) ASC",
    "-recorded_at": "COALESCE(recorded_at, created_at) DESC",
    "created_at": "created_at ASC",
    "-created_at": "created_at DESC",
    "original_name": "original_name ASC",
    "-original_name": "original_name DESC",
}


def insert(
    conn: sqlite3.Connection,
    *,
    original_name: str,
    original_ext: str,
    sha256: str,
    size_bytes: int,
    boulder_id: str | None = None,
    session_id: str | None = None,
    duration_s: float | None = None,
    src_fps: float | None = None,
    is_vfr: int = 0,
    src_width: int | None = None,
    src_height: int | None = None,
    rotation: int | None = None,
    codec: str | None = None,
    recorded_at: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    video_id = new_id()
    conn.execute(
        """
        INSERT INTO videos (
            id, boulder_id, session_id, original_name, original_ext, sha256, size_bytes,
            duration_s, src_fps, is_vfr, src_width, src_height, rotation, codec,
            recorded_at, proxy_fps, proxy_width, proxy_height, n_frames,
            ingest_status, pose_status, detect_status, review_status,
            error, notes, deleted_at, created_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, NULL, NULL, NULL, NULL,
            'pending', 'pending', 'pending', 'unreviewed',
            NULL, ?, NULL, ?
        )
        """,
        (
            video_id,
            boulder_id,
            session_id,
            original_name,
            original_ext,
            sha256,
            size_bytes,
            duration_s,
            src_fps,
            is_vfr,
            src_width,
            src_height,
            rotation,
            codec,
            recorded_at,
            notes,
            utc_now(),
        ),
    )
    conn.commit()
    row = get(conn, video_id, include_deleted=True)
    assert row is not None
    return row


def get(
    conn: sqlite3.Connection, video_id: str, *, include_deleted: bool = False
) -> dict[str, Any] | None:
    sql = "SELECT * FROM videos WHERE id = ?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    return as_dict(conn.execute(sql, (video_id,)).fetchone())


def find_by_sha256(conn: sqlite3.Connection, sha256: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute("SELECT * FROM videos WHERE sha256 = ?", (sha256,)).fetchone()
    )


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
) -> tuple[list[dict[str, Any]], int]:
    where = ["deleted_at IS NULL"]
    args: list[Any] = []
    if boulder_id:
        where.append("boulder_id = ?")
        args.append(boulder_id)
    if session_id:
        where.append("session_id = ?")
        args.append(session_id)
    if review_status:
        where.append("review_status = ?")
        args.append(review_status)
    if status:
        where.append(
            "(ingest_status = ? OR pose_status = ? OR detect_status = ?)"
        )
        args.extend([status, status, status])
    if q:
        where.append("(original_name LIKE ? OR IFNULL(notes,'') LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like])
    order = SORTS.get(sort, SORTS["-recorded_at"])
    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM videos{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM videos{clause} ORDER BY {order} LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return as_dicts(rows), int(total)


def update(
    conn: sqlite3.Connection,
    video_id: str,
    fields: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any] | None:
    if not fields:
        return get(conn, video_id, include_deleted=True)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE videos SET {cols} WHERE id = ?", [*fields.values(), video_id])
    if commit:
        conn.commit()
    return get(conn, video_id, include_deleted=True)


def soft_delete(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute(
        "UPDATE videos SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (utc_now(), video_id),
    )
    conn.commit()


def restore(conn: sqlite3.Connection, video_id: str) -> dict[str, Any] | None:
    conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
    conn.commit()
    return get(conn, video_id)


def pending_proposal_count(conn: sqlite3.Connection, video_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE video_id = ? AND status = 'pending'",
        (video_id,),
    ).fetchone()
    return int(row[0])


def attempt_count(conn: sqlite3.Connection, video_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM attempts WHERE video_id = ? AND deleted_at IS NULL",
        (video_id,),
    ).fetchone()
    return int(row[0])


def hard_delete(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute(
        """
        DELETE FROM alignment_anchors WHERE comparison_id IN (
            SELECT id FROM comparisons WHERE attempt_a IN (
                SELECT id FROM attempts WHERE video_id = ?
            ) OR attempt_b IN (
                SELECT id FROM attempts WHERE video_id = ?
            )
        )
        """,
        (video_id, video_id),
    )
    conn.execute(
        """
        DELETE FROM comparisons WHERE attempt_a IN (
            SELECT id FROM attempts WHERE video_id = ?
        ) OR attempt_b IN (
            SELECT id FROM attempts WHERE video_id = ?
        )
        """,
        (video_id, video_id),
    )
    conn.execute(
        "DELETE FROM pose_tracks WHERE run_id IN (SELECT id FROM pose_runs WHERE video_id = ?)",
        (video_id,),
    )
    conn.execute("DELETE FROM pose_runs WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM pose_edits WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM scene_marks WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM events WHERE video_id = ?", (video_id,))
    conn.execute("UPDATE proposals SET attempt_id = NULL WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM attempts WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM proposals WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM feedback_events WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
