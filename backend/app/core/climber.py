"""Climber selection and person-at-point lookup."""

from __future__ import annotations

import numpy as np

from .halpe26 import HIP, LEFT_HIP, RIGHT_HIP, SCORE_THR
from .tracking import Track


def hip_y(
    keypoints: np.ndarray, scores: np.ndarray, *, score_thr: float = SCORE_THR
) -> float | None:
    """Hip height in image y. Prefer keypoint 19, else the hip pair."""
    kpts = np.asarray(keypoints)
    sc = np.asarray(scores)
    if sc[HIP] >= score_thr:
        return float(kpts[HIP, 1])
    if sc[LEFT_HIP] >= score_thr and sc[RIGHT_HIP] >= score_thr:
        return float(0.5 * (kpts[LEFT_HIP, 1] + kpts[RIGHT_HIP, 1]))
    return None


def vertical_travel(track: Track, *, score_thr: float = SCORE_THR) -> float:
    """Range of hip y on the track. Larger means more climb travel."""
    values = [
        y
        for keypoints, scores in zip(track.keypoints, track.scores, strict=True)
        if (y := hip_y(keypoints, scores, score_thr=score_thr)) is not None
    ]
    if len(values) < 2:
        return 0.0
    return float(max(values) - min(values))


def coverage(track: Track) -> float:
    """Fraction of frames in [first, last] that have a detection."""
    if not track.frames:
        return 0.0
    span = track.last_frame - track.first_frame + 1
    if span <= 0:
        return 0.0
    return float(len(track.frames) / span)


def select_climber(tracks: list[Track]) -> int | None:
    """Pick the track with the largest vertical travel."""
    if not tracks:
        return None
    best = max(tracks, key=lambda track: (vertical_travel(track), coverage(track), -track.track_id))
    return best.track_id


def person_at_point(tracks: list[Track], frame: int, x: float, y: float) -> int | None:
    """Return the track whose box on this frame contains (x, y). Prefer the smallest box."""
    hits: list[tuple[float, int]] = []
    for track in tracks:
        try:
            index = track.frames.index(frame)
        except ValueError:
            continue
        box = track.boxes[index]
        if float(box[0]) <= x <= float(box[2]) and float(box[1]) <= y <= float(box[3]):
            area = max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))
            hits.append((area, track.track_id))
    if not hits:
        return None
    hits.sort()
    return hits[0][1]
