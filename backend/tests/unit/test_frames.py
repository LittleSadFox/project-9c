"""FrameReader checks. A missing file raises FrameError."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.media.frames import FrameError, FrameReader


def test_missing_proxy_raises(tmp_path: Path) -> None:
    reader = FrameReader(tmp_path / "missing.mp4")
    with pytest.raises(FrameError, match="cannot be opened"):
        reader.open()


def test_closed_reader_raises() -> None:
    reader = FrameReader(Path("/tmp/unused.mp4"))
    with pytest.raises(FrameError, match="closed"):
        _ = reader.n_frames
