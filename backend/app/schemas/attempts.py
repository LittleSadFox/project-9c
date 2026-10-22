"""Attempt request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class AttemptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    outcome: Literal["send", "fall", "unknown"]


class AttemptPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    outcome: Literal["send", "fall", "unknown"] | None = None
    proximity: StrictInt | None = Field(default=None, ge=0, le=10)
    exertion: StrictInt | None = Field(default=None, ge=0, le=10)
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class AttemptOut(BaseModel):
    id: str
    video_id: str
    boulder_id: str | None
    proposal_id: str | None
    start_frame: int
    end_frame: int
    outcome: str
    proximity: int | None
    exertion: int | None
    notes: str | None
    rated_at: str | None
    clip_version: int
    clip_status: str
    created_at: str
    fps: float | None = None
    duration_s: float | None = None
    clip_url: str | None = None
    job_id: str | None = None

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        fps: float | None = None,
        include_media: bool = False,
        job_id: str | None = None,
    ) -> AttemptOut:
        duration_s = None
        clip_url = None
        if include_media and fps:
            span = int(row["end_frame"]) - int(row["start_frame"]) + 1
            duration_s = span / float(fps)
            clip_url = f"/api/attempts/{row['id']}/clip?v={row['clip_version']}"
        return cls(
            id=str(row["id"]),
            video_id=str(row["video_id"]),
            boulder_id=row.get("boulder_id"),
            proposal_id=row.get("proposal_id"),
            start_frame=int(row["start_frame"]),
            end_frame=int(row["end_frame"]),
            outcome=str(row["outcome"]),
            proximity=row.get("proximity"),
            exertion=row.get("exertion"),
            notes=row.get("notes"),
            rated_at=row.get("rated_at"),
            clip_version=int(row["clip_version"]),
            clip_status=str(row["clip_status"]),
            created_at=str(row["created_at"]),
            fps=fps,
            duration_s=duration_s,
            clip_url=clip_url,
            job_id=job_id,
        )


class AttemptListOut(BaseModel):
    items: list[AttemptOut]
    total: int
