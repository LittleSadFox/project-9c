"""Helpers for API tests."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import api_headers

FAKE_VIDEO = b"\x00fake-video-body" + (b"A" * 200)


def wait_job(client: TestClient, job_id: str, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}", headers=api_headers())
        last = response.json()
        if last.get("status") in {"done", "failed", "cancelled"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish; last={last}")


def upload_video(
    client: TestClient, data: bytes = FAKE_VIDEO, filename: str = "clip.mp4", **params: str
) -> Any:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    path = "/api/videos/upload?filename=" + filename
    if query:
        path += "&" + query
    return client.post(
        path,
        content=data,
        headers=api_headers({"Content-Type": "application/octet-stream"}),
    )
