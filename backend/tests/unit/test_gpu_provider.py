"""CUDA session check. Skips on machines without CUDAExecutionProvider."""

from __future__ import annotations

import pytest

from ml.jobs import check_cuda_session


@pytest.mark.gpu
def test_tiny_model_runs_on_cuda_execution_provider() -> None:
    result = check_cuda_session(require_cuda=True)
    assert result["used_cuda"] is True
    assert result["session_providers"][0] == "CUDAExecutionProvider"
