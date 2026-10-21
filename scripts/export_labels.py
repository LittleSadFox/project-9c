#!/usr/bin/env python3
"""Golden labels from the library -> golden/labels/labels.json.

Keys are video sha256 values.
Times are seconds.
Do not write footage.
Do not write secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


class ExportError(Exception):
    """Raised when labels cannot be exported."""


def default_library_dir() -> Path:
    raw = os.environ.get("CC_LIBRARY_DIR")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return Path.home() / "Library" / "Application Support" / "ClimbingCoach" / "library-dev"


def default_golden_dir() -> Path:
    raw = os.environ.get("CC_GOLDEN_DIR")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return Path.home() / "Library" / "Application Support" / "ClimbingCoach" / "golden"


def _frames_to_s(frame: int | None, fps: float | None) -> float | None:
    if frame is None:
        return None
    rate = fps if fps and fps > 0 else 30.0
    return float(frame) / rate


def _json_or_none(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def load_labels(library_dir: Path) -> dict[str, Any]:
    db_path = library_dir / "library.sqlite3"
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        videos = conn.execute(
            """
            SELECT id, original_name, sha256, duration_s, proxy_fps, src_fps
            FROM videos
            WHERE deleted_at IS NULL
            ORDER BY created_at
            """
        ).fetchall()
        labels: dict[str, Any] = {}
        for video in videos:
            fps = video["proxy_fps"] if video["proxy_fps"] else video["src_fps"]
            attempts_rows = conn.execute(
                """
                SELECT start_frame, end_frame, outcome
                FROM attempts
                WHERE video_id = ? AND deleted_at IS NULL
                ORDER BY start_frame
                """,
                (video["id"],),
            ).fetchall()
            scene_row = conn.execute(
                """
                SELECT floor_line, top_zone, start_holds, ref_points, source
                FROM scene_marks
                WHERE video_id = ?
                """,
                (video["id"],),
            ).fetchone()
            scene = None
            if scene_row is not None:
                scene = {
                    "floor_line": _json_or_none(scene_row["floor_line"]),
                    "top_zone": _json_or_none(scene_row["top_zone"]),
                    "start_holds": _json_or_none(scene_row["start_holds"]),
                    "ref_points": _json_or_none(scene_row["ref_points"]),
                    "source": scene_row["source"],
                }
            labels[str(video["sha256"])] = {
                "original_name": video["original_name"],
                "duration_s": video["duration_s"],
                "attempts": [
                    {
                        "start_s": _frames_to_s(row["start_frame"], fps),
                        "end_s": _frames_to_s(row["end_frame"], fps),
                        "outcome": row["outcome"],
                    }
                    for row in attempts_rows
                ],
                "scene": scene,
            }
        return labels
    finally:
        conn.close()


def export_labels(library_dir: Path, golden_dir: Path) -> Path:
    if not library_dir.is_dir():
        raise ExportError(f"Library folder is missing: {library_dir}")
    golden_dir.mkdir(parents=True, exist_ok=True)
    dest = golden_dir / "labels" / "labels.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = load_labels(library_dir)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export golden labels from the library.")
    parser.add_argument("--library-dir", type=Path, default=None)
    parser.add_argument("--golden-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    library_dir = args.library_dir or default_library_dir()
    golden_dir = args.golden_dir or default_golden_dir()
    try:
        dest = export_labels(library_dir, golden_dir)
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
