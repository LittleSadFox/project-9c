"""Phase 1 pose read endpoints and Phase 2 slice E edit endpoints."""

from __future__ import annotations

import json

import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.halpe26 import LEFT, LEFT_WRIST, N_KEYPOINTS, RIGHT, swap_left_right
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


def _seed_two_tracks(client: TestClient, *, flip_at: int | None = None) -> str:
    conn = client.app.state.db_conn
    paths = client.app.state.paths
    video_id = "7a2d3c1f-5e8b-4a1f-8b62-3c4d5e6f7081"
    run_id = "f18b0c2d-3e4f-5061-9b7c-8d9e0f1a2b3c"
    conn.execute(
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, is_vfr,
            ingest_status, pose_status, detect_status, review_status, created_at,
            proxy_fps, n_frames, proxy_width, proxy_height
        ) VALUES (?, 'clip.mp4', 'mp4', 'def', 10, 0, 'done', 'done', 'pending', 'unreviewed',
                  '2026-10-22T00:00:00Z', 30, 8, 1280, 720)
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
        ) VALUES ('t1', ?, 1, 0, 7, 1.0, 80.0, 1),
                 ('t2', ?, 2, 0, 7, 1.0, 10.0, 0)
        """,
        (run_id, run_id),
    )
    conn.commit()
    n_rows = 16
    frame = np.array([index // 2 for index in range(n_rows)], dtype=np.int32)
    track_id = np.array([1, 2] * 8, dtype=np.int32)
    keypoints = np.zeros((n_rows, N_KEYPOINTS, 3), dtype=np.float32)
    keypoints[:, :, 2] = 0.9
    bbox = np.zeros((n_rows, 4), dtype=np.float32)
    for index in range(n_rows):
        frame_i = int(frame[index])
        y = 200.0 - 8.0 * frame_i
        if int(track_id[index]) == 1:
            for left, right in zip(LEFT, RIGHT, strict=True):
                keypoints[index, left] = (40.0, y, 0.9)
                keypoints[index, right] = (80.0, y, 0.9)
            if flip_at is not None and frame_i >= flip_at:
                keypoints[index] = np.asarray(swap_left_right(keypoints[index]))
            bbox[index] = (20.0, y - 20.0, 100.0, y + 40.0)
        else:
            keypoints[index, 0] = (400.0, 40.0, 0.9)
            bbox[index] = (380.0, 20.0, 430.0, 80.0)
    write_pose(
        paths.pose / video_id / f"{run_id}.npz",
        frame=frame,
        track_id=track_id,
        keypoints=keypoints,
        bbox=bbox,
        meta={
            "n_frames": 8,
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


def test_pose_edit_range_undo_and_one_feedback(
    client: TestClient, tmp_settings: Settings
) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_two_tracks(client)
    before = client.get(
        f"/api/videos/{video_id}/pose/keypoints?track=climber&start=0&end=7",
        headers=api_headers(),
    ).json()
    created = client.post(
        f"/api/videos/{video_id}/pose/edits",
        headers=api_headers({"Content-Type": "application/json"}),
        json={
            "kind": "move",
            "frame": 3,
            "range": [1, 5],
            "points": [{"kpt": LEFT_WRIST, "x": 120.0, "y": 60.0}],
        },
    )
    assert created.status_code == 201
    body = created.json()
    edit_id = body["edit_id"]
    assert body["start"] == 1
    assert body["end"] == 5
    assert abs(body["frames"][2][LEFT_WRIST][0] - 120.0) < 1e-2
    after = client.get(
        f"/api/videos/{video_id}/pose/keypoints?track=climber&start=0&end=7",
        headers=api_headers(),
    ).json()
    assert after["frames"][0] == before["frames"][0]
    assert after["frames"][6] == before["frames"][6]
    assert after["frames"][3][LEFT_WRIST][0] != before["frames"][3][LEFT_WRIST][0]
    listed = client.get(f"/api/videos/{video_id}/pose/edits", headers=api_headers())
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    undone = client.delete(
        f"/api/videos/{video_id}/pose/edits/{edit_id}",
        headers=api_headers(),
    )
    assert undone.status_code == 204
    restored = client.get(
        f"/api/videos/{video_id}/pose/keypoints?track=climber&start=0&end=7",
        headers=api_headers(),
    ).json()
    assert restored["frames"] == before["frames"]
    rows = client.app.state.db_conn.execute(
        "SELECT kind, before, after FROM feedback_events WHERE video_id = ?",
        (video_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "pose.edit"
    after_payload = json.loads(str(rows[0]["after"]))
    assert after_payload["edit_id"] == edit_id
    assert "path" not in after_payload
    assert "/" not in json.dumps(after_payload)


def test_pose_edit_conflict_while_pose_job_runs(
    client: TestClient, tmp_settings: Settings
) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_two_tracks(client)
    # Insert as running so the live compute worker cannot claim and finish it.
    client.app.state.db_conn.execute(
        """
        INSERT INTO jobs (
            id, kind, lane, status, progress, message,
            entity_type, entity_id, error, created_at, started_at, finished_at
        ) VALUES (
            'pose-busy-1', 'pose', 'compute', 'running', 0, NULL,
            'video', ?, NULL, '2026-10-24T00:00:00Z', '2026-10-24T00:00:01Z', NULL
        )
        """,
        (video_id,),
    )
    client.app.state.db_conn.commit()
    response = client.post(
        f"/api/videos/{video_id}/pose/edits",
        headers=api_headers({"Content-Type": "application/json"}),
        json={"kind": "confirm", "frame": 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "pose_busy"
    busy = client.app.state.db_conn.execute(
        "SELECT status FROM jobs WHERE id = 'pose-busy-1'"
    ).fetchone()
    assert busy["status"] == "running"
    edits = client.app.state.db_conn.execute(
        "SELECT COUNT(*) AS n FROM pose_edits WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    feedback = client.app.state.db_conn.execute(
        "SELECT COUNT(*) AS n FROM feedback_events WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    assert int(edits["n"]) == 0
    assert int(feedback["n"]) == 0


def test_climber_reassign_and_persons_hit_test(
    client: TestClient, tmp_settings: Settings
) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_two_tracks(client)
    hit = client.get(
        f"/api/videos/{video_id}/pose/persons?frame=2&x=400&y=40",
        headers=api_headers(),
    )
    assert hit.status_code == 200
    assert hit.json()["hit_track_id"] == 2
    assert len(hit.json()["persons"]) == 2
    by_point = client.put(
        f"/api/videos/{video_id}/pose/climber",
        headers=api_headers({"Content-Type": "application/json"}),
        json={"frame": 2, "x": 400.0, "y": 40.0},
    )
    assert by_point.status_code == 200
    assert by_point.json()["climber_track_id"] == 2
    by_id = client.put(
        f"/api/videos/{video_id}/pose/climber",
        headers=api_headers({"Content-Type": "application/json"}),
        json={"track_id": 1},
    )
    assert by_id.status_code == 200
    assert by_id.json()["climber_track_id"] == 1
    rows = client.app.state.db_conn.execute(
        "SELECT kind, before, after FROM feedback_events WHERE video_id = ? ORDER BY created_at",
        (video_id,),
    ).fetchall()
    assert [row["kind"] for row in rows] == ["climber.reassign", "climber.reassign"]
    first = json.loads(str(rows[0]["after"]))
    assert first == {"climber_track_id": 2}


def test_review_queue_flags_scripted_flip_worst_first(
    client: TestClient, tmp_settings: Settings
) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_two_tracks(client, flip_at=4)
    response = client.get(
        f"/api/videos/{video_id}/pose/review-queue",
        headers=api_headers(),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    flips = [item for item in items if item["kind"] == "lr_flip"]
    assert flips
    assert flips[0]["frame"] == 4
    severities = [item["severity"] for item in items]
    assert severities == sorted(severities, reverse=True)


def test_confirm_writes_pose_confirm(client: TestClient, tmp_settings: Settings) -> None:
    _auth(client, tmp_settings)
    video_id = _seed_two_tracks(client)
    response = client.post(
        f"/api/videos/{video_id}/pose/edits",
        headers=api_headers({"Content-Type": "application/json"}),
        json={"kind": "confirm", "frame": 2},
    )
    assert response.status_code == 201
    row = client.app.state.db_conn.execute(
        "SELECT kind FROM feedback_events WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    assert row["kind"] == "pose.confirm"
