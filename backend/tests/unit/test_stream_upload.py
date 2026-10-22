"""Upload writes chunks and never joins the whole body."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from app.errors import AppError
from app.services.ingest import content_length, stream_to_file


def test_stream_to_file_uses_chunks(tmp_path: Path) -> None:
    data = os.urandom(50_000)
    chunk = 4096

    def gen() -> object:
        for index in range(0, len(data), chunk):
            yield data[index : index + chunk]

    dest = tmp_path / "out.bin"
    digest, size = stream_to_file(gen(), dest, max_bytes=1_000_000)  # type: ignore[arg-type]
    assert size == len(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert dest.read_bytes() == data


def test_stream_to_file_enforces_max_and_removes_temp(tmp_path: Path) -> None:
    dest = tmp_path / "out.bin"
    with pytest.raises(AppError) as exc:
        stream_to_file(iter([b"abcd", b"efgh"]), dest, max_bytes=5)
    assert exc.value.status == 413
    assert not dest.exists()


def test_content_length_required_and_too_large() -> None:
    with pytest.raises(AppError) as missing:
        content_length(None, 100)
    assert missing.value.status == 400
    with pytest.raises(AppError) as huge:
        content_length("1000", 100)
    assert huge.value.status == 413
    assert content_length("50", 100) == 50
