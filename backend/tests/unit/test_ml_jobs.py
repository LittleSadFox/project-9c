"""ml.jobs gpu_tests writes metrics.json and registers the Phase 0 job."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ml.jobs import JOBS, JobError, check_cuda_session, gpu_tests, main, parse_junit
from ml.tiny_onnx import tiny_identity_bytes


def test_gpu_tests_is_registered() -> None:
    assert "gpu_tests" in JOBS
    assert callable(JOBS["gpu_tests"])


def test_tiny_identity_runs_on_cpu() -> None:
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(tiny_identity_bytes(), providers=["CPUExecutionProvider"])
    output = session.run(None, {"X": np.ones((1, 4), dtype=np.float32)})
    assert output[0].shape == (1, 4)
    assert session.get_providers()[0] == "CPUExecutionProvider"


def test_check_cuda_session_does_not_require_cuda_on_cpu() -> None:
    result = check_cuda_session(require_cuda=False)
    assert "session_providers" in result
    assert result["output_shape"] == [1, 4]


def test_parse_junit(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        """
        <testsuite tests="3" failures="1" skipped="1">
          <testcase name="ok"/>
          <testcase name="skip"><skipped message="ffmpeg 7+ is not available"/></testcase>
          <testcase name="fail"><failure message="boom"/></testcase>
        </testsuite>
        """,
        encoding="utf-8",
    )
    metrics = parse_junit(xml)
    assert metrics["passed"] == 1
    assert metrics["failed"] == 1
    assert metrics["skipped"] == 1
    assert metrics["skip_reasons"]["ffmpeg 7+ is not available"] == 1


def test_gpu_tests_job_writes_metrics(tmp_path: Path) -> None:
    sample = tmp_path / "sample_test.py"
    sample.write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    metrics = gpu_tests(
        run_dir,
        pytest_args=[str(sample), "-q"],
        require_cuda=False,
    )
    assert metrics["job"] == "gpu_tests"
    assert metrics["status"] == "passed"
    assert metrics["pytest"]["passed"] >= 1
    assert (run_dir / "metrics.json").is_file()
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    providers = ",".join(str(item) for item in metrics["cuda"]["session_providers"])
    used = "true" if metrics["cuda"]["used_cuda"] else "false"
    assert f"ort_providers={providers} used_cuda={used}" in log


def test_gpu_tests_writes_ort_providers_before_cuda_job_error(tmp_path: Path) -> None:
    sample = tmp_path / "sample_test.py"
    sample.write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    with pytest.raises(JobError, match="CUDAExecutionProvider"):
        gpu_tests(
            run_dir,
            pytest_args=[str(sample), "-q"],
            require_cuda=True,
        )
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "ort_providers=" in log
    assert "used_cuda=false" in log


def test_gpu_tests_writes_ort_providers_on_cuda_check_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*, require_cuda: bool) -> dict[str, object]:
        del require_cuda
        raise RuntimeError("ort missing")

    monkeypatch.setattr("ml.jobs.check_cuda_session", _boom)
    sample = tmp_path / "sample_test.py"
    sample.write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    with pytest.raises(JobError, match="CUDA session check failed"):
        gpu_tests(
            run_dir,
            pytest_args=[str(sample), "-q"],
            require_cuda=True,
        )
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "ort_providers=" in log
    assert "used_cuda=false" in log


def test_gpu_tests_does_not_leak_cc_require(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    sample = tmp_path / "sample_test.py"
    sample.write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    gpu_tests(
        tmp_path / "run",
        pytest_args=[str(sample), "-q"],
        require_cuda=False,
    )
    assert "CC_REQUIRE" not in os.environ


def test_gpu_tests_sets_require_only_in_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_MODELS_DIR", str(tmp_path / "no-models"))
    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path / "no-golden"))
    sample = tmp_path / "sample_test.py"
    sample.write_text(
        "import os\n"
        "def test_child_sees_require() -> None:\n"
        "    assert 'media' in os.environ.get('CC_REQUIRE', '')\n"
        "    assert 'model' not in os.environ.get('CC_REQUIRE', '').split(',')\n",
        encoding="utf-8",
    )
    metrics = gpu_tests(
        tmp_path / "run",
        pytest_args=[str(sample), "-q"],
        require_cuda=False,
    )
    assert metrics["status"] == "passed"
    assert "CC_REQUIRE" not in os.environ


def test_gpu_tests_drops_webhook_and_pod_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CC_WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.setenv("RUNPOD_API_KEY", "pod-scoped-key")
    sample = tmp_path / "sample_test.py"
    sample.write_text(
        "import os\n"
        "def test_child_has_no_secrets() -> None:\n"
        "    assert 'CC_WEBHOOK_URL' not in os.environ\n"
        "    assert 'RUNPOD_API_KEY' not in os.environ\n",
        encoding="utf-8",
    )
    metrics = gpu_tests(
        tmp_path / "run",
        pytest_args=[str(sample), "-q"],
        require_cuda=False,
    )
    assert metrics["status"] == "passed"


def test_ml_jobs_main_refuses_nested_gpu_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CC_IN_GPU_TESTS", "1")
    assert main(["gpu_tests", "--run-dir", str(tmp_path)]) == 1


def test_gpu_tests_sets_in_gpu_tests_only_in_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CC_IN_GPU_TESTS", raising=False)
    sample = tmp_path / "sample_test.py"
    sample.write_text(
        "import os\n"
        "def test_child_sees_guard() -> None:\n"
        "    assert os.environ.get('CC_IN_GPU_TESTS') == '1'\n",
        encoding="utf-8",
    )
    metrics = gpu_tests(
        tmp_path / "run",
        pytest_args=[str(sample), "-q"],
        require_cuda=False,
    )
    assert metrics["status"] == "passed"
    assert "CC_IN_GPU_TESTS" not in os.environ


def test_later_jobs_are_not_ready(tmp_path: Path) -> None:
    with pytest.raises(JobError, match="not implemented"):
        JOBS["finetune_pose"](tmp_path)
