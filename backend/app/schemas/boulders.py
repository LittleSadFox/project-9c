"""Boulder request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BoulderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    gym: str | None = None
    grade: str | None = None
    color: str | None = None
    sector: str | None = None
    set_date: str | None = None
    notes: str | None = None


class BoulderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    gym: str | None = None
    grade: str | None = None
    color: str | None = None
    sector: str | None = None
    set_date: str | None = None
    status: str | None = None
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class BoulderOut(BaseModel):
    id: str
    name: str
    gym: str | None
    grade: str | None
    color: str | None
    sector: str | None
    set_date: str | None
    status: str
    notes: str | None
    created_at: str
    video_count: int = 0
    attempt_count: int = 0
    sent: int = 0
    best_proximity: int | None = None
    last_attempt_at: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> BoulderOut:
        return cls(
            id=str(row["id"]),
            name=str(row["name"]),
            gym=row.get("gym"),
            grade=row.get("grade"),
            color=row.get("color"),
            sector=row.get("sector"),
            set_date=row.get("set_date"),
            status=str(row["status"]),
            notes=row.get("notes"),
            created_at=str(row["created_at"]),
            video_count=int(row.get("video_count") or 0),
            attempt_count=int(row.get("attempt_count") or 0),
            sent=int(row.get("sent") or 0),
            best_proximity=row.get("best_proximity"),
            last_attempt_at=row.get("last_attempt_at"),
        )


class BoulderListOut(BaseModel):
    items: list[BoulderOut]
    total: int
