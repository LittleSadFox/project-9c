"""SQL for events. Callers own the transaction."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    run_id: str | None,
    frame: int,
    kind: str,
    confidence: float | None,
    source: str,
    model_version_id: str | None,
) -> dict[str, Any]:
    event_id = new_id()
    conn.execute(
        """
        INSERT INTO events (
            id, video_id, run_id, frame, kind, confidence, source, model_version_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            video_id,
            run_id,
            frame,
            kind,
            confidence,
            source,
            model_version_id,
            utc_now(),
        ),
    )
    row = as_dict(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    assert row is not None
    return row


def delete_rule_for_video(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute("DELETE FROM events WHERE video_id = ? AND source = 'rule'", (video_id,))


def list_for_video(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    latest = conn.execute(
        """
        SELECT run_id FROM events
        WHERE video_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (video_id,),
    ).fetchone()
    if latest is None:
        return []
    run_id = latest["run_id"]
    if run_id:
        rows = conn.execute(
            """
            SELECT * FROM events
            WHERE video_id = ? AND run_id = ?
            ORDER BY frame, kind
            """,
            (video_id, run_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events WHERE video_id = ? ORDER BY frame, kind",
            (video_id,),
        ).fetchall()
    return as_dicts(rows)
