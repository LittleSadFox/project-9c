"""Scene marks, proposals, and review actions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import immediate
from app.errors import AppError
from app.jobs.queue import JobQueue
from app.learning.feedback import log_feedback
from app.repo import attempts as attempts_repo
from app.repo import events as events_repo
from app.repo import models as models_repo
from app.repo import proposals as proposals_repo
from app.repo import scene as scene_repo
from app.repo import videos as videos_repo
from app.services.attempts import request_cut
from app.services.detection import enqueue_detect


def _require_video(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    row = videos_repo.get(conn, video_id)
    if row is None:
        raise AppError("not_found", 404, "The video is not here.")
    return row


def _decode(raw: object) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    return json.loads(raw)


def _encode(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _scene_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "floor_line": None,
            "top_zone": None,
            "start_holds": None,
            "ref_points": None,
            "source": "auto",
        }
    return {
        "floor_line": _decode(row.get("floor_line")),
        "top_zone": _decode(row.get("top_zone")),
        "start_holds": _decode(row.get("start_holds")),
        "ref_points": _decode(row.get("ref_points")),
        "source": row.get("source") or "auto",
    }


def _in_frame(x: float, y: float, width: float, height: float) -> bool:
    return 0.0 <= float(x) <= float(width) and 0.0 <= float(y) <= float(height)


def _validate_scene(data: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    width = float(video.get("proxy_width") or 0)
    height = float(video.get("proxy_height") or 0)
    if width <= 0 or height <= 0:
        raise AppError("ingest_pending", 409, "Wait for ingest to finish.")

    def _points(
        name: str, raw: object, *, min_n: int, max_n: int | None = None
    ) -> list[list[float]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise AppError("bad_scene", 400, f"{name} must be a list of points.")
        if len(raw) < min_n:
            raise AppError("bad_scene", 400, f"{name} needs at least {min_n} points.")
        if max_n is not None and len(raw) > max_n:
            raise AppError("bad_scene", 400, f"{name} must have {max_n} points.")
        out: list[list[float]] = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                raise AppError("bad_scene", 400, f"{name} points must be [x, y].")
            x, y = float(item[0]), float(item[1])
            if not _in_frame(x, y, width, height):
                raise AppError("bad_scene", 400, "Points must lie inside the frame.")
            out.append([x, y])
        return out

    floor = data.get("floor_line")
    floor_pts = _points("floor_line", floor, min_n=2, max_n=2) if floor is not None else None
    zone = data.get("top_zone")
    zone_pts = _points("top_zone", zone, min_n=3) if zone else None
    holds = data.get("start_holds")
    hold_pts = _points("start_holds", holds, min_n=0) if holds else None
    refs_raw = data.get("ref_points")
    refs: list[dict[str, Any]] | None = None
    if refs_raw:
        if not isinstance(refs_raw, list):
            raise AppError("bad_scene", 400, "ref_points must be a list.")
        refs = []
        for item in refs_raw:
            if not isinstance(item, dict):
                raise AppError("bad_scene", 400, "ref_points items must be objects.")
            x, y = float(item["x"]), float(item["y"])
            if not _in_frame(x, y, width, height):
                raise AppError("bad_scene", 400, "Points must lie inside the frame.")
            refs.append({"name": str(item.get("name") or ""), "x": x, "y": y})
    return {
        "floor_line": floor_pts,
        "top_zone": zone_pts,
        "start_holds": hold_pts,
        "ref_points": refs,
    }


def get_scene(conn: sqlite3.Connection, video_id: str) -> dict[str, Any]:
    _require_video(conn, video_id)
    return _scene_payload(scene_repo.get(conn, video_id))


def put_scene(
    conn: sqlite3.Connection,
    queue: JobQueue,
    video_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    video = _require_video(conn, video_id)
    cleaned = _validate_scene(data, video)
    model_id = models_repo.active_event_id(conn)
    with immediate(conn):
        before = _scene_payload(scene_repo.get(conn, video_id))
        row = scene_repo.upsert(
            conn,
            video_id=video_id,
            floor_line=_encode(cleaned["floor_line"]),
            top_zone=_encode(cleaned["top_zone"]),
            start_holds=_encode(cleaned["start_holds"]),
            ref_points=_encode(cleaned["ref_points"]),
            source="user",
        )
        after = _scene_payload(row)
        log_feedback(
            conn,
            kind="scene.edit",
            entity_type="video",
            entity_id=video_id,
            video_id=video_id,
            before=before,
            after=after,
            model_version_id=model_id,
        )
    job = enqueue_detect(conn, video_id, queue)
    return {"scene": after, "job_id": None if job is None else job.get("id")}


def copy_scene_from(
    conn: sqlite3.Connection,
    queue: JobQueue,
    video_id: str,
    other_id: str,
) -> dict[str, Any]:
    dest = _require_video(conn, video_id)
    src = _require_video(conn, other_id)
    if not dest.get("boulder_id") or dest.get("boulder_id") != src.get("boulder_id"):
        raise AppError("scene_copy_blocked", 409, "Copy-from works only within the same boulder.")
    src_marks = scene_repo.get(conn, other_id)
    if src_marks is None:
        raise AppError("not_found", 404, "The source video has no scene marks.")
    model_id = models_repo.active_event_id(conn)
    with immediate(conn):
        before = _scene_payload(scene_repo.get(conn, video_id))
        row = scene_repo.upsert(
            conn,
            video_id=video_id,
            floor_line=src_marks.get("floor_line"),
            top_zone=src_marks.get("top_zone"),
            start_holds=src_marks.get("start_holds"),
            ref_points=src_marks.get("ref_points"),
            source="user",
        )
        after = _scene_payload(row)
        log_feedback(
            conn,
            kind="scene.edit",
            entity_type="video",
            entity_id=video_id,
            video_id=video_id,
            before=before,
            after={"source_video_id": other_id, **after},
            model_version_id=model_id,
        )
    job = enqueue_detect(conn, video_id, queue)
    return {"scene": after, "job_id": None if job is None else job.get("id")}


def list_events(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    _require_video(conn, video_id)
    return events_repo.list_for_video(conn, video_id)


def list_proposals(conn: sqlite3.Connection, video_id: str) -> list[dict[str, Any]]:
    _require_video(conn, video_id)
    return proposals_repo.list_for_video(conn, video_id)


def _accept_one(
    conn: sqlite3.Connection,
    proposal: dict[str, Any],
    *,
    start_frame: int | None,
    end_frame: int | None,
    outcome: str | None,
) -> dict[str, Any]:
    if str(proposal.get("status")) != "pending":
        raise AppError("proposal_conflict", 409, "This proposal is not pending.")
    video = _require_video(conn, str(proposal["video_id"]))
    start = int(proposal["start_frame"] if start_frame is None else start_frame)
    end = int(proposal["end_frame"] if end_frame is None else end_frame)
    n_frames = int(video.get("n_frames") or 0)
    if start < 0 or end <= start or (n_frames and end >= n_frames):
        raise AppError("bad_span", 400, "end_frame must be greater than start_frame.")
    chosen_outcome = str(outcome or proposal.get("outcome_guess") or "unknown")
    if chosen_outcome not in {"send", "fall", "unknown"}:
        raise AppError("bad_outcome", 400, "outcome must be send, fall, or unknown.")
    frames_changed = start != int(proposal["start_frame"]) or end != int(proposal["end_frame"])
    attempt = attempts_repo.insert(
        conn,
        video_id=str(proposal["video_id"]),
        boulder_id=video.get("boulder_id"),
        start_frame=start,
        end_frame=end,
        outcome=chosen_outcome,
        proposal_id=str(proposal["id"]),
        commit=False,
    )
    proposals_repo.update(
        conn,
        str(proposal["id"]),
        {"status": "accepted", "attempt_id": attempt["id"]},
    )
    kind = "cut.adjust" if frames_changed else "cut.accept"
    log_feedback(
        conn,
        kind=kind,
        entity_type="proposal",
        entity_id=str(proposal["id"]),
        video_id=str(proposal["video_id"]),
        before={
            "proposal_id": proposal["id"],
            "start_frame": proposal["start_frame"],
            "end_frame": proposal["end_frame"],
            "outcome_guess": proposal.get("outcome_guess"),
        },
        after={
            "attempt_id": attempt["id"],
            "start_frame": start,
            "end_frame": end,
            "outcome": chosen_outcome,
        },
        model_version_id=proposal.get("model_version_id"),
    )
    return attempt


def accept_proposal(
    conn: sqlite3.Connection,
    queue: JobQueue,
    proposal_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    proposal = proposals_repo.get(conn, proposal_id)
    if proposal is None:
        raise AppError("not_found", 404, "The proposal is not here.")
    _require_video(conn, str(proposal["video_id"]))
    with immediate(conn):
        locked = proposals_repo.get(conn, proposal_id)
        if locked is None:
            raise AppError("not_found", 404, "The proposal is not here.")
        attempt = _accept_one(
            conn,
            locked,
            start_frame=data.get("start_frame"),
            end_frame=data.get("end_frame"),
            outcome=data.get("outcome"),
        )
    job = request_cut(conn, queue, str(attempt["id"]))
    return {"attempt": attempt, "job_id": None if job is None else job.get("id")}


def batch_accept(
    conn: sqlite3.Connection,
    queue: JobQueue,
    ids: list[str],
) -> dict[str, Any]:
    if not ids:
        raise AppError("bad_ids", 400, "ids must not be empty.")
    accepted: list[dict[str, Any]] = []
    with immediate(conn):
        for proposal_id in ids:
            proposal = proposals_repo.get(conn, proposal_id)
            if proposal is None:
                raise AppError("not_found", 404, "The proposal is not here.")
            _require_video(conn, str(proposal["video_id"]))
            attempt = _accept_one(
                conn,
                proposal,
                start_frame=None,
                end_frame=None,
                outcome=None,
            )
            accepted.append(attempt)
    items = []
    for attempt in accepted:
        job = request_cut(conn, queue, str(attempt["id"]))
        items.append({"attempt": attempt, "job_id": None if job is None else job.get("id")})
    return {"items": items, "total": len(items)}


def reject_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    reason: str,
) -> dict[str, Any]:
    if reason not in {"not_attempt", "duplicate", "other"}:
        raise AppError("bad_reason", 400, "reason must be not_attempt, duplicate, or other.")
    proposal = proposals_repo.get(conn, proposal_id)
    if proposal is None:
        raise AppError("not_found", 404, "The proposal is not here.")
    _require_video(conn, str(proposal["video_id"]))
    with immediate(conn):
        locked = proposals_repo.get(conn, proposal_id)
        if locked is None:
            raise AppError("not_found", 404, "The proposal is not here.")
        if str(locked.get("status")) != "pending":
            raise AppError("proposal_conflict", 409, "This proposal is not pending.")
        row = proposals_repo.update(conn, proposal_id, {"status": "rejected"})
        assert row is not None
        log_feedback(
            conn,
            kind="cut.reject",
            entity_type="proposal",
            entity_id=proposal_id,
            video_id=str(locked["video_id"]),
            before={
                "proposal_id": locked["id"],
                "start_frame": locked["start_frame"],
                "end_frame": locked["end_frame"],
                "status": locked["status"],
            },
            after={"status": "rejected", "reason": reason},
            model_version_id=locked.get("model_version_id"),
        )
    return row
