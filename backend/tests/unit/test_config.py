"""Settings fail with a clear error when a CC_* path is missing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.errors import ConfigError


def _set_ok_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    library = tmp_path / "library"
    models = tmp_path / "models"
    golden = tmp_path / "golden"
    library.mkdir()
    models.mkdir()
    golden.mkdir()
    monkeypatch.setenv("CC_LIBRARY_DIR", str(library))
    monkeypatch.setenv("CC_MODELS_DIR", str(models))
    monkeypatch.setenv("CC_GOLDEN_DIR", str(golden))
    monkeypatch.setenv("CC_LAUNCH_TOKEN", "unit-test-token")


def test_missing_library_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ok_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("CC_LIBRARY_DIR", str(tmp_path / "missing-library"))
    with pytest.raises(ConfigError, match="CC_LIBRARY_DIR"):
        Settings.from_env()


def test_missing_models_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ok_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("CC_MODELS_DIR", str(tmp_path / "missing-models"))
    with pytest.raises(ConfigError, match="CC_MODELS_DIR"):
        Settings.from_env()


def test_missing_golden_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ok_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path / "missing-golden"))
    with pytest.raises(ConfigError, match="CC_GOLDEN_DIR"):
        Settings.from_env()


def test_empty_library_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ok_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("CC_LIBRARY_DIR", "   ")
    with pytest.raises(ConfigError, match="CC_LIBRARY_DIR"):
        Settings.from_env()


def test_from_env_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_ok_dirs(monkeypatch, tmp_path)
    settings = Settings.from_env()
    assert settings.library_dir == tmp_path / "library"
    assert settings.port == 8810
    assert settings.device == "auto"
