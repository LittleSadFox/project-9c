"""A proxy from the 1080p file matches the original n_frames and proxy_fps."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.sync_volume_prep import transcode_to_1080p

from app.config import Settings
from app.media.ffmpeg import FfmpegTool
from tests.fixtures.videos import write_corner_rotated_video, write_hevc_video

pytestmark = pytest.mark.media


def test_proxy_from_1080p_matches_original_n_frames_and_fps(
    tmp_settings: Settings, tmp_path: Path
) -> None:
    src = write_hevc_video(tmp_path / "orig.mp4", frames=45)
    transcoded = tmp_path / "1080p.mp4"
    transcode_to_1080p(src, transcoded)
    tool = FfmpegTool(tmp_settings.ffmpeg_bin, tmp_settings.ffprobe_bin)
    orig_proxy = tmp_path / "proxy_orig.mp4"
    trans_proxy = tmp_path / "proxy_1080.mp4"
    tool.make_proxy(src, orig_proxy)
    tool.make_proxy(transcoded, trans_proxy)
    orig_info = tool.probe(orig_proxy)
    trans_info = tool.probe(trans_proxy)
    src_1080 = tool.probe(transcoded)
    assert src_1080["codec"] == "h264"
    assert max(int(src_1080["width"] or 0), int(src_1080["height"] or 0)) == 1920
    assert abs(int(orig_info["n_frames"] or 0) - int(trans_info["n_frames"] or 0)) <= 1
    assert abs(float(orig_info["fps"] or 0) - float(trans_info["fps"] or 0)) < 0.01


def test_1080p_prestep_applies_iphone_rotation(
    tmp_settings: Settings, tmp_path: Path
) -> None:
    src = write_corner_rotated_video(tmp_path / "rot-90.mp4", rotation=-90, frames=12)
    transcoded = tmp_path / "1080p.mp4"
    transcode_to_1080p(src, transcoded)
    tool = FfmpegTool(tmp_settings.ffmpeg_bin, tmp_settings.ffprobe_bin)
    info = tool.probe(transcoded)
    assert int(info["rotation"] or 0) == 0
    assert int(info["height"] or 0) > int(info["width"] or 0)
    orig_proxy = tmp_path / "proxy_orig.mp4"
    trans_proxy = tmp_path / "proxy_1080.mp4"
    tool.make_proxy(src, orig_proxy)
    tool.make_proxy(transcoded, trans_proxy)
    orig_info = tool.probe(orig_proxy)
    trans_info = tool.probe(trans_proxy)
    assert abs(int(orig_info["n_frames"] or 0) - int(trans_info["n_frames"] or 0)) <= 1
    assert abs(float(orig_info["fps"] or 0) - float(trans_info["fps"] or 0)) < 0.01
