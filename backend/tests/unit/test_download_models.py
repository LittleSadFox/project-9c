"""download_models.py refuses pickle files and sha256 mismatches."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from scripts.download_models import (
    DownloadError,
    download_one,
    import_from_volume,
    refuse_if_unsafe,
)


def test_refuse_pickle(tmp_path: Path) -> None:
    pickle_file = tmp_path / "model.pkl"
    pickle_file.write_bytes(b"nope")
    with pytest.raises(DownloadError, match="pickle"):
        refuse_if_unsafe(pickle_file)


def test_from_volume_refuses_joblib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    volume = tmp_path / "volume"
    run = volume / "runs" / "run-1"
    run.mkdir(parents=True)
    model = run / "weights.joblib"
    model.write_bytes(b"joblib")
    (run / "metrics.json").write_text(
        json.dumps({"files": {"weights.joblib": "abc"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CC_VOLUME_DIR", str(volume))
    with pytest.raises(DownloadError, match="joblib"):
        import_from_volume("run-1", tmp_path / "models")


def test_from_volume_sha256_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    volume = tmp_path / "volume"
    run = volume / "runs" / "run-2"
    run.mkdir(parents=True)
    model = run / "model.onnx"
    model.write_bytes(b"onnx-bytes")
    (run / "metrics.json").write_text(
        json.dumps({"files": {"model.onnx": "0" * 64}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CC_VOLUME_DIR", str(volume))
    with pytest.raises(DownloadError, match="sha256"):
        import_from_volume("run-2", tmp_path / "models")


def test_from_volume_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.download_models import sha256_file

    volume = tmp_path / "volume"
    run = volume / "runs" / "run-3"
    run.mkdir(parents=True)
    model = run / "model.onnx"
    model.write_bytes(b"onnx-bytes")
    digest = sha256_file(model)
    params = run / "params.json"
    params.write_text("{}", encoding="utf-8")
    (run / "metrics.json").write_text(
        json.dumps({"files": {"model.onnx": digest, "params.json": sha256_file(params)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CC_VOLUME_DIR", str(volume))
    dest = import_from_volume("run-3", tmp_path / "models")
    assert (dest / "model.onnx").read_bytes() == b"onnx-bytes"


PAYLOAD = b"fake-zip-bytes"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": "yolox_m",
        "url": "http://example.invalid/yolox_m.zip",
        "sha256": _digest(PAYLOAD),
        "dest": "det/yolox_m.zip",
    }
    entry.update(overrides)
    return entry


def _fake_urlopen(_url: str, timeout: int = 120) -> io.BytesIO:
    del timeout
    return io.BytesIO(PAYLOAD)


def test_download_sha256_mismatch_deletes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", _fake_urlopen)
    dest = tmp_path / "det" / "yolox_m.zip"
    with pytest.raises(DownloadError, match="sha256"):
        download_one(_lock_entry(sha256="0" * 64), tmp_path)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()


def test_download_null_sha256_refused_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used")

    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", boom)
    with pytest.raises(DownloadError, match="allow-unpinned"):
        download_one(_lock_entry(sha256=None), tmp_path)
    assert not (tmp_path / "det" / "yolox_m.zip").exists()


def test_download_null_sha256_allowed_with_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", _fake_urlopen)
    dest = download_one(_lock_entry(sha256=None), tmp_path, allow_unpinned=True)
    assert dest.read_bytes() == PAYLOAD


def test_download_skips_when_present_and_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "det" / "yolox_m.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(PAYLOAD)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used")

    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", boom)
    result = download_one(_lock_entry(), tmp_path)
    assert result == dest
    assert dest.read_bytes() == PAYLOAD


def test_download_present_mismatch_deletes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "det" / "yolox_m.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"wrong-bytes")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used after a mismatch")

    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", boom)
    with pytest.raises(DownloadError, match="sha256"):
        download_one(_lock_entry(), tmp_path)
    assert not dest.exists()
