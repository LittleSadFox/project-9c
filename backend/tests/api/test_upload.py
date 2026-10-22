"""Upload contract: stream, duplicate, not-a-video, size limit."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pose.estimator import FixtureEstimator
from tests.api.helpers import upload_video, wait_job
from tests.conftest import api_headers
from tests.fakes import FakeMediaTool


def test_duplicate_upload_returns_existing_id(auth_client: TestClient) -> None:
    first = upload_video(auth_client)
    assert first.status_code == 202
    video_id = first.json()["video"]["id"]
    wait_job(auth_client, first.json()["job_id"])
    second = upload_video(auth_client)
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "duplicate_video"
    assert body["error"]["details"]["existing_video_id"] == video_id


def test_text_upload_is_415_and_tmp_stays_empty(
    auth_client: TestClient, tmp_settings: Settings
) -> None:
    response = upload_video(auth_client, data=b"this is not a video", filename="notes.txt")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "not_video"
    tmp = tmp_settings.library_dir / "tmp"
    assert list(tmp.iterdir()) == []


def test_upload_too_large_uses_content_length(tmp_settings: Settings) -> None:
    small = replace(tmp_settings, max_upload_gb=1 / (1024**3))
    app = create_app(small, media=FakeMediaTool(), estimator=FixtureEstimator())
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get(
            f"/auth/launch?token={small.launch_token}",
            headers=api_headers(),
            follow_redirects=False,
        )
        response = client.post(
            "/api/videos/upload?filename=big.mp4",
            content=b"\x00ab",
            headers=api_headers({"Content-Type": "application/octet-stream"}),
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


def test_upload_streams_and_ingest_writes_proxy(
    auth_client: TestClient, tmp_settings: Settings
) -> None:
    response = upload_video(auth_client)
    assert response.status_code == 202
    payload = response.json()
    assert "job_id" in payload
    assert payload["video"]["fps"] == 30
    job = wait_job(auth_client, payload["job_id"])
    assert job["status"] == "done"
    video_id = payload["video"]["id"]
    original = tmp_settings.library_dir / "originals" / f"{video_id}.mp4"
    proxy = tmp_settings.library_dir / "proxies" / f"{video_id}.mp4"
    assert original.is_file()
    assert proxy.is_file()
    assert list((tmp_settings.library_dir / "tmp").iterdir()) == []
