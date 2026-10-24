"""Parametric climber tracks for event-detector tests and the eval job."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.halpe26 import (
    HEAD,
    HIP,
    LEFT_ANKLE,
    LEFT_BIG_TOE,
    LEFT_ELBOW,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_SMALL_TOE,
    LEFT_WRIST,
    N_KEYPOINTS,
    NECK,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_BIG_TOE,
    RIGHT_ELBOW,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_SMALL_TOE,
    RIGHT_WRIST,
)


@dataclass
class LabelledAttempt:
    leave_ground: int
    ground_return: int
    outcome: str


@dataclass
class SynthVideo:
    keypoints: np.ndarray
    scores: np.ndarray
    fps: float
    n_frames: int
    floor_line: np.ndarray
    top_zone: np.ndarray | None
    attempts: list[LabelledAttempt]
    name: str = "synth"
    torso: float = 80.0
    meta: dict[str, Any] = field(default_factory=dict)


def _empty_pose(n_frames: int) -> tuple[np.ndarray, np.ndarray]:
    kpts = np.zeros((n_frames, N_KEYPOINTS, 2), dtype=np.float32)
    scores = np.zeros((n_frames, N_KEYPOINTS), dtype=np.float32)
    return kpts, scores


def _place_body(
    kpts: np.ndarray,
    scores: np.ndarray,
    frame: int,
    *,
    hip_xy: tuple[float, float],
    torso: float,
    foot_lift: float,
    hands_up: float,
    sit: float,
) -> None:
    hx, hy = hip_xy
    kpts[frame, HIP] = (hx, hy)
    kpts[frame, LEFT_HIP] = (hx - 0.12 * torso, hy + 0.02 * torso)
    kpts[frame, RIGHT_HIP] = (hx + 0.12 * torso, hy + 0.02 * torso)
    kpts[frame, NECK] = (hx, hy - torso)
    kpts[frame, HEAD] = (hx, hy - 1.25 * torso)
    kpts[frame, NOSE] = (hx, hy - 1.18 * torso)
    kpts[frame, LEFT_SHOULDER] = (hx - 0.28 * torso, hy - 0.92 * torso)
    kpts[frame, RIGHT_SHOULDER] = (hx + 0.28 * torso, hy - 0.92 * torso)
    kpts[frame, LEFT_ELBOW] = (hx - 0.38 * torso, hy - 0.55 * torso - 0.2 * hands_up)
    kpts[frame, RIGHT_ELBOW] = (hx + 0.38 * torso, hy - 0.55 * torso - 0.2 * hands_up)
    kpts[frame, LEFT_WRIST] = (hx - 0.34 * torso, hy - 0.20 * torso - hands_up)
    kpts[frame, RIGHT_WRIST] = (hx + 0.34 * torso, hy - 0.20 * torso - hands_up)
    hip_drop = sit * 0.85 * torso
    kpts[frame, LEFT_HIP, 1] += hip_drop
    kpts[frame, RIGHT_HIP, 1] += hip_drop
    kpts[frame, HIP, 1] += hip_drop
    hip_y = hy + hip_drop
    ankle_y = hip_y + 0.95 * torso - foot_lift
    toe_y = ankle_y + 0.06 * torso
    heel_y = ankle_y + 0.02 * torso
    kpts[frame, LEFT_KNEE] = (hx - 0.10 * torso, hip_y + 0.50 * torso - 0.3 * foot_lift)
    kpts[frame, RIGHT_KNEE] = (hx + 0.10 * torso, hip_y + 0.50 * torso - 0.3 * foot_lift)
    kpts[frame, LEFT_ANKLE] = (hx - 0.10 * torso, ankle_y)
    kpts[frame, RIGHT_ANKLE] = (hx + 0.10 * torso, ankle_y)
    kpts[frame, LEFT_BIG_TOE] = (hx - 0.10 * torso, toe_y)
    kpts[frame, RIGHT_BIG_TOE] = (hx + 0.10 * torso, toe_y)
    kpts[frame, LEFT_SMALL_TOE] = (hx - 0.16 * torso, toe_y)
    kpts[frame, RIGHT_SMALL_TOE] = (hx + 0.16 * torso, toe_y)
    kpts[frame, LEFT_HEEL] = (hx - 0.10 * torso, heel_y)
    kpts[frame, RIGHT_HEEL] = (hx + 0.10 * torso, heel_y)
    scores[frame] = 0.92


def standing_only(*, n_frames: int = 90, fps: float = 30.0, torso: float = 80.0) -> SynthVideo:
    kpts, scores = _empty_pose(n_frames)
    floor_y = 600.0
    hip_y = floor_y - 0.95 * torso
    for i in range(n_frames):
        _place_body(
            kpts,
            scores,
            i,
            hip_xy=(640.0, hip_y),
            torso=torso,
            foot_lift=0.0,
            hands_up=0.0,
            sit=0.0,
        )
    floor = np.array([[0.0, floor_y], [1280.0, floor_y]], dtype=np.float32)
    return SynthVideo(kpts, scores, fps, n_frames, floor, None, [], name="standing")


def _attempt_profile(
    n_frames: int,
    leave: int,
    land: int,
    *,
    sit: bool,
    send: bool,
    fps: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """foot_lift, hip_rise, hands_up per frame. Units are pixels via torso later."""
    foot = np.zeros((n_frames,), dtype=np.float32)
    rise = np.zeros((n_frames,), dtype=np.float32)
    hands = np.zeros((n_frames,), dtype=np.float32)
    sit_amt = np.zeros((n_frames,), dtype=np.float32)
    if sit:
        sit_amt[:leave] = 1.0
        # Feet stay on the wall (above the hips). Hips are the lowest point.
        foot[:leave] = 1.15
        for i in range(leave, min(leave + 3, n_frames)):
            sit_amt[i] = max(0.0, 1.0 - (i - leave + 1) / 3.0)
    climb = max(land - leave, 1)
    for i in range(n_frames):
        if i < leave:
            if not sit:
                foot[i] = 0.0
            rise[i] = 0.0
        elif i < land:
            # Feet stay off the floor until the labelled landing frame.
            t = (i - leave) / climb
            foot[i] = 0.45
            if send:
                rise[i] = 0.15 + 1.6 * (t if t < 0.7 else 0.7 - 0.4 * (t - 0.7) / 0.3)
                if 0.35 <= t <= 0.85:
                    hands[i] = 1.6
            else:
                # Hip drops fast in the last second; feet stay up until land.
                if t < 0.7:
                    rise[i] = 0.15 + 1.1 * t
                else:
                    rise[i] = max(0.05, 0.92 - 2.4 * (t - 0.7))
        else:
            foot[i] = 0.0
            rise[i] = 0.0
    return foot, rise, hands, sit_amt


def one_attempt(
    *,
    sit: bool = False,
    send: bool = False,
    fps: float = 30.0,
    torso: float = 80.0,
    leave: int = 30,
    land: int = 120,
    tail: int = 30,
) -> SynthVideo:
    n_frames = land + tail
    kpts, scores = _empty_pose(n_frames)
    floor_y = 600.0
    stand_hip = floor_y - 0.95 * torso
    foot, rise, hands, sit_amt = _attempt_profile(
        n_frames, leave, land, sit=sit, send=send, fps=fps
    )
    for i in range(n_frames):
        hip_y = stand_hip - rise[i] * torso
        _place_body(
            kpts,
            scores,
            i,
            hip_xy=(640.0, hip_y),
            torso=torso,
            foot_lift=foot[i] * torso,
            hands_up=hands[i] * torso,
            sit=float(sit_amt[i]),
        )
    floor = np.array([[0.0, floor_y], [1280.0, floor_y]], dtype=np.float32)
    top = None
    if send:
        top = np.array(
            [[560.0, 180.0], [720.0, 180.0], [720.0, 260.0], [560.0, 260.0]],
            dtype=np.float32,
        )
    outcome = "send" if send else "fall"
    if not send and top is None:
        outcome = "fall"
    return SynthVideo(
        kpts,
        scores,
        fps,
        n_frames,
        floor,
        top,
        [LabelledAttempt(leave, land, outcome)],
        name="sit_start" if sit else ("send" if send else "one_attempt"),
        torso=torso,
    )


def two_attempts(*, fps: float = 30.0, torso: float = 80.0) -> SynthVideo:
    leave_a, land_a = 30, 90
    leave_b, land_b = 150, 210
    n_frames = land_b + 30
    kpts, scores = _empty_pose(n_frames)
    floor_y = 600.0
    stand_hip = floor_y - 0.95 * torso
    foot_a, rise_a, hands_a, sit_a = _attempt_profile(
        n_frames, leave_a, land_a, sit=False, send=False, fps=fps
    )
    foot_b, rise_b, hands_b, sit_b = _attempt_profile(
        n_frames, leave_b, land_b, sit=False, send=False, fps=fps
    )
    foot = np.maximum(foot_a, foot_b)
    rise = np.maximum(rise_a, rise_b)
    hands = np.maximum(hands_a, hands_b)
    sit_amt = np.maximum(sit_a, sit_b)
    for i in range(n_frames):
        _place_body(
            kpts,
            scores,
            i,
            hip_xy=(640.0, stand_hip - rise[i] * torso),
            torso=torso,
            foot_lift=foot[i] * torso,
            hands_up=hands[i] * torso,
            sit=float(sit_amt[i]),
        )
    floor = np.array([[0.0, floor_y], [1280.0, floor_y]], dtype=np.float32)
    return SynthVideo(
        kpts,
        scores,
        fps,
        n_frames,
        floor,
        None,
        [
            LabelledAttempt(leave_a, land_a, "fall"),
            LabelledAttempt(leave_b, land_b, "fall"),
        ],
        name="two_attempts",
        torso=torso,
    )


def add_noise(
    video: SynthVideo,
    *,
    sigma_s: float = 0.02,
    drop_frac: float = 0.10,
    seed: int = 0,
) -> SynthVideo:
    rng = np.random.default_rng(seed)
    kpts = video.keypoints.copy()
    scores = video.scores.copy()
    sigma_px = float(sigma_s) * float(video.torso)
    kpts += rng.normal(0.0, sigma_px, size=kpts.shape).astype(np.float32)
    n = video.n_frames
    n_drop = int(round(drop_frac * n))
    if n_drop:
        dropped = rng.choice(n, size=n_drop, replace=False)
        scores[dropped] = 0.0
    return SynthVideo(
        kpts,
        scores,
        video.fps,
        video.n_frames,
        video.floor_line.copy(),
        None if video.top_zone is None else video.top_zone.copy(),
        list(video.attempts),
        name=f"{video.name}_noisy",
        torso=video.torso,
        meta={"sigma_s": sigma_s, "drop_frac": drop_frac, "seed": seed},
    )


def labelled_eval_fixture() -> list[SynthVideo]:
    """Clean labelled clips used by the CPU eval job."""
    return [
        standing_only(),
        one_attempt(),
        one_attempt(sit=True, leave=40, land=130),
        one_attempt(send=True, leave=30, land=140, tail=40),
        two_attempts(),
    ]
