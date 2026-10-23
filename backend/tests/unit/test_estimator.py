"""Fixture estimator: no boxes means no pose call."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pytest

from app.pose.estimator import FixtureEstimator, empty_boxes, resolve_device, resolve_onnx_file
from app.services.pose_service import process_frames


def test_estimate_skips_pose_when_detector_is_empty() -> None:
    estimator = FixtureEstimator()
    result = estimator.estimate(np.zeros((16, 16, 3), dtype=np.uint8))
    assert estimator.detect_calls == 1
    assert estimator.pose_calls == 0
    assert result["tracks"] == []
    assert np.asarray(result["boxes"]).shape[0] == 0


def test_process_frames_no_boxes_means_zero_tracks() -> None:
    estimator = FixtureEstimator()
    frames = [(index, np.zeros((16, 16, 3), dtype=np.uint8)) for index in range(12)]
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=5)
    assert estimator.pose_calls == 0
    assert tracks == []
    assert climber is None


def test_fixture_pose_runs_only_when_boxes_exist() -> None:
    detections = {
        0: np.array([[10.0, 10.0, 50.0, 80.0]], dtype=np.float32),
        5: empty_boxes(),
    }
    estimator = FixtureEstimator(detections=detections)
    frames = [(index, np.zeros((16, 16, 3), dtype=np.uint8)) for index in range(6)]
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=1)
    assert estimator.pose_calls == 1
    assert len(tracks) == 1
    assert climber == tracks[0].track_id


def test_resolve_device_cpu() -> None:
    assert resolve_device("cpu") == "cpu"


def _write_onnx_zip(path: Path, payload: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("end2end.onnx", payload)
    return path


def test_interrupted_extract_leaves_no_final_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zip_path = _write_onnx_zip(tmp_path / "yolox_tiny.zip", b"onnx-bytes")
    extract_dir = zip_path.with_suffix("")

    def boom(self: zipfile.ZipFile, dest: object) -> None:
        Path(str(dest)).mkdir(parents=True, exist_ok=True)
        (Path(str(dest)) / "partial").write_bytes(b"x")
        raise RuntimeError("interrupted extract")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", boom)
    with pytest.raises(RuntimeError, match="interrupted extract"):
        resolve_onnx_file(zip_path)
    assert not extract_dir.exists()
    leftovers = [path for path in tmp_path.iterdir() if path.name.startswith("yolox_tiny.extract.")]
    assert leftovers == []


def test_truncated_onnx_is_detected_and_reextracted(tmp_path: Path) -> None:
    payload = b"full-end2end-onnx-bytes"
    zip_path = _write_onnx_zip(tmp_path / "rtmpose_s_halpe26.zip", payload)
    extract_dir = zip_path.with_suffix("")
    extract_dir.mkdir()
    truncated = extract_dir / "end2end.onnx"
    truncated.write_bytes(payload[:4])
    found = resolve_onnx_file(zip_path)
    assert found.read_bytes() == payload
    assert found.stat().st_size == len(payload)
