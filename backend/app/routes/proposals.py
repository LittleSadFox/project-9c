"""Proposal list and review actions. Routes call services only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.schemas.attempts import AttemptOut
from app.schemas.proposals import (
    ProposalAcceptIn,
    ProposalAcceptOut,
    ProposalBatchIn,
    ProposalBatchOut,
    ProposalOut,
    ProposalRejectIn,
)
from app.security import require_session
from app.services import review as review_service

router = APIRouter(tags=["proposals"], dependencies=[Depends(require_session)])


def _proposal_out(row: dict[str, Any]) -> ProposalOut:
    return ProposalOut(
        id=str(row["id"]),
        start_frame=int(row["start_frame"]),
        end_frame=int(row["end_frame"]),
        outcome_guess=row.get("outcome_guess"),
        confidence=row.get("confidence"),
        model_version=row.get("model_version_id"),
        status=str(row["status"]),
        attempt_id=row.get("attempt_id"),
    )


def _accept_out(payload: dict[str, Any]) -> ProposalAcceptOut:
    attempt = payload["attempt"]
    assert isinstance(attempt, dict)
    return ProposalAcceptOut(
        attempt=AttemptOut.from_row(attempt, fps=attempt.get("fps"), include_media=True),
        job_id=str(payload["job_id"]) if payload.get("job_id") else None,
    )


@router.get("/api/videos/{video_id}/proposals", response_model=list[ProposalOut])
def list_proposals(request: Request, video_id: str) -> list[ProposalOut]:
    rows = review_service.list_proposals(request.app.state.db_conn, video_id)
    return [_proposal_out(row) for row in rows]


@router.post(
    "/api/proposals/{proposal_id}/accept",
    response_model=ProposalAcceptOut,
    status_code=201,
)
def accept_proposal(
    request: Request, proposal_id: str, body: ProposalAcceptIn
) -> ProposalAcceptOut:
    payload = review_service.accept_proposal(
        request.app.state.db_conn,
        request.app.state.queue,
        proposal_id,
        body.model_dump(exclude_unset=True),
    )
    attempt = payload["attempt"]
    from app.services.attempts import get_attempt

    rich = get_attempt(request.app.state.db_conn, str(attempt["id"]))
    return _accept_out({"attempt": rich, "job_id": payload.get("job_id")})


@router.post("/api/proposals/batch-accept", response_model=ProposalBatchOut)
def batch_accept(request: Request, body: ProposalBatchIn) -> ProposalBatchOut:
    payload = review_service.batch_accept(
        request.app.state.db_conn,
        request.app.state.queue,
        body.ids,
    )
    from app.services.attempts import get_attempt

    items = []
    for item in payload["items"]:
        rich = get_attempt(request.app.state.db_conn, str(item["attempt"]["id"]))
        items.append(_accept_out({"attempt": rich, "job_id": item.get("job_id")}))
    return ProposalBatchOut(items=items, total=len(items))


@router.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(
    request: Request, proposal_id: str, body: ProposalRejectIn
) -> dict[str, object]:
    row = review_service.reject_proposal(request.app.state.db_conn, proposal_id, body.reason)
    return _proposal_out(row).model_dump()
