"""safe_join and safe_ext refuse escapes and unknown suffixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.storage import VIDEO_EXTS, safe_ext, safe_join


def test_safe_ext_accepts_video_suffix(tmp_path: Path) -> None:
    path = safe_ext(tmp_path / "sample1.mp4", VIDEO_EXTS)
    assert path.suffix == ".mp4"


def test_safe_ext_rejects_other_suffix(tmp_path: Path) -> None:
    with pytest.raises(AppError) as exc:
        safe_ext(tmp_path / "notes.txt", VIDEO_EXTS)
    assert exc.value.status == 400
    assert exc.value.code == "bad_path"


def test_safe_join_then_safe_ext(tmp_path: Path) -> None:
    path = safe_ext(safe_join(tmp_path, "sample1.mp4"), VIDEO_EXTS)
    assert path == (tmp_path / "sample1.mp4").resolve()
