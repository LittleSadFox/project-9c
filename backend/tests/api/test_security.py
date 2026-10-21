"""Host allow-list and session cookie tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from tests.conftest import api_headers


def test_evil_host_is_forbidden(client: TestClient) -> None:
    response = client.get("/health", headers={"Host": "evil.example"})
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "bad_host"


def test_api_without_cookie_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/jobs", headers=api_headers())
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "no_session"


def test_launch_sets_httponly_samesite_strict_cookie(
    client: TestClient, tmp_settings: Settings
) -> None:
    response = client.get(
        f"/auth/launch?token={tmp_settings.launch_token}",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = response.headers.get("set-cookie", "")
    assert "cc_session=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()


def test_launch_wrong_token_is_unauthorized(client: TestClient) -> None:
    response = client.get(
        "/auth/launch?token=wrong-token",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "bad_token"


def test_health_needs_no_session(client: TestClient) -> None:
    response = client.get("/health", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "ffmpeg" in body
    assert "onnx" in body
    assert body["dev"] is False


def test_authed_jobs_list(client: TestClient, tmp_settings: Settings) -> None:
    launch = client.get(
        f"/auth/launch?token={tmp_settings.launch_token}",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert launch.status_code == 303
    response = client.get("/api/jobs?state=recent", headers=api_headers())
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_no_cors_headers(client: TestClient) -> None:
    response = client.get("/health", headers=api_headers())
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
