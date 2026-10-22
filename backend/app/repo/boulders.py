"""SQL for boulders."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id

COUNT_SQL = """
SELECT
    b.*,
    (SELECT COUNT(*) FROM videos v
     WHERE v.boulder_id = b.id AND v.deleted_at IS NULL) AS video_count,
    (SELECT COUNT(*) FROM attempts a
     WHERE a.boulder_id = b.id AND a.deleted_at IS NULL) AS attempt_count,
    (SELECT COUNT(*) FROM attempts a
     WHERE a.boulder_id = b.id AND a.deleted_at IS NULL AND a.outcome = 'send') AS sent,
    (SELECT MAX(a.proximity) FROM attempts a
     WHERE a.boulder_id = b.id AND a.deleted_at IS NULL) AS best_proximity,
    (SELECT MAX(COALESCE(a.rated_at, a.created_at)) FROM attempts a
     WHERE a.boulder_id = b.id AND a.deleted_at IS NULL) AS last_attempt_at
FROM boulders b
"""


def insert(
    conn: sqlite3.Connection,
    *,
    name: str,
    gym: str | None = None,
    grade: str | None = None,
    color: str | None = None,
    sector: str | None = None,
    set_date: str | None = None,
    notes: str | None = None,
    status: str = "active",
) -> dict[str, Any]:
    boulder_id = new_id()
    conn.execute(
        """
        INSERT INTO boulders (
            id, name, gym, grade, color, sector, set_date, status, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (boulder_id, name, gym, grade, color, sector, set_date, status, notes, utc_now()),
    )
    conn.commit()
    row = get(conn, boulder_id)
    assert row is not None
    return row


def get(conn: sqlite3.Connection, boulder_id: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute(COUNT_SQL + " WHERE b.id = ?", (boulder_id,)).fetchone()
    )


def list_boulders(
    conn: sqlite3.Connection,
    *,
    status: str | None,
    gym: str | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = ["1=1"]
    args: list[Any] = []
    if status:
        where.append("b.status = ?")
        args.append(status)
    if gym:
        where.append("b.gym = ?")
        args.append(gym)
    if q:
        where.append("(b.name LIKE ? OR IFNULL(b.gym,'') LIKE ? OR IFNULL(b.notes,'') LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like])
    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM boulders b{clause}", args
    ).fetchone()[0]
    rows = conn.execute(
        COUNT_SQL + clause + " ORDER BY b.created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return as_dicts(rows), int(total)


def update(
    conn: sqlite3.Connection, boulder_id: str, fields: dict[str, Any]
) -> dict[str, Any] | None:
    if not fields:
        return get(conn, boulder_id)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE boulders SET {cols} WHERE id = ?",
        [*fields.values(), boulder_id],
    )
    conn.commit()
    return get(conn, boulder_id)


def delete(conn: sqlite3.Connection, boulder_id: str) -> None:
    conn.execute("DELETE FROM boulders WHERE id = ?", (boulder_id,))
    conn.commit()


def video_count(conn: sqlite3.Connection, boulder_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE boulder_id = ? AND deleted_at IS NULL",
        (boulder_id,),
    ).fetchone()
    return int(row[0])
