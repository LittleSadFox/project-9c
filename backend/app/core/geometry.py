"""Line and polygon ops, floor-frame rotation, and Umeyama similarity.

core/ imports only numpy and the Python standard library.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-9


def as_points(points: object) -> np.ndarray:
    """Return an (N, 2) float32 array."""
    array = np.asarray(points, dtype=np.float32)
    if array.size == 0:
        return np.zeros((0, 2), dtype=np.float32)
    return array.reshape(-1, 2)


def line_from_points(a: object, b: object) -> np.ndarray:
    """Return a floor line as two points [[x1, y1], [x2, y2]]."""
    return np.stack([as_points(a)[0], as_points(b)[0]]).astype(np.float32)


def line_angle(line: object) -> float:
    """Angle of the line in radians, image coordinates."""
    pts = as_points(line)
    if pts.shape[0] < 2:
        return 0.0
    delta = pts[1] - pts[0]
    return float(np.arctan2(float(delta[1]), float(delta[0])))


def signed_distance_to_line(points: object, line: object) -> np.ndarray:
    """Signed distance from each point to the infinite line.

    Positive is to the left of the direction a -> b.
    """
    pts = as_points(points)
    ends = as_points(line)
    if pts.shape[0] == 0:
        return np.zeros((0,), dtype=np.float32)
    if ends.shape[0] < 2:
        return np.zeros((pts.shape[0],), dtype=np.float32)
    start = ends[0]
    direction = ends[1] - ends[0]
    length = float(np.linalg.norm(direction))
    if length < EPS:
        return np.linalg.norm(pts - start, axis=1).astype(np.float32)
    normal = np.array([-direction[1], direction[0]], dtype=np.float32) / length
    return ((pts - start) @ normal).astype(np.float32)


def project_to_line(points: object, line: object) -> np.ndarray:
    """Orthogonal projection of points onto the infinite line."""
    pts = as_points(points)
    ends = as_points(line)
    if pts.shape[0] == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if ends.shape[0] < 2:
        return pts.copy()
    start = ends[0]
    direction = ends[1] - ends[0]
    length_sq = float(np.dot(direction, direction))
    if length_sq < EPS:
        return np.broadcast_to(start, pts.shape).copy()
    t = ((pts - start) @ direction) / length_sq
    return (start + t[:, None] * direction).astype(np.float32)


def rotate_points(points: object, angle: float, origin: object = (0.0, 0.0)) -> np.ndarray:
    """Rotate points by angle radians about origin. Positive is clockwise in image y-down."""
    pts = as_points(points)
    org = as_points(origin)[0]
    if pts.shape[0] == 0:
        return pts
    cos_a = float(np.cos(angle))
    sin_a = float(np.sin(angle))
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
    return ((pts - org) @ rot.T + org).astype(np.float32)


def normalize_floor_line(floor_line: object) -> np.ndarray:
    """Return two points with increasing x so left-to-right is +x."""
    line = as_points(floor_line)
    if line.shape[0] < 2:
        return line.copy()
    if float(line[1, 0]) < float(line[0, 0]):
        return line[::-1].copy()
    return line.copy()


def to_floor_frame(points: object, floor_line: object) -> np.ndarray:
    """Rotate so the floor line is horizontal. Up is -y."""
    pts = as_points(points)
    line = normalize_floor_line(floor_line)
    if pts.shape[0] == 0 or line.shape[0] < 2:
        return pts.copy()
    angle = line_angle(line)
    origin = line[0]
    return rotate_points(pts, -angle, origin)


def floor_y(floor_line: object) -> float:
    """Y of the floor after it is made horizontal, in the original frame if already flat."""
    line = as_points(floor_line)
    if line.shape[0] < 2:
        return 0.0
    return float(0.5 * (line[0, 1] + line[1, 1]))


def height_above_line(points: object, floor_line: object) -> np.ndarray:
    """Positive height on the up (-y) side of the floor line, in pixels."""
    pts = as_points(points)
    if pts.shape[0] == 0:
        return np.zeros((0,), dtype=np.float32)
    line = normalize_floor_line(floor_line)
    frame = to_floor_frame(pts, line)
    floor = to_floor_frame(line, line) if line.shape[0] >= 2 else np.array([[0.0, 0.0]])
    y0 = float(floor[0, 1]) if floor.size else 0.0
    return (y0 - frame[:, 1]).astype(np.float32)


def point_in_polygon(points: object, polygon: object) -> np.ndarray:
    """Ray-cast test. True when the point is inside or on the boundary."""
    pts = as_points(points)
    poly = as_points(polygon)
    if pts.shape[0] == 0:
        return np.zeros((0,), dtype=bool)
    if poly.shape[0] < 3:
        return np.zeros((pts.shape[0],), dtype=bool)
    x = pts[:, 0]
    y = pts[:, 1]
    x_poly = poly[:, 0]
    y_poly = poly[:, 1]
    x_next = np.roll(x_poly, -1)
    y_next = np.roll(y_poly, -1)
    inside = np.zeros((pts.shape[0],), dtype=bool)
    for i in range(poly.shape[0]):
        cond = (y_poly[i] > y) != (y_next[i] > y)
        denom = y_next[i] - y_poly[i]
        denom = np.where(np.abs(denom) < EPS, EPS, denom)
        x_hit = (x_next[i] - x_poly[i]) * (y - y_poly[i]) / denom + x_poly[i]
        crossing = cond & (x < x_hit)
        inside ^= crossing
    on_edge = _on_polygon_edges(pts, poly)
    return inside | on_edge


def _on_polygon_edges(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    nxt = np.roll(poly, -1, axis=0)
    on = np.zeros((pts.shape[0],), dtype=bool)
    for start, end in zip(poly, nxt, strict=True):
        seg = end - start
        length_sq = float(np.dot(seg, seg))
        if length_sq < EPS:
            on |= np.linalg.norm(pts - start, axis=1) < 1e-4
            continue
        t = ((pts - start) @ seg) / length_sq
        proj = start + t[:, None] * seg
        dist = np.linalg.norm(pts - proj, axis=1)
        on |= (t >= -1e-5) & (t <= 1.0 + 1e-5) & (dist < 1e-3)
    return on


def grow_polygon(polygon: object, radius: float) -> np.ndarray:
    """Grow a polygon by a pixel radius along vertex normals."""
    poly = as_points(polygon)
    if poly.shape[0] < 3 or radius == 0:
        return poly.copy()
    prev = np.roll(poly, 1, axis=0)
    nxt = np.roll(poly, -1, axis=0)
    e1 = poly - prev
    e2 = nxt - poly
    n1 = np.stack([-e1[:, 1], e1[:, 0]], axis=1)
    n2 = np.stack([-e2[:, 1], e2[:, 0]], axis=1)
    n1 = n1 / np.maximum(np.linalg.norm(n1, axis=1, keepdims=True), EPS)
    n2 = n2 / np.maximum(np.linalg.norm(n2, axis=1, keepdims=True), EPS)
    normal = n1 + n2
    normal = normal / np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), EPS)
    return (poly + normal * float(radius)).astype(np.float32)


def umeyama(src: object, dst: object) -> tuple[np.ndarray, float]:
    """Similarity transform (scale, rotation, translation) from src to dst.

    Returns (matrix 2x3 [a, b, tx; c, d, ty] as a length-6 row, residual_px).
    Needs at least two point pairs.
    """
    a = as_points(src)
    b = as_points(dst)
    n = min(a.shape[0], b.shape[0])
    if n < 2:
        return np.array([1.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32), 0.0
    a = a[:n]
    b = b[:n]
    mu_a = a.mean(axis=0)
    mu_b = b.mean(axis=0)
    a0 = a - mu_a
    b0 = b - mu_b
    var_a = float(np.sum(a0**2) / n)
    cov = (b0.T @ a0) / n
    u, d, vt = np.linalg.svd(cov)
    r = u @ vt
    if np.linalg.det(r) < 0:
        vt[-1] *= -1
        r = u @ vt
    scale = float(np.sum(d) / var_a) if var_a > EPS else 1.0
    t = mu_b - scale * (r @ mu_a)
    mapped = (scale * (r @ a.T).T) + t
    residual = float(np.sqrt(np.mean(np.sum((mapped - b) ** 2, axis=1))))
    matrix = np.array(
        [scale * r[0, 0], scale * r[0, 1], t[0], scale * r[1, 0], scale * r[1, 1], t[1]],
        dtype=np.float32,
    )
    return matrix, residual
