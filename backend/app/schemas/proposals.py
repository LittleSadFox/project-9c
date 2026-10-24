"""Proposal review payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.attempts import AttemptOut


class ProposalOut(BaseModel):
    id: str
    start_frame: int
    end_frame: int
    outcome_guess: str | None = None
    confidence: float | None = None
    model_version: str | None = None
    status: str
    attempt_id: str | None = None


class ProposalAcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    outcome: Literal["send", "fall", "unknown"] | None = None


class ProposalAcceptOut(BaseModel):
    attempt: AttemptOut
    job_id: str | None = None


class ProposalBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1)


class ProposalBatchOut(BaseModel):
    items: list[ProposalAcceptOut]
    total: int


class ProposalRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["not_attempt", "duplicate", "other"]
