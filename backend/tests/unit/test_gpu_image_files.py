"""GPU image files match the Phase 0 pins and omit trainer stacks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "docker" / "gpu" / "Dockerfile"
ENTRYPOINT = ROOT / "docker" / "gpu" / "entrypoint.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "gpu-image.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
GPU_SCRIPTS = [
    ROOT / "scripts" / "gpu" / "lib.sh",
    ROOT / "scripts" / "gpu" / "pod_up.sh",
    ROOT / "scripts" / "gpu" / "run_job.sh",
    ROOT / "scripts" / "gpu" / "wait_job.sh",
    ROOT / "scripts" / "gpu" / "pod_down.sh",
    ROOT / "scripts" / "gpu" / "pod_ls.sh",
    ROOT / "scripts" / "gpu" / "defaults.env",
    ROOT / "scripts" / "sync_volume.sh",
    ROOT / "scripts" / "export_labels.py",
]


def test_dockerfile_pins_and_omits_trainer_stack() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:" in text
    assert "ac55d124da4882b497f732d8dfd9a702d5447a5f29d08d56da6f64f0a1eb34bc" in text
    assert "onnxruntime-gpu" in text or "requirements-gpu.txt" in text
    assert "openssh-server" in text
    assert "No PyTorch" in text
    assert "requirements-gpu.txt" in text
    assert "PIP_NO_CACHE_DIR=1" in text
    assert "pip==25.2" in text
    assert "shellcheck" in text
    assert "ssh-keygen" not in text
    assert "rm -f /etc/ssh/ssh_host_*" in text
    assert "ssh_host_*" in text
    lowered = text.lower()
    assert "torch==" not in lowered
    assert "mmpose==" not in lowered
    assert "mmcv==" not in lowered


def test_entrypoint_generates_host_keys_and_starts_sshd() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "ssh-keygen -A" in text
    assert "CC_SSH_DIR" in text
    assert "test-only override" in text
    assert "skips sshd" in text
    assert "CC_SSH_HOME" in (ROOT / "scripts" / "gpu" / "lib.sh").read_text(encoding="utf-8")
    assert "test-only override" in (ROOT / "scripts" / "gpu" / "lib.sh").read_text(encoding="utf-8")
    assert "ssh_host_*" in text
    assert "/usr/sbin/sshd" in text
    assert "cc_require_job_or_interactive" in text
    assert "cc_early_cleanup" in text
    assert "unset CC_IN_GPU_TESTS" in text
    assert text.index("unset CC_IN_GPU_TESTS") < text.index(
        "exec /opt/cc/scripts/gpu/run_job.sh"
    )
    job_exec = text.index("exec /opt/cc/scripts/gpu/run_job.sh")
    sshd = text.index("/usr/sbin/sshd")
    keys = text.index("ssh-keygen -A")
    wipe = text.index('rm -f "${ssh_dir}"/ssh_host_*')
    assert wipe < keys < sshd < job_exec


def test_ci_runs_gpu_tests_from_tmp_cc_src() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "/tmp/cc-src" in text
    assert 'pytest backend/tests -m "not macos"' in text
    assert "backend/tests/unit/test_sync_volume.py" in text
    assert "pod-layout" in text
    assert "/opt/cc/venv/bin/python" in text


def test_ci_ubuntu_sets_require_media() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "CC_REQUIRE_MEDIA=1" in text
    assert "matrix.os == 'ubuntu-24.04'" in text
    ci_job, pod_job = text.split("pod-layout:", 1)
    assert "CC_REQUIRE_MEDIA=1" in ci_job
    assert "CC_REQUIRE_MEDIA" not in pod_job
    require_step = ci_job.split("Require media on Ubuntu", 1)[1].split("Pytest unmarked", 1)[0]
    assert "ubuntu-24.04" in require_step
    assert "macos-15" not in require_step


def test_dockerfile_uses_ci_ffmpeg_pin() -> None:
    docker = DOCKERFILE.read_text(encoding="utf-8")
    ci = CI.read_text(encoding="utf-8")
    url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n7.1.5-12-g1fdbca85aa-linux64-gpl-7.1.tar.xz"
    sha = "c1e6caf48923dd8e6bc5e54d51ba70c321175b8162ae9c414c392990e72f0e79"
    assert url in docker
    assert sha in docker
    assert url in ci
    assert sha in ci


def test_dockerfile_uses_ci_shellcheck_pin() -> None:
    docker = DOCKERFILE.read_text(encoding="utf-8")
    ci = CI.read_text(encoding="utf-8")
    url = "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.x86_64.tar.xz"
    sha = "8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198"
    assert url in docker
    assert sha in docker
    assert url in ci
    assert sha in ci
    apt_pkgs = docker.split("apt-get install", 1)[-1].split("&&", 1)[0]
    assert "shellcheck" not in apt_pkgs
    assert "sudo apt-get install -y -qq shellcheck" not in ci
    assert "shellcheck-v0.11.0/shellcheck" in docker
    assert "0.11.0" in docker
    assert "0.11.0" in ci


def test_gpu_image_workflow_tags_sha_and_latest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ghcr.io" in text
    assert "climbing-coach-gpu" in text
    assert "github.sha" in text
    assert "latest" in text
    assert "docker/gpu/**" in text
    assert "requirements" in text
    assert "packages: write" in text
    assert "load: false" in text
    assert "cache-to: type=gha,mode=min" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "Free disk" in text
    assert "refs/heads/main" in text
    assert "branches: [main]" in text


def test_gpu_image_workflow_pins_actions_by_sha() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "docker/setup-buildx-action@e468171a9de216ec08956ac3ada2f0791b6bd435" in text
    assert "docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772" in text
    assert "docker/build-push-action@263435318d21b8e681c14492fe198d362a7d2c83" in text


def test_runner_files_do_not_invent_secrets() -> None:
    paths = [
        DOCKERFILE,
        WORKFLOW,
        ENTRYPOINT,
        ROOT / "README.md",
        *GPU_SCRIPTS,
    ]
    forbidden = ("rpa_", "rps_", "ghp_", "github_pat_", "https://hooks.")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains {token}"
        assert "example-secret" not in text
        assert "AKIA" not in text
