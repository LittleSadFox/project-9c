"""Attempt CRUD and clip routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from app.schemas.attempts import AttemptCreate, AttemptListOut, AttemptOut, AttemptPatch
from app.security import require_session
from app.services import attempts as attempts_service

router = APIRouter(tags=["attempts"], dependencies=[Depends(require_session)])


@router.post("/api/videos/{video_id}/attempts", response_model=AttemptOut, status_code=201)
def create_attempt(request: Request, video_id: str, body: AttemptCreate) -> AttemptOut:
    row = attempts_service.create_attempt(
        request.app.state.db_conn,
        request.app.state.queue,
        video_id,
        body.model_dump(),
    )
    return AttemptOut.from_row(
        row, fps=row.get("fps"), include_media=True, job_id=row.get("job_id")
    )


@router.get("/api/attempts", response_model=AttemptListOut)
def list_attempts(
    request: Request,
    boulder_id: Annotated[str | None, Query()] = None,
    video_id: Annotated[str | None, Query()] = None,
    outcome: Annotated[str | None, Query()] = None,
    rated: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    payload = attempts_service.list_attempts(
        request.app.state.db_conn,
        boulder_id=boulder_id,
        video_id=video_id,
        outcome=outcome,
        rated=rated,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            AttemptOut.from_row(row, fps=row.get("fps"), include_media=True)
            for row in payload["items"]
        ],
        "total": payload["total"],
    }


@router.get("/api/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(request: Request, attempt_id: str) -> AttemptOut:
    row = attempts_service.get_attempt(request.app.state.db_conn, attempt_id)
    return AttemptOut.from_row(row, fps=row.get("fps"), include_media=True)


@router.patch("/api/attempts/{attempt_id}", response_model=AttemptOut)
def patch_attempt(request: Request, attempt_id: str, body: AttemptPatch) -> AttemptOut:
    row = attempts_service.patch_attempt(
        request.app.state.db_conn,
        request.app.state.queue,
        attempt_id,
        body.changes(),
    )
    return AttemptOut.from_row(
        row, fps=row.get("fps"), include_media=True, job_id=row.get("job_id")
    )


@router.delete("/api/attempts/{attempt_id}", status_code=204)
def delete_attempt(request: Request, attempt_id: str) -> Response:
    attempts_service.delete_attempt(
        request.app.state.db_conn, request.app.state.paths, attempt_id
    )
    return Response(status_code=204)


@router.get("/api/attempts/{attempt_id}/clip")
def get_clip(request: Request, attempt_id: str) -> FileResponse:
    path, attempt = attempts_service.resolve_clip(
        request.app.state.db_conn, request.app.state.paths, attempt_id
    )
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={
            "ETag": f'"{attempt_id}-v{attempt["clip_version"]}"',
            "Cache-Control": "private, max-age=86400",
        },
    )
