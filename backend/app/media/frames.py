"""FrameReader over a proxy video. Uses OpenCV."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


class FrameError(RuntimeError):
    """Raised when the proxy cannot be opened or a frame is missing."""


class FrameReader:
    """Read proxy frames in order. Check the frame count against the database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise FrameError(f"The proxy cannot be opened: {self.path}")
        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> FrameReader:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _cap_or_raise(self) -> cv2.VideoCapture:
        if self._cap is None:
            raise FrameError("FrameReader is closed.")
        return self._cap

    @property
    def n_frames(self) -> int:
        return int(self._cap_or_raise().get(cv2.CAP_PROP_FRAME_COUNT))

    @property
    def fps(self) -> float:
        return float(self._cap_or_raise().get(cv2.CAP_PROP_FPS) or 0.0)

    @property
    def size(self) -> tuple[int, int]:
        cap = self._cap_or_raise()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return width, height

    def check_count(self, expected: int | None) -> int:
        """Compare the container frame count to the stored n_frames."""
        actual = self.n_frames
        if actual <= 0:
            raise FrameError(f"The proxy has no frames: {self.path}")
        if expected is not None and expected > 0 and actual != int(expected):
            raise FrameError(f"Proxy frame count is {actual}, expected {expected}.")
        return actual

    def read(self, index: int) -> np.ndarray:
        cap = self._cap_or_raise()
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(index))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise FrameError(f"Cannot read frame {index} from {self.path}.")
        return frame

    def iter_frames(self) -> Iterator[tuple[int, np.ndarray]]:
        cap = self._cap_or_raise()
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0.0)
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            yield index, frame
            index += 1
