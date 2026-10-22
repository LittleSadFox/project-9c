"""Tracker, keypoint boxes, and fragment stitch tests."""

from __future__ import annotations

import numpy as np

from app.core.halpe26 import N_KEYPOINTS
from app.core.tracking import Tracker, box_from_keypoints, box_iou, stitch_fragments
from app.pose.estimator import stick_figure


def _person(
    x: float, y: float, w: float = 40.0, h: float = 80.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    box = np.array([x, y, x + w, y + h], dtype=np.float32)
    kpts, scores = stick_figure(box)
    return box, kpts, scores


def test_two_people_keep_identities() -> None:
    tracker = Tracker()
    for frame in range(8):
        left = _person(10, 40)
        right = _person(200, 40)
        boxes = np.stack([left[0], right[0]])
        kpts = np.stack([left[1], right[1]])
        scores = np.stack([left[2], right[2]])
        tracker.update(frame, boxes, kpts, scores)
    tracks = tracker.finalize()
    assert len(tracks) == 2
    xs = sorted(float(track.boxes[0][0]) for track in tracks)
    assert xs[0] < 50
    assert xs[1] > 150
    assert all(len(track.frames) == 8 for track in tracks)


def test_empty_detections_give_zero_tracks() -> None:
    tracker = Tracker()
    empty_k = np.zeros((0, N_KEYPOINTS, 2), dtype=np.float32)
    empty_s = np.zeros((0, N_KEYPOINTS), dtype=np.float32)
    for frame in range(5):
        tracker.update(frame, np.zeros((0, 4), dtype=np.float32), empty_k, empty_s)
    assert tracker.finalize() == []


def test_box_from_keypoints_and_iou() -> None:
    box, kpts, scores = _person(20, 30)
    derived = box_from_keypoints(kpts, scores)
    assert derived is not None
    assert box_iou(box, derived) > 0.4
    low = np.zeros(N_KEYPOINTS, dtype=np.float32)
    assert box_from_keypoints(kpts, low) is None


def test_fragment_stitch_merges_short_gap() -> None:
    tracker = Tracker(max_age=1, stitch_gap=10)
    empty = np.zeros((0, 4), dtype=np.float32)
    empty_k = np.zeros((0, N_KEYPOINTS, 2), dtype=np.float32)
    empty_s = np.zeros((0, N_KEYPOINTS), dtype=np.float32)
    for frame in (0, 1, 2):
        box, kpts, scores = _person(30, 40)
        tracker.update(
            frame,
            box.reshape(1, 4),
            kpts.reshape(1, N_KEYPOINTS, 2),
            scores.reshape(1, N_KEYPOINTS),
        )
    for frame in (3, 4, 5):
        tracker.update(frame, empty, empty_k, empty_s)
    for frame in (8, 9, 10):
        box, kpts, scores = _person(32, 42)
        tracker.update(
            frame,
            box.reshape(1, 4),
            kpts.reshape(1, N_KEYPOINTS, 2),
            scores.reshape(1, N_KEYPOINTS),
        )
    tracks = tracker.finalize()
    assert len(tracks) == 1
    assert tracks[0].first_frame == 0
    assert tracks[0].last_frame == 10


def test_stitch_skips_far_boxes() -> None:
    first = Tracker()
    box_a, k_a, s_a = _person(10, 20)
    box_b, k_b, s_b = _person(300, 20)
    first.update(0, box_a.reshape(1, 4), k_a.reshape(1, 26, 2), s_a.reshape(1, 26))
    first.update(2, box_b.reshape(1, 4), k_b.reshape(1, 26, 2), s_b.reshape(1, 26))
    tracks = stitch_fragments(first.finalize(), max_gap=10, iou_thr=0.3)
    assert len(tracks) == 2
