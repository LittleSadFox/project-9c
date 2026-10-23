"""Settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.schemas.settings import SettingsOut, SettingsPatch
from app.security import require_session
from app.services import library as library_service

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_session)]
)


@router.get("", response_model=SettingsOut)
def get_settings(request: Request) -> dict[str, object]:
    return library_service.get_settings(request.app.state.db_conn)


@router.patch("", response_model=SettingsOut)
def patch_settings(request: Request, body: SettingsPatch) -> dict[str, object]:
    return library_service.patch_settings(request.app.state.db_conn, body.changes())
