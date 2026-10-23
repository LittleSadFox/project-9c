"""Shared request helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
