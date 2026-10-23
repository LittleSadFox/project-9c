"""Test fakes for MediaTool and related protocols."""

from __future__ import annotations

from pathlib import Path

from app.media.tool import MediaError

MIN_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def looks_like_text(data: bytes) -> bool:
    sample = data[:1024]
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


class FakeMediaTool:
    """MediaTool stand-in. API tests do not need ffmpeg."""

    def __init__(self) -> None:
        self.proxy_fps = 30.0
        self.proxy_long_side = 1280

    def probe(self, path: Path) -> dict[str, object]:
        if not path.is_file():
            raise MediaError("not_video", "This file is not a video.")
        data = path.read_bytes()
        if looks_like_text(data):
            raise MediaError("not_video", "This file is not a video.")
        return {
            "duration_s": 1.0,
            "fps": 30.0,
            "width": 1280,
            "height": 720,
            "codec": "h264",
            "is_vfr": False,
            "rotation": 0,
            "n_frames": 30,
            "recorded_at": None,
        }

    def make_proxy(self, src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes() if src.exists() else b"fake-proxy")

    def cut_clip(self, src: Path, dest: Path, start_s: float, end_s: float) -> None:
        del src, start_s, end_s
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-clip" * 32)

    def extract_frame(self, src: Path, frame: int) -> bytes:
        del src, frame
        return MIN_JPEG

    def thumbnails(self, src: Path, dest_dir: Path) -> list[Path]:
        del src
        dest_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for index in range(2):
            thumb = dest_dir / f"{index}.jpg"
            thumb.write_bytes(MIN_JPEG)
            written.append(thumb)
        return written

    def render(self, frames_iter: object, dest: Path) -> None:
        del frames_iter
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-render")
