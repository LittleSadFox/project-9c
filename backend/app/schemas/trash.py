"""Trash response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TrashItemOut(BaseModel):
    id: str
    kind: str
    entity_id: str
    payload: str | None
    path: str | None
    deleted_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TrashItemOut:
        return cls(
            id=str(row["id"]),
            kind=str(row["kind"]),
            entity_id=str(row["entity_id"]),
            payload=row.get("payload"),
            path=row.get("path"),
            deleted_at=str(row["deleted_at"]),
        )


class TrashListOut(BaseModel):
    items: list[TrashItemOut]
    total: int
