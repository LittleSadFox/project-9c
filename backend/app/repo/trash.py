"""SQL for trash_items."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    kind: str,
    entity_id: str,
    payload: str | None,
    path: str | None,
    trash_id: str | None = None,
) -> dict[str, Any]:
    trash_id = trash_id or new_id()
    conn.execute(
        """
        INSERT INTO trash_items (id, kind, entity_id, payload, path, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (trash_id, kind, entity_id, payload, path, utc_now()),
    )
    conn.commit()
    row = get(conn, trash_id)
    assert row is not None
    return row


def get(conn: sqlite3.Connection, trash_id: str) -> dict[str, Any] | None:
    return as_dict(conn.execute("SELECT * FROM trash_items WHERE id = ?", (trash_id,)).fetchone())


def list_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM trash_items ORDER BY deleted_at DESC").fetchall()
    return as_dicts(rows)


def delete(conn: sqlite3.Connection, trash_id: str) -> None:
    conn.execute("DELETE FROM trash_items WHERE id = ?", (trash_id,))
    conn.commit()


def delete_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items = list_items(conn)
    conn.execute("DELETE FROM trash_items")
    conn.commit()
    return items
