"""Boulder routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.schemas.boulders import BoulderCreate, BoulderListOut, BoulderOut, BoulderPatch
from app.security import require_session
from app.services import library as library_service

router = APIRouter(
    prefix="/api/boulders", tags=["boulders"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=BoulderListOut)
def list_boulders(
    request: Request,
    status: Annotated[str | None, Query()] = None,
    gym: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    payload = library_service.list_boulders(
        request.app.state.db_conn, status=status, gym=gym, q=q, limit=limit, offset=offset
    )
    return {
        "items": [BoulderOut.from_row(row) for row in payload["items"]],
        "total": payload["total"],
    }


@router.post("", response_model=BoulderOut, status_code=201)
def create_boulder(request: Request, body: BoulderCreate) -> BoulderOut:
    return BoulderOut.from_row(
        library_service.create_boulder(request.app.state.db_conn, body.model_dump())
    )


@router.get("/{boulder_id}", response_model=BoulderOut)
def get_boulder(request: Request, boulder_id: str) -> BoulderOut:
    return BoulderOut.from_row(library_service.get_boulder(request.app.state.db_conn, boulder_id))


@router.patch("/{boulder_id}", response_model=BoulderOut)
def patch_boulder(request: Request, boulder_id: str, body: BoulderPatch) -> BoulderOut:
    return BoulderOut.from_row(
        library_service.patch_boulder(request.app.state.db_conn, boulder_id, body.changes())
    )


@router.delete("/{boulder_id}", status_code=204)
def delete_boulder(request: Request, boulder_id: str) -> Response:
    library_service.delete_boulder(request.app.state.db_conn, boulder_id)
    return Response(status_code=204)
