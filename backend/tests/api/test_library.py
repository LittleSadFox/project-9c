"""Boulder, session, video, and settings API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.helpers import upload_video, wait_job
from tests.conftest import api_headers


def test_boulder_crud_and_delete_conflict(auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/boulders",
        headers=api_headers(),
        json={"name": "Red 6A", "gym": "Arch"},
    )
    assert created.status_code == 201
    boulder_id = created.json()["id"]
    listed = auth_client.get("/api/boulders", headers=api_headers())
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["video_count"] == 0
    patched = auth_client.patch(
        f"/api/boulders/{boulder_id}",
        headers=api_headers(),
        json={"grade": "6A"},
    )
    assert patched.status_code == 200
    assert patched.json()["grade"] == "6A"
    upload = upload_video(auth_client, boulder_id=boulder_id)
    assert upload.status_code == 202
    wait_job(auth_client, upload.json()["job_id"])
    blocked = auth_client.delete(f"/api/boulders/{boulder_id}", headers=api_headers())
    assert blocked.status_code == 409


def test_session_create_and_filter(auth_client: TestClient) -> None:
    created = auth_client.post(
        "/api/sessions",
        headers=api_headers(),
        json={"date": "2026-10-22", "gym": "Arch"},
    )
    assert created.status_code == 201
    listed = auth_client.get("/api/sessions?from=2026-10-22&to=2026-10-22", headers=api_headers())
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    session_id = created.json()["id"]
    patched = auth_client.patch(
        f"/api/sessions/{session_id}",
        headers=api_headers(),
        json={"notes": "evening"},
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "evening"


def test_video_get_patch_and_settings(auth_client: TestClient) -> None:
    settings = auth_client.get("/api/settings", headers=api_headers())
    assert settings.status_code == 200
    assert settings.json()["proxy_fps"] == 30
    patched = auth_client.patch("/api/settings", headers=api_headers(), json={"proxy_fps": 24})
    assert patched.status_code == 200
    assert patched.json()["proxy_fps"] == 24
    upload = upload_video(auth_client)
    assert upload.status_code == 202
    video_id = upload.json()["video"]["id"]
    wait_job(auth_client, upload.json()["job_id"])
    detail = auth_client.get(f"/api/videos/{video_id}", headers=api_headers())
    assert detail.status_code == 200
    body = detail.json()
    assert "fps" in body
    assert "n_frames" in body
    assert body["stages"]["ingest"] == "done"
    assert body["counts"]["attempts"] == 0
    marked = auth_client.patch(
        f"/api/videos/{video_id}",
        headers=api_headers(),
        json={"review_status": "reviewed", "notes": "ok"},
    )
    assert marked.status_code == 200
    assert marked.json()["review_status"] == "reviewed"
    listed = auth_client.get("/api/videos?review_status=reviewed", headers=api_headers())
    assert listed.json()["total"] == 1
