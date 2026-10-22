"""Video request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class VideoStages(BaseModel):
    ingest: str
    pose: str
    detect: str


class VideoCounts(BaseModel):
    pending_proposals: int
    attempts: int


class VideoOut(BaseModel):
    id: str
    boulder_id: str | None
    session_id: str | None
    original_name: str
    original_ext: str
    sha256: str
    size_bytes: int
    duration_s: float | None
    src_fps: float | None
    is_vfr: bool
    src_width: int | None
    src_height: int | None
    rotation: int | None
    codec: str | None
    recorded_at: str | None
    proxy_fps: float | None
    proxy_width: int | None
    proxy_height: int | None
    n_frames: int | None
    fps: float | None
    ingest_status: str
    pose_status: str
    detect_status: str
    review_status: str
    error: str | None
    notes: str | None
    created_at: str
    stages: VideoStages | None = None
    counts: VideoCounts | None = None

    @classmethod
    def from_row(
        cls,
        row: dict[str, Any],
        *,
        pending_proposals: int | None = None,
        attempts: int | None = None,
        include_detail: bool = False,
    ) -> VideoOut:
        fps = row.get("proxy_fps")
        if fps is None:
            fps = row.get("src_fps")
        stages = None
        counts = None
        if include_detail:
            stages = VideoStages(
                ingest=str(row["ingest_status"]),
                pose=str(row["pose_status"]),
                detect=str(row["detect_status"]),
            )
            counts = VideoCounts(
                pending_proposals=int(pending_proposals or 0),
                attempts=int(attempts or 0),
            )
        return cls(
            id=str(row["id"]),
            boulder_id=row.get("boulder_id"),
            session_id=row.get("session_id"),
            original_name=str(row["original_name"]),
            original_ext=str(row["original_ext"]),
            sha256=str(row["sha256"]),
            size_bytes=int(row["size_bytes"]),
            duration_s=row.get("duration_s"),
            src_fps=row.get("src_fps"),
            is_vfr=bool(row.get("is_vfr")),
            src_width=row.get("src_width"),
            src_height=row.get("src_height"),
            rotation=row.get("rotation"),
            codec=row.get("codec"),
            recorded_at=row.get("recorded_at"),
            proxy_fps=row.get("proxy_fps"),
            proxy_width=row.get("proxy_width"),
            proxy_height=row.get("proxy_height"),
            n_frames=row.get("n_frames"),
            fps=fps,
            ingest_status=str(row["ingest_status"]),
            pose_status=str(row["pose_status"]),
            detect_status=str(row["detect_status"]),
            review_status=str(row["review_status"]),
            error=row.get("error"),
            notes=row.get("notes"),
            created_at=str(row["created_at"]),
            stages=stages,
            counts=counts,
        )


class VideoListOut(BaseModel):
    items: list[VideoOut]
    total: int


class VideoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boulder_id: str | None = None
    session_id: str | None = None
    recorded_at: str | None = None
    notes: str | None = None
    review_status: Literal["unreviewed", "reviewed"] | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ReprocessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_stage: Literal["proxy", "pose", "detect"]


class UploadOut(BaseModel):
    video: VideoOut
    job_id: str


class JobAcceptedOut(BaseModel):
    job_id: str
