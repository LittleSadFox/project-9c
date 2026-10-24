"""Climber selection and click-to-pick tests."""

from __future__ import annotations

import numpy as np

from app.core.climber import (
    coverage,
    person_at_point,
    person_at_xy,
    select_climber,
    vertical_travel,
)
from app.core.halpe26 import HIP, N_KEYPOINTS
from app.core.tracking import Track
from app.pose.estimator import stick_figure


def _track(track_id: int, frames: list[int], hip_ys: list[float], x: float = 40.0) -> Track:
    track = Track(track_id=track_id)
    for frame, hip in zip(frames, hip_ys, strict=True):
        box = np.array([x, hip - 20.0, x + 40.0, hip + 40.0], dtype=np.float32)
        kpts, scores = stick_figure(box)
        kpts[HIP, 1] = hip
        track.frames.append(frame)
        track.boxes.append(box)
        track.keypoints.append(kpts)
        track.scores.append(scores)
    return track


def test_selects_largest_vertical_travel() -> None:
    standing = _track(1, list(range(10)), [180.0] * 10, x=20.0)
    climbing = _track(2, list(range(10)), [200.0 - 12.0 * i for i in range(10)], x=200.0)
    assert vertical_travel(climbing) > vertical_travel(standing)
    assert select_climber([standing, climbing]) == 2
    assert coverage(climbing) == 1.0


def test_select_climber_empty() -> None:
    assert select_climber([]) is None


def test_person_at_point_picks_smallest_box() -> None:
    outer = _track(1, [3], [80.0], x=10.0)
    outer.boxes[0] = np.array([0.0, 0.0, 100.0, 100.0], dtype=np.float32)
    inner = _track(2, [3], [80.0], x=40.0)
    inner.boxes[0] = np.array([30.0, 30.0, 60.0, 70.0], dtype=np.float32)
    assert person_at_point([outer, inner], 3, 45.0, 50.0) == 2
    assert person_at_point([outer, inner], 3, 5.0, 5.0) == 1
    assert person_at_point([outer, inner], 9, 45.0, 50.0) is None
    frames = np.array([3, 3], dtype=np.int32)
    track_ids = np.array([1, 2], dtype=np.int32)
    boxes = np.stack([outer.boxes[0], inner.boxes[0]])
    assert person_at_xy(frames, track_ids, boxes, 3, 45.0, 50.0) == 2
    assert person_at_xy(frames, track_ids, boxes, 3, 5.0, 5.0) == 1
    assert N_KEYPOINTS == 26
