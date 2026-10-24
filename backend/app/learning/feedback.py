"""The only write path for correction events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.repo import feedback as feedback_repo

FEEDBACK_KINDS = frozenset(
    {
        "cut.accept",
        "cut.adjust",
        "cut.reject",
        "cut.missed",
        "cut.delete",
        "outcome.correct",
        "scene.edit",
        "climber.reassign",
        "pose.edit",
        "pose.confirm",
        "align.anchor",
        "review.complete",
    }
)


def log_feedback(
    conn: sqlite3.Connection,
    *,
    kind: str,
    entity_type: str,
    entity_id: str,
    video_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    model_version_id: str | None = None,
) -> dict[str, Any]:
    """Write one feedback_events row inside the caller's transaction.

    before and after hold ids and values only. They never hold file paths
    or frame image bytes.
    """
    if kind not in FEEDBACK_KINDS:
        raise ValueError(f"Unknown feedback kind: {kind}.")
    return feedback_repo.insert(
        conn,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        video_id=video_id,
        before=None if before is None else json.dumps(before),
        after=None if after is None else json.dumps(after),
        model_version_id=model_version_id,
    )
