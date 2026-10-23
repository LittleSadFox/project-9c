"""Phase 1 pose read endpoints with the fixture store."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.halpe26 import N_KEYPOINTS
from app.pose.store import write_pose
from tests.conftest import api_headers


def _auth(client: TestClient, settings: Settings) -> None:
    response = client.get(
        f"/auth/launch?token={settings.launch_token}",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert response.status_code == 303


def _seed_pose(client: TestClient) -> str:
    conn = client.app.state.db_conn
    paths = client.app.state.paths
    video_id = "6f1c2b0e-4f7a-4d0e-9a51-2b3c4d5e6f70"
    run_id = "e07a9b1c-2d3e-4f50-8a6b-7c8d9e0f1a2b"
    conn.execute(
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, is_vfr,
            ingest_status, pose_status, detect_status, review_status, created_at,
            proxy_fps, n_frames, proxy_width, proxy_height
        ) VALUES (?, 'clip.mp4', 'mp4', 'abc', 10, 0, 'done', 'done', 'pending', 'unreviewed',
                  '2026-10-22T00:00:00Z', 30, 4, 1280, 720)
        """,
        (video_id,),
    )
    conn.execute(
        """
        INSERT INTO pose_runs (
            id, video_id, model_version_id, device, provider, mode, det_every,
            fps_measured, climber_track_id, status, created_at
        ) VALUES (?, ?, NULL, 'cpu', 'CPUExecutionProvider', 'balanced', 5, 30, 1, 'done',
                  '2026-10-22T00:00:01Z')
        """,
        (run_id, video_id),
    )
    conn.execute(
        """
        INSERT INTO pose_tracks (
            id, run_id, track_id, first_frame, last_frame, coverage, vertical_travel, is_climber
        ) VALUES ('t1', ?, 1, 0, 2, 1.0, 40.0, 1)
        """,
        (run_id,),
    )
    conn.commit()
    keypoints = np.zeros((3, N_KEYPOINTS, 3), dtype=np.float32)
    keypoints[:, 0] = (412.3, 220.1, 0.93)
    keypoints[:, 1] = (415.0, 214.2, 0.88)
    write_pose(
        paths.pose / video_id / f"{run_id}.npz",
        frame=np.array([0, 1, 2], dtype=np.int32),
        track_id=np.array([1, 1, 1], dtype=np.int32),
        keypoints=keypoints,
        bbox=np.array([[400, 200, 430, 260]] * 3, dtype=np.float32),
        meta={
            "n_frames": 4,
            "fps": 30.0,
            "climber_track_id": 1,
            "run_id": run_id,
            "provider": "CPUExecutionProvider",
            "model_version": "fixture",
            "det_every": 5,
            "mode": "balanced",
            "device": "cpu",
        },
    )
    return video_id


def test_pose_summary_and_keypoints(client: TestClient, tmp_settings: Settings) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_pose(client)
    summary = client.get(f"/api/videos/{video_id}/pose", headers=api_headers())
    assert summary.status_code == 200
    body = summary.json()
    assert body["run_id"] == "e07a9b1c-2d3e-4f50-8a6b-7c8d9e0f1a2b"
    assert body["keypoint_names"][19] == "hip"
    assert body["climber_track_id"] == 1
    assert body["tracks"][0]["track_id"] == 1

    keypoints = client.get(
        f"/api/videos/{video_id}/pose/keypoints?track=climber&start=0&end=1",
        headers=api_headers(),
    )
    assert keypoints.status_code == 200
    assert keypoints.headers.get("content-encoding") == "gzip"
    payload = keypoints.json()
    assert payload["start"] == 0
    assert payload["end"] == 1
    assert len(payload["frames"]) == 2
    assert payload["frames"][0] is not None
    assert payload["frames"][0][0][0] == 412.3

    missing = client.get(
        f"/api/videos/{video_id}/pose/keypoints?start=3&end=3",
        headers=api_headers(),
    )
    assert missing.json()["frames"] == [None]


def test_pose_persons(client: TestClient, tmp_settings: Settings) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_pose(client)
    response = client.get(f"/api/videos/{video_id}/pose/persons?frame=1", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["frame"] == 1
    assert body["persons"][0]["track_id"] == 1
    assert len(body["persons"][0]["keypoints"]) == N_KEYPOINTS


def test_pose_not_ready(client: TestClient, tmp_settings: Settings) -> None:
    _auth(client, tmp_settings)
    response = client.get("/api/videos/missing/pose", headers=api_headers())
    assert response.status_code == 404


def test_pose_requires_session(client: TestClient) -> None:
    response = client.get("/api/videos/x/pose", headers=api_headers())
    assert response.status_code == 401
