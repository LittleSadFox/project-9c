"""Pod job registry.

Phase 0 implements gpu_tests.
Later phases add pose_bench, eval, train_events, tune_align, and finetune_pose.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ml.tiny_onnx import tiny_identity_bytes

ROOT = Path(__file__).resolve().parents[1]
JobFn = Callable[[Path], dict[str, Any]]


class JobError(Exception):
    """Raised when a pod job cannot run."""


def ffmpeg_version() -> str | None:
    ffmpeg = shutil.which(os.environ.get("CC_FFMPEG_BIN", "ffmpeg"))
    if ffmpeg is None:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or "").splitlines()[:1]
    return line[0] if line else None


def parse_junit(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"passed": 0, "failed": 0, "skipped": 0, "error": 0, "skip_reasons": {}}
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    passed = 0
    failed = 0
    skipped = 0
    error = 0
    reasons: dict[str, int] = {}
    for suite in suites:
        for case in suite.findall("testcase"):
            skip = case.find("skipped")
            fail = case.find("failure")
            err = case.find("error")
            if skip is not None:
                skipped += 1
                message = skip.get("message") or skip.text or "skipped"
                reasons[message] = reasons.get(message, 0) + 1
            elif fail is not None:
                failed += 1
            elif err is not None:
                error += 1
            else:
                passed += 1
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "error": error,
        "skip_reasons": reasons,
    }


def check_cuda_session(*, require_cuda: bool) -> dict[str, Any]:
    """Create a session and read session.get_providers(), not only the available list."""
    import numpy as np
    import onnxruntime as ort

    available = list(ort.get_available_providers())
    requested = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession(tiny_identity_bytes(), providers=requested)
    used = list(session.get_providers())
    feeds = {"X": np.zeros((1, 4), dtype=np.float32)}
    outputs = session.run(None, feeds)
    used_cuda = bool(used) and used[0] == "CUDAExecutionProvider"
    result = {
        "available_providers": available,
        "session_providers": used,
        "used_cuda": used_cuda,
        "output_shape": list(outputs[0].shape) if outputs else [],
    }
    if require_cuda and not used_cuda:
        raise JobError(
            "CUDAExecutionProvider did not run the session. "
            f"session.get_providers()={used!r}."
        )
    return result


def gpu_tests(run_dir: Path, *, pytest_args: list[str] | None = None, require_cuda: bool = True) -> dict[str, Any]:
    """Run every pytest tier that Linux supports. Record counts and the CUDA check."""
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    junit = artifacts / "junit.xml"

    args = pytest_args or [
        str(ROOT / "backend" / "tests"),
        "-m",
        "not macos",
        "--tb=short",
    ]
    cmd = [sys.executable, "-m", "pytest", *args, f"--junitxml={junit}"]
    env = os.environ.copy()
    env.pop("CC_WEBHOOK_URL", None)
    env.pop("RUNPOD_API_KEY", None)
    env["CC_IN_GPU_TESTS"] = "1"
    require = env.get("CC_REQUIRE", "").strip()
    if not require:
        bits = ["media"]
        if require_cuda:
            bits.append("gpu")
        models = Path(env.get("CC_MODELS_DIR", "/workspace/models"))
        if models.is_dir() and any(models.rglob("*.onnx")):
            bits.append("model")
        golden = Path(env.get("CC_GOLDEN_DIR", "/workspace/videos"))
        if golden.is_dir() and any(golden.iterdir()):
            bits.append("golden")
        env["CC_REQUIRE"] = ",".join(bits)
    env["PYTHONPATH"] = f"{ROOT / 'backend'}{os.pathsep}{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    pytest_metrics = parse_junit(junit)
    cuda_metrics: dict[str, Any]
    try:
        cuda_metrics = check_cuda_session(require_cuda=require_cuda)
    except JobError:
        raise
    except Exception as exc:
        if require_cuda:
            raise JobError(f"CUDA session check failed: {exc}") from exc
        cuda_metrics = {"error": str(exc), "used_cuda": False}

    status = "passed"
    if proc.returncode != 0 or pytest_metrics["failed"] or pytest_metrics["error"]:
        status = "failed"
    metrics = {
        "job": "gpu_tests",
        "status": status,
        "pytest": pytest_metrics,
        "cuda": cuda_metrics,
        "ffmpeg": {"version": ffmpeg_version()},
        "exit_code": proc.returncode,
    }
    dest = run_dir / "metrics.json"
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    if status != "passed":
        raise JobError("gpu_tests failed.")
    return metrics


def _not_ready(name: str) -> JobFn:
    def _job(run_dir: Path) -> dict[str, Any]:
        del run_dir
        raise JobError(f"{name} is not implemented in Phase 0.")

    return _job


JOBS: dict[str, JobFn] = {
    "gpu_tests": gpu_tests,
    "pose_bench": _not_ready("pose_bench"),
    "eval": _not_ready("eval"),
    "train_events": _not_ready("train_events"),
    "tune_align": _not_ready("tune_align"),
    "finetune_pose": _not_ready("finetune_pose"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Climbing Coach pod job.")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.job == "gpu_tests" and os.environ.get("CC_IN_GPU_TESTS") == "1":
        print(
            "ERROR: Refuse to start nested gpu_tests. CC_IN_GPU_TESTS is already set.",
            file=sys.stderr,
        )
        return 1
    try:
        JOBS[args.job](args.run_dir)
    except JobError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
