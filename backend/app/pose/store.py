"""NPZ pose store and the effective-track cache."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from app.core.halpe26 import N_KEYPOINTS


def pose_path(pose_dir: Path, video_id: str, run_id: str) -> Path:
    return pose_dir / video_id / f"{run_id}.npz"


def effective_path(raw_path: Path) -> Path:
    return raw_path.with_name(raw_path.stem + ".effective.npz")


def _hashable_edits(edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for edit in edits:
        item: dict[str, Any] = {
            "id": edit.get("id"),
            "kind": edit.get("kind"),
            "frame": edit.get("frame"),
            "kpt": edit.get("kpt"),
            "x": edit.get("x"),
            "y": edit.get("y"),
            "range_start": edit.get("range_start"),
            "range_end": edit.get("range_end"),
        }
        points = edit.get("points")
        if points:
            item["points"] = [
                {"kpt": point.get("kpt"), "x": point.get("x"), "y": point.get("y")}
                for point in points
            ]
        payload.append(item)
    return payload


def edits_hash(edits: list[dict[str, Any]] | None = None) -> str:
    payload = json.dumps(_hashable_edits(edits or []), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def raw_version(raw_path: Path) -> str:
    """Identity of one raw NPZ. A pose re-run writes a new file and a new hash."""
    digest = hashlib.sha256()
    with raw_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def effective_cache_key(
    raw_path: Path,
    edits: list[dict[str, Any]] | None = None,
    *,
    climber_track_id: int | None = None,
) -> str:
    """Cache key = raw track version + edits hash (+ current climber)."""
    body = f"{raw_version(raw_path)}:{edits_hash(edits)}:{climber_track_id}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def write_pose(
    path: Path,
    *,
    frame: np.ndarray,
    track_id: np.ndarray,
    keypoints: np.ndarray,
    bbox: np.ndarray,
    meta: dict[str, Any],
) -> None:
    """Write an NPZ file through a temp name, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    climber = meta.get("climber_track_id")
    with tmp.open("wb") as handle:
        np.savez_compressed(
            handle,
            frame=np.asarray(frame, dtype=np.int32),
            track_id=np.asarray(track_id, dtype=np.int32),
            keypoints=np.asarray(keypoints, dtype=np.float32),
            bbox=np.asarray(bbox, dtype=np.float32),
            n_frames=np.int32(meta.get("n_frames") or 0),
            fps=np.float32(meta.get("fps") or 0.0),
            climber_track_id=np.int32(-1 if climber is None else climber),
            run_id=np.asarray(str(meta.get("run_id") or "")),
            provider=np.asarray(str(meta.get("provider") or "")),
            model_version=np.asarray(str(meta.get("model_version") or "")),
            det_every=np.int32(meta.get("det_every") or 5),
            mode=np.asarray(str(meta.get("mode") or "balanced")),
            device=np.asarray(str(meta.get("device") or "")),
            edits_hash=np.asarray(str(meta.get("edits_hash") or "")),
        )
    os.replace(tmp, path)


def read_pose(path: Path) -> dict[str, Any]:
    """Read one NPZ. Refuse pickle arrays."""
    with np.load(path, allow_pickle=False) as payload:
        data = {key: payload[key] for key in payload.files}
    keypoints = np.asarray(data["keypoints"], dtype=np.float32)
    if keypoints.ndim != 3:
        keypoints = keypoints.reshape(-1, N_KEYPOINTS, 3)
    data["keypoints"] = keypoints
    data["frame"] = np.asarray(data["frame"], dtype=np.int32)
    data["track_id"] = np.asarray(data["track_id"], dtype=np.int32)
    data["bbox"] = np.asarray(data["bbox"], dtype=np.float32).reshape(-1, 4)
    data["n_frames"] = int(np.asarray(data.get("n_frames", 0)))
    data["fps"] = float(np.asarray(data.get("fps", 0.0)))
    climber = int(np.asarray(data.get("climber_track_id", -1)))
    data["climber_track_id"] = None if climber < 0 else climber
    data["run_id"] = str(np.asarray(data.get("run_id", "")))
    data["provider"] = str(np.asarray(data.get("provider", "")))
    data["model_version"] = str(np.asarray(data.get("model_version", "")))
    data["det_every"] = int(np.asarray(data.get("det_every", 5)))
    data["mode"] = str(np.asarray(data.get("mode", "balanced")))
    data["device"] = str(np.asarray(data.get("device", "")))
    data["edits_hash"] = str(np.asarray(data.get("edits_hash", "")))
    return data


def write_effective(raw_path: Path, data: dict[str, Any], *, hash_value: str) -> Path:
    dest = effective_path(raw_path)
    meta = {
        "n_frames": data.get("n_frames"),
        "fps": data.get("fps"),
        "climber_track_id": data.get("climber_track_id"),
        "run_id": data.get("run_id"),
        "provider": data.get("provider"),
        "model_version": data.get("model_version"),
        "det_every": data.get("det_every"),
        "mode": data.get("mode"),
        "device": data.get("device"),
        "edits_hash": hash_value,
    }
    write_pose(
        dest,
        frame=np.asarray(data["frame"]),
        track_id=np.asarray(data["track_id"]),
        keypoints=np.asarray(data["keypoints"]),
        bbox=np.asarray(data["bbox"]),
        meta=meta,
    )
    return dest


def read_effective(raw_path: Path, hash_value: str) -> dict[str, Any] | None:
    dest = effective_path(raw_path)
    if not dest.is_file():
        return None
    data = read_pose(dest)
    if data.get("edits_hash") != hash_value:
        return None
    return data


def tracks_to_arrays(tracks: list[Any], *, n_keypoints: int = N_KEYPOINTS) -> dict[str, np.ndarray]:
    """Flatten Track objects into store arrays."""
    frames: list[int] = []
    ids: list[int] = []
    kpts: list[np.ndarray] = []
    boxes: list[np.ndarray] = []
    for track in tracks:
        for index, frame in enumerate(track.frames):
            frames.append(int(frame))
            ids.append(int(track.track_id))
            xy = np.asarray(track.keypoints[index], dtype=np.float32).reshape(n_keypoints, 2)
            score = np.asarray(track.scores[index], dtype=np.float32).reshape(n_keypoints)
            kpts.append(np.concatenate([xy, score[:, None]], axis=1))
            boxes.append(np.asarray(track.boxes[index], dtype=np.float32).reshape(4))
    if not frames:
        return {
            "frame": np.zeros((0,), dtype=np.int32),
            "track_id": np.zeros((0,), dtype=np.int32),
            "keypoints": np.zeros((0, n_keypoints, 3), dtype=np.float32),
            "bbox": np.zeros((0, 4), dtype=np.float32),
        }
    return {
        "frame": np.asarray(frames, dtype=np.int32),
        "track_id": np.asarray(ids, dtype=np.int32),
        "keypoints": np.stack(kpts).astype(np.float32),
        "bbox": np.stack(boxes).astype(np.float32),
    }
