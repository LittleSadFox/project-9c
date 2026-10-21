"""download_models.py refuses pickle files and sha256 mismatches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.download_models import DownloadError, import_from_volume, refuse_if_unsafe


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
