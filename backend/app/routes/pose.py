"""Phase 1 pose read routes plus Phase 2 slice E edit handlers."""

from __future__ import annotations

import gzip
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.schemas.pose import (
    PoseClimberIn,
    PoseClimberOut,
    PoseEditIn,
    PoseEditOut,
    PoseEditsOut,
    PosePersonsOut,
    PoseReviewQueueOut,
    PoseRunOut,
)
from app.security import require_session
from app.services import pose_service

router = APIRouter(prefix="/api/videos", tags=["pose"], dependencies=[Depends(require_session)])


class GzipJSONResponse(Response):
    media_type = "application/json"

    def __init__(self, content: dict[str, Any]) -> None:
        raw = json.dumps(content, separators=(",", ":")).encode("utf-8")
        super().__init__(
            content=gzip.compress(raw),
            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
        )


@router.get("/{video_id}/pose", response_model=PoseRunOut)
def get_pose(request: Request, video_id: str) -> dict[str, Any]:
    return pose_service.get_pose_summary(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
    )


@router.get("/{video_id}/pose/keypoints")
def get_keypoints(
    request: Request,
    video_id: str,
    track: Annotated[str, Query()] = "climber",
    start: Annotated[int | None, Query()] = None,
    end: Annotated[int | None, Query()] = None,
    effective: Annotated[bool, Query()] = True,
) -> GzipJSONResponse:
    payload = pose_service.get_keypoints(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        track=track,
        start=start,
        end=end,
        effective=effective,
    )
    return GzipJSONResponse(payload)


@router.get("/{video_id}/pose/persons", response_model=PosePersonsOut)
def get_persons(
    request: Request,
    video_id: str,
    frame: Annotated[int, Query()],
    x: Annotated[float | None, Query()] = None,
    y: Annotated[float | None, Query()] = None,
) -> dict[str, Any]:
    return pose_service.get_persons(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        frame=frame,
        x=x,
        y=y,
    )


@router.put("/{video_id}/pose/climber", response_model=PoseClimberOut)
def put_climber(request: Request, video_id: str, body: PoseClimberIn) -> dict[str, Any]:
    return pose_service.set_climber(
        request.app.state.db_conn,
        request.app.state.paths,
        request.app.state.queue,
        video_id,
        body.model_dump(),
    )


@router.get("/{video_id}/pose/review-queue", response_model=PoseReviewQueueOut)
def get_review_queue(request: Request, video_id: str) -> dict[str, Any]:
    return pose_service.review_queue(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
    )


@router.get("/{video_id}/pose/edits", response_model=PoseEditsOut)
def get_edits(
    request: Request,
    video_id: str,
    start: Annotated[int | None, Query()] = None,
    end: Annotated[int | None, Query()] = None,
) -> dict[str, Any]:
    return pose_service.list_edits(
        request.app.state.db_conn,
        video_id,
        start=start,
        end=end,
    )


@router.post("/{video_id}/pose/edits", response_model=PoseEditOut, status_code=201)
def post_edit(request: Request, video_id: str, body: PoseEditIn) -> dict[str, Any]:
    return pose_service.create_edit(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        body.model_dump(),
    )


@router.delete("/{video_id}/pose/edits/{edit_id}", status_code=204)
def delete_edit(request: Request, video_id: str, edit_id: str) -> Response:
    pose_service.delete_edit(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        edit_id,
    )
    return Response(status_code=204)
