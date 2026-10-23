"""Shared SQL helpers."""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def as_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
