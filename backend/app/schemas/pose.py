"""Pose response models. Phase 1 subset of coding_plan §9."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PoseTrackOut(BaseModel):
    track_id: int
    first_frame: int
    last_frame: int
    coverage: float | None
    vertical_travel: float | None


class PoseRunOut(BaseModel):
    run_id: str
    model_version: str | None
    provider: str | None
    fps: float
    n_frames: int
    keypoint_names: list[str]
    edges: list[list[int]]
    climber_track_id: int | None
    tracks: list[PoseTrackOut]


class PoseKeypointsOut(BaseModel):
    run_id: str
    fps: float
    start: int
    end: int
    frames: list[list[list[float]] | None]


class PosePersonOut(BaseModel):
    track_id: int
    bbox: list[float]
    keypoints: list[list[float]]


class PosePersonsOut(BaseModel):
    frame: int
    persons: list[PosePersonOut]


class ClimberPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: int | None = None
    frame: int | None = None
    x: float | None = None
    y: float | None = None


class ClimberOut(BaseModel):
    climber_track_id: int
    job_id: str | None = None


def track_out(row: dict[str, Any]) -> PoseTrackOut:
    return PoseTrackOut(
        track_id=int(row["track_id"]),
        first_frame=int(row["first_frame"]),
        last_frame=int(row["last_frame"]),
        coverage=row.get("coverage"),
        vertical_travel=row.get("vertical_travel"),
    )
