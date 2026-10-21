"""Job response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    kind: str
    lane: str
    status: str
    progress: float | None
    message: str | None
    entity_type: str | None
    entity_id: str | None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> JobOut:
        return cls(
            id=str(row["id"]),
            kind=str(row["kind"]),
            lane=str(row["lane"]),
            status=str(row["status"]),
            progress=row["progress"],
            message=row["message"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            error=row["error"],
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
