"""Trash list, restore, and empty routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.schemas.trash import TrashItemOut, TrashListOut
from app.security import require_session
from app.services import library as library_service

router = APIRouter(prefix="/api/trash", tags=["trash"], dependencies=[Depends(require_session)])


@router.get("", response_model=TrashListOut)
def list_trash(request: Request) -> dict[str, object]:
    payload = library_service.list_trash(request.app.state.db_conn)
    return {
        "items": [TrashItemOut.from_row(row) for row in payload["items"]],
        "total": payload["total"],
    }


@router.post("/{trash_id}/restore", response_model=TrashItemOut)
def restore_trash(request: Request, trash_id: str) -> TrashItemOut:
    row = library_service.restore_trash(
        request.app.state.db_conn, request.app.state.paths, trash_id
    )
    return TrashItemOut.from_row(row)


@router.delete("", status_code=204)
def empty_trash(request: Request) -> Response:
    library_service.empty_trash(request.app.state.db_conn, request.app.state.paths)
    return Response(status_code=204)
