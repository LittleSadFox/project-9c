"""Greedy IoU tracker, keypoint-box propagation, and fragment stitching."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .halpe26 import N_KEYPOINTS, SCORE_THR

DEFAULT_IOU_THR = 0.3
DEFAULT_MAX_AGE = 15
DEFAULT_STITCH_GAP = 15
BOX_PAD = 0.1


@dataclass
class Track:
    """One person across frames."""

    track_id: int
    frames: list[int] = field(default_factory=list)
    boxes: list[np.ndarray] = field(default_factory=list)
    keypoints: list[np.ndarray] = field(default_factory=list)
    scores: list[np.ndarray] = field(default_factory=list)
    age: int = 0

    @property
    def first_frame(self) -> int:
        return self.frames[0] if self.frames else -1

    @property
    def last_frame(self) -> int:
        return self.frames[-1] if self.frames else -1


def empty_boxes() -> np.ndarray:
    return np.zeros((0, 4), dtype=np.float32)


def empty_keypoints() -> np.ndarray:
    return np.zeros((0, N_KEYPOINTS, 2), dtype=np.float32)


def empty_scores() -> np.ndarray:
    return np.zeros((0, N_KEYPOINTS), dtype=np.float32)


def box_iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU of two xyxy boxes."""
    ix1 = max(float(a[0]), float(b[0]))
    iy1 = max(float(a[1]), float(b[1]))
    ix2 = min(float(a[2]), float(b[2]))
    iy2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def box_from_keypoints(
    keypoints: np.ndarray,
    scores: np.ndarray,
    *,
    score_thr: float = SCORE_THR,
    pad: float = BOX_PAD,
) -> np.ndarray | None:
    """Axis-aligned box from valid keypoints. Return None when none are valid."""
    valid = np.asarray(scores) >= score_thr
    if not np.any(valid):
        return None
    pts = np.asarray(keypoints, dtype=np.float32)[valid]
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    width = float(x2 - x1)
    height = float(y2 - y1)
    return np.array(
        [x1 - width * pad, y1 - height * pad, x2 + width * pad, y2 + height * pad],
        dtype=np.float32,
    )


def boxes_from_people(
    keypoints: np.ndarray,
    scores: np.ndarray,
    *,
    fallback: np.ndarray | None = None,
) -> np.ndarray:
    """One box per person. Fall back to the matching input box when needed."""
    n = int(keypoints.shape[0]) if keypoints is not None and len(keypoints) else 0
    if n == 0:
        return empty_boxes()
    out = np.zeros((n, 4), dtype=np.float32)
    for index in range(n):
        derived = box_from_keypoints(keypoints[index], scores[index])
        if derived is not None:
            out[index] = derived
        elif fallback is not None and index < len(fallback):
            out[index] = np.asarray(fallback[index], dtype=np.float32)
    return out


class Tracker:
    """Greedy IoU tracker. One identity per person."""

    def __init__(
        self,
        *,
        iou_thr: float = DEFAULT_IOU_THR,
        max_age: int = DEFAULT_MAX_AGE,
        stitch_gap: int = DEFAULT_STITCH_GAP,
    ) -> None:
        self.iou_thr = iou_thr
        self.max_age = max_age
        self.stitch_gap = stitch_gap
        self._next_id = 1
        self._active: list[Track] = []
        self._finished: list[Track] = []

    def update(
        self,
        frame_index: int,
        boxes: np.ndarray,
        keypoints: np.ndarray,
        scores: np.ndarray,
    ) -> None:
        boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4) if len(boxes) else empty_boxes()
        n = int(boxes.shape[0])
        if n == 0:
            for track in self._active:
                track.age += 1
            self._retire()
            return

        keypoints = np.asarray(keypoints, dtype=np.float32).reshape(n, N_KEYPOINTS, 2)
        scores = np.asarray(scores, dtype=np.float32).reshape(n, N_KEYPOINTS)
        predicted = [self._predict_box(track) for track in self._active]
        assigned_tracks: set[int] = set()
        assigned_dets: set[int] = set()
        pairs: list[tuple[float, int, int]] = []
        for track_i, pred in enumerate(predicted):
            for det_i in range(n):
                pairs.append((box_iou(pred, boxes[det_i]), track_i, det_i))
        pairs.sort(key=lambda item: item[0], reverse=True)
        for iou, track_i, det_i in pairs:
            if iou < self.iou_thr:
                break
            if track_i in assigned_tracks or det_i in assigned_dets:
                continue
            assigned_tracks.add(track_i)
            assigned_dets.add(det_i)
            self._append(
                self._active[track_i],
                frame_index,
                boxes[det_i],
                keypoints[det_i],
                scores[det_i],
            )

        for det_i in range(n):
            if det_i in assigned_dets:
                continue
            track = Track(track_id=self._next_id)
            self._next_id += 1
            self._append(track, frame_index, boxes[det_i], keypoints[det_i], scores[det_i])
            self._active.append(track)

        for track_i, track in enumerate(self._active):
            if track_i not in assigned_tracks:
                track.age += 1
        self._retire()

    def finalize(self) -> list[Track]:
        """Close active tracks and stitch fragments."""
        tracks = [track for track in self._finished + self._active if track.frames]
        self._finished = []
        self._active = []
        return stitch_fragments(tracks, max_gap=self.stitch_gap, iou_thr=self.iou_thr)

    def _predict_box(self, track: Track) -> np.ndarray:
        derived = box_from_keypoints(track.keypoints[-1], track.scores[-1])
        if derived is not None:
            return derived
        return track.boxes[-1]

    def _retire(self) -> None:
        keep: list[Track] = []
        for track in self._active:
            if track.age > self.max_age:
                self._finished.append(track)
            else:
                keep.append(track)
        self._active = keep

    @staticmethod
    def _append(
        track: Track,
        frame_index: int,
        box: np.ndarray,
        keypoints: np.ndarray,
        scores: np.ndarray,
    ) -> None:
        track.frames.append(int(frame_index))
        track.boxes.append(np.asarray(box, dtype=np.float32))
        track.keypoints.append(np.asarray(keypoints, dtype=np.float32))
        track.scores.append(np.asarray(scores, dtype=np.float32))
        track.age = 0


def stitch_fragments(
    tracks: list[Track],
    *,
    max_gap: int = DEFAULT_STITCH_GAP,
    iou_thr: float = DEFAULT_IOU_THR,
) -> list[Track]:
    """Merge short gaps when the next fragment starts near the last box."""
    if len(tracks) < 2:
        return tracks
    remaining = sorted(tracks, key=lambda track: (track.first_frame, track.track_id))
    merged: list[Track] = []
    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            best_i: int | None = None
            for index, other in enumerate(remaining):
                gap = other.first_frame - current.last_frame
                if gap <= 0 or gap > max_gap:
                    continue
                if box_iou(current.boxes[-1], other.boxes[0]) < iou_thr:
                    continue
                if best_i is None or other.first_frame < remaining[best_i].first_frame:
                    best_i = index
            if best_i is not None:
                current = _concat_tracks(current, remaining.pop(best_i))
                changed = True
        merged.append(current)
    return merged


def _concat_tracks(left: Track, right: Track) -> Track:
    out = Track(track_id=left.track_id)
    out.frames = left.frames + right.frames
    out.boxes = left.boxes + right.boxes
    out.keypoints = left.keypoints + right.keypoints
    out.scores = left.scores + right.scores
    return out
