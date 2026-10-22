"""Session request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(min_length=8, max_length=32)
    gym: str | None = None
    notes: str | None = None


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str | None = None
    gym: str | None = None
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class SessionOut(BaseModel):
    id: str
    date: str
    gym: str | None
    notes: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SessionOut:
        return cls(
            id=str(row["id"]),
            date=str(row["date"]),
            gym=row.get("gym"),
            notes=row.get("notes"),
            created_at=str(row["created_at"]),
        )


class SessionListOut(BaseModel):
    items: list[SessionOut]
    total: int
