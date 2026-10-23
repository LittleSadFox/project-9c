"""Proxy CFR, rotation, VFR, and HEVC import. Needs ffmpeg 7+."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.media.ffmpeg import FfmpegTool
from tests.api.helpers import wait_job
from tests.conftest import api_headers
from tests.fixtures.videos import (
    extract_png_frame,
    probe_json,
    write_corner_rotated_video,
    write_hevc_video,
    write_vfr_video,
)

pytestmark = pytest.mark.media


def _upload(client: TestClient, path: Path, name: str) -> dict[str, object]:
    response = client.post(
        f"/api/videos/upload?filename={name}",
        content=path.read_bytes(),
        headers=api_headers({"Content-Type": "application/octet-stream"}),
    )
    assert response.status_code == 202, response.text
    job = wait_job(client, str(response.json()["job_id"]), timeout=30)
    assert job["status"] == "done", job
    return response.json()


def _video_stream(path: Path) -> dict[str, object]:
    payload = probe_json(path)
    streams = payload.get("streams")
    assert isinstance(streams, list)
    video = next(s for s in streams if s.get("codec_type") == "video")
    assert isinstance(video, dict)
    return video


def test_proxy_is_cfr_and_frame_count(
    media_client: TestClient, tmp_settings: Settings, tmp_path: Path
) -> None:
    src = write_hevc_video(tmp_path / "src_hevc.mp4", frames=45)
    # HEVC used below; this case uses a short H.264 source via FfmpegTool directly
    tool = FfmpegTool(tmp_settings.ffmpeg_bin, tmp_settings.ffprobe_bin)
    dest = tmp_path / "proxy.mp4"
    tool.make_proxy(src, dest)
    info = tool.probe(dest)
    duration = float(info["duration_s"])
    fps = float(info["fps"])
    n_frames = int(info["n_frames"] or 0)
    assert abs(n_frames - round(duration * fps)) <= 1
    stream = _video_stream(dest)
    assert stream.get("avg_frame_rate") == stream.get("r_frame_rate")
    assert info["is_vfr"] is False


@pytest.mark.parametrize(
    ("rotation", "expected_corner"),
    [(-90, "TR"), (90, "BL")],
)
def test_rotated_proxy_is_upright_and_has_no_rotation_flag(
    tmp_settings: Settings, tmp_path: Path, rotation: int, expected_corner: str
) -> None:
    src = write_corner_rotated_video(tmp_path / f"rot{rotation}.mp4", rotation=rotation)
    tool = FfmpegTool(tmp_settings.ffmpeg_bin, tmp_settings.ffprobe_bin)
    dest = tmp_path / f"proxy{rotation}.mp4"
    tool.make_proxy(src, dest)
    info = tool.probe(dest)
    assert int(info["rotation"] or 0) == 0
    assert int(info["height"] or 0) > int(info["width"] or 0)
    stream = _video_stream(dest)
    assert _stream_rotation(stream) == 0
    assert int(stream["height"]) > int(stream["width"])
    png = extract_png_frame(dest, 0, tmp_path / f"proxy{rotation}.png")
    assert _hot_corner(_read_png(png)) == expected_corner


def _stream_rotation(stream: dict[str, object]) -> int:
    side = stream.get("side_data_list")
    if isinstance(side, list):
        for item in side:
            if isinstance(item, dict) and item.get("rotation") not in (None, "", 0, 0.0):
                return int(float(item["rotation"]))
    tags = stream.get("tags")
    if isinstance(tags, dict) and tags.get("rotate") not in (None, "", "0", 0):
        return int(float(str(tags["rotate"])))
    return 0


def _hot_corner(image: object) -> str:
    import numpy as np

    arr = np.asarray(image)
    height, width = arr.shape[:2]
    box = max(8, min(height, width) // 16)
    patches = {
        "TL": arr[0:box, 0:box],
        "TR": arr[0:box, width - box : width],
        "BL": arr[height - box : height, 0:box],
        "BR": arr[height - box : height, width - box : width],
    }
    scores = {
        name: float(patch.astype("float32").max(axis=2).mean())
        for name, patch in patches.items()
    }
    return max(scores, key=scores.get)


def _read_png(path: Path) -> object:
    import cv2
    import numpy as np

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image)


def test_vfr_and_hevc_import(media_client: TestClient, tmp_path: Path) -> None:
    vfr = write_vfr_video(tmp_path / "vfr.mp4")
    hevc = write_hevc_video(tmp_path / "hevc.mp4")
    vfr_up = _upload(media_client, vfr, "vfr.mp4")
    hevc_up = _upload(media_client, hevc, "hevc.mp4")
    vfr_detail = media_client.get(
        f"/api/videos/{vfr_up['video']['id']}", headers=api_headers()
    ).json()
    hevc_detail = media_client.get(
        f"/api/videos/{hevc_up['video']['id']}", headers=api_headers()
    ).json()
    assert vfr_detail["ingest_status"] == "done"
    assert vfr_detail["is_vfr"] is True
    assert hevc_detail["ingest_status"] == "done"
    assert hevc_detail["codec"] in {"hevc", "h265"}
    assert hevc_detail["proxy_fps"]
    assert hevc_detail["n_frames"]
