"""CPU eval job writes metrics.json from the synthetic labelled fixture."""

from __future__ import annotations

from pathlib import Path

from ml.jobs import JOBS, eval_job


def test_eval_is_registered() -> None:
    assert JOBS["eval"] is eval_job


def test_eval_job_writes_metrics(tmp_path: Path) -> None:
    metrics = eval_job(tmp_path / "run")
    assert metrics["job"] == "eval"
    assert metrics["status"] == "passed"
    assert metrics["source"] == "synthetic"
    assert (tmp_path / "run" / "metrics.json").is_file()
    assert metrics["gates"]["standing_zero_proposals"] is True
    assert metrics["gates"]["sit_start_detected"] is True
    assert metrics["gates"]["two_attempts"] is True
    assert metrics["overall"]["n_match"] >= 3
