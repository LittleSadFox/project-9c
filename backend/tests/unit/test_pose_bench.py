"""pose_bench writes metrics with the fixture backend."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from app.pose.estimator import POSE_MODES, FixtureEstimator
from ml.jobs import (
    DEFAULT_BENCH_CLIP,
    DEFAULT_BENCH_N_FRAMES,
    DEFAULT_BENCH_START,
    DEFAULT_MIN_COMPARED_FRAC,
    JOBS,
    JobError,
    _debug_enabled,
    _take_frames,
    apply_cuda_tf32_off,
    compare_keypoints,
    cuda_tf32_off,
    ensure_bench_weights,
    main,
    pair_people,
    pose_bench,
    resolve_bench_clip,
)


def test_apply_cuda_tf32_off_only_changes_cuda() -> None:
    assert apply_cuda_tf32_off(["CPUExecutionProvider"]) == ["CPUExecutionProvider"]
    assert apply_cuda_tf32_off(["CUDAExecutionProvider"]) == [
        ("CUDAExecutionProvider", {"use_tf32": 0})
    ]
    merged = apply_cuda_tf32_off([("CUDAExecutionProvider", {"device_id": 0})])
    assert merged == [("CUDAExecutionProvider", {"device_id": 0, "use_tf32": 0})]


def test_app_and_bench_build_identical_cuda_provider_options(tmp_path: Path) -> None:
    from app.pose.estimator import (
        RtmlibEstimator,
        apply_cuda_provider_options,
        cuda_provider_options,
        provider_for_device,
    )

    app = RtmlibEstimator(models_dir=tmp_path, device="cuda")
    bench = apply_cuda_tf32_off([provider_for_device("cuda")])
    assert app.session_providers() == bench
    assert app.session_providers() == apply_cuda_provider_options(["CUDAExecutionProvider"])
    assert bench == [("CUDAExecutionProvider", {"use_tf32": 0})]
    assert cuda_provider_options() == {"use_tf32": 0}


def test_cuda_tf32_off_patches_inference_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import onnxruntime as ort

    seen: list[object] = []

    class FakeSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen.append(kwargs.get("providers") or (args[1] if len(args) > 1 else None))

    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    with cuda_tf32_off():
        ort.InferenceSession(path_or_bytes=b"x", providers=["CUDAExecutionProvider"])
    assert seen == [[("CUDAExecutionProvider", {"use_tf32": 0})]]


def test_pose_bench_is_registered() -> None:
    assert JOBS["pose_bench"] is pose_bench


def test_pose_bench_fixture_writes_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.halpe26 import NAMES, SCORE_THR

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
    assert saved["clip"]["name"] == "sample1.mp4"
    assert saved["clip"]["start_frame"] == 0
    assert "debug" in saved
    assert saved["debug"]["channel_order"] == "BGR"
    assert "pose_bench status=passed" in (run_dir / "log.txt").read_text(encoding="utf-8")
    cuda = saved["modes"]["balanced"]["cuda"]
    assert cuda["parity_ok"] is True
    assert cuda["mean_abs_px"] == 0.0
    assert cuda["score_thr"] == SCORE_THR
    assert cuda["mean_abs_px_confident"] == 0.0
    assert cuda["keypoints_kept"] == 8 * 26
    assert cuda["keypoints_dropped"] == 0
    assert set(cuda["frame_error"]) == {"median", "p95", "max", "worst"}
    assert cuda["frame_error"]["median"] == 0.0
    assert cuda["frame_error"]["p95"] == 0.0
    assert cuda["frame_error"]["max"] == 0.0
    assert len(cuda["frame_error"]["worst"]) == 5
    assert set(cuda["keypoints"]) == set(NAMES)
    assert cuda["keypoints"]["nose"]["mean_error_px"] == 0.0
    assert cuda["keypoints"]["nose"]["mean_score_cpu"] == 0.9
    assert cuda["keypoints"]["nose"]["mean_score_cuda"] == 0.9
    assert cuda["cuda_provider_options"] == {"use_tf32": 0}


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


def test_compare_keypoints_low_score_error_is_diagnostic_only() -> None:
    from app.core.halpe26 import SCORE_THR

    cpu = [_kpts()]
    cuda = [_kpts(shift=50.0)]
    cuda[0][0, 1:, 0] = 10.0
    cpu_scores = [np.full((1, 26), 0.9, dtype=np.float32)]
    cuda_scores = [np.full((1, 26), 0.9, dtype=np.float32)]
    cpu_scores[0][0, 0] = 0.1
    cuda_scores[0][0, 0] = 0.1
    result = compare_keypoints(
        cpu,
        cuda,
        frames_total=1,
        min_compared_frac=0.9,
        cpu_scores=cpu_scores,
        cuda_scores=cuda_scores,
    )
    assert result["score_thr"] == SCORE_THR
    assert result["mean_abs_px"] is not None
    assert result["mean_abs_px"] > 1.0
    assert result["parity_ok"] is False
    assert result["mean_abs_px_confident"] is not None
    assert result["mean_abs_px_confident"] == 0.0
    assert result["keypoints_kept"] == 25
    assert result["keypoints_dropped"] == 1
    assert result["keypoints"]["nose"]["mean_error_px"] == 50.0
    assert result["keypoints"]["left_eye"]["mean_error_px"] == 0.0


def test_compare_keypoints_records_frame_and_keypoint_stats() -> None:
    cpu = [_kpts() for _ in range(3)]
    cuda = [_kpts(), _kpts(shift=0.4), _kpts(shift=2.0)]
    result = compare_keypoints(cpu, cuda, frames_total=3, min_compared_frac=0.9)
    assert result["frames_compared"] == 3
    assert result["frame_error"]["max"] == 2.0
    assert result["frame_error"]["median"] == 0.4
    assert result["frame_error"]["worst"][0]["frame_index"] == 2
    assert result["frame_error"]["worst"][0]["error_px"] == 2.0
    assert set(result["keypoints"]) == {
        "nose",
        "left_eye",
        "right_eye",
        "left_ear",
        "right_ear",
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
        "head",
        "neck",
        "hip",
        "left_big_toe",
        "right_big_toe",
        "left_small_toe",
        "right_small_toe",
        "left_heel",
        "right_heel",
    }
    assert result["keypoints"]["hip"]["mean_score_cpu"] == 1.0
    assert result["keypoints"]["hip"]["mean_score_cuda"] == 1.0


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


def test_take_frames_honors_start() -> None:
    reads = {"n": 0}

    def source() -> object:
        for index in range(1000):
            reads["n"] += 1
            yield index, f"frame-{index}"

    frames = _take_frames(source(), 3, start_frame=4)
    assert frames == ["frame-4", "frame-5", "frame-6"]
    assert reads["n"] == 7


def _person(x: float) -> np.ndarray:
    array = np.zeros((26, 2), dtype=np.float32)
    array[:, 0] = x + np.linspace(0.0, 20.0, 26)
    array[:, 1] = np.linspace(10.0, 80.0, 26)
    return array


def test_compare_keypoints_swapped_people_matches_by_iou() -> None:
    left = _person(10.0)
    right = _person(100.0)
    cpu = [np.stack([left, right])]
    cuda = [np.stack([right, left])]
    result = compare_keypoints(cpu, cuda, frames_total=1, min_compared_frac=0.9)
    assert result["frames_compared"] == 1
    assert result["mean_abs_px"] is not None
    assert result["mean_abs_px"] <= 1.0
    assert result["parity_ok"] is True
    list_order = float(np.linalg.norm(cpu[0][..., :2] - cuda[0][..., :2], axis=-1).mean())
    assert list_order > 1.0


def test_pair_people_uses_iou_not_list_order() -> None:
    left = _person(10.0)
    right = _person(100.0)
    pairs = pair_people(np.stack([left, right]), np.stack([right, left]))
    assert set(pairs) == {(0, 1), (1, 0)}


@pytest.mark.parametrize("name", ["..", "../../etc/x", "/etc/x", "/tmp/sample1.mp4"])
def test_resolve_bench_clip_rejects_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(JobError, match="filename"):
        resolve_bench_clip(name, tmp_path)


def test_resolve_bench_clip_accepts_filename(tmp_path: Path) -> None:
    path = resolve_bench_clip("sample1.mp4", tmp_path)
    assert path == (tmp_path / "sample1.mp4").resolve()
    assert path.name == "sample1.mp4"


def test_load_bench_frames_does_not_read_past_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ml.jobs import _load_bench_frames

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    reads = {"n": 0, "closed": False, "opened": []}

    class CountingReader:
        def __init__(self, path: Path) -> None:
            reads["opened"].append(Path(path))

        def __enter__(self) -> CountingReader:
            return self

        def __exit__(self, *_exc: object) -> None:
            reads["closed"] = True

        def iter_frames(self) -> object:
            for index in range(1000):
                reads["n"] += 1
                yield index, np.zeros((2, 2, 3), dtype=np.uint8)

    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path))
    monkeypatch.setenv("CC_BENCH_CLIP", "clip.mp4")
    monkeypatch.setenv("CC_POSE_BACKEND", "rtmlib")
    monkeypatch.setattr("app.media.frames.FrameReader", CountingReader)
    monkeypatch.setattr("app.media.frames.make_upright_u8_proxy", lambda src, dest: dest)
    monkeypatch.setattr(
        "app.media.frames.probe_video_stream",
        lambda _path: {"codec_name": "hevc", "pix_fmt": "yuv420p10le"},
    )
    monkeypatch.setattr("app.media.frames.probe_rotation_degrees", lambda _path: 90)
    frames, meta = _load_bench_frames(7, proxy_dir=tmp_path / "proxy")
    assert len(frames) == 7
    assert reads["n"] == 7
    assert reads["closed"] is True
    assert meta["name"] == "clip.mp4"
    assert meta["source_codec"] == "hevc"
    assert meta["source_pix_fmt"] == "yuv420p10le"
    assert meta["rotation_applied_deg"] == 90
    assert meta["sha256"]
    assert all(".u8." in path.name for path in reads["opened"])


def test_load_bench_frames_uses_named_clip_not_first_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ml.jobs import _load_bench_frames

    (tmp_path / "aaa.mp4").write_bytes(b"first-if-sorted")
    (tmp_path / "sample1.mp4").write_bytes(b"named-clip")
    seen: list[str] = []

    class DummyReader:
        def __init__(self, path: Path) -> None:
            seen.append(Path(path).name)

        def __enter__(self) -> DummyReader:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def iter_frames(self) -> object:
            yield 0, np.zeros((4, 4, 3), dtype=np.uint8)

    def fake_proxy(src: Path, dest: Path) -> Path:
        seen.append(f"src:{src.name}")
        dest.write_bytes(b"proxy")
        return dest

    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path))
    monkeypatch.setenv("CC_BENCH_CLIP", "sample1.mp4")
    monkeypatch.setenv("CC_POSE_BACKEND", "rtmlib")
    monkeypatch.setattr("app.media.frames.FrameReader", DummyReader)
    monkeypatch.setattr("app.media.frames.make_upright_u8_proxy", fake_proxy)
    monkeypatch.setattr(
        "app.media.frames.probe_video_stream",
        lambda _path: {"codec_name": "h264", "pix_fmt": "yuv420p"},
    )
    monkeypatch.setattr("app.media.frames.probe_rotation_degrees", lambda _path: 0)
    frames, meta = _load_bench_frames(1, proxy_dir=tmp_path / "proxy")
    assert len(frames) == 1
    assert meta["name"] == "sample1.mp4"
    assert "src:sample1.mp4" in seen
    assert "src:aaa.mp4" not in seen


def test_load_bench_frames_defaults_to_sample1_and_start_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.storage import safe_ext, safe_join
    from ml.jobs import _load_bench_frames

    joined: list[tuple[str, ...]] = []
    checked: list[str] = []

    def record_join(root: Path, *parts: str) -> Path:
        joined.append(parts)
        return safe_join(root, *parts)

    def record_ext(path: Path, allowed: set[str] | None = None) -> Path:
        checked.append(path.name)
        return safe_ext(path, allowed)

    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path))
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_BENCH_CLIP", raising=False)
    monkeypatch.delenv("CC_BENCH_START", raising=False)
    monkeypatch.setattr("app.storage.safe_join", record_join)
    monkeypatch.setattr("app.storage.safe_ext", record_ext)
    frames, meta = _load_bench_frames(3)
    assert len(frames) == 3
    assert joined == [(DEFAULT_BENCH_CLIP,)]
    assert checked == [DEFAULT_BENCH_CLIP]
    assert meta["name"] == DEFAULT_BENCH_CLIP
    assert meta["start_frame"] == DEFAULT_BENCH_START


def test_pose_bench_bare_cli_uses_sample1_100_frames_and_frac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_pose_bench(run_dir: Path, **kwargs: object) -> dict[str, object]:
        seen["run_dir"] = run_dir
        seen.update(kwargs)
        return {}

    monkeypatch.delenv("CC_POSE_BENCH_DEBUG", raising=False)
    monkeypatch.setattr("ml.jobs.pose_bench", fake_pose_bench)
    assert main(["pose_bench", "--run-dir", str(tmp_path / "run")]) == 0
    assert seen["n_frames"] == DEFAULT_BENCH_N_FRAMES
    assert seen["min_compared_frac"] == DEFAULT_MIN_COMPARED_FRAC
    assert seen["clip_name"] is None
    assert seen["start_frame"] is None
    assert seen["debug"] is None
    assert _debug_enabled(None) is True
    assert DEFAULT_BENCH_CLIP == "sample1.mp4"
    assert DEFAULT_BENCH_START == 0
    assert DEFAULT_BENCH_N_FRAMES == 100
    assert DEFAULT_MIN_COMPARED_FRAC == 0.9


def test_load_bench_frames_missing_named_clip_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ml.jobs import _load_bench_frames

    (tmp_path / "aaa.mp4").write_bytes(b"not-the-named-clip")
    monkeypatch.setenv("CC_GOLDEN_DIR", str(tmp_path))
    monkeypatch.delenv("CC_BENCH_CLIP", raising=False)
    monkeypatch.setenv("CC_POSE_BACKEND", "rtmlib")
    with pytest.raises(JobError, match="sample1.mp4"):
        _load_bench_frames(4)


def test_pose_bench_debug_off_omits_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")
    monkeypatch.setenv("CC_POSE_BENCH_DEBUG", "0")
    metrics = pose_bench(tmp_path / "run", n_frames=4, require_cuda=False, modes=["balanced"])
    assert "debug" not in metrics
    assert "debug_detections" not in metrics["modes"]["balanced"]


def test_pose_bench_debug_writes_numbers_not_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")
    run_dir = tmp_path / "run"
    metrics = pose_bench(run_dir, n_frames=4, require_cuda=False, modes=["balanced"])
    assert "debug" in metrics
    debug = metrics["debug"]
    assert debug["dtype"] == "uint8"
    assert debug["channel_order"] == "BGR"
    assert debug["frame_shape"][-1] == 3
    assert len(debug["channel_mean"]) == 3
    assert "clip" in metrics
    assert metrics["clip"]["name"] == "sample1.mp4"
    assert metrics["clip"]["start_frame"] == 0
    detections = metrics["modes"]["balanced"]["debug_detections"]["cpu"]
    assert detections[0]["count"] == 1
    assert len(detections[0]["boxes"][0]) == 4
    images = list(run_dir.rglob("*.png"))
    images.extend(run_dir.rglob("*.jpg"))
    images.extend(run_dir.rglob("*.webp"))
    assert images == []


def _run_videos(run_dir: Path) -> list[Path]:
    found: list[Path] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".mp4", ".mov", ".m4v"} or path.name.endswith(".u8.mp4"):
            found.append(path)
    return found


def _install_proxy_mocks(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    written: list[Path] = []

    class DummyReader:
        def __init__(self, path: Path) -> None:
            del path

        def __enter__(self) -> DummyReader:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def iter_frames(self) -> object:
            yield 0, np.zeros((4, 4, 3), dtype=np.uint8)

    def fake_proxy(src: Path, dest: Path) -> Path:
        del src
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"proxy-bytes")
        written.append(Path(dest))
        return dest

    monkeypatch.setattr("app.media.frames.FrameReader", DummyReader)
    monkeypatch.setattr("app.media.frames.make_upright_u8_proxy", fake_proxy)
    monkeypatch.setattr(
        "app.media.frames.probe_video_stream",
        lambda _path: {"codec_name": "h264", "pix_fmt": "yuv420p"},
    )
    monkeypatch.setattr("app.media.frames.probe_rotation_degrees", lambda _path: 0)
    return written


def test_pose_bench_leaves_no_video_under_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "sample1.mp4").write_bytes(b"named-clip")
    written = _install_proxy_mocks(monkeypatch)
    monkeypatch.setenv("CC_GOLDEN_DIR", str(golden))
    monkeypatch.setenv("CC_POSE_BACKEND", "fixture")
    monkeypatch.delenv("CC_REQUIRE", raising=False)
    monkeypatch.setenv("CC_DEVICE", "cpu")
    monkeypatch.delenv("CC_BENCH_CLIP", raising=False)

    passed = tmp_path / "pass"
    pose_bench(passed, n_frames=1, require_cuda=False, modes=["balanced"])
    assert written
    assert all(passed.resolve() not in path.resolve().parents for path in written)
    assert all(not path.exists() for path in written)
    assert _run_videos(passed) == []

    def no_compare(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "mean_abs_px": None,
            "parity_ok": False,
            "frames_total": 1,
            "frames_with_detections_cpu": 0,
            "frames_with_detections_cuda": 0,
            "frames_compared": 0,
            "min_compared_frac": 0.9,
            "parity_limit_px": 1.0,
        }

    written.clear()
    monkeypatch.setattr("ml.jobs.compare_keypoints", no_compare)
    failed = tmp_path / "fail"
    with pytest.raises(JobError):
        pose_bench(failed, n_frames=1, require_cuda=False, modes=["balanced"])
    assert written
    assert all(failed.resolve() not in path.resolve().parents for path in written)
    assert all(not path.exists() for path in written)
    assert _run_videos(failed) == []


@pytest.mark.media
def test_bench_loader_upright_from_rotated_10bit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.media.frames import FrameReader as RealReader
    from ml.jobs import _load_bench_frames

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "pose" / "rotated_10bit_testsrc.mp4"
    )
    assert fixture.is_file()
    golden = tmp_path / "golden"
    golden.mkdir()
    dest = golden / "rotated_10bit_testsrc.mp4"
    dest.write_bytes(fixture.read_bytes())
    opened: list[Path] = []

    class RecordingReader(RealReader):
        def __init__(self, path: Path) -> None:
            opened.append(Path(path))
            super().__init__(path)

    monkeypatch.setenv("CC_GOLDEN_DIR", str(golden))
    monkeypatch.setenv("CC_BENCH_CLIP", "rotated_10bit_testsrc.mp4")
    monkeypatch.setenv("CC_BENCH_START", "0")
    monkeypatch.setenv("CC_POSE_BACKEND", "rtmlib")
    monkeypatch.setattr("app.media.frames.FrameReader", RecordingReader)
    frames, meta = _load_bench_frames(2, proxy_dir=tmp_path / "proxy")
    assert opened
    assert all(path != dest for path in opened)
    assert all(".u8." in path.name for path in opened)
    assert meta["name"] == "rotated_10bit_testsrc.mp4"
    assert meta["source_codec"] == "hevc"
    assert meta["source_pix_fmt"] == "yuv420p10le"
    assert meta["source_rotation_deg"] in {90, 270}
    assert meta["proxy_codec"] == "h264"
    assert meta["proxy_pix_fmt"] == "yuv420p"
    assert frames[0].dtype == np.uint8
    assert frames[0].ndim == 3
    assert frames[0].shape[2] == 3
    assert bool(frames[0].flags["C_CONTIGUOUS"])
    height, width = frames[0].shape[:2]
    assert height == 128
    assert width == 64
    assert meta["size_bytes"] == dest.stat().st_size
    assert meta["sha256"] == hashlib.sha256(dest.read_bytes()).hexdigest()


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
