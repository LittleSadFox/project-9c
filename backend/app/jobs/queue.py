"""Two-lane job queue with crash recovery."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db import connect
from app.errors import AppError, JobCancelled
from app.jobs.context import JobContext
from app.jobs.handlers import HANDLERS, JobHandler
from app.repo import jobs as jobs_repo

log = logging.getLogger("climbing_coach.jobs")

LANES = ("media", "compute")

KIND_LANE = {
    "ingest": "media",
    "cut": "media",
    "render": "media",
    "pose": "compute",
    "detect": "compute",
    "train": "compute",
    "noop": "compute",
}

class JobQueue:
    """Persist jobs in SQLite. One worker thread per lane."""

    def __init__(self, db_path: Path, handlers: dict[str, JobHandler] | None = None) -> None:
        self.db_path = db_path
        self.handlers: dict[str, JobHandler] = dict(HANDLERS)
        if handlers:
            self.handlers.update(handlers)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self._request_conn = connect(db_path)

    def close(self) -> None:
        self._request_conn.close()

    def register(self, kind: str, handler: JobHandler) -> None:
        self.handlers[kind] = handler

    def recover(self) -> int:
        """Move running jobs back to queued. Call this at start-up."""
        return jobs_repo.requeue_running(self._request_conn)

    def enqueue(
        self,
        kind: str,
        *,
        lane: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_lane = lane or KIND_LANE.get(kind)
        if resolved_lane not in LANES:
            raise AppError("bad_job_kind", 400, f"Unknown job kind: {kind}.")
        job = jobs_repo.insert_job(
            self._request_conn,
            job_id=str(uuid4()),
            kind=kind,
            lane=resolved_lane,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self._wake.set()
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return jobs_repo.get_job(self._request_conn, job_id)

    def list(self, state: str) -> list[dict[str, Any]]:
        if state not in {"active", "recent"}:
            raise AppError("bad_job_state", 400, "state must be active or recent.")
        return jobs_repo.list_jobs(self._request_conn, state)

    def cancel(self, job_id: str) -> dict[str, Any]:
        row = jobs_repo.cancel_job(self._request_conn, job_id)
        if row is None:
            raise AppError("not_found", 404, "The job is not here.")
        return row

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for lane in LANES:
            thread = threading.Thread(
                target=self._run_lane,
                args=(lane,),
                name=f"cc-job-{lane}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _run_lane(self, lane: str) -> None:
        conn = connect(self.db_path)
        try:
            while not self._stop.is_set():
                job = jobs_repo.claim_next(conn, lane)
                if job is None:
                    self._wake.wait(0.05)
                    self._wake.clear()
                    continue
                self._execute(conn, job)
        finally:
            conn.close()

    def _execute(self, conn: Any, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        kind = str(job["kind"])
        handler = self.handlers.get(kind)
        ctx = JobContext(conn, job_id)
        if handler is None:
            jobs_repo.finish_job(
                conn, job_id, status="failed", error=f"No handler for {kind}."
            )
            return
        try:
            ctx.check_cancel()
            handler(ctx)
            status = jobs_repo.job_status(conn, job_id)
            if status == "cancelled":
                return
            jobs_repo.finish_job(conn, job_id, status="done", message="Done")
        except JobCancelled:
            current = jobs_repo.get_job(conn, job_id)
            if current and current["status"] != "cancelled":
                jobs_repo.finish_job(conn, job_id, status="cancelled", message="Cancelled")
        except Exception as exc:
            log.exception("Job %s failed", job_id)
            jobs_repo.finish_job(conn, job_id, status="failed", error=str(exc))
