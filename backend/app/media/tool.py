"""MediaTool protocol. FakeMediaTool lives in tests."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class MediaError(Exception):
    """Raised when probe or ffmpeg work fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MediaTool(Protocol):
    """ffmpeg work used by ingest, cut, and render jobs."""

    def probe(self, path: Path) -> dict[str, object]: ...

    def make_proxy(self, src: Path, dest: Path) -> None: ...

    def cut_clip(self, src: Path, dest: Path, start_s: float, end_s: float) -> None: ...

    def extract_frame(self, src: Path, frame: int) -> bytes: ...

    def thumbnails(self, src: Path, dest_dir: Path) -> list[Path]: ...

    def render(self, frames_iter: object, dest: Path) -> None: ...
