"""Pod scripts enforce TTL and refuse account-key injection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POD_UP = ROOT / "scripts" / "gpu" / "pod_up.sh"
POD_DOWN = ROOT / "scripts" / "gpu" / "pod_down.sh"
POD_LS = ROOT / "scripts" / "gpu" / "pod_ls.sh"
WAIT_JOB = ROOT / "scripts" / "gpu" / "wait_job.sh"
SYNC = ROOT / "scripts" / "sync_volume.sh"


def _payload(stdout: str) -> dict[str, object]:
    start = stdout.index("{")
    end = stdout.rindex("}")
    data = json.loads(stdout[start : end + 1])
    if not isinstance(data, dict):
        raise AssertionError("pod_up dry-run must print a JSON object")
    return data


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("RUNPOD_API_KEY", None)
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=str(ROOT),
        env=merged,
        check=False,
        capture_output=True,
        text=True,
    )


def test_pod_up_refuses_without_job_or_interactive() -> None:
    result = _run([str(POD_UP), "--ref", "abc1234", "--dry-run"])
    assert result.returncode != 0
    assert "CC_JOB" in result.stderr or "interactive" in result.stderr


def test_pod_up_refuses_job_without_ref() -> None:
    result = _run([str(POD_UP), "--job", "gpu_tests", "--dry-run"])
    assert result.returncode != 0
    assert "ref" in result.stderr


def test_pod_up_dry_run_sets_ttl_and_secret_refs() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef", "--dry-run"],
        env={"RUNPOD_API_KEY": "test-key-do-not-inject"},
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["CC_TTL_S"] == "3600"
    assert env["CC_JOB"] == "gpu_tests"
    assert env["CC_GIT_REF"] == "deadbeef"
    assert env["CC_REPO_TOKEN"] == "{{ RUNPOD_SECRET_cc_repo_token }}"
    assert env["CC_WEBHOOK_URL"] == "{{ RUNPOD_SECRET_cc_webhook_url }}"
    assert "RUNPOD_API_KEY" not in env
    assert "test-key-do-not-inject" not in result.stdout
    assert payload["cloudType"] == "SECURE"
    assert "NVIDIA GeForce RTX 4090" in payload["gpuTypeIds"]


def test_pod_up_ttl_flag_overrides_default() -> None:
    result = _run(
        [str(POD_UP), "--interactive", "--ttl", "10m", "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["CC_TTL_S"] == "600"
    assert "CC_JOB" not in payload["env"]


def test_pod_up_refuses_zero_ttl() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef", "--ttl", "0", "--dry-run"],
    )
    assert result.returncode != 0
    assert "CC_TTL_S" in result.stderr or "TTL" in result.stderr


def test_live_pod_up_refuses_without_api_key() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef"],
        env={
            "CC_RUNPOD_TEMPLATE_ID": "template-unset",
            "CC_RUNPOD_VOLUME_ID": "volume-unset",
        },
    )
    assert result.returncode != 0
    assert "RUNPOD_API_KEY" in result.stderr


def test_pod_down_and_ls_dry_run() -> None:
    down = _run([str(POD_DOWN), "pod-example", "--dry-run"])
    assert down.returncode == 0
    assert "DELETE /pods/pod-example" in down.stdout
    listed = _run([str(POD_LS), "--dry-run"])
    assert listed.returncode == 0
    assert "GET /pods" in listed.stdout


def test_wait_job_dry_run_uses_volume_env() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1"},
    )
    assert result.returncode == 0, result.stderr
    assert "s3://vol-1/runs/job-1/status" in result.stdout
    assert "s3api-eu-ro-1.runpod.io" in result.stdout


def test_sync_volume_dry_run(tmp_path: Path) -> None:
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    result = _run(
        [str(SYNC), "--dry-run"],
        env={
            "CC_GOLDEN_DIR": str(golden),
            "CC_LIBRARY_DIR": str(library),
            "CC_VOLUME_ID": "vol-1",
            "CC_VOLUME_DC": "EU-RO-1",
        },
    )
    assert result.returncode == 0, result.stderr
    assert (golden / "labels" / "labels.json").is_file()
    assert "s3api-eu-ro-1.runpod.io" in result.stdout
