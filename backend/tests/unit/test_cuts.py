"""Proposal padding, overlap split, and IoU matching."""

from __future__ import annotations

from app.core.cuts import build_proposals, match_spans, span_iou, split_overlaps
from app.core.events import AttemptSpan
from app.core.metrics import attempt_eval, pck


def test_overlap_splits_at_midpoint() -> None:
    spans = [
        AttemptSpan(30, 90, "fall", 0.8),
        AttemptSpan(80, 140, "fall", 0.8),
    ]
    proposals = build_proposals(spans, fps=30.0, n_frames=200, pre_roll_s=0.0, post_roll_s=0.0)
    assert len(proposals) == 2
    assert proposals[0].end_frame < proposals[1].start_frame or proposals[0].end_frame + 1 == (
        proposals[1].start_frame
    )


def test_match_spans_and_eval() -> None:
    pred = [(30, 90), (150, 210)]
    truth = [(30, 90), (148, 212)]
    matches = match_spans(pred, truth)
    assert len(matches) == 2
    stats = attempt_eval(
        pred,
        truth,
        pred_outcomes=["fall", "fall"],
        truth_outcomes=["fall", "fall"],
    )
    assert stats["n_match"] == 2
    assert stats["precision"] == 1.0
    assert stats["recall"] == 1.0
    assert span_iou(0, 9, 0, 9) == 1.0
    assert pck([[0.0, 0.0]], [[0.2, 0.0]], ref_length=10.0, thr=0.05) == 1.0


def test_split_overlaps_empty() -> None:
    assert split_overlaps([]) == []
