"""Keyframe edits change only their range. Undo restores the previous output."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.edits import apply_edits, confirmed_frames
from app.core.halpe26 import LEFT_WRIST, N_KEYPOINTS, RIGHT_WRIST, swap_left_right


def _series(n_frames: int = 6, x0: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    frames = np.arange(n_frames, dtype=np.int32)
    keypoints = np.zeros((n_frames, N_KEYPOINTS, 3), dtype=np.float32)
    keypoints[:, :, 2] = 0.9
    for index in range(n_frames):
        keypoints[index, LEFT_WRIST] = (x0 + index, 20.0 + index, 0.9)
        keypoints[index, RIGHT_WRIST] = (x0 + 20.0 + index, 20.0 + index, 0.9)
    return frames, keypoints


def test_move_changes_only_interior_of_range() -> None:
    frames, raw = _series()
    edit = {
        "kind": "move",
        "frame": 3,
        "range_start": 1,
        "range_end": 5,
        "points": [{"kpt": LEFT_WRIST, "x": 80.0, "y": 40.0}],
    }
    out = apply_edits(frames, raw, [edit])
    assert np.allclose(out[0], raw[0])
    assert np.allclose(out[1], raw[1])
    assert np.allclose(out[5], raw[5])
    assert abs(float(out[3, LEFT_WRIST, 0]) - 80.0) < 1e-5
    assert abs(float(out[3, LEFT_WRIST, 1]) - 40.0) < 1e-5
    assert float(out[2, LEFT_WRIST, 0]) != float(raw[2, LEFT_WRIST, 0])
    assert float(out[4, LEFT_WRIST, 0]) != float(raw[4, LEFT_WRIST, 0])
    assert np.allclose(out[:, RIGHT_WRIST], raw[:, RIGHT_WRIST])


def test_single_frame_move() -> None:
    frames, raw = _series()
    edit = {
        "kind": "move",
        "frame": 2,
        "kpt": LEFT_WRIST,
        "x": 50.0,
        "y": 8.0,
    }
    out = apply_edits(frames, raw, [edit])
    assert abs(float(out[2, LEFT_WRIST, 0]) - 50.0) < 1e-5
    for index in (0, 1, 3, 4, 5):
        assert np.allclose(out[index], raw[index])


def test_lr_swap_range() -> None:
    frames, raw = _series()
    edit = {"kind": "lr_swap", "frame": 2, "range_start": 2, "range_end": 3}
    out = apply_edits(frames, raw, [edit])
    assert np.allclose(out[2], swap_left_right(raw[2]))
    assert np.allclose(out[3], swap_left_right(raw[3]))
    assert np.allclose(out[1], raw[1])
    assert np.allclose(out[4], raw[4])


def test_invalid_zeroes_scores_in_range() -> None:
    frames, raw = _series()
    edit = {
        "kind": "invalid",
        "frame": 1,
        "range_start": 1,
        "range_end": 2,
        "kpt": LEFT_WRIST,
    }
    out = apply_edits(frames, raw, [edit])
    assert float(out[1, LEFT_WRIST, 2]) == 0.0
    assert float(out[2, LEFT_WRIST, 2]) == 0.0
    assert float(out[0, LEFT_WRIST, 2]) == pytest.approx(0.9)
    assert float(out[1, RIGHT_WRIST, 2]) == pytest.approx(0.9)


def test_confirm_is_noop_and_records_frames() -> None:
    frames, raw = _series()
    edit = {"kind": "confirm", "frame": 4, "range_start": 4, "range_end": 4}
    out = apply_edits(frames, raw, [edit])
    assert np.array_equal(out, raw)
    assert confirmed_frames([edit]) == {4}


def test_delete_undo_restores_previous_output() -> None:
    frames, raw = _series()
    first = {
        "kind": "move",
        "frame": 2,
        "range_start": 1,
        "range_end": 3,
        "points": [{"kpt": LEFT_WRIST, "x": 70.0, "y": 15.0}],
    }
    second = {
        "kind": "lr_swap",
        "frame": 2,
        "range_start": 2,
        "range_end": 4,
    }
    after_first = apply_edits(frames, raw, [first])
    after_both = apply_edits(frames, raw, [first, second])
    after_undo = apply_edits(frames, raw, [first])
    assert not np.allclose(after_both, after_first)
    assert np.allclose(after_undo, after_first)
