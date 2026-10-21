"""PoseEstimator protocol and the fixture backend."""

from __future__ import annotations

from typing import Protocol


class PoseEstimator(Protocol):
    """Estimate people and keypoints on one frame."""

    def estimate(self, frame: object) -> dict[str, object]: ...


class FixtureEstimator:
    """Test backend. Set CC_POSE_BACKEND=fixture to use it."""

    def estimate(self, frame: object) -> dict[str, object]:
        del frame
        return {"tracks": []}
