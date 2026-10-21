"""Host allow-list and the per-launch session cookie."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import Settings
from app.errors import AppError, error_body

SESSION_COOKIE = "cc_session"


class HostAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject Host headers that are not 127.0.0.1 or localhost."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._allowed = settings.allowed_hosts()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host = request.headers.get("host", "").strip().lower()
        if host not in self._allowed:
            return JSONResponse(
                status_code=403,
                content=error_body("bad_host", "This host is not allowed."),
            )
        return await call_next(request)


def tokens_match(given: str, expected: str) -> bool:
    """Compare tokens in constant time when the lengths match."""
    if not given or not expected:
        return False
    given_b = given.encode("utf-8")
    expected_b = expected.encode("utf-8")
    if len(given_b) != len(expected_b):
        return False
    return hmac.compare_digest(given_b, expected_b)


def require_session(request: Request) -> None:
    """Require the cc_session cookie on /api routes."""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE, "")
    if not tokens_match(token, settings.launch_token):
        raise AppError("no_session", 401, "Sign in through the launch URL.")


def set_session_cookie(response: Response, token: str) -> None:
    """Set the HttpOnly SameSite=Strict session cookie."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
