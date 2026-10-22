"""pose_bench writes metrics with the fixture backend."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.pose.estimator import POSE_MODES, FixtureEstimator
from ml.jobs import (
    JOBS,
    JobError,
    _take_frames,
    compare_keypoints,
    ensure_bench_weights,
    pose_bench,
)


def test_pose_bench_is_registered() -> None:
    assert JOBS["pose_bench"] is pose_bench


def test_pose_bench_fixture_writes_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")
    run_dir = tmp_path / "run"
    metrics = pose_bench(run_dir, n_frames=8, require_cuda=False)
    assert metrics["job"] == "pose_bench"
    assert metrics["status"] == "passed"
    assert metrics["backend"] == "fixture"
    assert list(metrics["modes"]) == list(POSE_MODES)
    assert metrics["modes"]["balanced"]["cpu"]["fps"] > 0
    saved = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert saved["status"] == "passed"
    assert "pose_bench status=passed" in (run_dir / "log.txt").read_text(encoding="utf-8")


def test_pose_bench_passes_mode_to_estimator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    class RecordingEstimator(FixtureEstimator):
        def __init__(self, *args: object, mode: str = "balanced", **kwargs: object) -> None:
            super().__init__(*args, mode=mode, **kwargs)  # type: ignore[arg-type]
            seen.append(mode)

    monkeypatch.setattr("app.pose.estimator.FixtureEstimator", RecordingEstimator)
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")
    pose_bench(tmp_path / "run", n_frames=4, require_cuda=False, modes=["performance"])
    assert seen
    assert all(mode == "performance" for mode in seen)


def _empty() -> np.ndarray:
    return np.zeros((0, 26, 2), dtype=np.float32)


def _kpts(*, shift: float = 0.0) -> np.ndarray:
    array = np.zeros((1, 26, 2), dtype=np.float32)
    array[..., 0] = 10.0 + shift
    array[..., 1] = 20.0
    return array


def test_compare_keypoints_zero_compared_fails() -> None:
    cpu = [_empty() for _ in range(100)]
    cuda = [_empty() for _ in range(100)]
    result = compare_keypoints(cpu, cuda, frames_total=100, min_compared_frac=0.9)
    assert result["frames_compared"] == 0
    assert result["mean_abs_px"] is None
    assert result["parity_ok"] is False


def test_compare_keypoints_three_of_hundred_fails() -> None:
    cpu = [_kpts() if index < 3 else _empty() for index in range(100)]
    cuda = [_kpts() if index < 3 else _empty() for index in range(100)]
    result = compare_keypoints(cpu, cuda, frames_total=100, min_compared_frac=0.9)
    assert result["frames_compared"] == 3
    assert result["mean_abs_px"] == 0.0
    assert result["parity_ok"] is False


def test_compare_keypoints_ninety_five_within_one_px_passes() -> None:
    cpu = [_kpts() if index < 95 else _empty() for index in range(100)]
    cuda = [_kpts() if index < 95 else _empty() for index in range(100)]
    result = compare_keypoints(cpu, cuda, frames_total=100, min_compared_frac=0.9)
    assert result["frames_compared"] == 95
    assert result["mean_abs_px"] is not None
    assert result["mean_abs_px"] <= 1.0
    assert result["parity_ok"] is True


def test_compare_keypoints_ninety_five_over_one_px_fails() -> None:
    cpu = [_kpts() if index < 95 else _empty() for index in range(100)]
    cuda = [_kpts(shift=2.0) if index < 95 else _empty() for index in range(100)]
    result = compare_keypoints(cpu, cuda, frames_total=100, min_compared_frac=0.9)
    assert result["frames_compared"] == 95
    assert result["mean_abs_px"] is not None
    assert result["mean_abs_px"] > 1.0
    assert result["parity_ok"] is False


def test_pose_bench_zero_compared_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")

    def no_compare(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "mean_abs_px": None,
            "parity_ok": False,
            "frames_total": 8,
            "frames_with_detections_cpu": 0,
            "frames_with_detections_cuda": 0,
            "frames_compared": 0,
            "min_compared_frac": 0.9,
            "parity_limit_px": 1.0,
        }

    monkeypatch.setattr("ml.jobs.compare_keypoints", no_compare)
    run_dir = tmp_path / "run"
    with pytest.raises(JobError):
        pose_bench(run_dir, n_frames=8, require_cuda=False, modes=["balanced"])
    saved = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
    assert saved["modes"]["balanced"]["cuda"]["parity_ok"] is False
    assert saved["modes"]["balanced"]["cuda"]["frames_compared"] == 0
    assert saved["frames_compared"] == 0


def test_take_frames_stops_at_n() -> None:
    reads = {"n": 0}

    def source() -> object:
        for index in range(1000):
            reads["n"] += 1
            yield index, f"frame-{index}"

    frames = _take_frames(source(), 5)
    assert frames == ["frame-0", "frame-1", "frame-2", "frame-3", "frame-4"]
    assert reads["n"] == 5


def test_load_bench_frames_does_not_read_past_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ml.jobs import _load_bench_frames

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    reads = {"n": 0, "closed": False}

    class CountingReader:
        def __init__(self, _path: Path) -> None:
            del _path

        def __enter__(self) -> CountingReader:
            return self

        def __exit__(self, *_exc: object) -> None:
            reads["closed"] = True

        def iter_frames(self) -> object:
            for index in range(1000):
                reads["n"] += 1
                yield index, np.zeros((2, 2, 3), dtype=np.uint8)

    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path))
    monkeypatch.setattr("app.media.frames.FrameReader", CountingReader)
    frames = _load_bench_frames(7)
    assert len(frames) == 7
    assert reads["n"] == 7
    assert reads["closed"] is True


def test_ensure_bench_weights_skips_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"present-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "det" / "yolox_m.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(payload)
    entry = {
        "name": "yolox_m",
        "url": "http://example.invalid/yolox_m.zip",
        "sha256": digest,
        "dest": "det/yolox_m.zip",
    }

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used")

    monkeypatch.setattr("scripts.download_models.load_lock", lambda: [entry])
    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", boom)
    names = ensure_bench_weights(tmp_path, ["balanced"])
    assert names == ["yolox_m"]
    assert dest.read_bytes() == payload


def test_ensure_bench_weights_mismatch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "det" / "yolox_m.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"wrong")
    entry = {
        "name": "yolox_m",
        "url": "http://example.invalid/yolox_m.zip",
        "sha256": "0" * 64,
        "dest": "det/yolox_m.zip",
    }

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network should not be used after a mismatch")

    monkeypatch.setattr("scripts.download_models.load_lock", lambda: [entry])
    monkeypatch.setattr("scripts.download_models.urllib.request.urlopen", boom)
    with pytest.raises(JobError, match="sha256"):
        ensure_bench_weights(tmp_path, ["balanced"])
    assert not dest.exists()
