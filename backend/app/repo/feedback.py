"""SQL for feedback_events."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    kind: str,
    entity_type: str,
    entity_id: str,
    video_id: str | None = None,
    before: str | None = None,
    after: str | None = None,
    model_version_id: str | None = None,
) -> dict[str, Any]:
    event_id = new_id()
    conn.execute(
        """
        INSERT INTO feedback_events (
            id, kind, entity_type, entity_id, video_id, before, after,
            model_version_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            kind,
            entity_type,
            entity_id,
            video_id,
            before,
            after,
            model_version_id,
            utc_now(),
        ),
    )
    row = as_dict(
        conn.execute("SELECT * FROM feedback_events WHERE id = ?", (event_id,)).fetchone()
    )
    assert row is not None
    return row
