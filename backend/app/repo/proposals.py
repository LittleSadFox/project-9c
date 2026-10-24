"""SQL for proposals. Callers own the transaction."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict, as_dicts, new_id


def insert(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    start_frame: int,
    end_frame: int,
    outcome_guess: str | None,
    confidence: float | None,
    model_version_id: str | None,
    status: str = "pending",
    attempt_id: str | None = None,
) -> dict[str, Any]:
    proposal_id = new_id()
    conn.execute(
        """
        INSERT INTO proposals (
            id, video_id, start_frame, end_frame, outcome_guess, confidence,
            model_version_id, status, attempt_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal_id,
            video_id,
            start_frame,
            end_frame,
            outcome_guess,
            confidence,
            model_version_id,
            status,
            attempt_id,
            utc_now(),
        ),
    )
    row = get(conn, proposal_id)
    assert row is not None
    return row


def get(conn: sqlite3.Connection, proposal_id: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    )


def list_for_video(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM proposals
        WHERE video_id = ?
        ORDER BY start_frame, created_at
        """,
        (video_id,),
    ).fetchall()
    return as_dicts(rows)


def pending_for_video(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM proposals
        WHERE video_id = ? AND status = 'pending'
        ORDER BY start_frame
        """,
        (video_id,),
    ).fetchall()
    return as_dicts(rows)


def pending_count(conn: sqlite3.Connection, video_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE video_id = ? AND status = 'pending'",
        (video_id,),
    ).fetchone()
    return int(row[0])


def supersede_pending(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute(
        """
        UPDATE proposals
        SET status = 'superseded'
        WHERE video_id = ? AND status = 'pending'
        """,
        (video_id,),
    )


def update(
    conn: sqlite3.Connection, proposal_id: str, fields: dict[str, Any]
) -> dict[str, Any] | None:
    if not fields:
        return get(conn, proposal_id)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE proposals SET {cols} WHERE id = ?",
        [*fields.values(), proposal_id],
    )
    return get(conn, proposal_id)
