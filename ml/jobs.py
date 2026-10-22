"""Pod job registry.

Phase 0 implements gpu_tests.
Phase 1 adds pose_bench.
Later phases add eval, train_events, tune_align, and finetune_pose.
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
from itertools import islice
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


def _write_ort_providers(run_dir: Path, cuda_metrics: dict[str, Any]) -> None:
    providers = cuda_metrics.get("session_providers") or []
    if not isinstance(providers, list):
        providers = []
    used = "true" if cuda_metrics.get("used_cuda") else "false"
    with (run_dir / "log.txt").open("a", encoding="utf-8") as log:
        log.write(
            "ort_providers="
            + ",".join(str(item) for item in providers)
            + f" used_cuda={used}\n"
        )


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
    env.pop("CC_WEBHOOK_KEY", None)
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
        cuda_metrics = check_cuda_session(require_cuda=False)
    except Exception as exc:
        if require_cuda:
            cuda_metrics = {"error": str(exc), "used_cuda": False}
            _write_ort_providers(run_dir, cuda_metrics)
            raise JobError(f"CUDA session check failed: {exc}") from exc
        cuda_metrics = {"error": str(exc), "used_cuda": False}

    _write_ort_providers(run_dir, cuda_metrics)
    if require_cuda and not cuda_metrics.get("used_cuda"):
        raise JobError(
            "CUDAExecutionProvider did not run the session. "
            f"session.get_providers()={cuda_metrics.get('session_providers')!r}."
        )

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


def _atomic_metrics(run_dir: Path, metrics: dict[str, Any]) -> None:
    dest = run_dir / "metrics.json"
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, dest)


def _synthetic_bench_frames(n_frames: int) -> list[Any]:
    import numpy as np

    frames: list[Any] = []
    for index in range(n_frames):
        image = np.zeros((128, 128, 3), dtype=np.uint8)
        x = 20 + (index % 60)
        y = 70 - index // 3
        image[max(y, 0) : max(y, 0) + 40, x : x + 24] = 200
        frames.append(image)
    return frames


def _take_frames(source: Any, n_frames: int) -> list[Any]:
    """Read at most n_frames from a (index, frame) iterator, then stop."""
    frames: list[Any] = []
    for item in islice(source, n_frames):
        frames.append(item[1] if isinstance(item, tuple) else item)
    return frames


def _load_bench_frames(n_frames: int) -> list[Any]:
    golden = Path(os.environ.get("CC_GOLDEN_DIR", "/workspace/videos"))
    if golden.is_dir():
        videos = sorted(
            path
            for path in golden.iterdir()
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v"}
        )
        if videos:
            from app.media.frames import FrameReader

            with FrameReader(videos[0]) as reader:
                frames = _take_frames(reader.iter_frames(), n_frames)
            if frames:
                return frames
    return _synthetic_bench_frames(n_frames)


def _has_detections(raw: Any) -> bool:
    import numpy as np

    array = np.asarray(raw)
    return array.size > 0


def compare_keypoints(
    cpu_kpts: Any,
    cuda_kpts: Any,
    *,
    frames_total: int,
    min_compared_frac: float = 0.9,
    limit_px: float = 1.0,
) -> dict[str, Any]:
    """Compare CUDA and CPU keypoints. Fail when too few frames match."""
    import numpy as np

    totals: list[float] = []
    frames_compared = 0
    frames_cpu = 0
    frames_cuda = 0
    for a_raw, b_raw in zip(cpu_kpts, cuda_kpts, strict=False):
        a = np.asarray(a_raw, dtype=np.float32)
        b = np.asarray(b_raw, dtype=np.float32)
        if _has_detections(a):
            frames_cpu += 1
        if _has_detections(b):
            frames_cuda += 1
        if a.size == 0 or b.size == 0 or a.shape != b.shape:
            continue
        frames_compared += 1
        delta = np.linalg.norm(a[..., :2] - b[..., :2], axis=-1)
        totals.extend(float(v) for v in delta.ravel())
    mean_abs: float | None
    if not totals:
        mean_abs = None
    else:
        mean_abs = float(sum(totals) / len(totals))
    denom = max(0, frames_total)
    frac = (frames_compared / denom) if denom else 0.0
    parity_ok = (
        mean_abs is not None
        and mean_abs <= limit_px
        and frames_compared > 0
        and frac >= min_compared_frac
    )
    return {
        "mean_abs_px": mean_abs,
        "parity_ok": parity_ok,
        "frames_total": frames_total,
        "frames_with_detections_cpu": frames_cpu,
        "frames_with_detections_cuda": frames_cuda,
        "frames_compared": frames_compared,
        "min_compared_frac": min_compared_frac,
        "parity_limit_px": limit_px,
    }


def _run_estimator(estimator: Any, frames: list[Any]) -> tuple[list[Any], float]:
    import time

    import numpy as np

    keypoints: list[Any] = []
    started = time.perf_counter()
    for index, frame in enumerate(frames):
        boxes = np.asarray(estimator.detect(frame, frame_index=index))
        if boxes.size == 0:
            keypoints.append(np.zeros((0, 26, 2), dtype=np.float32))
            continue
        result = estimator.pose(frame, boxes, frame_index=index)
        keypoints.append(np.asarray(result["keypoints"], dtype=np.float32))
    elapsed = max(time.perf_counter() - started, 1e-6)
    return keypoints, len(frames) / elapsed


def _lock_dests_for_modes(modes: list[str]) -> set[str]:
    from app.pose.estimator import MODE_FILES

    dests: set[str] = set()
    for mode in modes:
        spec = MODE_FILES.get(mode)
        if spec is None:
            continue
        for key in ("det", "pose"):
            names = spec.get(key)
            if isinstance(names, tuple) and names:
                dests.add(str(names[0]))
    return dests


def ensure_bench_weights(models_dir: Path, modes: list[str] | None = None) -> list[str]:
    """Download any missing lock-file weights. Skip files that already verify."""
    from scripts.download_models import DownloadError, download_one, load_lock

    wanted = None if modes is None else _lock_dests_for_modes(modes)
    names: list[str] = []
    try:
        for entry in load_lock():
            dest = str(entry.get("dest") or "")
            if wanted is not None and dest not in wanted:
                continue
            download_one(entry, models_dir)
            names.append(str(entry["name"]))
    except DownloadError as exc:
        raise JobError(str(exc)) from exc
    return names


def _selected_modes(requested: list[str] | None) -> list[str]:
    from app.pose.estimator import MODE_FILES

    available = list(MODE_FILES)
    if not requested:
        return available
    unknown = [name for name in requested if name not in MODE_FILES]
    if unknown:
        raise JobError(
            "Unknown pose mode(s): "
            + ", ".join(unknown)
            + ". Use: "
            + ", ".join(available)
            + "."
        )
    return requested


def pose_bench(
    run_dir: Path,
    *,
    n_frames: int = 100,
    require_cuda: bool | None = None,
    min_compared_frac: float = 0.9,
    modes: list[str] | None = None,
    limit_px: float = 1.0,
) -> dict[str, Any]:
    """Measure pose fps per mode. Compare CUDA and CPU keypoints (mean ≤ 1 px)."""
    import numpy as np
    from app.pose.estimator import (
        MODE_FILES,
        FixtureEstimator,
        RtmlibEstimator,
        resolve_device,
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    backend = os.environ.get("CC_POSE_BACKEND", "rtmlib").strip() or "rtmlib"
    models_dir = Path(os.environ.get("CC_MODELS_DIR", "/workspace/models"))
    device_env = os.environ.get("CC_DEVICE", "auto").strip() or "auto"
    if require_cuda is None:
        require = {part.strip() for part in os.environ.get("CC_REQUIRE", "").split(",") if part.strip()}
        require_cuda = "gpu" in require or device_env == "cuda"

    selected = _selected_modes(modes)
    if backend != "fixture":
        ensure_bench_weights(models_dir, selected)
    frames = _load_bench_frames(n_frames)
    n_used = len(frames)
    modes_out: dict[str, Any] = {}
    resolved = resolve_device(device_env)
    try:
        import onnxruntime as ort

        available = list(ort.get_available_providers())
    except ImportError:
        available = []
    have_cuda = "CUDAExecutionProvider" in available

    for mode in selected:
        if mode not in MODE_FILES:
            raise JobError(f"Unknown pose mode {mode!r}.")
        if backend == "fixture":
            detections = {
                index: np.array([[20.0 + (index % 60), 30.0, 44.0 + (index % 60), 90.0]], dtype=np.float32)
                for index in range(n_used)
            }
            cpu_est: Any = FixtureEstimator(detections=detections, mode=mode)
            cuda_est: Any = FixtureEstimator(detections=detections, mode=mode)
        else:
            try:
                cpu_est = RtmlibEstimator(models_dir=models_dir, device="cpu", mode=mode)
                cpu_est._ensure()
            except FileNotFoundError as exc:
                raise JobError(str(exc)) from exc
            cuda_est = None
            if have_cuda:
                cuda_est = RtmlibEstimator(models_dir=models_dir, device="cuda", mode=mode)

        cpu_kpts, cpu_fps = _run_estimator(cpu_est, frames)
        mode_metrics: dict[str, Any] = {
            "mode": mode,
            "estimator_mode": getattr(cpu_est, "mode", mode),
            "cpu": {"fps": round(cpu_fps, 3), "provider": getattr(cpu_est, "provider", "CPUExecutionProvider")},
        }
        if cuda_est is not None:
            cuda_kpts, cuda_fps = _run_estimator(cuda_est, frames)
            parity = compare_keypoints(
                cpu_kpts,
                cuda_kpts,
                frames_total=n_used,
                min_compared_frac=min_compared_frac,
                limit_px=limit_px,
            )
            mean_abs = parity["mean_abs_px"]
            mode_metrics["cuda"] = {
                "fps": round(cuda_fps, 3),
                "provider": getattr(cuda_est, "provider", "CUDAExecutionProvider"),
                "mean_abs_px": None if mean_abs is None else round(float(mean_abs), 4),
                "parity_ok": parity["parity_ok"],
                "frames_total": parity["frames_total"],
                "frames_with_detections_cpu": parity["frames_with_detections_cpu"],
                "frames_with_detections_cuda": parity["frames_with_detections_cuda"],
                "frames_compared": parity["frames_compared"],
            }
        elif have_cuda:
            mode_metrics["cuda"] = {"error": "CUDA estimator failed to start", "parity_ok": False}
        else:
            mode_metrics["cuda"] = None
        modes_out[mode] = mode_metrics

    parity_fail = any(
        isinstance(item.get("cuda"), dict)
        and item["cuda"].get("parity_ok") is False
        for item in modes_out.values()
    )
    cuda_ran = any(isinstance(item.get("cuda"), dict) and "fps" in item["cuda"] for item in modes_out.values())
    status = "passed"
    if require_cuda and (not have_cuda or not cuda_ran):
        status = "failed"
    if parity_fail:
        status = "failed"

    first_cuda: dict[str, Any] = next(
        (
            item["cuda"]
            for item in modes_out.values()
            if isinstance(item.get("cuda"), dict) and "frames_compared" in item["cuda"]
        ),
        {},
    )
    metrics = {
        "job": "pose_bench",
        "status": status,
        "n_frames": n_used,
        "backend": backend,
        "device": resolved,
        "available_providers": available,
        "modes": modes_out,
        "mode_list": selected,
        "parity_limit_px": limit_px,
        "min_compared_frac": min_compared_frac,
        "frames_total": first_cuda.get("frames_total", n_used),
        "frames_with_detections_cpu": first_cuda.get("frames_with_detections_cpu"),
        "frames_with_detections_cuda": first_cuda.get("frames_with_detections_cuda"),
        "frames_compared": first_cuda.get("frames_compared"),
    }
    _atomic_metrics(run_dir, metrics)
    with (run_dir / "log.txt").open("a", encoding="utf-8") as log:
        log.write(f"pose_bench status={status} backend={backend} n_frames={n_used}\n")
        for name, item in modes_out.items():
            cpu_fps = item.get("cpu", {}).get("fps")
            cuda_block = item.get("cuda") if isinstance(item.get("cuda"), dict) else {}
            log.write(
                f"pose_bench mode={name} cpu_fps={cpu_fps} "
                f"cuda_fps={cuda_block.get('fps')} parity_ok={cuda_block.get('parity_ok')}\n"
            )
    if status != "passed":
        raise JobError("pose_bench failed CUDA/CPU parity or CUDA was required and missing.")
    return metrics


JOBS: dict[str, JobFn] = {
    "gpu_tests": gpu_tests,
    "pose_bench": pose_bench,
    "eval": _not_ready("eval"),
    "train_events": _not_ready("train_events"),
    "tune_align": _not_ready("tune_align"),
    "finetune_pose": _not_ready("finetune_pose"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Climbing Coach pod job.")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--n-frames", type=int, default=100)
    parser.add_argument(
        "--min-compared-frac",
        type=float,
        default=0.9,
        help="Minimum fraction of frames that must compare for pose_bench parity.",
    )
    parser.add_argument(
        "--modes",
        default="",
        help="Comma-separated pose modes. Default: every mode in MODE_FILES.",
    )
    args = parser.parse_args(argv)
    if args.job == "gpu_tests" and os.environ.get("CC_IN_GPU_TESTS") == "1":
        print(
            "ERROR: Refuse to start nested gpu_tests. CC_IN_GPU_TESTS is already set.",
            file=sys.stderr,
        )
        return 1
    try:
        if args.job == "pose_bench":
            requested = [part.strip() for part in args.modes.split(",") if part.strip()]
            pose_bench(
                args.run_dir,
                n_frames=args.n_frames,
                min_compared_frac=args.min_compared_frac,
                modes=requested or None,
            )
        else:
            JOBS[args.job](args.run_dir)
    except JobError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
