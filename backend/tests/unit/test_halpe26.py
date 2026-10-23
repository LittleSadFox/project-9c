"""Halpe26 schema tests."""

from __future__ import annotations

import numpy as np

from app.core.halpe26 import EDGES, GROUPS, LR_SWAP, N_KEYPOINTS, NAMES, swap_left_right


def test_names_and_edges() -> None:
    assert len(NAMES) == N_KEYPOINTS
    assert NAMES[18] == "neck"
    assert NAMES[19] == "hip"
    assert NAMES[20] == "left_big_toe"
    assert all(0 <= a < N_KEYPOINTS and 0 <= b < N_KEYPOINTS for a, b in EDGES)
    assert len(GROUPS["left"]) == len(GROUPS["right"])


def test_lr_swap_is_involution() -> None:
    assert len(LR_SWAP) == N_KEYPOINTS
    twice = tuple(LR_SWAP[index] for index in LR_SWAP)
    assert twice == tuple(range(N_KEYPOINTS))
    points = np.arange(N_KEYPOINTS * 2, dtype=np.float32).reshape(N_KEYPOINTS, 2)
    swapped = swap_left_right(points)
    assert np.array_equal(swap_left_right(swapped), points)
