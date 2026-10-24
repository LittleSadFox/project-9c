"""Scene marks, proposals, review actions, and feedback rows."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from app.pose.store import write_pose
from app.repo.models import RULE_V1_ID
from app.services.detection import run_detect_for_video
from tests.conftest import api_headers
from tests.fixtures.synth_pose import one_attempt, two_attempts


def _seed_video(client: TestClient, video: Any, *, video_id: str, run_id: str) -> str:
    conn = client.app.state.db_conn
    paths = client.app.state.paths
    n = video.n_frames
    conn.execute(
        """
        INSERT INTO videos (
            id, original_name, original_ext, sha256, size_bytes, is_vfr,
            ingest_status, pose_status, detect_status, review_status, created_at,
            proxy_fps, n_frames, proxy_width, proxy_height
        ) VALUES (?, 'clip.mp4', 'mp4', ?, 10, 0, 'done', 'done', 'pending', 'unreviewed',
                  '2026-10-24T00:00:00Z', ?, ?, 1280, 720)
        """,
        (video_id, video_id.replace("-", ""), video.fps, n),
    )
    conn.execute(
        """
        INSERT INTO pose_runs (
            id, video_id, model_version_id, device, provider, mode, det_every,
            fps_measured, climber_track_id, status, created_at
        ) VALUES (?, ?, NULL, 'cpu', 'CPUExecutionProvider', 'balanced', 5, ?, 1, 'done',
                  '2026-10-24T00:00:01Z')
        """,
        (run_id, video_id, video.fps),
    )
    conn.execute(
        """
        INSERT INTO pose_tracks (
            id, run_id, track_id, first_frame, last_frame, coverage, vertical_travel, is_climber
        ) VALUES (?, ?, 1, 0, ?, 1.0, 40.0, 1)
        """,
        (run_id, run_id, n - 1),
    )
    conn.commit()
    kpts = np.concatenate(
        [video.keypoints, video.scores[..., None]],
        axis=-1,
    ).astype(np.float32)
    write_pose(
        paths.pose / video_id / f"{run_id}.npz",
        frame=np.arange(n, dtype=np.int32),
        track_id=np.ones((n,), dtype=np.int32),
        keypoints=kpts,
        bbox=np.array([[600.0, 200.0, 700.0, 620.0]] * n, dtype=np.float32),
        meta={
            "n_frames": n,
            "fps": video.fps,
            "climber_track_id": 1,
            "run_id": run_id,
            "provider": "CPUExecutionProvider",
            "model_version": "fixture",
            "det_every": 5,
            "mode": "balanced",
            "device": "cpu",
        },
    )
    run_detect_for_video(conn, paths, video_id, run_id=run_id)
    return video_id


def _feedback(conn: Any, **filters: str) -> list[dict[str, Any]]:
    where = " AND ".join(f"{key} = ?" for key in filters)
    sql = "SELECT * FROM feedback_events"
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY created_at, id"
    return [dict(row) for row in conn.execute(sql, tuple(filters.values())).fetchall()]


def test_scene_put_copy_and_events(auth_client: TestClient) -> None:
    video_id = "11111111-1111-4111-8111-111111111111"
    _seed_video(auth_client, one_attempt(), video_id=video_id, run_id="run-one")
    scene = auth_client.get(f"/api/videos/{video_id}/scene", headers=api_headers())
    assert scene.status_code == 200
    body = scene.json()
    assert body["floor_line"] is not None
    put = auth_client.put(
        f"/api/videos/{video_id}/scene",
        headers=api_headers(),
        json={
            "floor_line": [[0, 600], [1280, 600]],
            "top_zone": [[500, 100], [800, 100], [800, 220], [500, 220]],
            "start_holds": [[640, 400]],
            "ref_points": [{"name": "left", "x": 200, "y": 300}],
        },
    )
    assert put.status_code == 200
    assert put.json()["scene"]["source"] == "user"
    events = auth_client.get(f"/api/videos/{video_id}/events", headers=api_headers())
    assert events.status_code == 200
    kinds = {item["kind"] for item in events.json()}
    assert "leave_ground" in kinds
    rows = _feedback(auth_client.app.state.db_conn, kind="scene.edit")
    assert len(rows) == 1
    assert rows[0]["model_version_id"] == RULE_V1_ID

    other = "22222222-2222-4222-8222-222222222222"
    conn = auth_client.app.state.db_conn
    boulder = conn.execute(
        """
        INSERT INTO boulders (id, name, status, created_at)
        VALUES ('b1', 'X', 'active', '2026-10-24T00:00:00Z')
        """
    )
    del boulder
    conn.execute("UPDATE videos SET boulder_id = 'b1' WHERE id = ?", (video_id,))
    _seed_video(auth_client, one_attempt(), video_id=other, run_id="run-other")
    conn.execute("UPDATE videos SET boulder_id = 'b1' WHERE id = ?", (other,))
    conn.commit()
    copied = auth_client.post(
        f"/api/videos/{other}/scene/copy-from/{video_id}",
        headers=api_headers(),
    )
    assert copied.status_code == 200
    assert copied.json()["scene"]["source"] == "user"
    outside = auth_client.put(
        f"/api/videos/{video_id}/scene",
        headers=api_headers(),
        json={"floor_line": [[0, 600], [2000, 600]]},
    )
    assert outside.status_code == 400


def test_review_actions_write_one_feedback_row(auth_client: TestClient) -> None:
    video_id = "33333333-3333-4333-8333-333333333333"
    _seed_video(auth_client, two_attempts(), video_id=video_id, run_id="run-two")
    listed = auth_client.get(f"/api/videos/{video_id}/proposals", headers=api_headers())
    assert listed.status_code == 200
    proposals = listed.json()
    assert len(proposals) == 2
    first, second = proposals

    accepted = auth_client.post(
        f"/api/proposals/{first['id']}/accept",
        headers=api_headers(),
        json={},
    )
    assert accepted.status_code == 201
    assert accepted.json()["attempt"]["proposal_id"] == first["id"]
    assert accepted.json()["job_id"]

    adjusted = auth_client.post(
        f"/api/proposals/{second['id']}/accept",
        headers=api_headers(),
        json={
            "start_frame": second["start_frame"] + 1,
            "end_frame": second["end_frame"],
            "outcome": "fall",
        },
    )
    assert adjusted.status_code == 201

    # Re-seed a third proposal by writing one pending row.
    conn = auth_client.app.state.db_conn
    conn.execute(
        """
        INSERT INTO proposals (
            id, video_id, start_frame, end_frame, outcome_guess, confidence,
            model_version_id, status, attempt_id, created_at
        ) VALUES ('p-rej', ?, 10, 40, 'fall', 0.5, ?, 'pending', NULL, '2026-10-24T00:00:02Z')
        """,
        (video_id, RULE_V1_ID),
    )
    conn.commit()
    rejected = auth_client.post(
        "/api/proposals/p-rej/reject",
        headers=api_headers(),
        json={"reason": "not_attempt"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    missed = auth_client.post(
        f"/api/videos/{video_id}/attempts",
        headers=api_headers(),
        json={"start_frame": 0, "end_frame": 8, "outcome": "unknown"},
    )
    assert missed.status_code == 201

    finish = auth_client.patch(
        f"/api/videos/{video_id}",
        headers=api_headers(),
        json={"review_status": "reviewed"},
    )
    assert finish.status_code == 200

    conn = auth_client.app.state.db_conn
    kinds = [row["kind"] for row in _feedback(conn, video_id=video_id)]
    assert kinds.count("cut.accept") == 1
    assert kinds.count("cut.adjust") == 1
    assert kinds.count("cut.reject") == 1
    assert kinds.count("cut.missed") == 1
    assert kinds.count("review.complete") == 1
    for row in _feedback(conn, video_id=video_id):
        assert row["before"] is None or "path" not in row["before"]
        assert row["model_version_id"]


def test_batch_accept_is_one_transaction(auth_client: TestClient) -> None:
    video_id = "44444444-4444-4444-8444-444444444444"
    _seed_video(auth_client, two_attempts(), video_id=video_id, run_id="run-batch")
    proposals = auth_client.get(f"/api/videos/{video_id}/proposals", headers=api_headers()).json()
    ids = [proposals[0]["id"], "missing-proposal"]
    failed = auth_client.post(
        "/api/proposals/batch-accept",
        headers=api_headers(),
        json={"ids": ids},
    )
    assert failed.status_code == 404
    leftover = auth_client.get(f"/api/videos/{video_id}/proposals", headers=api_headers()).json()
    assert all(item["status"] == "pending" for item in leftover)
    assert _feedback(auth_client.app.state.db_conn, video_id=video_id, kind="cut.accept") == []

    ok = auth_client.post(
        "/api/proposals/batch-accept",
        headers=api_headers(),
        json={"ids": [item["id"] for item in leftover]},
    )
    assert ok.status_code == 200
    assert ok.json()["total"] == 2
    accepts = _feedback(auth_client.app.state.db_conn, video_id=video_id, kind="cut.accept")
    assert len(accepts) == 2


def test_finish_review_409_with_pending(auth_client: TestClient) -> None:
    video_id = "55555555-5555-4555-8555-555555555555"
    _seed_video(auth_client, one_attempt(), video_id=video_id, run_id="run-pending")
    blocked = auth_client.patch(
        f"/api/videos/{video_id}",
        headers=api_headers(),
        json={"review_status": "reviewed"},
    )
    assert blocked.status_code == 409
    assert _feedback(auth_client.app.state.db_conn, kind="review.complete") == []


def test_unknown_ids_404_before_path_touch(auth_client: TestClient) -> None:
    missing = auth_client.get(
        "/api/videos/00000000-0000-4000-8000-000000000099/scene",
        headers=api_headers(),
    )
    assert missing.status_code == 404
    missing_copy = auth_client.post(
        "/api/videos/00000000-0000-4000-8000-000000000099/scene/copy-from/00000000-0000-4000-8000-000000000098",
        headers=api_headers(),
    )
    assert missing_copy.status_code == 404
