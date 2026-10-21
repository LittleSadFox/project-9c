"""Job use cases."""

from __future__ import annotations

from typing import Any

from app.errors import AppError
from app.jobs.queue import JobQueue


def list_jobs(queue: JobQueue, state: str) -> dict[str, Any]:
    items = queue.list(state)
    return {"items": items, "total": len(items)}


def get_job(queue: JobQueue, job_id: str) -> dict[str, Any]:
    row = queue.get(job_id)
    if row is None:
        raise AppError("not_found", 404, "The job is not here.")
    return row


def cancel_job(queue: JobQueue, job_id: str) -> dict[str, Any]:
    return queue.cancel(job_id)
