"""Shared fixtures and marker skip rules."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import apply_migrations, connect
from app.main import create_app
from app.pose.estimator import FixtureEstimator
from tests.fakes import FakeMediaTool

HOST = "127.0.0.1:8810"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "media: needs ffmpeg 7+ and ffprobe")
    config.addinivalue_line("markers", "model: needs ONNX weights")
    config.addinivalue_line("markers", "gpu: needs CUDAExecutionProvider")
    config.addinivalue_line("markers", "macos: needs CoreML or VideoToolbox on a Mac")
    config.addinivalue_line("markers", "golden: needs labelled footage")
    config.addinivalue_line("markers", "slow: omit from the default run")


def _required() -> set[str]:
    raw = os.environ.get("CC_REQUIRE", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _require_media() -> bool:
    raw = os.environ.get("CC_REQUIRE_MEDIA", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _skip_or_fail(name: str, reason: str) -> None:
    if name in _required():
        pytest.fail(f"CC_REQUIRE includes {name}, but the need is missing: {reason}")
    if name == "media" and _require_media():
        pytest.fail(f"CC_REQUIRE_MEDIA=1, but the need is missing: {reason}")
    pytest.skip(reason)


def _media_bin(name: str, env_key: str) -> str | None:
    raw = os.environ.get(env_key, name).strip() or name
    return shutil.which(raw)


def _media_bins_on_path() -> bool:
    return (
        _media_bin("ffmpeg", "CC_FFMPEG_BIN") is not None
        and _media_bin("ffprobe", "CC_FFPROBE_BIN") is not None
    )


def _ffmpeg_major() -> int | None:
    ffmpeg = _media_bin("ffmpeg", "CC_FFMPEG_BIN")
    if ffmpeg is None:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or "").splitlines()[:1]
    if not line:
        return None
    for token in line[0].replace("n", " ").split():
        if token and token[0].isdigit():
            try:
                return int(token.split(".")[0])
            except ValueError:
                return None
    return None


def pytest_runtest_setup(item: pytest.Item) -> None:
    marks = {mark.name for mark in item.iter_markers()}
    if "media" in marks:
        if not _media_bins_on_path():
            _skip_or_fail("media", "ffmpeg or ffprobe is not on PATH")
        major = _ffmpeg_major()
        if major is None or major < 7:
            _skip_or_fail("media", "ffmpeg 7+ is not available")
    if "model" in marks:
        models = Path(os.environ.get("CC_MODELS_DIR", ""))
        if not models.is_dir() or not any(models.rglob("*.onnx")):
            _skip_or_fail("model", "ONNX weights are not available")
    if "gpu" in marks:
        try:
            import onnxruntime as ort

            if "CUDAExecutionProvider" not in ort.get_available_providers():
                _skip_or_fail("gpu", "CUDAExecutionProvider is not available")
        except Exception:
            _skip_or_fail("gpu", "onnxruntime is not available")
    if "macos" in marks:
        if os.uname().sysname != "Darwin":
            _skip_or_fail("macos", "this machine is not a Mac")
    if "golden" in marks:
        golden = Path(os.environ.get("CC_GOLDEN_DIR", ""))
        if not golden.is_dir() or not any(golden.iterdir()):
            _skip_or_fail("golden", "labelled footage is not available")


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    library = tmp_path / "library"
    models = tmp_path / "models"
    golden = tmp_path / "golden"
    library.mkdir()
    models.mkdir()
    golden.mkdir()
    return Settings(
        library_dir=library,
        models_dir=models,
        golden_dir=golden,
        ffmpeg_bin=os.environ.get("CC_FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.environ.get("CC_FFPROBE_BIN", "ffprobe"),
        host="127.0.0.1",
        port=8810,
        launch_token="test-launch-token-value-32chars",
        dev=False,
        max_upload_gb=8.0,
        device="cpu",
        pose_backend="fixture",
    )


@pytest.fixture
def db_conn(tmp_settings: Settings) -> Iterator[object]:
    conn = connect(tmp_settings.library_dir / "library.sqlite3")
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app(tmp_settings: Settings) -> object:
    return create_app(tmp_settings, media=FakeMediaTool(), estimator=FixtureEstimator())


@pytest.fixture
def client(app: object) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client: TestClient, tmp_settings: Settings) -> TestClient:
    launch = client.get(
        f"/auth/launch?token={tmp_settings.launch_token}",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert launch.status_code == 303
    return client


def api_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Host": HOST}
    if extra:
        headers.update(extra)
    return headers
