"""Gap fill and One Euro tests on synthetic tracks."""

from __future__ import annotations

import numpy as np

from app.core.halpe26 import HIP, N_KEYPOINTS, NECK
from app.core.smoothing import fill_gaps, one_euro_1d, smooth_track, torso_length


def _series(
    n: int, *, gap: tuple[int, int] | None = None, noise: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    kpts = np.zeros((n, N_KEYPOINTS, 2), dtype=np.float32)
    scores = np.full((n, N_KEYPOINTS), 0.9, dtype=np.float32)
    rng = np.random.default_rng(0)
    for frame in range(n):
        kpts[frame, :, 0] = 100.0 + 0.2 * frame
        kpts[frame, :, 1] = 200.0 - frame
        kpts[frame, NECK] = (100.0, 160.0 - frame)
        kpts[frame, HIP] = (100.0, 200.0 - frame)
        if noise:
            kpts[frame] += rng.normal(0.0, noise, size=kpts[frame].shape).astype(np.float32)
    if gap is not None:
        start, end = gap
        scores[start:end] = 0.0
    return kpts, scores


def test_fill_gaps_linear_for_short_hole() -> None:
    kpts, scores = _series(10, gap=(3, 5))
    filled_k, filled_s = fill_gaps(kpts, scores, fps=30.0, max_gap_s=0.5)
    assert filled_s[4, HIP] >= 0.3
    weight = 2.0 / 3.0
    expected = (1.0 - weight) * kpts[2, HIP, 1] + weight * kpts[5, HIP, 1]
    assert abs(float(filled_k[4, HIP, 1]) - float(expected)) < 1e-3


def test_fill_gaps_skips_long_hole() -> None:
    kpts, scores = _series(40, gap=(5, 30))
    _filled_k, filled_s = fill_gaps(kpts, scores, fps=30.0, max_gap_s=0.5)
    assert filled_s[15, HIP] < 0.3


def test_one_euro_reduces_jitter() -> None:
    times = np.linspace(0.0, 1.0, 30)
    clean = np.sin(2 * np.pi * times)
    noisy = clean + np.array([0.4 if i % 2 else -0.4 for i in range(30)])
    filtered = one_euro_1d(noisy, times, min_cutoff=1.0, beta=0.3)
    assert float(np.var(filtered - clean)) < float(np.var(noisy - clean))


def test_smooth_track_uses_torso_units() -> None:
    kpts, scores = _series(20, noise=3.0)
    assert torso_length(kpts, scores) > 1.0
    out, out_s = smooth_track(kpts, scores, fps=30.0)
    assert out.shape == kpts.shape
    assert out_s.shape == scores.shape
    assert float(np.var(out[:, HIP, 0])) < float(np.var(kpts[:, HIP, 0]))
