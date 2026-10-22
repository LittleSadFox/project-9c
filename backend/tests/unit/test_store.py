"""NPZ pose store round-trip and effective cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.halpe26 import N_KEYPOINTS
from app.pose.store import edits_hash, read_effective, read_pose, write_effective, write_pose


def test_pose_npz_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "pose" / "run.npz"
    frame = np.array([0, 1, 1], dtype=np.int32)
    track_id = np.array([1, 1, 2], dtype=np.int32)
    keypoints = np.zeros((3, N_KEYPOINTS, 3), dtype=np.float32)
    keypoints[0, 19] = (10.0, 20.0, 0.9)
    bbox = np.array([[1, 2, 3, 4], [1, 2, 3, 4], [8, 8, 20, 40]], dtype=np.float32)
    write_pose(
        path,
        frame=frame,
        track_id=track_id,
        keypoints=keypoints,
        bbox=bbox,
        meta={
            "n_frames": 2,
            "fps": 30.0,
            "climber_track_id": 1,
            "run_id": "run-1",
            "provider": "CPUExecutionProvider",
            "model_version": "fixture",
            "det_every": 5,
            "mode": "balanced",
            "device": "cpu",
        },
    )
    data = read_pose(path)
    assert data["run_id"] == "run-1"
    assert data["climber_track_id"] == 1
    assert data["n_frames"] == 2
    assert data["keypoints"].shape == (3, N_KEYPOINTS, 3)
    assert float(data["keypoints"][0, 19, 0]) == 10.0


def test_effective_cache_keyed_by_edits_hash(tmp_path: Path) -> None:
    raw = tmp_path / "run.npz"
    frame = np.array([0], dtype=np.int32)
    track_id = np.array([1], dtype=np.int32)
    keypoints = np.zeros((1, N_KEYPOINTS, 3), dtype=np.float32)
    bbox = np.array([[0, 0, 10, 10]], dtype=np.float32)
    write_pose(
        raw,
        frame=frame,
        track_id=track_id,
        keypoints=keypoints,
        bbox=bbox,
        meta={"n_frames": 1, "fps": 30.0, "run_id": "run-2", "climber_track_id": 1},
    )
    data = read_pose(raw)
    empty = edits_hash([])
    write_effective(raw, data, hash_value=empty)
    assert read_effective(raw, empty) is not None
    assert read_effective(raw, edits_hash([{"kind": "move"}])) is None
