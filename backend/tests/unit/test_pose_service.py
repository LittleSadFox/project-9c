"""Pose job pipeline with the fixture backend."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.config import Settings
from app.db import apply_migrations, connect
from app.jobs.context import JobContext
from app.pose.estimator import FixtureEstimator
from app.repo import jobs as jobs_repo
from app.services.pose_service import bind_pose_runtime, handle_pose_job, process_frames
from app.storage import LibraryPaths


def _settings(tmp_path: Path) -> Settings:
    library = tmp_path / "library"
    models = tmp_path / "models"
    golden = tmp_path / "golden"
    library.mkdir()
    models.mkdir()
    golden.mkdir()
    return Settings(
        library_dir=library,
        models_dir=models,
        golden_dir=golden,
        ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe",
        host="127.0.0.1",
        port=8810,
        launch_token="test-launch-token-value-32chars",
        dev=False,
        max_upload_gb=8.0,
        device="cpu",
        pose_backend="fixture",
    )


def _insert_video(conn: object, video_id: str, n_frames: int = 10) -> None:
    conn.execute(
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, is_vfr,
            ingest_status, pose_status, detect_status, review_status, created_at,
            proxy_fps, n_frames, proxy_width, proxy_height
        ) VALUES (?, 'a.mp4', 'mp4', ?, 10, 0, 'done', 'pending', 'pending', 'unreviewed',
                  '2026-10-22T00:00:00Z', 30, ?, 1280, 720)
        """,
        (video_id, f"sha-{video_id}", n_frames),
    )
    conn.commit()


def test_process_frames_selects_climber() -> None:
    detections = {}
    for index in range(8):
        left = np.array([[20.0, 160.0, 60.0, 220.0]], dtype=np.float32)
        y = 200.0 - 15.0 * index
        right = np.array([[200.0, y, 240.0, y + 60.0]], dtype=np.float32)
        detections[index] = np.vstack([left, right])
    estimator = FixtureEstimator(detections=detections)
    frames = [(index, np.zeros((8, 8, 3), dtype=np.uint8)) for index in range(8)]
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=1)
    assert len(tracks) == 2
    assert climber is not None
    assert estimator.pose_calls == 8


def test_handle_pose_job_writes_run(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = LibraryPaths(settings.library_dir)
    paths.ensure()
    conn = connect(paths.db)
    apply_migrations(conn)
    video_id = "11111111-1111-1111-1111-111111111111"
    _insert_video(conn, video_id, n_frames=6)
    job = jobs_repo.insert_job(
        conn,
        job_id="pose-job-1",
        kind="pose",
        lane="compute",
        entity_type="video",
        entity_id=video_id,
    )
    detections = {
        index: np.array([[10.0, 10.0 + index, 50.0, 80.0 + index]], dtype=np.float32)
        for index in range(6)
    }
    estimator = FixtureEstimator(detections=detections)
    bind_pose_runtime(settings=settings, paths=paths, estimator=estimator)
    frames = [(index, np.zeros((8, 8, 3), dtype=np.uint8)) for index in range(6)]
    ctx = JobContext(conn, str(job["id"]))
    result = handle_pose_job(ctx, frames=frames)
    assert result["n_tracks"] == 1
    row = conn.execute("SELECT pose_status FROM videos WHERE id = ?", (video_id,)).fetchone()
    assert row["pose_status"] == "done"
    run = conn.execute("SELECT id, climber_track_id, status FROM pose_runs").fetchone()
    assert run["status"] == "done"
    assert (paths.pose / video_id / f"{run['id']}.npz").is_file()
    conn.close()
