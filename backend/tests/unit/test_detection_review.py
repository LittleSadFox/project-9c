"""Detect enqueue and finish-review locks under concurrent writers."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.db import apply_migrations, connect, immediate
from app.errors import AppError
from app.repo import models as models_repo
from app.repo.util import new_id
from app.services.detection import enqueue_detect
from app.services.library import patch_video


def _seed_video(conn: object, *, reviewed: bool = False, pending: bool = False) -> str:
    video_id = new_id()
    conn.execute(  # type: ignore[union-attr]
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, is_vfr,
            ingest_status, pose_status, detect_status, review_status, created_at,
            proxy_fps, n_frames, proxy_width, proxy_height
        ) VALUES (?, 'clip.mp4', 'mp4', ?, 10, 0, 'done', 'done', 'pending', ?,
                  '2026-10-24T00:00:00Z', 30, 60, 1280, 720)
        """,
        (video_id, video_id.replace("-", ""), "reviewed" if reviewed else "unreviewed"),
    )
    if pending:
        conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO proposals (
                id, video_id, start_frame, end_frame, outcome_guess, confidence,
                model_version_id, status, attempt_id, created_at
            ) VALUES (?, ?, 0, 10, 'fall', 0.5, ?, 'pending', NULL, '2026-10-24T00:00:01Z')
            """,
            (new_id(), video_id, models_repo.RULE_V1_ID),
        )
    conn.commit()  # type: ignore[union-attr]
    return video_id


def test_enqueue_detect_noop_for_reviewed(tmp_path: Path) -> None:
    conn = connect(tmp_path / "library.sqlite3")
    apply_migrations(conn)
    video_id = _seed_video(conn, reviewed=True)
    assert enqueue_detect(conn, video_id) is None
    jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'detect'").fetchone()[0]
    assert int(jobs) == 0
    conn.close()


def test_enqueue_detect_holds_reviewed_check(tmp_path: Path) -> None:
    db = tmp_path / "library.sqlite3"
    conn_a = connect(db)
    apply_migrations(conn_a)
    video_id = _seed_video(conn_a)
    conn_b = connect(db)
    result: list[object] = []

    def worker() -> None:
        result.append(enqueue_detect(conn_b, video_id))

    conn_a.execute("BEGIN IMMEDIATE")
    conn_a.execute("UPDATE videos SET review_status = 'reviewed' WHERE id = ?", (video_id,))
    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.2)
    conn_a.commit()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result == [None]
    jobs = conn_b.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'detect'").fetchone()[0]
    assert int(jobs) == 0
    conn_a.close()
    conn_b.close()


def test_finish_review_409_holds_pending_lock(tmp_path: Path) -> None:
    db = tmp_path / "library.sqlite3"
    conn_a = connect(db)
    apply_migrations(conn_a)
    video_id = _seed_video(conn_a)
    conn_b = connect(db)
    errors: list[int] = []

    def worker() -> None:
        try:
            patch_video(conn_b, video_id, {"review_status": "reviewed"})
        except AppError as exc:
            errors.append(exc.status)

    with immediate(conn_a):
        conn_a.execute(
            """
            INSERT INTO proposals (
                id, video_id, start_frame, end_frame, outcome_guess, confidence,
                model_version_id, status, attempt_id, created_at
            ) VALUES (?, ?, 0, 10, 'fall', 0.5, ?, 'pending', NULL, '2026-10-24T00:00:02Z')
            """,
            (new_id(), video_id, models_repo.RULE_V1_ID),
        )
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.2)
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert errors == [409]
    feedback = conn_b.execute(
        "SELECT COUNT(*) FROM feedback_events WHERE kind = 'review.complete'"
    ).fetchone()[0]
    assert int(feedback) == 0
    conn_a.close()
    conn_b.close()
