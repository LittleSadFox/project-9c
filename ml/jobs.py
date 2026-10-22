"""Pod job registry.

Phase 0 implements gpu_tests.
Phase 1 adds pose_bench.
Later phases add eval, train_events, tune_align, and finetune_pose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import AbstractContextManager
from itertools import islice
from pathlib import Path
from typing import Any

from ml.tiny_onnx import tiny_identity_bytes

ROOT = Path(__file__).resolve().parents[1]
JobFn = Callable[[Path], dict[str, Any]]
DEFAULT_BENCH_CLIP = "sample1.mp4"
DEFAULT_BENCH_START = 0
DEFAULT_BENCH_N_FRAMES = 100
DEFAULT_MIN_COMPARED_FRAC = 0.9


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


def _empty_clip_meta(start_frame: int, *, name: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "size_bytes": 0,
        "sha256": None,
        "start_frame": start_frame,
        "source_codec": None,
        "source_pix_fmt": None,
        "source_rotation_deg": 0,
        "proxy_codec": None,
        "proxy_pix_fmt": None,
        "proxy_rotation_deg": 0,
        "rotation_applied_deg": 0,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_filename_only(name: str) -> bool:
    if not name or name.strip() != name:
        return False
    if name in {".", ".."}:
        return False
    if any(sep in name for sep in ("/", "\\")):
        return False
    if Path(name).is_absolute():
        return False
    return Path(name).name == name


def _pick_clip_name(clip_name: str | None) -> str:
    """Return a filename. Code default is sample1.mp4. Env and args override it."""
    if clip_name is not None and str(clip_name).strip():
        return str(clip_name).strip()
    env_name = os.environ.get("CC_BENCH_CLIP", "").strip()
    if env_name:
        return env_name
    return DEFAULT_BENCH_CLIP


def _pick_start_frame(start_frame: int | None) -> int:
    """Return a start frame. Code default is 0. Env and args override it."""
    if start_frame is not None:
        return max(0, int(start_frame))
    raw = os.environ.get("CC_BENCH_START", "").strip()
    if not raw:
        return DEFAULT_BENCH_START
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise JobError("CC_BENCH_START must be an integer.") from exc


def resolve_bench_clip(name: str, golden_dir: Path) -> Path:
    """Resolve a golden-dir filename. Refuse paths and unknown suffixes."""
    from app.errors import AppError
    from app.storage import VIDEO_EXTS, safe_ext, safe_join

    raw = (name or "").strip()
    if not _is_filename_only(raw):
        raise JobError("CC_BENCH_CLIP must be a filename, not a path.")
    try:
        joined = safe_join(Path(golden_dir), raw)
        joined.relative_to(Path(golden_dir).resolve())
        return safe_ext(joined, VIDEO_EXTS)
    except AppError as exc:
        raise JobError(str(exc.message)) from exc
    except ValueError as exc:
        raise JobError("The bench clip is not inside CC_GOLDEN_DIR.") from exc


def _take_frames(source: Any, n_frames: int, start_frame: int = 0) -> list[Any]:
    """Read at most n_frames from a (index, frame) iterator, then stop."""
    start = max(0, int(start_frame))
    frames: list[Any] = []
    for item in islice(source, start, start + n_frames):
        frames.append(item[1] if isinstance(item, tuple) else item)
    return frames


def _load_bench_frames(
    n_frames: int,
    *,
    clip_name: str | None = None,
    start_frame: int | None = None,
    proxy_dir: Path | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Load an explicit golden clip through the upright 8-bit proxy."""
    backend = os.environ.get("CC_POSE_BACKEND", "rtmlib").strip() or "rtmlib"
    requested = _pick_clip_name(clip_name)
    start_frame = _pick_start_frame(start_frame)
    golden = Path(os.environ.get("CC_GOLDEN_DIR", "/workspace/videos"))
    src = resolve_bench_clip(requested, golden)
    if not src.is_file():
        if backend == "fixture":
            return _synthetic_bench_frames(n_frames), _empty_clip_meta(start_frame, name=requested)
        raise JobError(f"Bench clip {requested} is not in CC_GOLDEN_DIR.")

    from app.media.frames import (
        FrameError,
        FrameReader,
        make_upright_u8_proxy,
        probe_rotation_degrees,
        probe_video_stream,
    )

    source_probe = probe_video_stream(src)
    rotation = probe_rotation_degrees(src)
    digest = _file_sha256(src)
    owned_dir: Path | None = None
    try:
        if proxy_dir is None:
            owned_dir = Path(tempfile.mkdtemp(prefix="cc-bench-proxy-"))
            dest_dir = owned_dir
        else:
            dest_dir = Path(proxy_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{src.stem}.{digest[:12]}.u8.mp4"
        try:
            make_upright_u8_proxy(src, dest)
        except FrameError as exc:
            raise JobError(str(exc)) from exc
        proxy_probe = probe_video_stream(dest)
        proxy_rotation = probe_rotation_degrees(dest)
        with FrameReader(dest) as reader:
            frames = _take_frames(reader.iter_frames(), n_frames, start_frame)
        if not frames:
            raise JobError(f"Bench clip {requested} produced no frames.")
        return frames, {
            "name": src.name,
            "size_bytes": int(src.stat().st_size),
            "sha256": digest,
            "start_frame": start_frame,
            "source_codec": source_probe.get("codec_name"),
            "source_pix_fmt": source_probe.get("pix_fmt"),
            "source_rotation_deg": rotation,
            "proxy_codec": proxy_probe.get("codec_name"),
            "proxy_pix_fmt": proxy_probe.get("pix_fmt"),
            "proxy_rotation_deg": proxy_rotation,
            "rotation_applied_deg": rotation,
        }
    finally:
        if owned_dir is not None:
            shutil.rmtree(owned_dir, ignore_errors=True)


def _has_detections(raw: Any) -> bool:
    import numpy as np

    array = np.asarray(raw)
    return array.size > 0


def _as_scores(raw: Any, kpts: Any) -> Any:
    import numpy as np

    people = _as_people(kpts)
    if raw is not None:
        array = np.asarray(raw, dtype=np.float32)
        if array.size > 0:
            if array.ndim == 1:
                array = array[None, ...]
            if array.shape[:2] == people.shape[:2]:
                return array
    if people.ndim == 3 and people.shape[-1] >= 3:
        return people[..., 2]
    return np.ones(people.shape[:2], dtype=np.float32)


def _as_people(raw: Any) -> Any:
    import numpy as np

    array = np.asarray(raw, dtype=np.float32)
    if array.size == 0:
        return np.zeros((0, 26, 2), dtype=np.float32)
    if array.ndim == 2:
        return array[None, ...]
    return array


def _boxes_from_keypoints(kpts: Any) -> Any:
    import numpy as np

    people = _as_people(kpts)
    if people.shape[0] == 0:
        return np.zeros((0, 4), dtype=np.float32)
    xy = people[..., :2]
    x1 = xy[..., 0].min(axis=1)
    y1 = xy[..., 1].min(axis=1)
    x2 = xy[..., 0].max(axis=1)
    y2 = xy[..., 1].max(axis=1)
    return np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)


def _as_boxes(raw: Any, kpts: Any) -> Any:
    import numpy as np

    if raw is None:
        return _boxes_from_keypoints(kpts)
    array = np.asarray(raw, dtype=np.float32)
    if array.size == 0:
        return _boxes_from_keypoints(kpts)
    boxes = array.reshape(-1, 4)
    people = _as_people(kpts)
    if boxes.shape[0] != people.shape[0]:
        return _boxes_from_keypoints(kpts)
    return boxes


def _box_iou(a: Any, b: Any) -> float:
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, float(a[2] - a[0])) * max(0.0, float(a[3] - a[1]))
    area_b = max(0.0, float(b[2] - b[0])) * max(0.0, float(b[3] - b[1]))
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


def _centroid(box: Any) -> Any:
    import numpy as np

    return np.array(
        [(float(box[0]) + float(box[2])) * 0.5, (float(box[1]) + float(box[3])) * 0.5],
        dtype=np.float32,
    )


def pair_people(
    cpu_kpts: Any,
    cuda_kpts: Any,
    cpu_boxes: Any = None,
    cuda_boxes: Any = None,
    *,
    min_iou: float = 0.1,
) -> list[tuple[int, int]]:
    """Match people in one frame by box IoU, then by nearest centroid."""
    import numpy as np

    cpu = _as_people(cpu_kpts)
    cuda = _as_people(cuda_kpts)
    boxes_a = _as_boxes(cpu_boxes, cpu)
    boxes_b = _as_boxes(cuda_boxes, cuda)
    n_a = int(cpu.shape[0])
    n_b = int(cuda.shape[0])
    if n_a == 0 or n_b == 0:
        return []
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    scores: list[tuple[float, int, int]] = []
    for i in range(n_a):
        for j in range(n_b):
            scores.append((_box_iou(boxes_a[i], boxes_b[j]), i, j))
    scores.sort(key=lambda item: item[0], reverse=True)
    for score, i, j in scores:
        if score < min_iou:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    remain_a = [i for i in range(n_a) if i not in used_a]
    remain_b = [j for j in range(n_b) if j not in used_b]
    dists: list[tuple[float, int, int]] = []
    for i in remain_a:
        center_a = _centroid(boxes_a[i])
        for j in remain_b:
            center_b = _centroid(boxes_b[j])
            dists.append((float(np.linalg.norm(center_a - center_b)), i, j))
    dists.sort(key=lambda item: item[0])
    for _, i, j in dists:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    return pairs


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def apply_cuda_tf32_off(providers: Any) -> Any:
    """Apply the shared CUDA provider options. Same helper as RtmlibEstimator."""
    from app.pose.estimator import apply_cuda_provider_options

    return apply_cuda_provider_options(providers)


def cuda_tf32_off() -> AbstractContextManager[None]:
    """Patch ORT session create with the shared CUDA provider options."""
    from app.pose.estimator import cuda_provider_session

    return cuda_provider_session()


def compare_keypoints(
    cpu_kpts: Any,
    cuda_kpts: Any,
    *,
    frames_total: int,
    min_compared_frac: float = 0.9,
    limit_px: float = 1.0,
    cpu_boxes: Any = None,
    cuda_boxes: Any = None,
    cpu_scores: Any = None,
    cuda_scores: Any = None,
) -> dict[str, Any]:
    """Compare CUDA and CPU keypoints. Gate on the all-keypoint mean."""
    import numpy as np
    from app.core.halpe26 import N_KEYPOINTS, NAMES, SCORE_THR

    totals: list[float] = []
    confident: list[float] = []
    kept = 0
    dropped = 0
    frame_errors: list[tuple[int, float]] = []
    kpt_errors: list[list[float]] = [[] for _ in range(N_KEYPOINTS)]
    kpt_score_cpu: list[list[float]] = [[] for _ in range(N_KEYPOINTS)]
    kpt_score_cuda: list[list[float]] = [[] for _ in range(N_KEYPOINTS)]
    frames_compared = 0
    frames_cpu = 0
    frames_cuda = 0
    n_frames = min(len(cpu_kpts), len(cuda_kpts))
    for index in range(n_frames):
        a = _as_people(cpu_kpts[index])
        b = _as_people(cuda_kpts[index])
        if _has_detections(a):
            frames_cpu += 1
        if _has_detections(b):
            frames_cuda += 1
        if a.size == 0 or b.size == 0:
            continue
        box_a = cpu_boxes[index] if cpu_boxes is not None and index < len(cpu_boxes) else None
        box_b = cuda_boxes[index] if cuda_boxes is not None and index < len(cuda_boxes) else None
        score_a = cpu_scores[index] if cpu_scores is not None and index < len(cpu_scores) else None
        score_b = cuda_scores[index] if cuda_scores is not None and index < len(cuda_scores) else None
        pairs = pair_people(a, b, box_a, box_b)
        if not pairs:
            continue
        frames_compared += 1
        sa = _as_scores(score_a, a)
        sb = _as_scores(score_b, b)
        frame_deltas: list[float] = []
        for ia, ib in pairs:
            left = a[ia, ..., :2]
            right = b[ib, ..., :2]
            if left.shape != right.shape:
                continue
            delta = np.linalg.norm(left - right, axis=-1)
            left_s = sa[ia] if ia < sa.shape[0] else np.ones(left.shape[0], dtype=np.float32)
            right_s = sb[ib] if ib < sb.shape[0] else np.ones(right.shape[0], dtype=np.float32)
            for joint, err in enumerate(delta.ravel()):
                value = float(err)
                totals.append(value)
                frame_deltas.append(value)
                if joint < N_KEYPOINTS:
                    kpt_errors[joint].append(value)
                    cpu_s = float(left_s[joint]) if joint < len(left_s) else 1.0
                    cuda_s = float(right_s[joint]) if joint < len(right_s) else 1.0
                    kpt_score_cpu[joint].append(cpu_s)
                    kpt_score_cuda[joint].append(cuda_s)
                    if cpu_s >= SCORE_THR and cuda_s >= SCORE_THR:
                        confident.append(value)
                        kept += 1
                    else:
                        dropped += 1
        if frame_deltas:
            frame_errors.append((index, float(sum(frame_deltas) / len(frame_deltas))))
    mean_abs = _mean_or_none(totals)
    denom = max(0, frames_total)
    frac = (frames_compared / denom) if denom else 0.0
    parity_ok = (
        mean_abs is not None
        and mean_abs <= limit_px
        and frames_compared > 0
        and frac >= min_compared_frac
    )
    frame_values = [error for _, error in frame_errors]
    worst = sorted(frame_errors, key=lambda item: item[1], reverse=True)[:5]
    keypoints_out: dict[str, Any] = {}
    for joint, name in enumerate(NAMES):
        keypoints_out[name] = {
            "mean_error_px": None
            if not kpt_errors[joint]
            else round(float(sum(kpt_errors[joint]) / len(kpt_errors[joint])), 4),
            "mean_score_cpu": None
            if not kpt_score_cpu[joint]
            else round(float(sum(kpt_score_cpu[joint]) / len(kpt_score_cpu[joint])), 4),
            "mean_score_cuda": None
            if not kpt_score_cuda[joint]
            else round(float(sum(kpt_score_cuda[joint]) / len(kpt_score_cuda[joint])), 4),
        }
    return {
        "mean_abs_px": mean_abs,
        "parity_ok": parity_ok,
        "frames_total": frames_total,
        "frames_with_detections_cpu": frames_cpu,
        "frames_with_detections_cuda": frames_cuda,
        "frames_compared": frames_compared,
        "min_compared_frac": min_compared_frac,
        "parity_limit_px": limit_px,
        "score_thr": SCORE_THR,
        "mean_abs_px_confident": _mean_or_none(confident),
        "keypoints_kept": kept,
        "keypoints_dropped": dropped,
        "frame_error": {
            "median": None if not frame_values else round(float(np.median(frame_values)), 4),
            "p95": None if not frame_values else round(float(np.percentile(frame_values, 95)), 4),
            "max": None if not frame_values else round(float(max(frame_values)), 4),
            "worst": [{"frame_index": idx, "error_px": round(err, 4)} for idx, err in worst],
        },
        "keypoints": keypoints_out,
    }


def _run_estimator(
    estimator: Any, frames: list[Any]
) -> tuple[list[Any], list[Any], list[Any], float]:
    import time

    import numpy as np

    keypoints: list[Any] = []
    boxes_out: list[Any] = []
    scores_out: list[Any] = []
    started = time.perf_counter()
    for index, frame in enumerate(frames):
        boxes = np.asarray(estimator.detect(frame, frame_index=index))
        if boxes.size == 0:
            keypoints.append(np.zeros((0, 26, 2), dtype=np.float32))
            boxes_out.append(np.zeros((0, 4), dtype=np.float32))
            scores_out.append(np.zeros((0, 26), dtype=np.float32))
            continue
        result = estimator.pose(frame, boxes, frame_index=index)
        keypoints.append(np.asarray(result["keypoints"], dtype=np.float32))
        boxes_out.append(np.asarray(result.get("boxes", boxes), dtype=np.float32))
        scores_out.append(np.asarray(result.get("scores"), dtype=np.float32))
    elapsed = max(time.perf_counter() - started, 1e-6)
    return keypoints, boxes_out, scores_out, len(frames) / elapsed


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


def _debug_enabled(flag: bool | None = None) -> bool:
    """Debug numbers are on unless an arg or env turns them off."""
    if flag is not None:
        return bool(flag)
    raw = os.environ.get("CC_POSE_BENCH_DEBUG", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _frame_debug(frames: list[Any], clip: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    if not frames:
        return {
            "frame_shape": [],
            "dtype": None,
            "channel_order": "BGR",
            "channel_mean": [],
            "rotation_applied_deg": clip.get("rotation_applied_deg"),
            "source_codec": clip.get("source_codec"),
            "source_pix_fmt": clip.get("source_pix_fmt"),
        }
    frame = np.asarray(frames[0])
    means = []
    if frame.ndim == 3 and frame.shape[2] >= 3:
        means = [round(float(frame[:, :, index].mean()), 4) for index in range(3)]
    return {
        "frame_shape": [int(v) for v in frame.shape],
        "dtype": str(frame.dtype),
        "channel_order": "BGR",
        "channel_mean": means,
        "rotation_applied_deg": clip.get("rotation_applied_deg"),
        "source_codec": clip.get("source_codec"),
        "source_pix_fmt": clip.get("source_pix_fmt"),
    }


def _boxes_debug(boxes_list: list[Any]) -> list[dict[str, Any]]:
    import numpy as np

    out: list[dict[str, Any]] = []
    for index, raw in enumerate(boxes_list):
        array = np.asarray(raw, dtype=np.float32)
        if array.size == 0:
            out.append({"frame_index": index, "count": 0, "boxes": []})
            continue
        boxes = array.reshape(-1, 4)
        out.append(
            {
                "frame_index": index,
                "count": int(boxes.shape[0]),
                "boxes": [[round(float(v), 2) for v in row] for row in boxes],
            }
        )
    return out


def pose_bench(
    run_dir: Path,
    *,
    n_frames: int = DEFAULT_BENCH_N_FRAMES,
    require_cuda: bool | None = None,
    min_compared_frac: float = DEFAULT_MIN_COMPARED_FRAC,
    modes: list[str] | None = None,
    limit_px: float = 1.0,
    clip_name: str | None = None,
    start_frame: int | None = None,
    debug: bool | None = None,
) -> dict[str, Any]:
    """Measure pose fps per mode. Compare CUDA and CPU keypoints (mean ≤ 1 px)."""
    import numpy as np
    from app.pose.estimator import (
        MODE_FILES,
        FixtureEstimator,
        RtmlibEstimator,
        cuda_provider_options,
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
    frames, clip_meta = _load_bench_frames(
        n_frames,
        clip_name=clip_name,
        start_frame=start_frame,
        proxy_dir=None,
    )
    n_used = len(frames)
    want_debug = _debug_enabled(debug)
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
                with cuda_tf32_off():
                    cuda_est = RtmlibEstimator(models_dir=models_dir, device="cuda", mode=mode)
                    cuda_est._ensure()

        cpu_kpts, cpu_boxes, cpu_scores, cpu_fps = _run_estimator(cpu_est, frames)
        mode_metrics: dict[str, Any] = {
            "mode": mode,
            "estimator_mode": getattr(cpu_est, "mode", mode),
            "cpu": {"fps": round(cpu_fps, 3), "provider": getattr(cpu_est, "provider", "CPUExecutionProvider")},
        }
        if want_debug:
            mode_metrics["debug_detections"] = {
                "cpu": _boxes_debug(cpu_boxes),
            }
        if cuda_est is not None:
            cuda_kpts, cuda_boxes, cuda_scores, cuda_fps = _run_estimator(cuda_est, frames)
            if want_debug:
                mode_metrics["debug_detections"]["cuda"] = _boxes_debug(cuda_boxes)
            parity = compare_keypoints(
                cpu_kpts,
                cuda_kpts,
                frames_total=n_used,
                min_compared_frac=min_compared_frac,
                limit_px=limit_px,
                cpu_boxes=cpu_boxes,
                cuda_boxes=cuda_boxes,
                cpu_scores=cpu_scores,
                cuda_scores=cuda_scores,
            )
            mean_abs = parity["mean_abs_px"]
            conf_mean = parity.get("mean_abs_px_confident")
            mode_metrics["cuda"] = {
                "fps": round(cuda_fps, 3),
                "provider": getattr(cuda_est, "provider", "CUDAExecutionProvider"),
                "mean_abs_px": None if mean_abs is None else round(float(mean_abs), 4),
                "parity_ok": parity["parity_ok"],
                "frames_total": parity["frames_total"],
                "frames_with_detections_cpu": parity["frames_with_detections_cpu"],
                "frames_with_detections_cuda": parity["frames_with_detections_cuda"],
                "frames_compared": parity["frames_compared"],
                "score_thr": parity.get("score_thr"),
                "mean_abs_px_confident": None if conf_mean is None else round(float(conf_mean), 4),
                "keypoints_kept": parity.get("keypoints_kept"),
                "keypoints_dropped": parity.get("keypoints_dropped"),
                "frame_error": parity.get("frame_error"),
                "keypoints": parity.get("keypoints"),
                "cuda_provider_options": cuda_provider_options(),
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
        "clip": clip_meta,
    }
    if want_debug:
        metrics["debug"] = _frame_debug(frames, clip_meta)
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
    parser.add_argument("--n-frames", type=int, default=DEFAULT_BENCH_N_FRAMES)
    parser.add_argument(
        "--min-compared-frac",
        type=float,
        default=DEFAULT_MIN_COMPARED_FRAC,
        help="Minimum fraction of frames that must compare for pose_bench parity.",
    )
    parser.add_argument(
        "--modes",
        default="",
        help="Comma-separated pose modes. Default: every mode in MODE_FILES.",
    )
    parser.add_argument(
        "--clip",
        default="",
        help="Filename of the golden clip. Never a path. Default: sample1.mp4.",
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        default=None,
        help="First proxy frame to read. Default: 0.",
    )
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write frame numbers and boxes to metrics.json. Default: on. No images.",
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
                clip_name=args.clip or None,
                start_frame=args.start_frame,
                debug=args.debug,
            )
        else:
            JOBS[args.job](args.run_dir)
    except JobError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
