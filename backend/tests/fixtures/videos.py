"""Generate short videos for media tests. Do not commit the output files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np

FRAME_BLOCK = 16
N_BITS = 16


def ffmpeg_bin() -> str:
    return os.environ.get("CC_FFMPEG_BIN", "ffmpeg")


def ffprobe_bin() -> str:
    return os.environ.get("CC_FFPROBE_BIN", "ffprobe")


def encode_frame_index(frame: int, width: int = 320, height: int = 240) -> np.ndarray:
    image = np.full((height, width, 3), 32, dtype=np.uint8)
    for bit in range(N_BITS):
        x0 = bit * FRAME_BLOCK
        color = 255 if (frame >> bit) & 1 else 0
        image[0:FRAME_BLOCK, x0 : x0 + FRAME_BLOCK] = color
    return image


def decode_frame_index(image: np.ndarray) -> int:
    value = 0
    for bit in range(N_BITS):
        x = bit * FRAME_BLOCK + FRAME_BLOCK // 2
        y = FRAME_BLOCK // 2
        pixel = image[y, x]
        if float(np.mean(pixel)) > 128:
            value |= 1 << bit
    return value


def write_frame_code_video(
    dest: Path, n_frames: int = 90, fps: float = 30.0, width: int = 320, height: int = 240
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for index in range(n_frames):
            proc.stdin.write(encode_frame_index(index, width, height).tobytes())
    finally:
        proc.stdin.close()
        code = proc.wait(timeout=60)
    if code != 0:
        raise RuntimeError("frame-code ffmpeg failed")
    return dest


def write_corner_rotated_video(
    dest: Path,
    *,
    rotation: int,
    width: int = 320,
    height: int = 180,
    frames: int = 8,
) -> Path:
    """Write a landscape clip with a red block in the stored top-left corner.

    Remux with -display_rotation so ffprobe sees the display matrix.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((height, width, 3), 16, dtype=np.uint8)
    image[0:40, 0:40] = (255, 0, 0)
    base = dest.with_name(dest.stem + ".base.mp4")
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        "15",
        "-i",
        "-",
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(base),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        blob = image.tobytes()
        for _ in range(frames):
            proc.stdin.write(blob)
    finally:
        proc.stdin.close()
        code = proc.wait(timeout=60)
    if code != 0:
        raise RuntimeError("corner ffmpeg failed")
    # -display_rotation is an input option. A remux writes the display matrix.
    subprocess.run(
        [
            ffmpeg_bin(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-display_rotation",
            str(rotation),
            "-i",
            str(base),
            "-c",
            "copy",
            str(dest),
        ],
        check=True,
        timeout=60,
    )
    base.unlink(missing_ok=True)
    return dest


def write_hevc_video(dest: Path, frames: int = 30) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate=30:duration={frames / 30}",
        "-c:v",
        "libx265",
        "-pix_fmt",
        "yuv420p",
        "-tag:v",
        "hvc1",
        str(dest),
    ]
    subprocess.run(cmd, check=True, timeout=60)
    return dest


def write_vfr_video(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=30:duration=2",
        "-fps_mode",
        "vfr",
        "-vf",
        "setpts=N*N*0.0008+0.04*N/TB",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    subprocess.run(cmd, check=True, timeout=60)
    return dest


def extract_png_frame(src: Path, frame: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vf",
        f"select=eq(n\\,{int(frame)})",
        "-vframes",
        "1",
        str(dest),
    ]
    subprocess.run(cmd, check=True, timeout=30)
    return dest


def probe_json(path: Path) -> dict[str, object]:
    import json

    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    payload = json.loads(result.stdout.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("ffprobe json was not an object")
    return payload
