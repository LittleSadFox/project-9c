"""export_labels.py writes sha256-keyed labels with times in seconds."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.export_labels import export_labels, load_labels

from app.db import apply_migrations, connect


def test_export_empty_library(tmp_path: Path) -> None:
    library = tmp_path / "library"
    golden = tmp_path / "golden"
    library.mkdir()
    dest = export_labels(library, golden)
    assert dest == golden / "labels" / "labels.json"
    assert json.loads(dest.read_text(encoding="utf-8")) == {}


def test_export_labels_from_sqlite(tmp_path: Path) -> None:
    library = tmp_path / "library"
    golden = tmp_path / "golden"
    library.mkdir()
    conn = connect(library / "library.sqlite3")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, duration_s,
            src_fps, is_vfr, proxy_fps, ingest_status, pose_status, detect_status,
            review_status, created_at
        ) VALUES (
            'vid-1', 'wall.mov', 'mov', 'abc123', 10, 12.0,
            30, 0, 30, 'done', 'done', 'done',
            'reviewed', '2026-10-21T00:00:00Z'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO attempts (
            id, video_id, start_frame, end_frame, outcome,
            clip_version, clip_status, created_at
        ) VALUES (
            'att-1', 'vid-1', 30, 90, 'send', 1, 'done', '2026-10-21T00:00:00Z'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO scene_marks (
            video_id, floor_line, top_zone, start_holds, ref_points, source, updated_at
        ) VALUES (
            'vid-1', '[[0, 10], [20, 10]]', NULL, NULL, NULL, 'user', '2026-10-21T00:00:00Z'
        )
        """
    )
    conn.commit()
    conn.close()

    labels = load_labels(library)
    assert "abc123" in labels
    assert labels["abc123"]["attempts"][0]["start_s"] == 1.0
    assert labels["abc123"]["attempts"][0]["end_s"] == 3.0
    assert labels["abc123"]["attempts"][0]["outcome"] == "send"
    assert labels["abc123"]["scene"]["source"] == "user"

    dest = export_labels(library, golden)
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["abc123"]["original_name"] == "wall.mov"
