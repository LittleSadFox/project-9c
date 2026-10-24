"""Pose response models. Phase 1 subset plus Phase 2 slice E edits."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    hit_track_id: int | None = None


class PoseClimberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: int | None = None
    frame: int | None = Field(default=None, ge=0)
    x: float | None = None
    y: float | None = None


class PoseClimberOut(BaseModel):
    climber_track_id: int
    job_id: str | None = None


class PoseEditPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpt: int = Field(ge=0, le=25)
    x: float | None = None
    y: float | None = None


class PoseEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["move", "lr_swap", "invalid", "confirm"]
    frame: int = Field(ge=0)
    range: list[int] | None = Field(default=None, min_length=2, max_length=2)
    points: list[PoseEditPoint] | None = None


class PoseEditOut(BaseModel):
    edit_id: str
    start: int
    end: int
    frames: list[list[list[float]] | None]


class PoseEditItemOut(BaseModel):
    id: str
    kind: str
    frame: int
    range_start: int | None
    range_end: int | None
    points: list[PoseEditPoint]
    created_at: str | None = None


class PoseEditsOut(BaseModel):
    items: list[PoseEditItemOut]
    total: int


class PoseReviewItemOut(BaseModel):
    frame: int
    kind: Literal["lr_flip", "low_score"]
    severity: float


class PoseReviewQueueOut(BaseModel):
    items: list[PoseReviewItemOut]
    total: int


ClimberPut = PoseClimberIn
ClimberOut = PoseClimberOut


def track_out(row: dict[str, Any]) -> PoseTrackOut:
    return PoseTrackOut(
        track_id=int(row["track_id"]),
        first_frame=int(row["first_frame"]),
        last_frame=int(row["last_frame"]),
        coverage=row.get("coverage"),
        vertical_travel=row.get("vertical_travel"),
    )
