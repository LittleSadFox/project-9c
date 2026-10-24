"""Scene marks and events. Routes call services only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas.scene import EventOut, SceneOut, ScenePut, SceneWriteOut
from app.security import require_session
from app.services import review as review_service

router = APIRouter(prefix="/api/videos", tags=["scene"], dependencies=[Depends(require_session)])


@router.get("/{video_id}/scene", response_model=SceneOut)
def get_scene(request: Request, video_id: str) -> SceneOut:
    return SceneOut.model_validate(review_service.get_scene(request.app.state.db_conn, video_id))


@router.put("/{video_id}/scene", response_model=SceneWriteOut)
def put_scene(request: Request, video_id: str, body: ScenePut) -> SceneWriteOut:
    payload = review_service.put_scene(
        request.app.state.db_conn,
        request.app.state.queue,
        video_id,
        body.model_dump(),
    )
    return SceneWriteOut(
        scene=SceneOut.model_validate(payload["scene"]),
        job_id=payload.get("job_id"),
    )


@router.post("/{video_id}/scene/copy-from/{other_id}", response_model=SceneWriteOut)
def copy_scene(request: Request, video_id: str, other_id: str) -> SceneWriteOut:
    payload = review_service.copy_scene_from(
        request.app.state.db_conn,
        request.app.state.queue,
        video_id,
        other_id,
    )
    return SceneWriteOut(
        scene=SceneOut.model_validate(payload["scene"]),
        job_id=payload.get("job_id"),
    )


@router.get("/{video_id}/events", response_model=list[EventOut])
def list_events(request: Request, video_id: str) -> list[EventOut]:
    rows = review_service.list_events(request.app.state.db_conn, video_id)
    return [EventOut.model_validate(row) for row in rows]
