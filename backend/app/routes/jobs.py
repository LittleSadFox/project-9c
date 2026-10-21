"""Job list, detail, and cancel routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.schemas.jobs import JobListOut, JobOut
from app.security import require_session
from app.services import jobs as jobs_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_session)])


@router.get("", response_model=JobListOut)
def list_jobs(
    request: Request,
    state: Annotated[str, Query()] = "active",
) -> dict[str, object]:
    payload = jobs_service.list_jobs(request.app.state.queue, state)
    items = [JobOut.from_row(row) for row in payload["items"]]
    return {"items": items, "total": payload["total"]}


@router.get("/{job_id}", response_model=JobOut)
def get_job(request: Request, job_id: str) -> JobOut:
    return JobOut.from_row(jobs_service.get_job(request.app.state.queue, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(request: Request, job_id: str) -> JobOut:
    return JobOut.from_row(jobs_service.cancel_job(request.app.state.queue, job_id))
