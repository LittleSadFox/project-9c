"""Halpe26 keypoint names, edges, L/R swap, and groups.

Indices 0-16 follow COCO. 17 is head. 18 is neck. 19 is hip.
20 and 21 are big toes. 22 and 23 are small toes. 24 and 25 are heels.
"""

from __future__ import annotations

N_KEYPOINTS = 26
SCORE_THR = 0.3

NOSE = 0
LEFT_EYE = 1
RIGHT_EYE = 2
LEFT_EAR = 3
RIGHT_EAR = 4
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_ELBOW = 7
RIGHT_ELBOW = 8
LEFT_WRIST = 9
RIGHT_WRIST = 10
LEFT_HIP = 11
RIGHT_HIP = 12
LEFT_KNEE = 13
RIGHT_KNEE = 14
LEFT_ANKLE = 15
RIGHT_ANKLE = 16
HEAD = 17
NECK = 18
HIP = 19
LEFT_BIG_TOE = 20
RIGHT_BIG_TOE = 21
LEFT_SMALL_TOE = 22
RIGHT_SMALL_TOE = 23
LEFT_HEEL = 24
RIGHT_HEEL = 25

NAMES: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "head",
    "neck",
    "hip",
    "left_big_toe",
    "right_big_toe",
    "left_small_toe",
    "right_small_toe",
    "left_heel",
    "right_heel",
)

_NAME_TO_INDEX = {name: index for index, name in enumerate(NAMES)}

_EDGE_NAMES: tuple[tuple[str, str], ...] = (
    ("left_ankle", "left_knee"),
    ("left_knee", "left_hip"),
    ("left_hip", "hip"),
    ("right_ankle", "right_knee"),
    ("right_knee", "right_hip"),
    ("right_hip", "hip"),
    ("head", "neck"),
    ("neck", "hip"),
    ("neck", "left_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("neck", "right_shoulder"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_eye", "right_eye"),
    ("nose", "left_eye"),
    ("nose", "right_eye"),
    ("left_eye", "left_ear"),
    ("right_eye", "right_ear"),
    ("left_ear", "left_shoulder"),
    ("right_ear", "right_shoulder"),
    ("left_ankle", "left_big_toe"),
    ("left_ankle", "left_small_toe"),
    ("left_ankle", "left_heel"),
    ("right_ankle", "right_big_toe"),
    ("right_ankle", "right_small_toe"),
    ("right_ankle", "right_heel"),
)

EDGES: tuple[tuple[int, int], ...] = tuple(
    (_NAME_TO_INDEX[a], _NAME_TO_INDEX[b]) for a, b in _EDGE_NAMES
)

LEFT: tuple[int, ...] = (
    LEFT_EYE,
    LEFT_EAR,
    LEFT_SHOULDER,
    LEFT_ELBOW,
    LEFT_WRIST,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_ANKLE,
    LEFT_BIG_TOE,
    LEFT_SMALL_TOE,
    LEFT_HEEL,
)
RIGHT: tuple[int, ...] = (
    RIGHT_EYE,
    RIGHT_EAR,
    RIGHT_SHOULDER,
    RIGHT_ELBOW,
    RIGHT_WRIST,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_ANKLE,
    RIGHT_BIG_TOE,
    RIGHT_SMALL_TOE,
    RIGHT_HEEL,
)
CENTER: tuple[int, ...] = (NOSE, HEAD, NECK, HIP)

GROUPS: dict[str, tuple[int, ...]] = {
    "left": LEFT,
    "right": RIGHT,
    "center": CENTER,
}

_LR_PAIRS = dict(zip(LEFT, RIGHT, strict=True))
_LR_PAIRS.update(dict(zip(RIGHT, LEFT, strict=True)))
LR_SWAP: tuple[int, ...] = tuple(_LR_PAIRS.get(index, index) for index in range(N_KEYPOINTS))


def swap_left_right(keypoints: object) -> object:
    """Permute the last keypoint axis with the L/R swap."""
    import numpy as np

    array = np.asarray(keypoints)
    return array[..., LR_SWAP, :] if array.shape[-2] == N_KEYPOINTS else array[..., LR_SWAP]
