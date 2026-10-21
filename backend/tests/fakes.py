"""Test fakes for MediaTool and related protocols."""

from __future__ import annotations

from pathlib import Path


class FakeMediaTool:
    """MediaTool stand-in. API tests do not need ffmpeg."""

    def probe(self, path: Path) -> dict[str, object]:
        del path
        return {
            "duration_s": 1.0,
            "fps": 30.0,
            "width": 1280,
            "height": 720,
            "codec": "h264",
        }

    def make_proxy(self, src: Path, dest: Path) -> None:
        dest.write_bytes(src.read_bytes() if src.exists() else b"fake-proxy")

    def cut_clip(self, src: Path, dest: Path, start_s: float, end_s: float) -> None:
        del src, start_s, end_s
        dest.write_bytes(b"fake-clip")

    def extract_frame(self, src: Path, frame: int) -> bytes:
        del src, frame
        return b"fake-jpeg"

    def thumbnails(self, src: Path, dest_dir: Path) -> list[Path]:
        del src
        dest_dir.mkdir(parents=True, exist_ok=True)
        thumb = dest_dir / "0.jpg"
        thumb.write_bytes(b"fake-thumb")
        return [thumb]

    def render(self, frames_iter: object, dest: Path) -> None:
        del frames_iter
        dest.write_bytes(b"fake-render")
