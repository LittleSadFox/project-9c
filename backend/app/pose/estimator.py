"""PoseEstimator protocol, fixture backend, and rtmlib YOLOX + RTMPose backend."""

from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.core.halpe26 import (
    HEAD,
    HIP,
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    N_KEYPOINTS,
    NECK,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

ALLOWED_DEVICES = ("auto", "cuda", "mps", "cpu")
POSE_MODES = ("lightweight", "balanced", "performance")


def _weight_names(folder: str, stem: str) -> tuple[str, ...]:
    return (f"{folder}/{stem}.zip", f"{folder}/{stem}.onnx", f"{stem}.zip", f"{stem}.onnx")


MODE_FILES: dict[str, dict[str, object]] = {
    "lightweight": {
        "det": _weight_names("det", "yolox_tiny"),
        "pose": _weight_names("pose", "rtmpose_s_halpe26"),
        "det_size": (416, 416),
        "pose_size": (192, 256),
        "model_version": "rtmpose-s-halpe26",
    },
    "balanced": {
        "det": _weight_names("det", "yolox_m"),
        "pose": _weight_names("pose", "rtmpose_m_halpe26"),
        "det_size": (640, 640),
        "pose_size": (192, 256),
        "model_version": "rtmpose-m-halpe26",
    },
    "performance": {
        "det": _weight_names("det", "yolox_x"),
        "pose": _weight_names("pose", "rtmpose_x_halpe26"),
        "det_size": (640, 640),
        "pose_size": (288, 384),
        "model_version": "rtmpose-x-halpe26",
    },
}


def empty_boxes() -> np.ndarray:
    return np.zeros((0, 4), dtype=np.float32)


def empty_keypoints() -> np.ndarray:
    return np.zeros((0, N_KEYPOINTS, 2), dtype=np.float32)


def empty_scores() -> np.ndarray:
    return np.zeros((0, N_KEYPOINTS), dtype=np.float32)


def empty_result() -> dict[str, object]:
    return {
        "tracks": [],
        "boxes": empty_boxes(),
        "keypoints": empty_keypoints(),
        "scores": empty_scores(),
    }


def as_boxes(boxes: object) -> np.ndarray:
    if boxes is None:
        return empty_boxes()
    array = np.asarray(boxes, dtype=np.float32)
    if array.size == 0:
        return empty_boxes()
    return array.reshape(-1, 4)


class PoseEstimator(Protocol):
    """Estimate people and keypoints on one frame."""

    def detect(self, frame: object, *, frame_index: int = 0) -> np.ndarray: ...

    def pose(self, frame: object, boxes: object, *, frame_index: int = 0) -> dict[str, object]: ...

    def estimate(self, frame: object) -> dict[str, object]: ...


def stick_figure(box: np.ndarray, *, score: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    """Build a Halpe26 stick figure inside a box. Used by the fixture backend."""
    x1, y1, x2, y2 = (float(v) for v in box)
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2)
    width = max(x2 - x1, 1.0)
    height = max(y2 - y1, 1.0)
    kpts = np.zeros((N_KEYPOINTS, 2), dtype=np.float32)
    kpts[HIP] = (cx, cy + 0.05 * height)
    kpts[NECK] = (cx, cy - 0.22 * height)
    kpts[HEAD] = (cx, cy - 0.38 * height)
    kpts[NOSE] = (cx, cy - 0.32 * height)
    kpts[LEFT_SHOULDER] = (cx - 0.22 * width, cy - 0.18 * height)
    kpts[RIGHT_SHOULDER] = (cx + 0.22 * width, cy - 0.18 * height)
    kpts[LEFT_ELBOW] = (cx - 0.30 * width, cy + 0.02 * height)
    kpts[RIGHT_ELBOW] = (cx + 0.30 * width, cy + 0.02 * height)
    kpts[LEFT_WRIST] = (cx - 0.32 * width, cy + 0.18 * height)
    kpts[RIGHT_WRIST] = (cx + 0.32 * width, cy + 0.18 * height)
    kpts[LEFT_HIP] = (cx - 0.12 * width, cy + 0.08 * height)
    kpts[RIGHT_HIP] = (cx + 0.12 * width, cy + 0.08 * height)
    kpts[LEFT_KNEE] = (cx - 0.14 * width, cy + 0.28 * height)
    kpts[RIGHT_KNEE] = (cx + 0.14 * width, cy + 0.28 * height)
    kpts[LEFT_ANKLE] = (cx - 0.14 * width, y2 - 0.06 * height)
    kpts[RIGHT_ANKLE] = (cx + 0.14 * width, y2 - 0.06 * height)
    kpts[20] = (kpts[LEFT_ANKLE, 0] - 2.0, kpts[LEFT_ANKLE, 1] + 4.0)
    kpts[21] = (kpts[RIGHT_ANKLE, 0] + 2.0, kpts[RIGHT_ANKLE, 1] + 4.0)
    kpts[22] = (kpts[LEFT_ANKLE, 0] + 2.0, kpts[LEFT_ANKLE, 1] + 4.0)
    kpts[23] = (kpts[RIGHT_ANKLE, 0] - 2.0, kpts[RIGHT_ANKLE, 1] + 4.0)
    kpts[24] = (kpts[LEFT_ANKLE, 0], kpts[LEFT_ANKLE, 1] - 2.0)
    kpts[25] = (kpts[RIGHT_ANKLE, 0], kpts[RIGHT_ANKLE, 1] - 2.0)
    kpts[1] = (cx - 4.0, cy - 0.34 * height)
    kpts[2] = (cx + 4.0, cy - 0.34 * height)
    kpts[3] = (cx - 8.0, cy - 0.30 * height)
    kpts[4] = (cx + 8.0, cy - 0.30 * height)
    return kpts, np.full(N_KEYPOINTS, score, dtype=np.float32)


class FixtureEstimator:
    """Test backend. Set CC_POSE_BACKEND=fixture to use it."""

    model_version = "fixture"
    provider = "CPUExecutionProvider"
    device_name = "cpu"

    def __init__(
        self,
        detections: dict[int, np.ndarray] | None = None,
        people: dict[int, dict[str, np.ndarray]] | None = None,
        *,
        mode: str = "balanced",
    ) -> None:
        self.detections = detections or {}
        self.people = people or {}
        self.mode = mode
        self.detect_calls = 0
        self.pose_calls = 0

    def detect(self, frame: object, *, frame_index: int = 0) -> np.ndarray:
        del frame
        self.detect_calls += 1
        if frame_index in self.detections:
            return as_boxes(self.detections[frame_index])
        if self.detections or self.people:
            return empty_boxes()
        return empty_boxes()

    def pose(self, frame: object, boxes: object, *, frame_index: int = 0) -> dict[str, object]:
        del frame
        self.pose_calls += 1
        prepared = self.people.get(frame_index)
        if prepared is not None:
            return {
                "tracks": [],
                "boxes": as_boxes(prepared.get("boxes", boxes)),
                "keypoints": np.asarray(prepared["keypoints"], dtype=np.float32),
                "scores": np.asarray(prepared["scores"], dtype=np.float32),
            }
        box_array = as_boxes(boxes)
        if box_array.shape[0] == 0:
            return empty_result()
        keypoints = []
        scores = []
        for box in box_array:
            kpts, sc = stick_figure(box)
            keypoints.append(kpts)
            scores.append(sc)
        return {
            "tracks": [],
            "boxes": box_array,
            "keypoints": np.stack(keypoints),
            "scores": np.stack(scores),
        }

    def estimate(self, frame: object) -> dict[str, object]:
        boxes = self.detect(frame, frame_index=0)
        if boxes.shape[0] == 0:
            return empty_result()
        return self.pose(frame, boxes, frame_index=0)


def resolve_device(requested: str) -> str:
    """Map CC_DEVICE to an rtmlib device name."""
    name = (requested or "auto").strip() or "auto"
    if name in {"cpu", "cuda", "mps"}:
        return name
    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        providers = list(ort.get_available_providers())
    except ImportError:
        return "cpu"
    if "CUDAExecutionProvider" in providers:
        return "cuda"
    if "CoreMLExecutionProvider" in providers or "MPSExecutionProvider" in providers:
        return "mps"
    return "cpu"


def provider_for_device(device: str) -> str:
    if device == "cuda":
        return "CUDAExecutionProvider"
    if device == "mps":
        return "CoreMLExecutionProvider"
    return "CPUExecutionProvider"


def _find_weight(models_dir: Path, candidates: tuple[str, ...]) -> Path | None:
    for relative in candidates:
        path = models_dir / relative
        if path.is_file():
            return path
    for relative in candidates:
        matches = list(models_dir.rglob(Path(relative).name))
        files = [item for item in matches if item.is_file()]
        if files:
            return files[0]
    return None


def extract_temp_dir(extract_dir: Path) -> Path:
    pid = os.getpid()
    job = os.environ.get("CC_JOB_ID") or os.environ.get("CC_JOB") or "local"
    token = uuid.uuid4().hex[:8]
    return extract_dir.with_name(f"{extract_dir.name}.extract.{pid}.{job}.{token}")


def extract_matches_zip(zip_path: Path, extract_dir: Path) -> bool:
    """Return True when every zip member is present with the stored size."""
    if not extract_dir.is_dir():
        return False
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            dest = extract_dir / info.filename
            if not dest.is_file() or dest.stat().st_size != info.file_size:
                return False
    return True


def resolve_onnx_file(path: Path) -> Path:
    """Return a local .onnx file. Extract a zip once. Never download."""
    if path.suffix.lower() == ".onnx" and path.is_file():
        return path
    if path.suffix.lower() == ".zip" and path.is_file():
        extract_dir = path.with_suffix("")
        if extract_dir.is_dir() and extract_matches_zip(path, extract_dir):
            found = sorted(extract_dir.rglob("*.onnx"))
            if found:
                return found[0]
        tmp_dir = extract_temp_dir(extract_dir)
        try:
            tmp_dir.mkdir(parents=True)
            with zipfile.ZipFile(path) as archive:
                archive.extractall(tmp_dir)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            os.replace(tmp_dir, extract_dir)
        except Exception:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        found = sorted(extract_dir.rglob("*.onnx"))
        if not found:
            raise FileNotFoundError(f"{path} has no ONNX file.")
        return found[0]
    raise FileNotFoundError(f"ONNX weight is missing: {path}")


def resolve_mode_paths(
    models_dir: Path, mode: str = "balanced"
) -> tuple[Path, Path, dict[str, object]]:
    spec = MODE_FILES.get(mode)
    if spec is None:
        raise FileNotFoundError(f"Unknown pose mode {mode!r}.")
    det = _find_weight(models_dir, spec["det"])  # type: ignore[arg-type]
    pose = _find_weight(models_dir, spec["pose"])  # type: ignore[arg-type]
    if det is None or pose is None:
        raise FileNotFoundError(
            "ONNX weights are missing. Run download_models.py into CC_MODELS_DIR "
            "before the first pose_bench or pose job."
        )
    return resolve_onnx_file(det), resolve_onnx_file(pose), spec


class RtmlibEstimator:
    """Real backend. Calls rtmlib YOLOX and RTMPose. Does not use PoseTracker."""

    def __init__(
        self,
        models_dir: Path,
        device: str = "auto",
        *,
        mode: str = "balanced",
    ) -> None:
        self.models_dir = Path(models_dir)
        self.requested_device = device
        self.mode = mode
        self.device_name = resolve_device(device)
        self.provider = provider_for_device(self.device_name)
        spec = MODE_FILES.get(mode, MODE_FILES["balanced"])
        self.model_version = str(spec["model_version"])
        self._det: Any | None = None
        self._pose: Any | None = None
        self.detect_calls = 0
        self.pose_calls = 0

    def _ensure(self) -> None:
        if self._det is not None and self._pose is not None:
            return
        from rtmlib import YOLOX, RTMPose  # type: ignore[import-not-found, import-untyped]

        det_path, pose_path, spec = resolve_mode_paths(self.models_dir, self.mode)
        self._det = YOLOX(
            onnx_model=str(det_path),
            model_input_size=spec["det_size"],
            backend="onnxruntime",
            device=self.device_name,
        )
        self._pose = RTMPose(
            onnx_model=str(pose_path),
            model_input_size=spec["pose_size"],
            backend="onnxruntime",
            device=self.device_name,
        )
        session = getattr(self._pose, "session", None)
        if session is not None:
            used = list(session.get_providers())
            if used:
                self.provider = str(used[0])
        self.model_version = str(spec["model_version"])

    def detect(self, frame: object, *, frame_index: int = 0) -> np.ndarray:
        del frame_index
        self._ensure()
        if self._det is None:
            raise RuntimeError("YOLOX failed to load.")
        self.detect_calls += 1
        image = np.asarray(frame)
        boxes = self._det(image)
        return as_boxes(boxes)

    def pose(self, frame: object, boxes: object, *, frame_index: int = 0) -> dict[str, object]:
        del frame_index
        box_array = as_boxes(boxes)
        if box_array.shape[0] == 0:
            return empty_result()
        self._ensure()
        if self._pose is None:
            raise RuntimeError("RTMPose failed to load.")
        self.pose_calls += 1
        image = np.asarray(frame)
        keypoints, scores = self._pose(image, bboxes=box_array)
        kpts = np.asarray(keypoints, dtype=np.float32)
        sc = np.asarray(scores, dtype=np.float32)
        if kpts.ndim == 2:
            kpts = kpts[None, ...]
        if sc.ndim == 1:
            sc = sc[None, ...]
        return {"tracks": [], "boxes": box_array, "keypoints": kpts, "scores": sc}

    def estimate(self, frame: object) -> dict[str, object]:
        boxes = self.detect(frame, frame_index=0)
        if boxes.shape[0] == 0:
            return empty_result()
        return self.pose(frame, boxes, frame_index=0)


def make_estimator(
    *,
    pose_backend: str,
    models_dir: Path,
    device: str = "auto",
    mode: str = "balanced",
) -> PoseEstimator:
    if pose_backend == "fixture":
        return FixtureEstimator(mode=mode)
    return RtmlibEstimator(models_dir=models_dir, device=device, mode=mode)
