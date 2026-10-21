"""GPU image files match the Phase 0 pins and omit trainer stacks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "docker" / "gpu" / "Dockerfile"
WORKFLOW = ROOT / ".github" / "workflows" / "gpu-image.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_dockerfile_pins_and_omits_trainer_stack() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04" in text
    assert "onnxruntime-gpu" in text or "requirements-gpu.txt" in text
    assert "openssh-server" in text
    assert "No PyTorch" in text
    assert "requirements-gpu.txt" in text
    lowered = text.lower()
    assert "torch==" not in lowered
    assert "mmpose==" not in lowered
    assert "mmcv==" not in lowered


def test_dockerfile_uses_ci_ffmpeg_pin() -> None:
    docker = DOCKERFILE.read_text(encoding="utf-8")
    ci = CI.read_text(encoding="utf-8")
    url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n7.1.5-12-g1fdbca85aa-linux64-gpl-7.1.tar.xz"
    sha = "c1e6caf48923dd8e6bc5e54d51ba70c321175b8162ae9c414c392990e72f0e79"
    assert url in docker
    assert sha in docker
    assert url in ci
    assert sha in ci


def test_gpu_image_workflow_tags_sha_and_latest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ghcr.io" in text
    assert "climbing-coach-gpu" in text
    assert "github.sha" in text
    assert "latest" in text
    assert "docker/gpu/**" in text
    assert "requirements" in text
    assert "packages: write" in text


def test_runner_files_do_not_invent_secrets() -> None:
    paths = [
        DOCKERFILE,
        WORKFLOW,
        ROOT / "scripts" / "gpu" / "lib.sh",
        ROOT / "scripts" / "gpu" / "pod_up.sh",
        ROOT / "README.md",
    ]
    forbidden = ("rpa_", "rps_", "ghp_", "github_pat_", "https://hooks.")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains {token}"
        assert "example-secret" not in text
        assert "AKIA" not in text
