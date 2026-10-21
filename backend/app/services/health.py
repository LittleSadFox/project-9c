"""Build the /health payload."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from typing import Any

from app import __version__
from app.config import Settings
from app.storage import LibraryPaths


def build_health(settings: Settings, conn: sqlite3.Connection) -> dict[str, Any]:
    """Collect status for the health endpoint. No session is required."""
    db_status = _db_status(conn)
    ffmpeg = _ffmpeg_info(settings.ffmpeg_bin)
    onnx = _onnx_info(settings.device)
    free_gb = shutil.disk_usage(settings.library_dir).free / (1024**3)
    status = "ok" if db_status == "ok" else "degraded"
    return {
        "status": status,
        "version": __version__,
        "db": db_status,
        "ffmpeg": ffmpeg,
        "onnx": onnx,
        "library_free_gb": round(free_gb, 2),
        "dev": settings.dev,
    }


def _db_status(conn: sqlite3.Connection) -> str:
    try:
        conn.execute("SELECT 1")
        return "ok"
    except sqlite3.Error:
        return "error"


def _ffmpeg_info(ffmpeg_bin: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"version": "unknown", "h264_encoder": "unknown"}
    first = (result.stdout or result.stderr).splitlines()
    version = first[0] if first else "unknown"
    encoder = "unknown"
    if "libx264" in (result.stdout or ""):
        encoder = "libx264"
    return {"version": version, "h264_encoder": encoder}


def _onnx_info(device: str) -> dict[str, Any]:
    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        providers = list(ort.get_available_providers())
    except Exception:
        providers = []
    return {"providers": providers, "device": device}


def library_paths(settings: Settings) -> LibraryPaths:
    return LibraryPaths(settings.library_dir)
