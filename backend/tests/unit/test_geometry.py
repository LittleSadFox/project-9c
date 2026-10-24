"""Line, polygon, floor-frame, and Umeyama tests."""

from __future__ import annotations

import numpy as np

from app.core.geometry import (
    grow_polygon,
    height_above_line,
    point_in_polygon,
    signed_distance_to_line,
    to_floor_frame,
    umeyama,
)


def test_height_above_horizontal_floor() -> None:
    floor = [[0.0, 100.0], [200.0, 100.0]]
    heights = height_above_line([[50.0, 60.0], [50.0, 100.0], [50.0, 130.0]], floor)
    assert heights[0] == 40.0
    assert heights[1] == 0.0
    assert heights[2] < 0.0


def test_to_floor_frame_makes_line_horizontal() -> None:
    floor = [[0.0, 10.0], [10.0, 20.0]]
    rotated = to_floor_frame(floor, floor)
    assert abs(rotated[0, 1] - rotated[1, 1]) < 1e-4


def test_point_in_polygon_and_grow() -> None:
    square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    inside = point_in_polygon([[5.0, 5.0], [20.0, 5.0]], square)
    assert bool(inside[0]) is True
    assert bool(inside[1]) is False
    grown = grow_polygon(square, 2.0)
    assert grown.shape == (4, 2)
    assert float(np.linalg.norm(grown[0])) > 0.0


def test_signed_distance_and_umeyama() -> None:
    dist = signed_distance_to_line([[0.0, 1.0]], [[0.0, 0.0], [1.0, 0.0]])
    assert abs(float(dist[0]) - 1.0) < 1e-5
    src = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    dst = src * 2.0 + np.array([3.0, -1.0], dtype=np.float32)
    matrix, residual = umeyama(src, dst)
    assert residual < 0.5
    assert matrix.shape == (6,)
