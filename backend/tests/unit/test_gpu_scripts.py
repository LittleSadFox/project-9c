"""Pod scripts enforce TTL and refuse account-key injection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
POD_UP = ROOT / "scripts" / "gpu" / "pod_up.sh"
POD_DOWN = ROOT / "scripts" / "gpu" / "pod_down.sh"
POD_LS = ROOT / "scripts" / "gpu" / "pod_ls.sh"
WAIT_JOB = ROOT / "scripts" / "gpu" / "wait_job.sh"
SYNC = ROOT / "scripts" / "sync_volume.sh"
LIB = ROOT / "scripts" / "gpu" / "lib.sh"
RUN_JOB = ROOT / "scripts" / "gpu" / "run_job.sh"
ENTRYPOINT = ROOT / "docker" / "gpu" / "entrypoint.sh"

EXPECTED_GPUS = [
    "NVIDIA L4",
    "NVIDIA RTX 2000 Ada Generation",
    "NVIDIA GeForce RTX 4090",
    "NVIDIA A100 80GB PCIe",
    "NVIDIA RTX PRO 4500 Blackwell",
    "NVIDIA RTX PRO 4000 Blackwell",
    "NVIDIA GeForce RTX 5090",
]


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
    for key in list(merged):
        if key.startswith("CC_"):
            merged.pop(key, None)
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
    assert payload["volumeInGb"] == 0
    assert payload["networkVolumeId"] == "wguvx2347m"
    assert payload["dataCenterIds"] == ["EU-RO-1"]
    assert payload["containerRegistryAuthId"] == "cmvhzigy8002b13z5y84jqc73"
    assert payload["imageName"] == "ghcr.io/littlesadfox/climbing-coach-gpu"
    gpus = payload["gpuTypeIds"]
    assert isinstance(gpus, list)
    for name in EXPECTED_GPUS:
        assert name in gpus
    assert "NVIDIA A40" not in gpus
    assert "NVIDIA RTX A5000" not in gpus


def test_pod_up_ttl_flag_overrides_default() -> None:
    result = _run(
        [str(POD_UP), "--interactive", "--ref", "deadbeef", "--ttl", "10m", "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["CC_TTL_S"] == "600"
    assert env["CC_INTERACTIVE"] == "1"
    assert "CC_JOB" not in env


def test_pod_up_refuses_zero_ttl() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef", "--ttl", "0", "--dry-run"],
    )
    assert result.returncode != 0
    assert "CC_TTL_S" in result.stderr or "TTL" in result.stderr


def test_pod_up_refuses_spot_for_on_demand_jobs() -> None:
    result = _run(
        [str(POD_UP), "--job", "eval", "--ref", "deadbeef", "--spot", "--dry-run"],
    )
    assert result.returncode != 0
    assert "spot" in result.stderr


def test_pod_up_allows_spot_for_gpu_tests() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef", "--spot", "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    assert payload["interruptible"] is True


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


def test_pod_down_rejects_invalid_id() -> None:
    result = _run([str(POD_DOWN), "bad id", "--dry-run"])
    assert result.returncode != 0
    assert "Invalid pod id" in result.stderr


def test_wait_job_dry_run_uses_volume_env() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1"},
    )
    assert result.returncode == 0, result.stderr
    assert "s3://vol-1/runs/job-1/status" in result.stdout
    assert "s3api-eu-ro-1.runpod.io" in result.stdout


def test_wait_job_dry_run_pod_id() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--pod-id", "pod-abc", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1"},
    )
    assert result.returncode == 0, result.stderr
    assert "pod_id=pod-abc" in result.stdout
    assert "GET /pods/pod-abc" in result.stdout


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
    assert not (golden / "labels" / "labels.json").exists()
    assert "s3api-eu-ro-1.runpod.io" in result.stdout


def test_run_job_uses_basic_git_auth() -> None:
    text = RUN_JOB.read_text(encoding="utf-8")
    assert "cc_git_auth_setup" in text
    assert "cc_git_auth_clear" in text
    assert "AUTHORIZATION: bearer" not in text
    assert "trap cleanup INT" in text
    assert "trap cleanup TERM" in text
    assert "set +e" in text


def test_lib_is_safe_on_bash_32_empty_arrays() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert '"${extra[@]}"' not in text
    assert '"${args[@]}"' not in text
    assert "@Q}" not in text
    assert "${JOB@Q}" not in POD_UP.read_text(encoding="utf-8")
    assert "${status@Q}" not in WAIT_JOB.read_text(encoding="utf-8")


def test_lib_keeps_account_key_off_curl_argv() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert '-H "@${hdr}"' in text
    assert "Authorization: Bearer" in text
    assert "curl" in text
    curl_lines = [line for line in text.splitlines() if "curl " in line]
    assert curl_lines
    for line in curl_lines:
        assert "RUNPOD_API_KEY" not in line


def test_lib_git_auth_is_basic_x_access_token() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert "x-access-token:" in text
    assert "AUTHORIZATION: basic" in text


def _fake_curl(tmp_path: Path, status: str, body: str) -> Path:
    script = tmp_path / "curl"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [[ -n "$out" ]]; then
  cat >"$out" <<'BODY'
{body}
BODY
fi
printf '%s' '{status}'
exit 0
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_pod_ls_fails_on_error_object(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_LS)],
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "RUNPOD_API_KEY": "broken-key",
        },
    )
    assert result.returncode != 0
    assert "no running pods" not in result.stdout
    assert "did not return an array" in result.stderr or "unauthorized" in result.stderr


def test_pod_down_fails_on_http_401(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "401", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_DOWN), "pod-example"],
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "RUNPOD_API_KEY": "broken-key",
        },
    )
    assert result.returncode != 0
    assert "terminated=" not in result.stdout
    assert "401" in result.stderr


def test_pod_ls_fails_on_http_401(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "401", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_LS)],
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "RUNPOD_API_KEY": "broken-key",
        },
    )
    assert result.returncode != 0
    assert "no running pods" not in result.stdout
    assert "401" in result.stderr


def test_terminate_self_fails_without_pod_id() -> None:
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_terminate_self",
        ],
        env={"RUNPOD_API_KEY": "pod-scoped-key"},
    )
    assert result.returncode != 0
    assert "RUNPOD_POD_ID is missing" in result.stderr


def test_run_job_trap_reaches_terminate(tmp_path: Path) -> None:
    result = _run(
        [str(RUN_JOB)],
        env={"CC_VOLUME_DIR": str(tmp_path)},
    )
    assert result.returncode != 0
    assert "CC_TTL_S" in result.stderr or "TTL" in result.stderr
    assert "RUNPOD_POD_ID is missing" in result.stderr


def test_run_job_sets_trap_before_mkdir() -> None:
    text = RUN_JOB.read_text(encoding="utf-8")
    trap_at = text.index("trap cleanup EXIT")
    require_at = text.index("cc_require_ttl")
    mkdir_at = text.index('mkdir -p "$RUN_DIR/artifacts" "$VOLUME/models"')
    assert trap_at < require_at < mkdir_at
    assert "trap cleanup INT" in text
    assert "trap cleanup TERM" in text
    assert "trap cleanup HUP" in text
    assert "set +e" in text.split("cleanup()")[1].split("cc_terminate_self")[0]


def test_entrypoint_requires_job_or_interactive() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "cc_require_job_or_interactive" in text
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && unset CC_JOB CC_INTERACTIVE && cc_require_job_or_interactive",
        ]
    )
    assert result.returncode != 0
    assert "CC_JOB" in result.stderr or "CC_INTERACTIVE" in result.stderr


def test_pods_from_response_rejects_error_object() -> None:
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_pods_from_response '{{\"error\":\"nope\"}}'",
        ]
    )
    assert result.returncode != 0
    assert "did not return an array" in result.stderr


def test_gpu_scripts_pass_shellcheck() -> None:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed")
    scripts = [
        LIB,
        POD_UP,
        RUN_JOB,
        WAIT_JOB,
        POD_DOWN,
        POD_LS,
        SYNC,
        ENTRYPOINT,
    ]
    result = subprocess.run(
        [shellcheck, "-x", *[str(path) for path in scripts]],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
