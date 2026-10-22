"""SQL for the settings table."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

ALLOWED_KEYS = frozenset(
    {
        "pose_mode",
        "det_every",
        "proxy_fps",
        "proxy_long_side",
        "pre_roll_s",
        "post_roll_s",
    }
)


def get_all(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[str(row["key"])] = json.loads(str(row["value"]))
        except json.JSONDecodeError:
            out[str(row["key"])] = row["value"]
    return out


def get_value(conn: sqlite3.Connection, key: str, default: Any) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(str(row["value"]))
    except json.JSONDecodeError:
        return row["value"]


def put_many(conn: sqlite3.Connection, updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()
    return get_all(conn)
