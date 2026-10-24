"""Boundary error, IoU P/R/F1, PCK, and anchor error.

core/ imports only numpy and the Python standard library.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .cuts import Match, match_spans, span_iou


def boundary_error(pred_frame: int, truth_frame: int) -> int:
    return abs(int(pred_frame) - int(truth_frame))


def prf(true_pos: int, pred_n: int, truth_n: int) -> dict[str, float]:
    precision = float(true_pos / pred_n) if pred_n else 0.0
    recall = float(true_pos / truth_n) if truth_n else 0.0
    denom = precision + recall
    f1 = float(2 * precision * recall / denom) if denom else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def iou_prf(
    pred: list[tuple[int, int]],
    truth: list[tuple[int, int]],
    *,
    min_iou: float = 0.5,
) -> dict[str, Any]:
    matches = match_spans(pred, truth, min_iou=min_iou)
    stats: dict[str, Any] = prf(len(matches), len(pred), len(truth))
    start_err = [abs(item.start_err) for item in matches]
    end_err = [abs(item.end_err) for item in matches]
    stats.update(
        {
            "n_pred": len(pred),
            "n_truth": len(truth),
            "n_match": len(matches),
            "mean_start_err": float(np.mean(start_err)) if start_err else None,
            "mean_end_err": float(np.mean(end_err)) if end_err else None,
            "matches": matches,
        }
    )
    return stats


def within_frames(errors: list[int], limit: int) -> float:
    if not errors:
        return 0.0
    return float(sum(1 for err in errors if abs(err) <= limit) / len(errors))


def pck(
    pred: object,
    truth: object,
    *,
    ref_length: float,
    thr: float = 0.05,
    mask: object | None = None,
) -> float:
    """Percentage of keypoints within thr * ref_length."""
    a = np.asarray(pred, dtype=np.float32)
    b = np.asarray(truth, dtype=np.float32)
    if a.size == 0 or b.size == 0 or ref_length <= 0:
        return 0.0
    a = a.reshape(-1, 2)
    b = b.reshape(-1, 2)
    n = min(a.shape[0], b.shape[0])
    if n == 0:
        return 0.0
    dist = np.linalg.norm(a[:n] - b[:n], axis=1)
    keep = np.ones((n,), dtype=bool)
    if mask is not None:
        keep = np.asarray(mask, dtype=bool).reshape(-1)[:n]
        if not np.any(keep):
            return 0.0
    ok = dist[keep] <= float(thr) * float(ref_length)
    return float(np.mean(ok)) if ok.size else 0.0


def anchor_error(pred_pairs: object, truth_pairs: object) -> float:
    """Mean absolute frame error of matched alignment anchors."""
    pred = np.asarray(pred_pairs, dtype=np.float32).reshape(-1, 2)
    truth = np.asarray(truth_pairs, dtype=np.float32).reshape(-1, 2)
    n = min(pred.shape[0], truth.shape[0])
    if n == 0:
        return 0.0
    return float(np.mean(np.abs(pred[:n] - truth[:n])))


def outcome_accuracy(pred: list[str], truth: list[str]) -> float:
    if not truth:
        return 0.0
    n = min(len(pred), len(truth))
    if n == 0:
        return 0.0
    hits = sum(1 for i in range(n) if pred[i] == truth[i])
    return float(hits / n)


def attempt_eval(
    pred_spans: list[tuple[int, int]],
    truth_spans: list[tuple[int, int]],
    *,
    pred_outcomes: list[str] | None = None,
    truth_outcomes: list[str] | None = None,
    fps: float = 30.0,
    min_iou: float = 0.5,
    time_limit_s: float = 0.5,
) -> dict[str, Any]:
    """Event/cut metrics used by the eval job and unit tests."""
    stats = iou_prf(pred_spans, truth_spans, min_iou=min_iou)
    matches: list[Match] = stats.pop("matches")
    start_err = [abs(item.start_err) for item in matches]
    end_err = [abs(item.end_err) for item in matches]
    frame_limit = int(round(float(time_limit_s) * float(fps)))
    matched_pred_out: list[str] = []
    matched_truth_out: list[str] = []
    if pred_outcomes is not None and truth_outcomes is not None:
        for item in matches:
            if item.pred_index < len(pred_outcomes) and item.truth_index < len(truth_outcomes):
                matched_pred_out.append(pred_outcomes[item.pred_index])
                matched_truth_out.append(truth_outcomes[item.truth_index])
    stats.update(
        {
            "start_within_limit": within_frames(start_err, frame_limit),
            "end_within_limit": within_frames(end_err, frame_limit),
            "time_limit_s": time_limit_s,
            "outcome_accuracy": outcome_accuracy(matched_pred_out, matched_truth_out),
            "ious": [
                span_iou(*pred_spans[item.pred_index], *truth_spans[item.truth_index])
                for item in matches
            ],
        }
    )
    return stats
