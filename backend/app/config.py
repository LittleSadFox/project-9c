"""Frozen Settings from CC_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.errors import ConfigError

ALLOWED_DEVICES = frozenset({"auto", "cuda", "mps", "cpu"})
ALLOWED_POSE_BACKENDS = frozenset({"rtmlib", "fixture"})

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "ClimbingCoach"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Environment variables stay here. User prefs stay in SQLite."""

    library_dir: Path
    models_dir: Path
    golden_dir: Path
    ffmpeg_bin: str
    ffprobe_bin: str
    host: str
    port: int
    launch_token: str
    dev: bool
    max_upload_gb: float
    device: str
    pose_backend: str

    @classmethod
    def from_env(cls) -> Settings:
        """Read CC_* variables and fail with a clear error when a path is missing."""
        library_dir = _path_from_env("CC_LIBRARY_DIR", DEFAULT_ROOT / "library")
        models_dir = _path_from_env("CC_MODELS_DIR", DEFAULT_ROOT / "models")
        golden_dir = _path_from_env("CC_GOLDEN_DIR", DEFAULT_ROOT / "golden")
        _require_dir("CC_LIBRARY_DIR", library_dir)
        _require_dir("CC_MODELS_DIR", models_dir)
        _require_dir("CC_GOLDEN_DIR", golden_dir)

        device = os.environ.get("CC_DEVICE", "auto").strip() or "auto"
        if device not in ALLOWED_DEVICES:
            allowed = ", ".join(sorted(ALLOWED_DEVICES))
            raise ConfigError(f"CC_DEVICE is {device!r}. Use one of: {allowed}.")

        pose_backend = os.environ.get("CC_POSE_BACKEND", "rtmlib").strip() or "rtmlib"
        if pose_backend not in ALLOWED_POSE_BACKENDS:
            allowed = ", ".join(sorted(ALLOWED_POSE_BACKENDS))
            raise ConfigError(f"CC_POSE_BACKEND is {pose_backend!r}. Use one of: {allowed}.")

        port_raw = os.environ.get("CC_PORT", "8810").strip() or "8810"
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ConfigError(f"CC_PORT is {port_raw!r}. Use an integer port.") from exc
        if port < 1 or port > 65535:
            raise ConfigError(f"CC_PORT is {port}. Use a port from 1 to 65535.")

        upload_raw = os.environ.get("CC_MAX_UPLOAD_GB", "8").strip() or "8"
        try:
            max_upload_gb = float(upload_raw)
        except ValueError as exc:
            raise ConfigError(f"CC_MAX_UPLOAD_GB is {upload_raw!r}. Use a number.") from exc

        launch_token = os.environ.get("CC_LAUNCH_TOKEN", "").strip()
        if not launch_token:
            raise ConfigError("CC_LAUNCH_TOKEN is missing. Set a per-launch session token.")

        host = os.environ.get("CC_HOST", "127.0.0.1").strip() or "127.0.0.1"
        return cls(
            library_dir=library_dir,
            models_dir=models_dir,
            golden_dir=golden_dir,
            ffmpeg_bin=os.environ.get("CC_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg",
            ffprobe_bin=os.environ.get("CC_FFPROBE_BIN", "ffprobe").strip() or "ffprobe",
            host=host,
            port=port,
            launch_token=launch_token,
            dev=_truthy(os.environ.get("CC_DEV", "")),
            max_upload_gb=max_upload_gb,
            device=device,
            pose_backend=pose_backend,
        )

    def allowed_hosts(self) -> frozenset[str]:
        """Hosts that the Host header may use."""
        names = ("127.0.0.1", "localhost")
        allowed = {self.host, f"{self.host}:{self.port}"}
        for name in names:
            allowed.add(name)
            allowed.add(f"{name}:{self.port}")
        return frozenset(host.lower() for host in allowed)


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        raise ConfigError(f"{name} is empty. Set a directory path.")
    return Path(value).expanduser()


def _require_dir(name: str, path: Path) -> None:
    if path.is_dir():
        return
    raise ConfigError(
        f"{name} is missing or is not a directory: {path}. "
        "Create the folder or set the variable to an existing path."
    )


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
