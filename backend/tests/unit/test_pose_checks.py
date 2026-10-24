"""Scripted L/R flips and low scores go into the review queue, worst first."""

from __future__ import annotations

import numpy as np

from app.core.halpe26 import LEFT, N_KEYPOINTS, RIGHT, swap_left_right
from app.core.pose_checks import flag_frames


def _smooth_track(n_frames: int = 8, *, flip_at: int | None = None) -> np.ndarray:
    keypoints = np.zeros((n_frames, N_KEYPOINTS, 3), dtype=np.float32)
    keypoints[:, :, 2] = 0.9
    for index in range(n_frames):
        y = 200.0 - 4.0 * index
        for left, right in zip(LEFT, RIGHT, strict=True):
            keypoints[index, left] = (40.0, y, 0.9)
            keypoints[index, right] = (80.0, y, 0.9)
        if flip_at is not None and index >= flip_at:
            keypoints[index] = np.asarray(swap_left_right(keypoints[index]))
    return keypoints


def test_scripted_lr_flip_is_flagged() -> None:
    keypoints = _smooth_track(flip_at=4)
    flags = flag_frames(np.arange(8, dtype=np.int32), keypoints)
    flips = [item for item in flags if item["kind"] == "lr_flip"]
    assert flips
    assert flips[0]["frame"] == 4
    assert float(flips[0]["severity"]) > 0.5


def test_low_score_is_flagged() -> None:
    keypoints = _smooth_track()
    keypoints[2, :, 2] = 0.2
    flags = flag_frames(np.arange(8, dtype=np.int32), keypoints)
    lows = [item for item in flags if item["kind"] == "low_score"]
    assert lows
    assert lows[0]["frame"] == 2
    assert flags[0]["kind"] in {"low_score", "lr_flip"}


def test_review_queue_is_worst_first() -> None:
    keypoints = _smooth_track(flip_at=5)
    keypoints[1, :, 2] = 0.4
    keypoints[6, :, 2] = 0.05
    flags = flag_frames(np.arange(8, dtype=np.int32), keypoints)
    severities = [float(item["severity"]) for item in flags]
    assert severities == sorted(severities, reverse=True)
    kinds = {item["kind"] for item in flags}
    assert "low_score" in kinds
    assert "lr_flip" in kinds
    assert flags[0]["severity"] >= 0.45


def test_confirmed_frames_are_skipped() -> None:
    keypoints = _smooth_track(flip_at=3)
    keypoints[3, :, 2] = 0.1
    flags = flag_frames(np.arange(8, dtype=np.int32), keypoints, confirmed={3})
    assert all(item["frame"] != 3 for item in flags)
