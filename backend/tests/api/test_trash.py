"""Trash, restore, and empty."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.helpers import upload_video, wait_job
from tests.conftest import api_headers


def test_delete_video_moves_to_trash_and_restore(auth_client: TestClient) -> None:
    upload = upload_video(auth_client)
    wait_job(auth_client, upload.json()["job_id"])
    video_id = upload.json()["video"]["id"]
    deleted = auth_client.delete(f"/api/videos/{video_id}", headers=api_headers())
    assert deleted.status_code == 204
    missing = auth_client.get(f"/api/videos/{video_id}", headers=api_headers())
    assert missing.status_code == 404
    trash = auth_client.get("/api/trash", headers=api_headers())
    assert trash.status_code == 200
    assert trash.json()["total"] == 1
    trash_id = trash.json()["items"][0]["id"]
    restored = auth_client.post(f"/api/trash/{trash_id}/restore", headers=api_headers())
    assert restored.status_code == 200
    again = auth_client.get(f"/api/videos/{video_id}", headers=api_headers())
    assert again.status_code == 200


def test_delete_attempt_and_empty_trash(auth_client: TestClient) -> None:
    upload = upload_video(auth_client)
    wait_job(auth_client, upload.json()["job_id"])
    video_id = upload.json()["video"]["id"]
    created = auth_client.post(
        f"/api/videos/{video_id}/attempts",
        headers=api_headers(),
        json={"start_frame": 0, "end_frame": 5, "outcome": "unknown"},
    )
    wait_job(auth_client, created.json()["job_id"])
    attempt_id = created.json()["id"]
    deleted = auth_client.delete(f"/api/attempts/{attempt_id}", headers=api_headers())
    assert deleted.status_code == 204
    trash = auth_client.get("/api/trash", headers=api_headers())
    assert trash.json()["total"] == 1
    emptied = auth_client.delete("/api/trash", headers=api_headers())
    assert emptied.status_code == 204
    empty = auth_client.get("/api/trash", headers=api_headers())
    assert empty.json()["total"] == 0
