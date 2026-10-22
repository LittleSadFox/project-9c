"""SQL for sessions."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    date: str,
    gym: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    session_id = new_id()
    conn.execute(
        "INSERT INTO sessions (id, date, gym, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, date, gym, notes, utc_now()),
    )
    conn.commit()
    row = get(conn, session_id)
    assert row is not None
    return row


def get(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return as_dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())


def find_by_date(
    conn: sqlite3.Connection, date: str, gym: str | None = None
) -> dict[str, Any] | None:
    if gym:
        row = conn.execute(
            "SELECT * FROM sessions WHERE date = ? AND IFNULL(gym,'') = ? "
            "ORDER BY created_at LIMIT 1",
            (date, gym),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM sessions WHERE date = ? ORDER BY created_at LIMIT 1",
            (date,),
        ).fetchone()
    return as_dict(row)


def get_or_create_for_day(
    conn: sqlite3.Connection, date: str, gym: str | None = None
) -> dict[str, Any]:
    existing = find_by_date(conn, date, gym)
    if existing is not None:
        return existing
    return insert(conn, date=date, gym=gym)


def list_sessions(
    conn: sqlite3.Connection,
    *,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = ["1=1"]
    args: list[Any] = []
    if date_from:
        where.append("date >= ?")
        args.append(date_from)
    if date_to:
        where.append("date <= ?")
        args.append(date_to)
    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM sessions{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM sessions{clause} ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return as_dicts(rows), int(total)


def update(
    conn: sqlite3.Connection, session_id: str, fields: dict[str, Any]
) -> dict[str, Any] | None:
    if not fields:
        return get(conn, session_id)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE sessions SET {cols} WHERE id = ?", [*fields.values(), session_id])
    conn.commit()
    return get(conn, session_id)
