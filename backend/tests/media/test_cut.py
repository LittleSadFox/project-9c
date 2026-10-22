"""Frame-code cut bounds and byte-range on a real proxy. Needs ffmpeg 7+."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import wait_job
from tests.conftest import api_headers
from tests.fixtures.videos import decode_frame_index, extract_png_frame, write_frame_code_video

pytestmark = pytest.mark.media


def test_cut_first_and_last_match_frame_codes(
    media_client: TestClient, tmp_path: Path
) -> None:
    src = write_frame_code_video(tmp_path / "coded.mp4", n_frames=90, fps=30)
    upload = media_client.post(
        "/api/videos/upload?filename=coded.mp4",
        content=src.read_bytes(),
        headers=api_headers({"Content-Type": "application/octet-stream"}),
    )
    assert upload.status_code == 202, upload.text
    wait_job(media_client, upload.json()["job_id"], timeout=30)
    video_id = upload.json()["video"]["id"]
    start, end = 10, 40
    created = media_client.post(
        f"/api/videos/{video_id}/attempts",
        headers=api_headers(),
        json={"start_frame": start, "end_frame": end, "outcome": "fall"},
    )
    assert created.status_code == 201, created.text
    job = wait_job(media_client, created.json()["job_id"], timeout=30)
    assert job["status"] == "done", job
    clip = media_client.get(
        f"/api/attempts/{created.json()['id']}/clip", headers=api_headers()
    )
    assert clip.status_code == 200
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(clip.content)
    first_png = extract_png_frame(clip_path, 0, tmp_path / "first.png")
    last_png = extract_png_frame(clip_path, end - start, tmp_path / "last.png")
    first = decode_frame_index(_read_png(first_png))
    last = decode_frame_index(_read_png(last_png))
    assert abs(first - start) <= 1
    assert abs(last - end) <= 1


def test_range_bytes_on_real_proxy(media_client: TestClient, tmp_path: Path) -> None:
    src = write_frame_code_video(tmp_path / "range.mp4", n_frames=30)
    upload = media_client.post(
        "/api/videos/upload?filename=range.mp4",
        content=src.read_bytes(),
        headers=api_headers({"Content-Type": "application/octet-stream"}),
    )
    wait_job(media_client, upload.json()["job_id"], timeout=30)
    video_id = upload.json()["video"]["id"]
    response = media_client.get(
        f"/api/videos/{video_id}/proxy",
        headers=api_headers({"Range": "bytes=0-99"}),
    )
    assert response.status_code == 206
    assert len(response.content) == 100


def _read_png(path: Path) -> np.ndarray:
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None
    return image
