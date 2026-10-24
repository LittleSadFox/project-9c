"""Phase 1 pose read routes. Routes call services only."""

from __future__ import annotations

import gzip
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.schemas.pose import ClimberOut, ClimberPut, PosePersonsOut, PoseRunOut
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
) -> dict[str, Any]:
    return pose_service.get_persons(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        frame=frame,
    )


@router.put("/{video_id}/pose/climber", response_model=ClimberOut)
def put_climber(request: Request, video_id: str, body: ClimberPut) -> ClimberOut:
    payload = pose_service.set_climber(
        request.app.state.db_conn,
        request.app.state.paths,
        video_id,
        body.model_dump(exclude_unset=True),
        request.app.state.queue,
    )
    return ClimberOut.model_validate(payload)
