"""SQL for model_versions."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.repo.util import as_dict

RULE_V1_ID = "c0ffee00-0002-4000-8000-000000000002"
RULE_V1_FAMILY = "event"
RULE_V1_VERSION = "rule-v1"


def get(conn: sqlite3.Connection, model_id: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute("SELECT * FROM model_versions WHERE id = ?", (model_id,)).fetchone()
    )


def get_active(conn: sqlite3.Connection, family: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute(
            """
            SELECT * FROM model_versions
            WHERE family = ? AND active = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (family,),
        ).fetchone()
    )


def active_event_id(conn: sqlite3.Connection) -> str:
    row = get_active(conn, RULE_V1_FAMILY)
    if row is None:
        return RULE_V1_ID
    return str(row["id"])
