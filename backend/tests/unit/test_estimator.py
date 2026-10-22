"""Fixture estimator: no boxes means no pose call."""

from __future__ import annotations

import numpy as np

from app.pose.estimator import FixtureEstimator, empty_boxes, resolve_device
from app.services.pose_service import process_frames


def test_estimate_skips_pose_when_detector_is_empty() -> None:
    estimator = FixtureEstimator()
    result = estimator.estimate(np.zeros((16, 16, 3), dtype=np.uint8))
    assert estimator.detect_calls == 1
    assert estimator.pose_calls == 0
    assert result["tracks"] == []
    assert np.asarray(result["boxes"]).shape[0] == 0


def test_process_frames_no_boxes_means_zero_tracks() -> None:
    estimator = FixtureEstimator()
    frames = [(index, np.zeros((16, 16, 3), dtype=np.uint8)) for index in range(12)]
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=5)
    assert estimator.pose_calls == 0
    assert tracks == []
    assert climber is None


def test_fixture_pose_runs_only_when_boxes_exist() -> None:
    detections = {
        0: np.array([[10.0, 10.0, 50.0, 80.0]], dtype=np.float32),
        5: empty_boxes(),
    }
    estimator = FixtureEstimator(detections=detections)
    frames = [(index, np.zeros((16, 16, 3), dtype=np.uint8)) for index in range(6)]
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=1)
    assert estimator.pose_calls == 1
    assert len(tracks) == 1
    assert climber == tracks[0].track_id


def test_resolve_device_cpu() -> None:
    assert resolve_device("cpu") == "cpu"
