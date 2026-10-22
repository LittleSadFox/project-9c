"""pose_bench writes metrics with the fixture backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.jobs import JOBS, pose_bench


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
    assert "balanced" in metrics["modes"]
    assert metrics["modes"]["balanced"]["cpu"]["fps"] > 0
    saved = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert saved["status"] == "passed"
    assert "pose_bench status=passed" in (run_dir / "log.txt").read_text(encoding="utf-8")
