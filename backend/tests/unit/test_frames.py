"""FrameReader checks. A missing file raises FrameError."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.media.frames import FrameError, FrameReader, apply_rotation, normalize_frame


def test_missing_proxy_raises(tmp_path: Path) -> None:
    reader = FrameReader(tmp_path / "missing.mp4")
    with pytest.raises(FrameError, match="cannot be opened"):
        reader.open()


def test_closed_reader_raises() -> None:
    reader = FrameReader(Path("/tmp/unused.mp4"))
    with pytest.raises(FrameError, match="closed"):
        _ = reader.n_frames


def test_normalize_frame_scales_10bit_and_stays_bgr() -> None:
    frame = np.full((4, 6, 3), 1023, dtype=np.uint16)
    frame[:, :, 0] = 100
    out = normalize_frame(frame)
    assert out.dtype == np.uint8
    assert out.shape == (4, 6, 3)
    assert bool(out.flags["C_CONTIGUOUS"])
    assert int(out[0, 0, 0]) == 25
    assert int(out[0, 0, 1]) == 255


def test_apply_rotation_90_swaps_axes() -> None:
    frame = np.zeros((8, 4, 3), dtype=np.uint8)
    frame[0, 0] = (1, 2, 3)
    out = apply_rotation(frame, 90)
    assert out.shape == (4, 8, 3)
    assert list(out[0, -1]) == [1, 2, 3]
