"""Keyframe edits with range interpolation, L/R swap, and invalid ranges."""

from __future__ import annotations

from typing import Any

import numpy as np

from .halpe26 import N_KEYPOINTS, swap_left_right

KINDS = ("move", "lr_swap", "invalid", "confirm")


def edit_range(edit: dict[str, Any]) -> tuple[int, int, int]:
    """Return inclusive (start, end, frame). Missing range uses the keyframe."""
    frame = int(edit["frame"])
    start = edit.get("range_start")
    end = edit.get("range_end")
    start_i = frame if start is None else int(start)
    end_i = frame if end is None else int(end)
    if end_i < start_i:
        start_i, end_i = end_i, start_i
    return start_i, end_i, frame


def edit_points(edit: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect move or invalid points from the row and an optional list."""
    points: list[dict[str, Any]] = []
    seen: set[int] = set()
    raw = edit.get("points") or []
    for item in raw:
        kpt = item.get("kpt")
        if kpt is None:
            continue
        index = int(kpt)
        if index in seen or index < 0 or index >= N_KEYPOINTS:
            continue
        seen.add(index)
        points.append(
            {
                "kpt": index,
                "x": None if item.get("x") is None else float(item["x"]),
                "y": None if item.get("y") is None else float(item["y"]),
            }
        )
    if edit.get("kpt") is not None:
        index = int(edit["kpt"])
        if index not in seen and 0 <= index < N_KEYPOINTS:
            points.append(
                {
                    "kpt": index,
                    "x": None if edit.get("x") is None else float(edit["x"]),
                    "y": None if edit.get("y") is None else float(edit["y"]),
                }
            )
    return points


def _row_for_frame(frame_index: np.ndarray, frame: int) -> int | None:
    hits = np.flatnonzero(np.asarray(frame_index) == int(frame))
    if hits.size == 0:
        return None
    return int(hits[0])


def _tent_weight(frame: int, start: int, peak: int, end: int) -> float:
    """1.0 at the keyframe. 0.0 at the exclusive range edges."""
    if frame == peak:
        return 1.0
    if frame < peak:
        span = peak - start
        if span <= 0:
            return 1.0
        return float(frame - start) / float(span)
    span = end - peak
    if span <= 0:
        return 1.0
    return float(end - frame) / float(span)


def _apply_move(keypoints: np.ndarray, frame_index: np.ndarray, edit: dict[str, Any]) -> None:
    start, end, peak = edit_range(edit)
    peak_row = _row_for_frame(frame_index, peak)
    if peak_row is None:
        return
    for point in edit_points(edit):
        if point["x"] is None or point["y"] is None:
            continue
        kpt = int(point["kpt"])
        origin = keypoints[peak_row, kpt]
        delta = np.asarray(
            [point["x"] - float(origin[0]), point["y"] - float(origin[1])],
            dtype=np.float32,
        )
        for row, frame in enumerate(frame_index):
            frame_i = int(frame)
            if frame_i < start or frame_i > end:
                continue
            weight = _tent_weight(frame_i, start, peak, end)
            keypoints[row, kpt, 0] += weight * delta[0]
            keypoints[row, kpt, 1] += weight * delta[1]


def _apply_lr_swap(keypoints: np.ndarray, frame_index: np.ndarray, edit: dict[str, Any]) -> None:
    start, end, _peak = edit_range(edit)
    for row, frame in enumerate(frame_index):
        frame_i = int(frame)
        if start <= frame_i <= end:
            keypoints[row] = np.asarray(swap_left_right(keypoints[row]), dtype=np.float32)


def _apply_invalid(keypoints: np.ndarray, frame_index: np.ndarray, edit: dict[str, Any]) -> None:
    start, end, _peak = edit_range(edit)
    points = edit_points(edit)
    kpts = [int(point["kpt"]) for point in points]
    for row, frame in enumerate(frame_index):
        frame_i = int(frame)
        if frame_i < start or frame_i > end:
            continue
        if kpts:
            keypoints[row, kpts, 2] = 0.0
        else:
            keypoints[row, :, 2] = 0.0


def apply_edits(
    frame_index: np.ndarray,
    keypoints: np.ndarray,
    edits: list[dict[str, Any]],
) -> np.ndarray:
    """Apply active edits in list order. Only frames inside each range change.

    ``keypoints`` is (T, 26, 3). ``confirm`` does not change values.
    """
    out = np.array(keypoints, dtype=np.float32, copy=True)
    frames = np.asarray(frame_index, dtype=np.int32)
    if out.ndim != 3 or out.shape[-2] != N_KEYPOINTS:
        return out
    for edit in edits:
        kind = str(edit.get("kind") or "")
        if kind == "move":
            _apply_move(out, frames, edit)
        elif kind == "lr_swap":
            _apply_lr_swap(out, frames, edit)
        elif kind == "invalid":
            _apply_invalid(out, frames, edit)
    return out


def apply_edits_to_arrays(
    data: dict[str, Any],
    edits: list[dict[str, Any]],
    *,
    climber_id: int | None,
) -> dict[str, Any]:
    """Copy pose arrays and apply edits to the climber track only."""
    out = dict(data)
    out["keypoints"] = np.array(data["keypoints"], dtype=np.float32, copy=True)
    out["frame"] = np.asarray(data["frame"], dtype=np.int32)
    out["track_id"] = np.asarray(data["track_id"], dtype=np.int32)
    out["bbox"] = np.asarray(data["bbox"], dtype=np.float32)
    out["climber_track_id"] = climber_id
    if climber_id is None or not edits:
        return out
    mask = out["track_id"] == int(climber_id)
    if not np.any(mask):
        return out
    edited = apply_edits(out["frame"][mask], out["keypoints"][mask], edits)
    out["keypoints"][mask] = edited
    return out


def confirmed_frames(edits: list[dict[str, Any]]) -> set[int]:
    """Proxy frames covered by an active confirm edit."""
    frames: set[int] = set()
    for edit in edits:
        if str(edit.get("kind") or "") != "confirm":
            continue
        start, end, _peak = edit_range(edit)
        frames.update(range(start, end + 1))
    return frames
