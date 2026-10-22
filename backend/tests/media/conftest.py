"""Media tests use the real FfmpegTool."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.media.ffmpeg import FfmpegTool
from app.pose.estimator import FixtureEstimator
from tests.conftest import api_headers


@pytest.fixture(autouse=True)
def _skip_without_ffmpeg_or_ffprobe() -> None:
    ffmpeg = shutil.which(os.environ.get("CC_FFMPEG_BIN", "ffmpeg") or "ffmpeg")
    ffprobe = shutil.which(os.environ.get("CC_FFPROBE_BIN", "ffprobe") or "ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("ffmpeg or ffprobe is not on PATH")


@pytest.fixture
def media_app(tmp_settings: Settings) -> object:
    tool = FfmpegTool(tmp_settings.ffmpeg_bin, tmp_settings.ffprobe_bin)
    return create_app(tmp_settings, media=tool, estimator=FixtureEstimator())


@pytest.fixture
def media_client(media_app: object, tmp_settings: Settings) -> Iterator[TestClient]:
    with TestClient(media_app, raise_server_exceptions=False) as client:
        client.get(
            f"/auth/launch?token={tmp_settings.launch_token}",
            headers=api_headers(),
            follow_redirects=False,
        )
        yield client
