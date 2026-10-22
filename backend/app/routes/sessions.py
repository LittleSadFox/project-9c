"""Session routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.schemas.sessions import SessionCreate, SessionListOut, SessionOut, SessionPatch
from app.security import require_session
from app.services import library as library_service

router = APIRouter(
    prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=SessionListOut)
def list_sessions(
    request: Request,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    payload = library_service.list_sessions(
        request.app.state.db_conn,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [SessionOut.from_row(row) for row in payload["items"]],
        "total": payload["total"],
    }


@router.post("", response_model=SessionOut, status_code=201)
def create_session(request: Request, body: SessionCreate) -> SessionOut:
    return SessionOut.from_row(
        library_service.create_session(request.app.state.db_conn, body.model_dump())
    )


@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(request: Request, session_id: str, body: SessionPatch) -> SessionOut:
    return SessionOut.from_row(
        library_service.patch_session(request.app.state.db_conn, session_id, body.changes())
    )
