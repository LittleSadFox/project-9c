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
    probe_json,
    write_hevc_video,
    write_rotated_video,
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


def test_rotation_90_comes_out_upright(
    media_client: TestClient, tmp_settings: Settings, tmp_path: Path
) -> None:
    src = write_rotated_video(tmp_path / "rot90.mp4")
    uploaded = _upload(media_client, src, "rot90.mp4")
    video_id = str(uploaded["video"]["id"])
    detail = media_client.get(f"/api/videos/{video_id}", headers=api_headers()).json()
    assert detail["proxy_width"] is not None
    assert detail["proxy_height"] is not None
    assert int(detail["proxy_height"]) > int(detail["proxy_width"])
    proxy = tmp_settings.library_dir / "proxies" / f"{video_id}.mp4"
    stream = _video_stream(proxy)
    width = int(stream["width"])
    height = int(stream["height"])
    assert height > width


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
