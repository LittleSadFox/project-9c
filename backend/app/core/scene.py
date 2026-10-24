"""Height above floor, progress, and the automatic Theil-Sen floor line.

core/ imports only numpy and the Python standard library.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import geometry
from .halpe26 import (
    HIP,
    LEFT_ANKLE,
    LEFT_BIG_TOE,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_SMALL_TOE,
    N_KEYPOINTS,
    NECK,
    RIGHT_ANKLE,
    RIGHT_BIG_TOE,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_SMALL_TOE,
    SCORE_THR,
)

FOOT_KPTS = (
    LEFT_ANKLE,
    RIGHT_ANKLE,
    LEFT_BIG_TOE,
    RIGHT_BIG_TOE,
    LEFT_SMALL_TOE,
    RIGHT_SMALL_TOE,
    LEFT_HEEL,
    RIGHT_HEEL,
)
LOW_BODY_KPTS = (
    LEFT_HIP,
    RIGHT_HIP,
    HIP,
    LEFT_ANKLE,
    RIGHT_ANKLE,
    LEFT_BIG_TOE,
    RIGHT_BIG_TOE,
    LEFT_SMALL_TOE,
    RIGHT_SMALL_TOE,
    LEFT_HEEL,
    RIGHT_HEEL,
)
STATIC_SPEED_S = 0.08
LOWEST_FRAC = 0.10


def _xy_scores(keypoints: object, scores: object | None = None) -> tuple[np.ndarray, np.ndarray]:
    kpts = np.asarray(keypoints, dtype=np.float32)
    if kpts.ndim == 2:
        kpts = kpts[None, ...]
    if kpts.shape[-1] >= 3 and scores is None:
        sc = kpts[..., 2]
        xy = kpts[..., :2]
    else:
        xy = kpts[..., :2]
        if scores is None:
            sc = np.ones(xy.shape[:2], dtype=np.float32)
        else:
            sc = np.asarray(scores, dtype=np.float32)
            if sc.ndim == 1:
                sc = sc[None, ...]
    if xy.shape[1] < N_KEYPOINTS:
        pad = N_KEYPOINTS - xy.shape[1]
        xy = np.pad(xy, ((0, 0), (0, pad), (0, 0)))
        sc = np.pad(sc, ((0, 0), (0, pad)))
    return xy, sc


def torso_length(
    keypoints: object,
    scores: object | None = None,
    *,
    score_thr: float = SCORE_THR,
    fallback: float = 80.0,
) -> float:
    """Median neck-to-hip distance in pixels over valid frames."""
    xy, sc = _xy_scores(keypoints, scores)
    valid = (sc[:, NECK] >= score_thr) & (sc[:, HIP] >= score_thr)
    if not np.any(valid):
        return float(fallback)
    lengths = np.linalg.norm(xy[valid, NECK] - xy[valid, HIP], axis=1)
    lengths = lengths[lengths > 1.0]
    if lengths.size == 0:
        return float(fallback)
    return float(np.median(lengths))


def lowest_points(
    keypoints: object,
    scores: object | None = None,
    *,
    indices: tuple[int, ...] = LOW_BODY_KPTS,
    score_thr: float = SCORE_THR,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame lowest valid body point (image y down) and its validity mask."""
    xy, sc = _xy_scores(keypoints, scores)
    n = xy.shape[0]
    out = np.full((n, 2), np.nan, dtype=np.float32)
    valid = np.zeros((n,), dtype=bool)
    idx = np.asarray(indices, dtype=np.int32)
    for i in range(n):
        good = sc[i, idx] >= score_thr
        if not np.any(good):
            continue
        pts = xy[i, idx[good]]
        pick = int(np.argmax(pts[:, 1]))
        out[i] = pts[pick]
        valid[i] = True
    return out, valid


def height_above_floor(
    points: object,
    floor_line: object,
    *,
    torso: float,
) -> np.ndarray:
    """Height above the floor line in torso units."""
    scale = max(float(torso), 1.0)
    return geometry.height_above_line(points, floor_line) / scale


def theil_sen_line(points: object) -> np.ndarray:
    """Robust line through 2D points. Returns two endpoints on the x span."""
    pts = geometry.as_points(points)
    if pts.shape[0] == 0:
        return np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    if pts.shape[0] == 1:
        x, y = float(pts[0, 0]), float(pts[0, 1])
        return np.array([[x - 1.0, y], [x + 1.0, y]], dtype=np.float32)
    xs = pts[:, 0]
    ys = pts[:, 1]
    slopes: list[float] = []
    for i in range(pts.shape[0] - 1):
        dx = xs[i + 1 :] - xs[i]
        dy = ys[i + 1 :] - ys[i]
        ok = np.abs(dx) > 1e-6
        if np.any(ok):
            slopes.extend((dy[ok] / dx[ok]).tolist())
    if not slopes:
        y = float(np.median(ys))
        return np.array([[float(xs.min()), y], [float(xs.max()), y]], dtype=np.float32)
    slope = float(np.median(np.asarray(slopes, dtype=np.float64)))
    intercept = float(np.median(ys - slope * xs))
    x0 = float(xs.min())
    x1 = float(xs.max())
    if abs(x1 - x0) < 1.0:
        x1 = x0 + 1.0
    return np.array([[x0, slope * x0 + intercept], [x1, slope * x1 + intercept]], dtype=np.float32)


def auto_floor_line(
    keypoints: object,
    scores: object | None = None,
    *,
    fps: float = 30.0,
    score_thr: float = SCORE_THR,
    static_speed_s: float = STATIC_SPEED_S,
    lowest_frac: float = LOWEST_FRAC,
    frame_width: float | None = None,
) -> np.ndarray:
    """Theil-Sen line through static feet in the lowest 10% of their height range."""
    xy, sc = _xy_scores(keypoints, scores)
    torso = torso_length(xy, sc, score_thr=score_thr)
    feet, valid = lowest_points(xy, sc, indices=FOOT_KPTS, score_thr=score_thr)
    if int(valid.sum()) < 2:
        y = float(np.nanmax(xy[..., 1])) if xy.size else 0.0
        width = float(frame_width or max(float(np.nanmax(xy[..., 0])) if xy.size else 1.0, 1.0))
        return np.array([[0.0, y], [width, y]], dtype=np.float32)

    idx = np.flatnonzero(valid)
    pts = feet[idx]
    if idx.size >= 2 and fps > 0 and torso > 0:
        dt = np.diff(idx.astype(np.float32)) / float(fps)
        disp = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        speed = disp / np.maximum(dt, 1.0 / max(float(fps), 1.0)) / max(torso, 1.0)
        static_pair = speed <= float(static_speed_s)
        static_mask = np.zeros((idx.size,), dtype=bool)
        static_mask[0] = bool(static_pair[0]) if static_pair.size else True
        static_mask[1:] = static_pair
        if static_mask[0] is False and static_pair.size:
            static_mask[0] = bool(static_pair[0])
        # A frame is static when both neighbour steps are slow.
        if static_pair.size:
            left = np.concatenate([[static_pair[0]], static_pair])
            right = np.concatenate([static_pair, [static_pair[-1]]])
            static_mask = left | right
        if int(static_mask.sum()) >= 2:
            idx = idx[static_mask]
            pts = pts[static_mask]

    ys = pts[:, 1]
    y_lo = float(np.min(ys))
    y_hi = float(np.max(ys))
    span = max(y_hi - y_lo, 1.0)
    low = ys >= (y_hi - float(lowest_frac) * span)
    if int(low.sum()) < 2:
        low = np.ones((pts.shape[0],), dtype=bool)
    line = theil_sen_line(pts[low])
    if frame_width is not None and frame_width > 0:
        x0, x1 = 0.0, float(frame_width)
        slope = (line[1, 1] - line[0, 1]) / max(float(line[1, 0] - line[0, 0]), 1e-6)
        intercept = float(line[0, 1] - slope * line[0, 0])
        line = np.array(
            [[x0, slope * x0 + intercept], [x1, slope * x1 + intercept]],
            dtype=np.float32,
        )
    return line.astype(np.float32)


def progress_along_wall(
    hip_points: object,
    floor_line: object,
    top_zone: object | None,
    *,
    torso: float,
) -> np.ndarray:
    """0-1 progress from the floor toward the top zone centroid. Else hip height in s."""
    hips = geometry.as_points(hip_points)
    heights = height_above_floor(hips, floor_line, torso=torso)
    if top_zone is None:
        return heights
    zone = geometry.as_points(top_zone)
    if zone.shape[0] < 3:
        return heights
    top_h = float(np.median(height_above_floor(zone, floor_line, torso=torso)))
    denom = max(top_h, 1e-3)
    return np.clip(heights / denom, 0.0, 1.5).astype(np.float32)


def scene_defaults() -> dict[str, Any]:
    return {
        "floor_line": None,
        "top_zone": None,
        "start_holds": None,
        "ref_points": None,
        "source": "auto",
    }
