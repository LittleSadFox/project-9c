"""Byte-range media, thumbs, and exact-frame JPEGs."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from app.security import require_session
from app.services import attempts as attempts_service
from app.services import library as library_service

router = APIRouter(
    prefix="/api/videos", tags=["media"], dependencies=[Depends(require_session)]
)


def _file_response(path: object, media_type: str, etag: str) -> FileResponse:
    return FileResponse(
        path,  # type: ignore[arg-type]
        media_type=media_type,
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.get("/{video_id}/proxy")
def get_proxy(request: Request, video_id: str) -> FileResponse:
    path = library_service.resolve_video_file(
        request.app.state.db_conn, request.app.state.paths, video_id, "proxy"
    )
    return _file_response(path, "video/mp4", f"{video_id}-proxy")


@router.get("/{video_id}/original")
def get_original(request: Request, video_id: str) -> FileResponse:
    video = library_service.get_video(request.app.state.db_conn, video_id)
    path = library_service.resolve_video_file(
        request.app.state.db_conn, request.app.state.paths, video_id, "original"
    )
    ext = str(video["original_ext"])
    media_type = "video/quicktime" if ext.lower() in {"mov", "qt"} else "video/mp4"
    return _file_response(path, media_type, str(video["sha256"]))


@router.get("/{video_id}/thumb")
def get_thumb(
    request: Request,
    video_id: str,
    i: Annotated[int, Query(ge=0)] = 0,
) -> FileResponse:
    path = library_service.resolve_thumb(
        request.app.state.db_conn, request.app.state.paths, video_id, i
    )
    return _file_response(path, "image/jpeg", f"{video_id}-thumb-{i}")


@router.get("/{video_id}/frame")
def get_frame(
    request: Request,
    video_id: str,
    n: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[Literal["proxy", "original"], Query()] = "proxy",
) -> Response:
    jpeg = attempts_service.extract_frame_bytes(
        request.app.state.db_conn,
        request.app.state.paths,
        request.app.state.media,
        video_id,
        n,
        source,
    )
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )
