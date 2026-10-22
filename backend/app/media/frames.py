"""FrameReader over a proxy video. Uses OpenCV."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


class FrameError(RuntimeError):
    """Raised when the proxy cannot be opened or a frame is missing."""


def normalize_frame(frame: object) -> np.ndarray:
    """Return a contiguous uint8 BGR HxWx3 frame for rtmlib."""
    array = np.asarray(frame)
    if array.ndim == 2:
        array = cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    elif array.ndim == 3 and array.shape[2] == 4:
        array = array[:, :, :3]
    elif array.ndim != 3 or array.shape[2] != 3:
        raise FrameError(f"Frame shape {array.shape} is not an image.")
    if array.dtype == np.uint16:
        peak = int(array.max()) if array.size else 0
        scale = 256.0 if peak > 1023 else 4.0
        array = np.clip(array.astype(np.float32) / scale, 0, 255).astype(np.uint8)
    elif array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def apply_rotation(frame: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate a frame so a tagged portrait clip is upright."""
    turns = int(degrees) % 360
    if turns == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if turns == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if turns == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def probe_rotation_degrees(path: Path) -> int:
    """Read the container rotation tag. 0 when none is set."""
    ffprobe = os.environ.get("CC_FFPROBE_BIN", "ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream_tags=rotate:stream_side_data=rotation",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode != 0 or not result.stdout.strip():
        return 0
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0
    streams = payload.get("streams") or []
    if not streams:
        return 0
    stream = streams[0]
    tags = stream.get("tags") or {}
    raw = tags.get("rotate")
    if raw is not None:
        try:
            return int(float(raw)) % 360
        except (TypeError, ValueError):
            pass
    for item in stream.get("side_data_list") or []:
        rotation = item.get("rotation")
        if rotation is None:
            continue
        try:
            return int(round(float(rotation))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def probe_video_stream(path: Path) -> dict[str, object]:
    """Read codec, pixel format, and size for the first video stream."""
    ffprobe = os.environ.get("CC_FFPROBE_BIN", "ffprobe")
    empty: dict[str, object] = {
        "codec_name": None,
        "pix_fmt": None,
        "width": None,
        "height": None,
    }
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,width,height:stream_tags=rotate:stream_side_data=rotation",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return empty
    if result.returncode != 0 or not result.stdout.strip():
        return empty
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return empty
    streams = payload.get("streams") or []
    if not streams:
        return empty
    stream = streams[0]
    return {
        "codec_name": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
        "width": stream.get("width"),
        "height": stream.get("height"),
    }


def make_upright_u8_proxy(src: Path, dest: Path) -> Path:
    """Transcode to an upright 8-bit H.264 proxy. ffmpeg applies the rotation tag."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    ffmpeg = os.environ.get("CC_FFMPEG_BIN", "ffmpeg")
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp.mp4")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-an",
        "-sn",
        "-vf",
        "format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if tmp.exists():
            tmp.unlink()
        raise FrameError(f"Cannot make a bench proxy from {src}: {exc}") from exc
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink()
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise FrameError(f"Cannot make a bench proxy from {src}: {detail}")
    os.replace(tmp, dest)
    return dest


class FrameReader:
    """Read proxy frames in order. Check the frame count against the database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise FrameError(f"The proxy cannot be opened: {self.path}")
        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> FrameReader:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _cap_or_raise(self) -> cv2.VideoCapture:
        if self._cap is None:
            raise FrameError("FrameReader is closed.")
        return self._cap

    @property
    def n_frames(self) -> int:
        return int(self._cap_or_raise().get(cv2.CAP_PROP_FRAME_COUNT))

    @property
    def fps(self) -> float:
        return float(self._cap_or_raise().get(cv2.CAP_PROP_FPS) or 0.0)

    @property
    def size(self) -> tuple[int, int]:
        cap = self._cap_or_raise()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return width, height

    def check_count(self, expected: int | None) -> int:
        """Compare the container frame count to the stored n_frames."""
        actual = self.n_frames
        if actual <= 0:
            raise FrameError(f"The proxy has no frames: {self.path}")
        if expected is not None and expected > 0 and actual != int(expected):
            raise FrameError(f"Proxy frame count is {actual}, expected {expected}.")
        return actual

    def read(self, index: int) -> np.ndarray:
        cap = self._cap_or_raise()
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(index))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise FrameError(f"Cannot read frame {index} from {self.path}.")
        return normalize_frame(frame)

    def iter_frames(self) -> Iterator[tuple[int, np.ndarray]]:
        cap = self._cap_or_raise()
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0.0)
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            yield index, normalize_frame(frame)
            index += 1
