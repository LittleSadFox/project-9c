"""Health and launch routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.errors import AppError
from app.schemas.health import HealthResponse
from app.security import set_session_cookie, tokens_match
from app.services import health as health_service

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> dict[str, object]:
    return health_service.build_health(request.app.state.settings, request.app.state.db_conn)


@router.get("/auth/launch")
def launch(request: Request, token: str) -> RedirectResponse:
    settings = request.app.state.settings
    if not tokens_match(token, settings.launch_token):
        raise AppError("bad_token", 401, "The launch token is wrong.")
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, settings.launch_token)
    return response
