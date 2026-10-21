"""Per-job progress and cancel checks."""

from __future__ import annotations

import sqlite3

from app.errors import JobCancelled
from app.repo import jobs as jobs_repo


class JobContext:
    """Worker-facing handle for one job."""

    def __init__(self, conn: sqlite3.Connection, job_id: str) -> None:
        self.conn = conn
        self.job_id = job_id

    def progress(self, p: float, msg: str) -> None:
        """Record progress in the range 0–1."""
        clamped = min(1.0, max(0.0, p))
        jobs_repo.update_progress(self.conn, self.job_id, clamped, msg)

    def check_cancel(self) -> None:
        """Stop the job when the status is cancelled."""
        status = jobs_repo.job_status(self.conn, self.job_id)
        if status == "cancelled":
            raise JobCancelled()
