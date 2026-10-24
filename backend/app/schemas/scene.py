"""Scene marks and event payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SceneOut(BaseModel):
    floor_line: list[list[float]] | None = None
    top_zone: list[list[float]] | None = None
    start_holds: list[list[float]] | None = None
    ref_points: list[dict[str, Any]] | None = None
    source: str = "auto"


class ScenePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor_line: list[list[float]] | None = None
    top_zone: list[list[float]] | None = None
    start_holds: list[list[float]] | None = None
    ref_points: list[dict[str, Any]] | None = None


class SceneWriteOut(BaseModel):
    scene: SceneOut
    job_id: str | None = None


class EventOut(BaseModel):
    id: str
    frame: int
    kind: str
    confidence: float | None = None
    source: str
