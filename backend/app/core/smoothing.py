"""Gap fill and One Euro smoothing for a pose track."""

from __future__ import annotations

import math

import numpy as np

from .halpe26 import HIP, NECK, SCORE_THR

MAX_GAP_S = 0.5
MIN_CUTOFF_HZ = 1.0
BETA = 0.3
D_CUTOFF_HZ = 1.0


def torso_length(
    keypoints: np.ndarray,
    scores: np.ndarray,
    *,
    score_thr: float = SCORE_THR,
) -> float:
    """Median neck-to-hip length in pixels. Fall back to 1.0."""
    dists: list[float] = []
    for kpts, sc in zip(keypoints, scores, strict=True):
        if sc[NECK] >= score_thr and sc[HIP] >= score_thr:
            dists.append(float(np.linalg.norm(kpts[NECK] - kpts[HIP])))
    if not dists:
        return 1.0
    return float(max(np.median(np.asarray(dists, dtype=np.float64)), 1e-3))


def fill_gaps(
    keypoints: np.ndarray,
    scores: np.ndarray,
    fps: float,
    *,
    max_gap_s: float = MAX_GAP_S,
    score_thr: float = SCORE_THR,
) -> tuple[np.ndarray, np.ndarray]:
    """Fill short invalid gaps with linear interpolation."""
    kpts = np.array(keypoints, dtype=np.float32, copy=True)
    sc = np.array(scores, dtype=np.float32, copy=True)
    if kpts.ndim != 3 or fps <= 0:
        return kpts, sc
    max_gap = max(1, int(round(max_gap_s * fps)))
    _, n_joints, _ = kpts.shape
    for joint in range(n_joints):
        valid = np.flatnonzero(sc[:, joint] >= score_thr)
        if valid.size < 2:
            continue
        for left, right in zip(valid[:-1], valid[1:], strict=True):
            gap = int(right - left)
            if gap <= 1 or gap - 1 > max_gap:
                continue
            span = float(right - left)
            for frame in range(int(left) + 1, int(right)):
                weight = (frame - left) / span
                left_pt = kpts[left, joint]
                right_pt = kpts[right, joint]
                kpts[frame, joint] = (1.0 - weight) * left_pt + weight * right_pt
                sc[frame, joint] = (1.0 - weight) * sc[left, joint] + weight * sc[right, joint]
    return kpts, sc


def _smoothing_factor(dt: float, cutoff: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


def one_euro_1d(
    values: np.ndarray,
    times: np.ndarray,
    *,
    min_cutoff: float = MIN_CUTOFF_HZ,
    beta: float = BETA,
    d_cutoff: float = D_CUTOFF_HZ,
) -> np.ndarray:
    """One Euro filter on a 1-D series."""
    out = np.empty_like(values, dtype=np.float64)
    if values.size == 0:
        return out
    x_prev = float(values[0])
    dx_prev = 0.0
    t_prev = float(times[0])
    out[0] = x_prev
    for index in range(1, values.size):
        t = float(times[index])
        x = float(values[index])
        dt = max(t - t_prev, 1e-6)
        dx = (x - x_prev) / dt
        a_d = _smoothing_factor(dt, d_cutoff)
        dx_hat = a_d * dx + (1.0 - a_d) * dx_prev
        cutoff = min_cutoff + beta * abs(dx_hat)
        alpha = _smoothing_factor(dt, cutoff)
        x_hat = alpha * x + (1.0 - alpha) * x_prev
        out[index] = x_hat
        x_prev = x_hat
        dx_prev = dx_hat
        t_prev = t
    return out


def smooth_track(
    keypoints: np.ndarray,
    scores: np.ndarray,
    fps: float,
    *,
    min_cutoff: float = MIN_CUTOFF_HZ,
    beta: float = BETA,
    max_gap_s: float = MAX_GAP_S,
    score_thr: float = SCORE_THR,
) -> tuple[np.ndarray, np.ndarray]:
    """Fill gaps of at most 0.5 s, then run One Euro in torso units."""
    filled_k, filled_s = fill_gaps(keypoints, scores, fps, max_gap_s=max_gap_s, score_thr=score_thr)
    if filled_k.shape[0] < 2 or fps <= 0:
        return filled_k, filled_s
    scale = torso_length(filled_k, filled_s, score_thr=score_thr)
    times = np.arange(filled_k.shape[0], dtype=np.float64) / float(fps)
    out = filled_k.copy()
    norm = filled_k / scale
    for joint in range(filled_k.shape[1]):
        mask = filled_s[:, joint] >= score_thr
        if int(mask.sum()) < 2:
            continue
        t = times[mask]
        for axis in range(2):
            filtered = one_euro_1d(norm[mask, joint, axis], t, min_cutoff=min_cutoff, beta=beta)
            out[mask, joint, axis] = (filtered * scale).astype(np.float32)
    return out, filled_s
