"""Attempt proposals, overlap split, and matching for evaluation.

core/ imports only numpy and the Python standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import AttemptSpan


@dataclass
class Proposal:
    start_frame: int
    end_frame: int
    outcome_guess: str
    confidence: float
    leave_ground: int
    ground_return: int


@dataclass
class Match:
    pred_index: int
    truth_index: int
    iou: float
    start_err: int
    end_err: int


def clamp_span(start: int, end: int, n_frames: int) -> tuple[int, int]:
    last = max(int(n_frames) - 1, 0)
    a = min(max(int(start), 0), last)
    b = min(max(int(end), 0), last)
    if b < a:
        b = a
    return a, b


def span_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    left = max(int(a0), int(b0))
    right = min(int(a1), int(b1))
    inter = max(0, right - left + 1)
    if inter <= 0:
        return 0.0
    union = (int(a1) - int(a0) + 1) + (int(b1) - int(b0) + 1) - inter
    return float(inter / union) if union > 0 else 0.0


def build_proposals(
    spans: list[AttemptSpan],
    *,
    fps: float,
    n_frames: int,
    pre_roll_s: float = 1.5,
    post_roll_s: float = 1.0,
) -> list[Proposal]:
    """Pad each span, clamp to the video, and split overlaps at the midpoint."""
    if fps <= 0:
        fps = 30.0
    pre = int(round(float(pre_roll_s) * float(fps)))
    post = int(round(float(post_roll_s) * float(fps)))
    raw: list[Proposal] = []
    for span in spans:
        start, end = clamp_span(span.leave_ground - pre, span.ground_return + post, n_frames)
        raw.append(
            Proposal(
                start_frame=start,
                end_frame=end,
                outcome_guess=span.outcome,
                confidence=span.confidence,
                leave_ground=span.leave_ground,
                ground_return=span.ground_return,
            )
        )
    raw.sort(key=lambda item: (item.start_frame, item.end_frame))
    return split_overlaps(raw)


def split_overlaps(proposals: list[Proposal]) -> list[Proposal]:
    """Split neighbouring overlapping proposals at the midpoint."""
    if len(proposals) < 2:
        return list(proposals)
    out = [proposals[0]]
    for current in proposals[1:]:
        prev = out[-1]
        if current.start_frame <= prev.end_frame:
            mid = (prev.end_frame + current.start_frame) // 2
            prev.end_frame = max(prev.start_frame, mid)
            current.start_frame = min(current.end_frame, mid + 1)
            if current.start_frame > current.end_frame:
                current.start_frame = current.end_frame
        out.append(current)
    return out


def match_spans(
    pred: list[tuple[int, int]],
    truth: list[tuple[int, int]],
    *,
    min_iou: float = 0.5,
) -> list[Match]:
    """Greedy IoU matching. Each truth and each pred is used at most once."""
    scores: list[tuple[float, int, int]] = []
    for i, (a0, a1) in enumerate(pred):
        for j, (b0, b1) in enumerate(truth):
            iou = span_iou(a0, a1, b0, b1)
            if iou >= min_iou:
                scores.append((iou, i, j))
    scores.sort(key=lambda item: item[0], reverse=True)
    used_p: set[int] = set()
    used_t: set[int] = set()
    matches: list[Match] = []
    for iou, i, j in scores:
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        a0, a1 = pred[i]
        b0, b1 = truth[j]
        matches.append(
            Match(
                pred_index=i,
                truth_index=j,
                iou=iou,
                start_err=int(a0) - int(b0),
                end_err=int(a1) - int(b1),
            )
        )
    return matches


def proposal_inner_spans(proposals: list[Proposal]) -> list[tuple[int, int]]:
    return [(item.leave_ground, item.ground_return) for item in proposals]


def as_proposal_dicts(proposals: list[Proposal]) -> list[dict[str, Any]]:
    return [
        {
            "start_frame": item.start_frame,
            "end_frame": item.end_frame,
            "outcome_guess": item.outcome_guess,
            "confidence": item.confidence,
            "leave_ground": item.leave_ground,
            "ground_return": item.ground_return,
        }
        for item in proposals
    ]
