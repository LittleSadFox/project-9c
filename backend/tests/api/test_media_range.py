"""Byte-range media responses with FakeMediaTool."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.helpers import FAKE_VIDEO, upload_video, wait_job
from tests.conftest import api_headers


def test_proxy_range_returns_206_and_100_bytes(auth_client: TestClient) -> None:
    upload = upload_video(auth_client, data=FAKE_VIDEO)
    assert upload.status_code == 202
    wait_job(auth_client, upload.json()["job_id"])
    video_id = upload.json()["video"]["id"]
    response = auth_client.get(
        f"/api/videos/{video_id}/proxy",
        headers=api_headers({"Range": "bytes=0-99"}),
    )
    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers.get("content-range", "").startswith("bytes 0-99/")
    assert "etag" in {key.lower() for key in response.headers}
    thumb = auth_client.get(f"/api/videos/{video_id}/thumb?i=0", headers=api_headers())
    assert thumb.status_code == 200
    frame = auth_client.get(f"/api/videos/{video_id}/frame?n=0", headers=api_headers())
    assert frame.status_code == 200
    assert frame.headers["content-type"].startswith("image/jpeg")
