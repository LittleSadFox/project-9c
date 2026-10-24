"""L/R flip and low-score flags for the skeleton review queue."""

from __future__ import annotations

from typing import Any

import numpy as np

from .halpe26 import SCORE_THR, swap_left_right

LOW_SCORE = 0.5
LR_IMPROVE = 0.5


def frame_jump(
    previous: np.ndarray,
    current: np.ndarray,
    *,
    score_thr: float = SCORE_THR,
) -> float:
    """Sum of valid keypoint travel between two frames."""
    prev = np.asarray(previous, dtype=np.float32)
    cur = np.asarray(current, dtype=np.float32)
    valid = (prev[:, 2] >= score_thr) & (cur[:, 2] >= score_thr)
    if not np.any(valid):
        return 0.0
    delta = cur[valid, :2] - prev[valid, :2]
    return float(np.linalg.norm(delta, axis=1).sum())


def flag_frames(
    frame_index: np.ndarray,
    keypoints: np.ndarray,
    *,
    confirmed: set[int] | None = None,
    score_thr: float = SCORE_THR,
    low_score: float = LOW_SCORE,
    lr_improve: float = LR_IMPROVE,
) -> list[dict[str, Any]]:
    """Flag L/R flips and low-score frames. Worst first.

    An L/R flip is a frame where swapping left and right cuts the
    frame-to-frame jump by more than 50 percent.
    """
    frames = np.asarray(frame_index, dtype=np.int32)
    kpts = np.asarray(keypoints, dtype=np.float32)
    skip = confirmed or set()
    flags: list[dict[str, Any]] = []
    if kpts.ndim != 3 or kpts.shape[0] != frames.shape[0]:
        return flags
    for index, frame in enumerate(frames):
        frame_i = int(frame)
        if frame_i in skip:
            continue
        mean_score = float(np.mean(kpts[index, :, 2]))
        if mean_score < low_score:
            flags.append(
                {
                    "frame": frame_i,
                    "kind": "low_score",
                    "severity": float(low_score - mean_score),
                }
            )
        if index == 0:
            continue
        jump = frame_jump(kpts[index - 1], kpts[index], score_thr=score_thr)
        if jump <= 0.0:
            continue
        swapped = np.asarray(swap_left_right(kpts[index]), dtype=np.float32)
        jump_swap = frame_jump(kpts[index - 1], swapped, score_thr=score_thr)
        if jump_swap < jump * (1.0 - lr_improve):
            flags.append(
                {
                    "frame": frame_i,
                    "kind": "lr_flip",
                    "severity": float(1.0 - (jump_swap / jump)),
                }
            )
    flags.sort(key=lambda item: (-float(item["severity"]), int(item["frame"]), str(item["kind"])))
    return flags
