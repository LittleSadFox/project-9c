"""SQL for scene_marks. Callers own the transaction."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dict


def get(conn: sqlite3.Connection, video_id: str) -> dict[str, Any] | None:
    return as_dict(
        conn.execute("SELECT * FROM scene_marks WHERE video_id = ?", (video_id,)).fetchone()
    )


def upsert(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    floor_line: str | None,
    top_zone: str | None,
    start_holds: str | None,
    ref_points: str | None,
    source: str,
) -> dict[str, Any]:
    conn.execute(
        """
        INSERT INTO scene_marks (
            video_id, floor_line, top_zone, start_holds, ref_points, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            floor_line = excluded.floor_line,
            top_zone = excluded.top_zone,
            start_holds = excluded.start_holds,
            ref_points = excluded.ref_points,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (video_id, floor_line, top_zone, start_holds, ref_points, source, utc_now()),
    )
    row = get(conn, video_id)
    assert row is not None
    return row
