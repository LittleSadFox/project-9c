"""Manual attempts, ratings, and clip jobs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.helpers import upload_video, wait_job
from tests.conftest import api_headers


def _ready_video(auth_client: TestClient) -> str:
    upload = upload_video(auth_client)
    assert upload.status_code == 202
    job = wait_job(auth_client, upload.json()["job_id"])
    assert job["status"] == "done"
    return str(upload.json()["video"]["id"])


def test_create_attempt_and_rating_validation(auth_client: TestClient) -> None:
    video_id = _ready_video(auth_client)
    created = auth_client.post(
        f"/api/videos/{video_id}/attempts",
        headers=api_headers(),
        json={"start_frame": 0, "end_frame": 10, "outcome": "fall"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["outcome"] == "fall"
    assert body["clip_url"].startswith(f"/api/attempts/{body['id']}/clip")
    assert body["fps"] == 30
    wait_job(auth_client, body["job_id"])
    bad = auth_client.patch(
        f"/api/attempts/{body['id']}",
        headers=api_headers(),
        json={"proximity": 11},
    )
    assert bad.status_code == 422
    rated = auth_client.patch(
        f"/api/attempts/{body['id']}",
        headers=api_headers(),
        json={"proximity": 7, "exertion": 4, "notes": "crux"},
    )
    assert rated.status_code == 200
    assert rated.json()["proximity"] == 7
    assert rated.json()["rated_at"]
    listed = auth_client.get("/api/attempts?rated=true", headers=api_headers())
    assert listed.json()["total"] == 1


def test_attempt_frame_change_recuts(auth_client: TestClient) -> None:
    video_id = _ready_video(auth_client)
    created = auth_client.post(
        f"/api/videos/{video_id}/attempts",
        headers=api_headers(),
        json={"start_frame": 0, "end_frame": 8, "outcome": "send"},
    )
    wait_job(auth_client, created.json()["job_id"])
    patched = auth_client.patch(
        f"/api/attempts/{created.json()['id']}",
        headers=api_headers(),
        json={"start_frame": 2, "end_frame": 9},
    )
    assert patched.status_code == 200
    assert patched.json()["clip_version"] == 2
    assert patched.json()["job_id"]
    wait_job(auth_client, patched.json()["job_id"])
    detail = auth_client.get(f"/api/attempts/{created.json()['id']}", headers=api_headers())
    assert detail.json()["clip_status"] == "done"
