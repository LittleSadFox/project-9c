"""Automatic floor line and torso-scale tests."""

from __future__ import annotations

import numpy as np

from app.core.scene import auto_floor_line, height_above_floor, theil_sen_line, torso_length
from tests.fixtures.synth_pose import one_attempt, standing_only


def test_theil_sen_recovers_a_line() -> None:
    x = np.linspace(0.0, 10.0, 11)
    y = 2.0 * x + 5.0
    y[3] = 80.0
    line = theil_sen_line(np.stack([x, y], axis=1))
    slope = (line[1, 1] - line[0, 1]) / (line[1, 0] - line[0, 0])
    assert abs(slope - 2.0) < 0.15


def test_auto_floor_on_standing_track() -> None:
    video = standing_only()
    line = auto_floor_line(video.keypoints, video.scores, fps=video.fps, frame_width=1280.0)
    assert line.shape == (2, 2)
    assert abs(float(line[0, 1]) - 600.0) < 8.0
    torso = torso_length(video.keypoints, video.scores)
    assert 60.0 < torso < 100.0
    hip = video.keypoints[0, 19]
    height = height_above_floor([hip], line, torso=torso)
    assert float(height[0]) > 0.5


def test_auto_floor_on_one_attempt() -> None:
    video = one_attempt()
    line = auto_floor_line(video.keypoints, video.scores, fps=video.fps, frame_width=1280.0)
    assert abs(float(np.mean(line[:, 1])) - 600.0) < 12.0
