"""Job queue: run, progress, cancel, and crash recovery."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db import apply_migrations, connect
from app.jobs.context import JobContext
from app.jobs.queue import JobQueue
from app.repo import jobs as jobs_repo


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    db_path = tmp_path / "library.sqlite3"
    conn = connect(db_path)
    apply_migrations(conn)
    conn.close()
    job_queue = JobQueue(db_path)
    try:
        yield job_queue
    finally:
        job_queue.stop()
        job_queue.close()


def _wait(job_queue: JobQueue, job_id: str, status: str, timeout: float = 3.0) -> dict[str, object]:
    deadline = time.time() + timeout
    last: dict[str, object] | None = None
    while time.time() < deadline:
        last = job_queue.get(job_id)
        if last is not None and last["status"] == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {status}; last={last}")


def test_job_runs_and_reports_progress(queue: JobQueue) -> None:
    seen: list[float] = []

    def handler(ctx: JobContext) -> None:
        ctx.progress(0.25, "Quarter")
        seen.append(0.25)
        ctx.progress(1.0, "Done")
        seen.append(1.0)

    queue.register("noop", handler)
    job = queue.enqueue("noop")
    queue.start()
    done = _wait(queue, str(job["id"]), "done")
    assert done["progress"] == 1
    assert seen == [0.25, 1.0]
    assert done["message"] == "Done"


def test_job_cancels(queue: JobQueue) -> None:
    started = threading.Event()
    release = threading.Event()

    def handler(ctx: JobContext) -> None:
        started.set()
        for _ in range(200):
            ctx.check_cancel()
            if release.wait(0.02):
                return

    queue.register("noop", handler)
    job = queue.enqueue("noop")
    queue.start()
    assert started.wait(2.0)
    cancelled = queue.cancel(str(job["id"]))
    assert cancelled["status"] == "cancelled"
    _wait(queue, str(job["id"]), "cancelled")
    release.set()


def test_running_job_returns_to_queued_after_crash(tmp_path: Path) -> None:
    db_path = tmp_path / "library.sqlite3"
    conn = connect(db_path)
    apply_migrations(conn)
    job = jobs_repo.insert_job(
        conn,
        job_id="crash-job",
        kind="noop",
        lane="compute",
        entity_type=None,
        entity_id=None,
    )
    conn.execute(
        "UPDATE jobs SET status = 'running', started_at = '2026-10-21T00:00:00Z' WHERE id = ?",
        (job["id"],),
    )
    conn.commit()
    conn.close()

    job_queue = JobQueue(db_path)
    try:
        recovered = job_queue.recover()
        assert recovered == 1
        row = job_queue.get(str(job["id"]))
        assert row is not None
        assert row["status"] == "queued"
        assert row["message"] == "Returned to queue after a restart"
    finally:
        job_queue.close()
