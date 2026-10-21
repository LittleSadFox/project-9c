"""SQL for the jobs table."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now

JobRow = dict[str, Any]


def _as_dict(row: sqlite3.Row | None) -> JobRow | None:
    if row is None:
        return None
    return dict(row)


def insert_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    kind: str,
    lane: str,
    entity_type: str | None,
    entity_id: str | None,
) -> JobRow:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO jobs (
            id, kind, lane, status, progress, message,
            entity_type, entity_id, error, created_at, started_at, finished_at
        ) VALUES (?, ?, ?, 'queued', 0, NULL, ?, ?, NULL, ?, NULL, NULL)
        """,
        (job_id, kind, lane, entity_type, entity_id, now),
    )
    row = get_job(conn, job_id)
    assert row is not None
    return row


def get_job(conn: sqlite3.Connection, job_id: str) -> JobRow | None:
    return _as_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def list_jobs(conn: sqlite3.Connection, state: str) -> list[JobRow]:
    if state == "active":
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
    return [dict(row) for row in rows]


def claim_next(conn: sqlite3.Connection, lane: str) -> JobRow | None:
    """Atomically claim the oldest queued job in a lane."""
    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """
            SELECT id FROM jobs
            WHERE lane = ? AND status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (lane,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        job_id = row["id"]
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', started_at = ?, finished_at = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (now, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_job(conn, job_id)


def update_progress(
    conn: sqlite3.Connection, job_id: str, progress: float, message: str
) -> None:
    conn.execute(
        "UPDATE jobs SET progress = ?, message = ? WHERE id = ?",
        (progress, message, job_id),
    )
    conn.commit()


def finish_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str,
    message: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET status = ?, progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END,
            message = COALESCE(?, message), error = ?, finished_at = ?
        WHERE id = ?
        """,
        (status, status, message, error, utc_now(), job_id),
    )
    conn.commit()


def cancel_job(conn: sqlite3.Connection, job_id: str) -> JobRow | None:
    row = get_job(conn, job_id)
    if row is None:
        return None
    if row["status"] not in {"queued", "running"}:
        return row
    conn.execute(
        """
        UPDATE jobs
        SET status = 'cancelled', message = 'Cancelled', finished_at = ?
        WHERE id = ? AND status IN ('queued', 'running')
        """,
        (utc_now(), job_id),
    )
    conn.commit()
    return get_job(conn, job_id)


def requeue_running(conn: sqlite3.Connection) -> int:
    """Return running jobs to queued after a crash or restart."""
    cursor = conn.execute(
        """
        UPDATE jobs
        SET status = 'queued',
            started_at = NULL,
            finished_at = NULL,
            message = 'Returned to queue after a restart'
        WHERE status = 'running'
        """
    )
    conn.commit()
    return int(cursor.rowcount)


def job_status(conn: sqlite3.Connection, job_id: str) -> str | None:
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return str(row["status"])
