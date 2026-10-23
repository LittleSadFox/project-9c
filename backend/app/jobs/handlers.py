"""Built-in job handlers. Phase 0 ships a noop job."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.jobs.context import JobContext

JobHandler = Callable[[JobContext], None]


def handle_noop(ctx: JobContext) -> None:
    """Report progress in five steps so tests can watch a job run."""
    steps = 5
    for index in range(steps):
        ctx.check_cancel()
        ctx.progress((index + 1) / steps, f"Step {index + 1} of {steps}")
        time.sleep(0.02)


def handle_pose(ctx: JobContext) -> None:
    """Compute-lane pose job. Registered here so A's ingest can enqueue it."""
    from app.services.pose_service import handle_pose_job

    handle_pose_job(ctx)


HANDLERS: dict[str, JobHandler] = {
    "noop": handle_noop,
    "pose": handle_pose,
}
