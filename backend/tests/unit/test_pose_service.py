"""Pose job pipeline with the fixture backend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.core.climber import coverage as real_coverage
from app.db import apply_migrations, connect
from app.errors import AppError
from app.jobs.context import JobContext
from app.pose.estimator import FixtureEstimator
from app.repo import jobs as jobs_repo
from app.services.pose_service import (
    bind_pose_runtime,
    current_estimator,
    get_pose_summary,
    handle_pose_job,
    process_frames,
)
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


class _OnceLazyFrames:
    """Yield frames once. Fail if the source is listed early or iterated twice."""

    def __init__(self, count: int, estimator: FixtureEstimator) -> None:
        self._count = count
        self._estimator = estimator
        self._started = 0

    def __iter__(self) -> object:
        self._started += 1
        if self._started > 1:
            raise AssertionError("frame source was read twice")
        for index in range(self._count):
            if index > 0 and self._estimator.detect_calls < index:
                raise AssertionError("frame source was turned into a list early")
            yield index, np.zeros((8, 8, 3), dtype=np.uint8)


def test_lazy_frames_reject_early_list() -> None:
    estimator = FixtureEstimator()
    frames = _OnceLazyFrames(3, estimator)
    with pytest.raises(AssertionError, match="list early"):
        list(frames)


def test_process_frames_reads_iterator_once_lazily() -> None:
    estimator = FixtureEstimator()
    frames = _OnceLazyFrames(6, estimator)
    tracks, climber = process_frames(frames, estimator, fps=30.0, det_every=5, n_frames=6)
    assert tracks == []
    assert climber is None
    assert estimator.detect_calls == 6
    assert estimator.pose_calls == 0
    with pytest.raises(AssertionError, match="read twice"):
        list(frames)


def test_handle_pose_job_streams_injected_frames(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = LibraryPaths(settings.library_dir)
    paths.ensure()
    conn = connect(paths.db)
    apply_migrations(conn)
    video_id = "22222222-2222-2222-2222-222222222222"
    _insert_video(conn, video_id, n_frames=5)
    job = jobs_repo.insert_job(
        conn,
        job_id="pose-job-lazy",
        kind="pose",
        lane="compute",
        entity_type="video",
        entity_id=video_id,
    )
    estimator = FixtureEstimator()
    bind_pose_runtime(settings=settings, paths=paths, estimator=estimator)
    frames = _OnceLazyFrames(5, estimator)
    ctx = JobContext(conn, str(job["id"]))
    result = handle_pose_job(ctx, frames=frames)
    assert result["n_tracks"] == 0
    assert estimator.detect_calls == 5
    with pytest.raises(AssertionError, match="read twice"):
        next(iter(frames))
    conn.close()


def test_handle_pose_job_rolls_back_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    paths = LibraryPaths(settings.library_dir)
    paths.ensure()
    conn = connect(paths.db)
    apply_migrations(conn)
    video_id = "33333333-3333-3333-3333-333333333333"
    _insert_video(conn, video_id, n_frames=8)
    job = jobs_repo.insert_job(
        conn,
        job_id="pose-job-rollback",
        kind="pose",
        lane="compute",
        entity_type="video",
        entity_id=video_id,
    )
    detections = {}
    for index in range(8):
        left = np.array([[20.0, 160.0, 60.0, 220.0]], dtype=np.float32)
        y = 200.0 - 15.0 * index
        right = np.array([[200.0, y, 240.0, y + 60.0]], dtype=np.float32)
        detections[index] = np.vstack([left, right])
    estimator = FixtureEstimator(detections=detections)
    bind_pose_runtime(settings=settings, paths=paths, estimator=estimator)
    frames = [(index, np.zeros((8, 8, 3), dtype=np.uint8)) for index in range(8)]
    ctx = JobContext(conn, str(job["id"]))
    seen = {"n": 0}

    def coverage_once(track: object) -> float:
        seen["n"] += 1
        if seen["n"] > 1:
            raise RuntimeError("injected track write failure")
        return float(real_coverage(track))  # type: ignore[arg-type]

    monkeypatch.setattr("app.services.pose_service.coverage", coverage_once)
    with pytest.raises(RuntimeError, match="injected track write failure"):
        handle_pose_job(ctx, frames=frames)
    tracks = conn.execute("SELECT COUNT(*) AS n FROM pose_tracks").fetchone()
    assert int(tracks["n"]) == 0
    run = conn.execute("SELECT id, status FROM pose_runs").fetchone()
    assert run is not None
    assert run["status"] != "done"
    with pytest.raises(AppError) as err:
        get_pose_summary(conn, paths, video_id)
    assert err.value.status == 404
    leftovers = list(paths.pose.rglob("*"))
    assert leftovers == [] or all(
        item.is_dir() or (item.suffix not in {".npz", ".tmp"} and ".tmp" not in item.name)
        for item in leftovers
    )
    assert not any(path.is_file() for path in paths.pose.rglob("*.npz"))
    assert not any(path.is_file() for path in paths.pose.rglob("*.tmp"))
    conn.close()


def test_pose_job_rebuilds_estimator_when_mode_changes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = LibraryPaths(settings.library_dir)
    paths.ensure()
    conn = connect(paths.db)
    apply_migrations(conn)
    bind_pose_runtime(settings=settings, paths=paths, estimator=None)
    video_a = "44444444-4444-4444-4444-444444444444"
    video_b = "55555555-5555-5555-5555-555555555555"
    _insert_video(conn, video_a, n_frames=3)
    _insert_video(conn, video_b, n_frames=3)
    frames = [(index, np.zeros((8, 8, 3), dtype=np.uint8)) for index in range(3)]
    conn.execute("UPDATE settings SET value = ? WHERE key = 'pose_mode'", ('"balanced"',))
    conn.commit()
    job_a = jobs_repo.insert_job(
        conn,
        job_id="pose-job-balanced",
        kind="pose",
        lane="compute",
        entity_type="video",
        entity_id=video_a,
    )
    handle_pose_job(JobContext(conn, str(job_a["id"])), frames=frames)
    first = current_estimator(mode="balanced")
    assert first.mode == "balanced"
    conn.execute("UPDATE settings SET value = ? WHERE key = 'pose_mode'", ('"lightweight"',))
    conn.commit()
    job_b = jobs_repo.insert_job(
        conn,
        job_id="pose-job-lightweight",
        kind="pose",
        lane="compute",
        entity_type="video",
        entity_id=video_b,
    )
    handle_pose_job(JobContext(conn, str(job_b["id"])), frames=frames)
    second = current_estimator(mode="lightweight")
    assert second.mode == "lightweight"
    assert second is not first
    mode_a = conn.execute(
        "SELECT mode FROM pose_runs WHERE video_id = ?", (video_a,)
    ).fetchone()
    mode_b = conn.execute(
        "SELECT mode FROM pose_runs WHERE video_id = ?", (video_b,)
    ).fetchone()
    assert mode_a["mode"] == "balanced"
    assert mode_b["mode"] == "lightweight"
    conn.close()
