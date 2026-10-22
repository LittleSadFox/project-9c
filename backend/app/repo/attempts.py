"""SQL for attempts."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    boulder_id: str | None,
    start_frame: int,
    end_frame: int,
    outcome: str,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    attempt_id = new_id()
    conn.execute(
        """
        INSERT INTO attempts (
            id, video_id, boulder_id, proposal_id, start_frame, end_frame, outcome,
            proximity, exertion, notes, rated_at, clip_version, clip_status,
            deleted_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 1, 'pending', NULL, ?)
        """,
        (attempt_id, video_id, boulder_id, proposal_id, start_frame, end_frame, outcome, utc_now()),
    )
    conn.commit()
    row = get(conn, attempt_id, include_deleted=True)
    assert row is not None
    return row


def get(
    conn: sqlite3.Connection, attempt_id: str, *, include_deleted: bool = False
) -> dict[str, Any] | None:
    sql = "SELECT * FROM attempts WHERE id = ?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    return as_dict(conn.execute(sql, (attempt_id,)).fetchone())


def list_attempts(
    conn: sqlite3.Connection,
    *,
    boulder_id: str | None,
    video_id: str | None,
    outcome: str | None,
    rated: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = ["deleted_at IS NULL"]
    args: list[Any] = []
    if boulder_id:
        where.append("boulder_id = ?")
        args.append(boulder_id)
    if video_id:
        where.append("video_id = ?")
        args.append(video_id)
    if outcome:
        where.append("outcome = ?")
        args.append(outcome)
    if rated is True:
        where.append("rated_at IS NOT NULL")
    elif rated is False:
        where.append("rated_at IS NULL")
    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM attempts{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM attempts{clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return as_dicts(rows), int(total)


def list_for_video(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM attempts WHERE video_id = ? ORDER BY created_at",
        (video_id,),
    ).fetchall()
    return as_dicts(rows)


def update(
    conn: sqlite3.Connection, attempt_id: str, fields: dict[str, Any]
) -> dict[str, Any] | None:
    if not fields:
        return get(conn, attempt_id, include_deleted=True)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE attempts SET {cols} WHERE id = ?", [*fields.values(), attempt_id])
    conn.commit()
    return get(conn, attempt_id, include_deleted=True)


def soft_delete(conn: sqlite3.Connection, attempt_id: str) -> None:
    conn.execute(
        "UPDATE attempts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (utc_now(), attempt_id),
    )
    conn.commit()


def soft_delete_for_video(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute(
        "UPDATE attempts SET deleted_at = ? WHERE video_id = ? AND deleted_at IS NULL",
        (utc_now(), video_id),
    )
    conn.commit()


def restore(conn: sqlite3.Connection, attempt_id: str) -> dict[str, Any] | None:
    conn.execute("UPDATE attempts SET deleted_at = NULL WHERE id = ?", (attempt_id,))
    conn.commit()
    return get(conn, attempt_id)


def restore_for_video(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute("UPDATE attempts SET deleted_at = NULL WHERE video_id = ?", (video_id,))
    conn.commit()


def hard_delete(conn: sqlite3.Connection, attempt_id: str) -> None:
    conn.execute(
        """
        DELETE FROM alignment_anchors WHERE comparison_id IN (
            SELECT id FROM comparisons WHERE attempt_a = ? OR attempt_b = ?
        )
        """,
        (attempt_id, attempt_id),
    )
    conn.execute(
        "DELETE FROM comparisons WHERE attempt_a = ? OR attempt_b = ?",
        (attempt_id, attempt_id),
    )
    conn.execute("UPDATE proposals SET attempt_id = NULL WHERE attempt_id = ?", (attempt_id,))
    conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
    conn.commit()
