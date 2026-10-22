"""Video list, upload, patch, delete, and reprocess routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.schemas.videos import (
    JobAcceptedOut,
    ReprocessIn,
    UploadOut,
    VideoListOut,
    VideoOut,
    VideoPatch,
)
from app.security import require_session
from app.services import ingest as ingest_service
from app.services import library as library_service

router = APIRouter(
    prefix="/api/videos", tags=["videos"], dependencies=[Depends(require_session)]
)


@router.post("/upload", response_model=UploadOut)
async def upload_video(
    request: Request,
    filename: Annotated[str, Query()],
    boulder_id: Annotated[str | None, Query()] = None,
    session_id: Annotated[str | None, Query()] = None,
    last_modified: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    payload = await ingest_service.upload_video(
        conn=request.app.state.db_conn,
        queue=request.app.state.queue,
        paths=request.app.state.paths,
        media=request.app.state.media,
        settings=request.app.state.settings,
        chunks=request.stream(),
        raw_length=request.headers.get("content-length"),
        filename=filename,
        boulder_id=boulder_id,
        session_id=session_id,
        last_modified=last_modified,
    )
    body = UploadOut(
        video=VideoOut.from_row(payload["video"]),
        job_id=str(payload["job_id"]),
    )
    return JSONResponse(body.model_dump(), status_code=202)


@router.get("", response_model=VideoListOut)
def list_videos(
    request: Request,
    boulder_id: Annotated[str | None, Query()] = None,
    session_id: Annotated[str | None, Query()] = None,
    review_status: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "-recorded_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    payload = library_service.list_videos(
        request.app.state.db_conn,
        boulder_id=boulder_id,
        session_id=session_id,
        review_status=review_status,
        status=status,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [VideoOut.from_row(row) for row in payload["items"]],
        "total": payload["total"],
    }


@router.get("/{video_id}", response_model=VideoOut)
def get_video(request: Request, video_id: str) -> VideoOut:
    row = library_service.get_video(request.app.state.db_conn, video_id)
    return VideoOut.from_row(
        row,
        pending_proposals=int(row.get("pending_proposals") or 0),
        attempts=int(row.get("attempts") or 0),
        include_detail=True,
    )


@router.patch("/{video_id}", response_model=VideoOut)
def patch_video(request: Request, video_id: str, body: VideoPatch) -> VideoOut:
    row = library_service.patch_video(request.app.state.db_conn, video_id, body.changes())
    return VideoOut.from_row(
        row,
        pending_proposals=int(row.get("pending_proposals") or 0),
        attempts=int(row.get("attempts") or 0),
        include_detail=True,
    )


@router.delete("/{video_id}", status_code=204)
def delete_video(request: Request, video_id: str) -> Response:
    library_service.delete_video(request.app.state.db_conn, request.app.state.paths, video_id)
    return Response(status_code=204)


@router.post("/{video_id}/reprocess", response_model=JobAcceptedOut)
def reprocess_video(request: Request, video_id: str, body: ReprocessIn) -> JSONResponse:
    payload = ingest_service.reprocess(
        request.app.state.db_conn, request.app.state.queue, video_id, body.from_stage
    )
    return JSONResponse(JobAcceptedOut(job_id=str(payload["job_id"])).model_dump(), status_code=202)
