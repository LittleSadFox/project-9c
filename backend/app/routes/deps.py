"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from app.config import Settings
from app.jobs.queue import JobQueue


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.db_conn


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def request_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request. Phase 0 reuses the app connection."""
    yield request.app.state.db_conn
