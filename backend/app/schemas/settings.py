"""Settings request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SettingsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    pose_mode: str | None = None
    det_every: int | None = None
    proxy_fps: float | None = None
    proxy_long_side: int | None = None
    pre_roll_s: float | None = None
    post_roll_s: float | None = None


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pose_mode: str | None = None
    det_every: int | None = Field(default=None, ge=1, le=60)
    proxy_fps: float | None = Field(default=None, gt=0, le=120)
    proxy_long_side: int | None = Field(default=None, ge=160, le=4096)
    pre_roll_s: float | None = Field(default=None, ge=0, le=30)
    post_roll_s: float | None = Field(default=None, ge=0, le=30)

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
