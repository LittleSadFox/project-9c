"""Rule event detector: leave_ground, top, drop, ground_return, and outcome.

Lengths are in torso units s. Time is in seconds.
core/ imports only numpy and the Python standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import geometry
from .halpe26 import (
    LEFT_ELBOW,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_WRIST,
    SCORE_THR,
)
from .scene import (
    height_above_floor,
    lowest_points,
    torso_length,
)

DEFAULT_THRESHOLDS: dict[str, float] = {
    "leave_ground_height_s": 0.15,
    "leave_ground_hold_s": 0.5,
    "ground_return_height_s": 0.10,
    "ground_return_hold_s": 0.3,
    "drop_speed_s": 3.0,
    "drop_window_s": 1.0,
    "top_hold_s": 1.0,
    "top_grow_s": 0.2,
    "gap_fill_s": 0.5,
}

LEAVE_GROUND = "leave_ground"
GROUND_RETURN = "ground_return"
DROP = "drop"
TOP = "top"
OUTCOME_SEND = "send"
OUTCOME_FALL = "fall"
OUTCOME_UNKNOWN = "unknown"


@dataclass
class DetectedEvent:
    frame: int
    kind: str
    confidence: float
    source: str = "rule"


@dataclass
class AttemptSpan:
    leave_ground: int
    ground_return: int
    outcome: str
    confidence: float
    events: list[DetectedEvent] = field(default_factory=list)


def _frames_for(seconds: float, fps: float) -> int:
    return max(1, int(round(float(seconds) * float(fps))))


def interpolate_heights(heights: np.ndarray, *, max_gap: int) -> np.ndarray:
    """Fill short NaN gaps so dropped frames do not break a run."""
    out = heights.astype(np.float32).copy()
    n = out.size
    i = 0
    while i < n:
        if not np.isnan(out[i]):
            i += 1
            continue
        start = i
        while i < n and np.isnan(out[i]):
            i += 1
        gap = i - start
        if gap > max_gap:
            continue
        left = out[start - 1] if start > 0 else np.nan
        right = out[i] if i < n else np.nan
        if np.isnan(left) and np.isnan(right):
            continue
        if np.isnan(left):
            out[start:i] = right
        elif np.isnan(right):
            out[start:i] = left
        else:
            out[start:i] = np.linspace(left, right, gap + 2)[1:-1]
    return out


def hip_heights(
    keypoints: object,
    scores: object | None,
    floor_line: object,
    *,
    torso: float,
    score_thr: float = SCORE_THR,
) -> np.ndarray:
    from .halpe26 import HIP

    kpts = np.asarray(keypoints, dtype=np.float32)
    if kpts.ndim == 2:
        kpts = kpts[None, ...]
    if kpts.shape[-1] >= 3 and scores is None:
        sc = kpts[..., 2]
        xy = kpts[..., :2]
    else:
        xy = kpts[..., :2]
        sc = (
            np.ones(xy.shape[:2], dtype=np.float32)
            if scores is None
            else np.asarray(scores, dtype=np.float32)
        )
        if sc.ndim == 1:
            sc = np.broadcast_to(sc, xy.shape[:2])
    points = np.full((xy.shape[0], 2), np.nan, dtype=np.float32)
    valid = sc[:, HIP] >= score_thr
    points[valid] = xy[valid, HIP]
    heights = np.full((xy.shape[0],), np.nan, dtype=np.float32)
    if np.any(valid):
        heights[valid] = height_above_floor(points[valid], floor_line, torso=torso)
    return heights


def hand_points(
    keypoints: object,
    scores: object | None = None,
    *,
    score_thr: float = SCORE_THR,
) -> tuple[np.ndarray, np.ndarray]:
    """Contact hands: wrist + 0.3 * (wrist - elbow)."""
    kpts = np.asarray(keypoints, dtype=np.float32)
    if kpts.ndim == 2:
        kpts = kpts[None, ...]
    if kpts.shape[-1] >= 3 and scores is None:
        sc = kpts[..., 2]
        xy = kpts[..., :2]
    else:
        xy = kpts[..., :2]
        sc = (
            np.ones(xy.shape[:2], dtype=np.float32)
            if scores is None
            else np.asarray(scores, dtype=np.float32)
        )
        if sc.ndim == 1:
            sc = np.broadcast_to(sc, xy.shape[:2])
    left = np.full((xy.shape[0], 2), np.nan, dtype=np.float32)
    right = np.full((xy.shape[0], 2), np.nan, dtype=np.float32)
    left_ok = (sc[:, LEFT_WRIST] >= score_thr) & (sc[:, LEFT_ELBOW] >= score_thr)
    right_ok = (sc[:, RIGHT_WRIST] >= score_thr) & (sc[:, RIGHT_ELBOW] >= score_thr)
    left[left_ok] = xy[left_ok, LEFT_WRIST] + 0.3 * (
        xy[left_ok, LEFT_WRIST] - xy[left_ok, LEFT_ELBOW]
    )
    right[right_ok] = xy[right_ok, RIGHT_WRIST] + 0.3 * (
        xy[right_ok, RIGHT_WRIST] - xy[right_ok, RIGHT_ELBOW]
    )
    return left, right


def _runs_where(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Inclusive (start, end) runs of True that last at least min_len frames."""
    runs: list[tuple[int, int]] = []
    n = int(mask.size)
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < n and mask[i]:
            i += 1
        if i - start >= min_len:
            runs.append((start, i - 1))
    return runs


def _mean_score(scores: object | None, start: int, end: int) -> float:
    if scores is None:
        return 0.8
    sc = np.asarray(scores, dtype=np.float32)
    if sc.ndim == 3:
        sc = sc[..., -1]
    window = sc[start : end + 1]
    if window.size == 0:
        return 0.5
    return float(np.nanmean(window))


def detect_events(
    keypoints: object,
    scores: object | None,
    floor_line: object,
    *,
    fps: float,
    top_zone: object | None = None,
    thresholds: dict[str, float] | None = None,
    score_thr: float = SCORE_THR,
) -> tuple[list[DetectedEvent], list[AttemptSpan]]:
    """Run the rule state machine. Return events and attempt spans."""
    params = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    kpts = np.asarray(keypoints, dtype=np.float32)
    if kpts.ndim == 2:
        kpts = kpts[None, ...]
    n = int(kpts.shape[0])
    if n == 0:
        return [], []
    torso = torso_length(kpts, scores, score_thr=score_thr)
    low_pts, low_ok = lowest_points(kpts, scores, score_thr=score_thr)
    heights = np.full((n,), np.nan, dtype=np.float32)
    if np.any(low_ok):
        heights[low_ok] = height_above_floor(low_pts[low_ok], floor_line, torso=torso)
    max_gap = _frames_for(float(params["gap_fill_s"]), fps)
    heights = interpolate_heights(heights, max_gap=max_gap)

    leave_h = float(params["leave_ground_height_s"])
    return_h = float(params["ground_return_height_s"])
    leave_hold = _frames_for(float(params["leave_ground_hold_s"]), fps)
    return_hold = _frames_for(float(params["ground_return_hold_s"]), fps)
    off = heights > leave_h
    on = heights <= return_h
    off[np.isnan(heights)] = False
    on[np.isnan(heights)] = False

    leave_runs = _runs_where(off, leave_hold)
    return_runs = _runs_where(on, return_hold)

    hips = interpolate_heights(
        hip_heights(kpts, scores, floor_line, torso=torso, score_thr=score_thr),
        max_gap=max_gap,
    )
    top_mask = _top_mask(
        kpts, scores, top_zone, torso=torso, grow_s=float(params["top_grow_s"]), score_thr=score_thr
    )
    top_hold = _frames_for(float(params["top_hold_s"]), fps)
    top_runs = _runs_where(top_mask, top_hold) if top_zone is not None else []

    events: list[DetectedEvent] = []
    spans: list[AttemptSpan] = []
    ret_i = 0
    for leave_start, _leave_end in leave_runs:
        while ret_i < len(return_runs) and return_runs[ret_i][0] <= leave_start:
            ret_i += 1
        if ret_i >= len(return_runs):
            break
        land_start, land_end = return_runs[ret_i]
        if land_start <= leave_start:
            continue
        mean_s = _mean_score(scores, leave_start, land_start)
        leave_margin = 0.0
        if leave_start < n and not np.isnan(heights[leave_start]):
            leave_margin = max(0.0, float(heights[leave_start]) - leave_h)
        margin = np.tanh(leave_margin / max(leave_h, 1e-3))
        conf = float(np.clip(0.45 + 0.4 * mean_s + 0.15 * margin, 0.05, 0.99))
        leave_ev = DetectedEvent(leave_start, LEAVE_GROUND, conf)
        land_ev = DetectedEvent(land_start, GROUND_RETURN, conf)
        span_events = [leave_ev, land_ev]
        drop_ev = _drop_event(
            hips,
            leave_start,
            land_start,
            fps=fps,
            window_s=float(params["drop_window_s"]),
            speed_s=float(params["drop_speed_s"]),
            confidence=conf,
        )
        if drop_ev is not None:
            span_events.append(drop_ev)
        top_ev = None
        for top_start, _top_end in top_runs:
            if leave_start <= top_start < land_start:
                top_ev = DetectedEvent(top_start, TOP, conf)
                span_events.append(top_ev)
                break
        if top_zone is None:
            outcome = OUTCOME_UNKNOWN
        elif top_ev is not None:
            outcome = OUTCOME_SEND
        else:
            outcome = OUTCOME_FALL
        span_events.sort(key=lambda item: (item.frame, item.kind))
        events.extend(span_events)
        spans.append(
            AttemptSpan(
                leave_ground=leave_start,
                ground_return=land_start,
                outcome=outcome,
                confidence=conf,
                events=span_events,
            )
        )
        ret_i += 1
        del land_end
    events.sort(key=lambda item: (item.frame, item.kind))
    return events, spans


def _top_mask(
    keypoints: np.ndarray,
    scores: object | None,
    top_zone: object | None,
    *,
    torso: float,
    grow_s: float,
    score_thr: float,
) -> np.ndarray:
    n = int(keypoints.shape[0])
    mask = np.zeros((n,), dtype=bool)
    if top_zone is None:
        return mask
    zone = geometry.as_points(top_zone)
    if zone.shape[0] < 3:
        return mask
    grown = geometry.grow_polygon(zone, float(grow_s) * max(float(torso), 1.0))
    left, right = hand_points(keypoints, scores, score_thr=score_thr)
    for i in range(n):
        if np.any(np.isnan(left[i])) or np.any(np.isnan(right[i])):
            continue
        inside = geometry.point_in_polygon(np.stack([left[i], right[i]]), grown)
        mask[i] = bool(np.all(inside))
    return mask


def _drop_event(
    hip_h: np.ndarray,
    leave: int,
    land: int,
    *,
    fps: float,
    window_s: float,
    speed_s: float,
    confidence: float,
) -> DetectedEvent | None:
    if fps <= 0 or land <= leave:
        return None
    window = _frames_for(window_s, fps)
    start = max(leave, land - window)
    segment = hip_h[start : land + 1]
    if segment.size < 2:
        return None
    vel = -np.diff(segment) * float(fps)
    vel = vel[np.isfinite(vel)]
    if vel.size == 0:
        return None
    peak = float(np.max(vel))
    if peak < float(speed_s):
        return None
    peak_i = int(np.argmax(np.concatenate([[-np.inf], vel])))
    frame = min(land, start + peak_i)
    return DetectedEvent(frame, DROP, confidence)


def thresholds_from_settings(settings: dict[str, Any] | None) -> dict[str, float]:
    out = dict(DEFAULT_THRESHOLDS)
    if not settings:
        return out
    for key in DEFAULT_THRESHOLDS:
        if key in settings and settings[key] is not None:
            out[key] = float(settings[key])
    return out
