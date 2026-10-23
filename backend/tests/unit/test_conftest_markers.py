"""Media skip becomes a fail when CC_REQUIRE_MEDIA=1."""

from __future__ import annotations

import pytest

from tests.conftest import _skip_or_fail


def test_cc_require_media_fails_media_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_REQUIRE_MEDIA", "1")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    with pytest.raises(pytest.fail.Exception, match="ffmpeg 7"):
        _skip_or_fail("media", "ffmpeg 7+ is not available")


def test_cc_require_media_unset_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CC_REQUIRE_MEDIA", raising=False)
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="ffmpeg 7"):
        _skip_or_fail("media", "ffmpeg 7+ is not available")


def test_cc_require_media_does_not_force_other_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_REQUIRE_MEDIA", "1")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="ONNX"):
        _skip_or_fail("model", "ONNX weights are not available")
