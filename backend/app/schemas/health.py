"""Health response models."""

from __future__ import annotations

from pydantic import BaseModel


class FfmpegInfo(BaseModel):
    version: str
    h264_encoder: str


class OnnxInfo(BaseModel):
    providers: list[str]
    device: str


class HealthResponse(BaseModel):
    status: str
    version: str
    db: str
    ffmpeg: FfmpegInfo
    onnx: OnnxInfo
    library_free_gb: float
    dev: bool
