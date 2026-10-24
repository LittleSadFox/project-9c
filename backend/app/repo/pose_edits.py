"""SQL for pose_edits."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.clock import utc_now
from app.repo.util import as_dicts, new_id

_POINT_SEP = ":"


def _sibling_ids(edit_id: str) -> tuple[str, str]:
    return edit_id, f"{edit_id}{_POINT_SEP}%"


def insert_edit(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    kind: str,
    frame: int,
    kpt: int | None = None,
    x: float | None = None,
    y: float | None = None,
    range_start: int | None = None,
    range_end: int | None = None,
    points: list[dict[str, Any]] | None = None,
    edit_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Insert one logical edit. Extra points become sibling rows. Does not commit."""
    row_id = edit_id or new_id()
    stamp = created_at or utc_now()
    extra = list(points or [])
    first_kpt = kpt
    first_x = x
    first_y = y
    if first_kpt is None and extra:
        head = extra[0]
        first_kpt = int(head["kpt"])
        first_x = None if head.get("x") is None else float(head["x"])
        first_y = None if head.get("y") is None else float(head["y"])
        extra = extra[1:]
    conn.execute(
        """
        INSERT INTO pose_edits (
            id, video_id, kind, frame, kpt, x, y, range_start, range_end,
            undone_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            row_id,
            video_id,
            kind,
            int(frame),
            first_kpt,
            first_x,
            first_y,
            range_start,
            range_end,
            stamp,
        ),
    )
    for index, point in enumerate(extra):
        conn.execute(
            """
            INSERT INTO pose_edits (
                id, video_id, kind, frame, kpt, x, y, range_start, range_end,
                undone_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                f"{row_id}{_POINT_SEP}{index}",
                video_id,
                kind,
                int(frame),
                int(point["kpt"]),
                None if point.get("x") is None else float(point["x"]),
                None if point.get("y") is None else float(point["y"]),
                range_start,
                range_end,
                stamp,
            ),
        )
    row = get_edit(conn, video_id, row_id)
    assert row is not None
    return row


def _group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        raw_id = str(row["id"])
        base = raw_id.split(_POINT_SEP, 1)[0]
        if base not in groups:
            item = dict(row)
            item["id"] = base
            item["points"] = []
            groups[base] = item
            order.append(base)
        group = groups[base]
        if row.get("kpt") is not None:
            group["points"].append(
                {
                    "kpt": int(row["kpt"]),
                    "x": None if row.get("x") is None else float(row["x"]),
                    "y": None if row.get("y") is None else float(row["y"]),
                }
            )
            if group.get("kpt") is None:
                group["kpt"] = int(row["kpt"])
                group["x"] = row.get("x")
                group["y"] = row.get("y")
    return [groups[key] for key in order]


def list_active(
    conn: sqlite3.Connection,
    video_id: str,
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[dict[str, Any]]:
    rows = as_dicts(
        list(
            conn.execute(
                """
                SELECT * FROM pose_edits
                WHERE video_id = ? AND undone_at IS NULL
                ORDER BY created_at ASC, id ASC
                """,
                (video_id,),
            ).fetchall()
        )
    )
    grouped = _group_rows(rows)
    if start is None and end is None:
        return grouped
    start_i = 0 if start is None else int(start)
    end_i = start_i if end is None else int(end)
    if end_i < start_i:
        start_i, end_i = end_i, start_i
    out: list[dict[str, Any]] = []
    for edit in grouped:
        range_start = int(edit["frame"] if edit.get("range_start") is None else edit["range_start"])
        range_end = int(edit["frame"] if edit.get("range_end") is None else edit["range_end"])
        if range_end < start_i or range_start > end_i:
            continue
        out.append(edit)
    return out


def get_edit(conn: sqlite3.Connection, video_id: str, edit_id: str) -> dict[str, Any] | None:
    rows = as_dicts(
        list(
            conn.execute(
                """
                SELECT * FROM pose_edits
                WHERE video_id = ? AND (id = ? OR id LIKE ?)
                ORDER BY created_at ASC, id ASC
                """,
                (video_id, edit_id, f"{edit_id}{_POINT_SEP}%"),
            ).fetchall()
        )
    )
    grouped = _group_rows(rows)
    return grouped[0] if grouped else None


def undo_edit(
    conn: sqlite3.Connection,
    video_id: str,
    edit_id: str,
    *,
    undone_at: str | None = None,
) -> dict[str, Any] | None:
    """Mark one logical edit undone. Does not commit."""
    current = get_edit(conn, video_id, edit_id)
    if current is None or current.get("undone_at") is not None:
        return current
    stamp = undone_at or utc_now()
    base, like = _sibling_ids(edit_id)
    conn.execute(
        """
        UPDATE pose_edits
        SET undone_at = ?
        WHERE video_id = ? AND undone_at IS NULL AND (id = ? OR id LIKE ?)
        """,
        (stamp, video_id, base, like),
    )
    return get_edit(conn, video_id, edit_id)
