"""Pod scripts enforce TTL and refuse account-key injection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
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

SHA40 = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

EXPECTED_GPUS = [
    "NVIDIA L4",
    "NVIDIA RTX 2000 Ada Generation",
    "NVIDIA GeForce RTX 4090",
    "NVIDIA A100 80GB PCIe",
    "NVIDIA RTX PRO 4500 Blackwell",
    "NVIDIA RTX PRO 4000 Blackwell",
    "NVIDIA GeForce RTX 5090",
]


_SHIM_DIR: Path | None = None
_SHIM_LOG: Path | None = None

_STRIP_EXACT = {
    "WEBHOOK_URL",
    "WEBHOOK_SECRET",
    "POD_ID",
    "POD_API_KEY",
    "API_KEY",
}


def _should_strip(key: str) -> bool:
    if key.startswith("CC_") or key.startswith("RUNPOD_"):
        return True
    if key in _STRIP_EXACT:
        return True
    if "WEBHOOK" in key:
        return True
    return key.endswith(("_API_KEY", "_POD_KEY", "_POD_ID"))


def _ensure_shims() -> Path:
    global _SHIM_DIR, _SHIM_LOG
    if _SHIM_DIR is not None:
        return _SHIM_DIR
    _SHIM_DIR = Path(tempfile.mkdtemp(prefix="cc-gpu-shims-"))
    _SHIM_LOG = _SHIM_DIR / "invocations.log"
    log = _SHIM_LOG
    curl = _SHIM_DIR / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' curl "$*" >> "{log}"
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [[ -n "$out" ]]; then
  printf '%s\\n' '{{"error":"shim-blocked"}}' >"$out"
fi
printf '599'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    runpodctl = _SHIM_DIR / "runpodctl"
    runpodctl.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' runpodctl "$*" >> "{log}"
echo "ERROR: shim runpodctl blocked network" >&2
exit 1
""",
        encoding="utf-8",
    )
    runpodctl.chmod(0o755)
    git = _SHIM_DIR / "git"
    git.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' git "$*" >> "{log}"
echo "ERROR: shim git blocked network" >&2
exit 1
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    aws = _SHIM_DIR / "aws"
    aws.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' aws "$*" >> "{log}"
echo "ERROR: shim aws blocked network" >&2
exit 1
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    return _SHIM_DIR


def _payload(stdout: str) -> dict[str, object]:
    start = stdout.index("{")
    end = stdout.rindex("}")
    data = json.loads(stdout[start : end + 1])
    if not isinstance(data, dict):
        raise AssertionError("pod_up dry-run must print a JSON object")
    return data


def _isolated_env(
    env: dict[str, str] | None = None,
    *,
    bin_dir: Path | None = None,
) -> dict[str, str]:
    merged = os.environ.copy()
    for key in list(merged):
        if _should_strip(key):
            merged.pop(key, None)
    merged["CC_TERMINATE_NO_SLEEP"] = "1"
    extra = dict(env) if env else {}
    extra_path = extra.pop("PATH", None)
    path_parts: list[str] = []
    if bin_dir is not None:
        path_parts.append(str(bin_dir))
    elif extra_path:
        first, _, rest = extra_path.partition(os.pathsep)
        path_parts.append(first)
        extra_path = rest
    path_parts.append(str(_ensure_shims()))
    if extra_path:
        path_parts.append(extra_path)
    path_parts.append(merged.get("PATH", ""))
    merged["PATH"] = os.pathsep.join(part for part in path_parts if part)
    merged.update(extra)
    return merged


def _run(
    args: list[str],
    env: dict[str, str] | None = None,
    *,
    bin_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        env=_isolated_env(env, bin_dir=bin_dir),
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
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"RUNPOD_API_KEY": "test-key-do-not-inject"},
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["CC_TTL_S"] == "3600"
    assert env["CC_JOB"] == "gpu_tests"
    assert env["CC_GIT_REF"] == SHA40
    assert env["CC_REPO_TOKEN"] == "{{ RUNPOD_SECRET_cc_repo_token }}"
    assert env["CC_WEBHOOK_URL"] == "{{ RUNPOD_SECRET_cc_webhook_url }}"
    assert "RUNPOD_API_KEY" not in env
    assert "test-key-do-not-inject" not in result.stdout
    assert "GET /containerregistryauth/cmvhzigy8002b13z5y84jqc73" in result.stdout
    assert payload["name"] == result.stdout.split("job_id=")[-1].splitlines()[0]
    assert payload["cloudType"] == "SECURE"
    assert payload["volumeInGb"] == 0
    assert payload["networkVolumeId"] == "wguvx2347m"
    assert payload["dataCenterIds"] == ["EU-RO-1"]
    assert payload["containerRegistryAuthId"] == "cmvhzigy8002b13z5y84jqc73"
    assert payload["imageName"] == "ghcr.io/littlesadfox/climbing-coach-gpu:latest"
    assert "allowedCudaVersions" not in payload
    gpus = payload["gpuTypeIds"]
    assert isinstance(gpus, list)
    for name in EXPECTED_GPUS:
        assert name in gpus
    assert "NVIDIA A40" not in gpus
    assert "NVIDIA RTX A5000" not in gpus


def test_pod_up_ttl_flag_overrides_default() -> None:
    result = _run(
        [str(POD_UP), "--interactive", "--ref", SHA40, "--ttl", "10m", "--dry-run"],
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
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--ttl", "0", "--dry-run"],
    )
    assert result.returncode != 0
    assert "CC_TTL_S" in result.stderr or "TTL" in result.stderr


def test_pod_up_refuses_spot_for_on_demand_jobs() -> None:
    result = _run(
        [str(POD_UP), "--job", "eval", "--ref", SHA40, "--spot", "--dry-run"],
    )
    assert result.returncode != 0
    assert "spot" in result.stderr


def test_pod_up_allows_spot_for_gpu_tests() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--spot", "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    assert payload["interruptible"] is True


def test_live_pod_up_refuses_without_api_key() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40],
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
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1", "CC_TTL_S": "3600"},
    )
    assert result.returncode == 0, result.stderr
    assert "s3://vol-1/runs/job-1/status" in result.stdout
    assert "s3api-eu-ro-1.runpod.io" in result.stdout
    assert "timeout_s=3900" in result.stdout


def test_wait_job_refuses_without_ttl() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1"},
    )
    assert result.returncode != 0
    assert "CC_TTL_S" in result.stderr
    assert "3600" in result.stderr


def test_wait_job_dry_run_pod_id() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--pod-id", "pod-abc", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1", "CC_TTL_S": "3600"},
    )
    assert result.returncode == 0, result.stderr
    assert "pod_id=pod-abc" in result.stdout
    assert "GET /pods/pod-abc" in result.stdout
    assert "pod_down=pod-abc" in result.stdout


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


def _fake_curl_routes(tmp_path: Path, routes: dict[str, tuple[str, str]]) -> Path:
    cases = []
    for method, (status, body) in routes.items():
        cases.append(f"    {method})\n      status='{status}'\n      body='{body}'\n      ;;")
    script = tmp_path / "curl"
    script.write_text(
        f"""#!/usr/bin/env bash
method=GET
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
status="500"
body='{{"error":"unmapped"}}'
case "$method" in
{chr(10).join(cases)}
esac
if [[ -n "$out" ]]; then
  printf '%s\\n' "$body" >"$out"
fi
printf '%s' "$status"
exit 0
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


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
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "no running pods" not in result.stdout
    assert "did not return an array" in result.stderr or "unauthorized" in result.stderr


def test_pod_down_fails_on_http_401(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "401", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_DOWN), "pod-example"],
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "terminated=" not in result.stdout
    assert "401" in result.stderr


def test_pod_ls_fails_on_http_401(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "401", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_LS)],
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
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


def test_suite_with_runpod_pod_id_does_not_invoke_real_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gpu_tests on a live pod must not terminate that pod with a fake key."""
    live_id = "live-pod-from-runtime"
    live_key = "live-key-must-not-be-used"
    monkeypatch.setenv("RUNPOD_POD_ID", live_id)
    monkeypatch.setenv("RUNPOD_API_KEY", live_key)
    monkeypatch.setenv("WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.setenv("CC_WEBHOOK_URL", "https://example.invalid/cc-hook")

    sentinel = tmp_path / "real-binaries.log"
    trap = tmp_path / "trap-bin"
    trap.mkdir()
    for name in ("curl", "runpodctl"):
        script = trap / name
        script.write_text(
            f"""#!/usr/bin/env bash
printf '%s %s\\n' '{name}' "$*" >> '{sentinel}'
exit 0
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{trap}{os.pathsep}{os.environ.get('PATH', '')}")

    if _SHIM_LOG is not None and _SHIM_LOG.exists():
        _SHIM_LOG.write_text("", encoding="utf-8")

    missing = _run(
        ["bash", "-c", f"source {LIB} && cc_terminate_self"],
        env={"RUNPOD_API_KEY": "pod-scoped-key"},
    )
    assert missing.returncode != 0
    assert "RUNPOD_POD_ID is missing" in missing.stderr

    trapped = _run(
        [str(RUN_JOB)],
        env={"CC_VOLUME_DIR": str(tmp_path / "vol")},
    )
    assert trapped.returncode != 0
    assert "RUNPOD_POD_ID is missing" in trapped.stderr

    which = _run(["bash", "-c", "command -v curl; command -v runpodctl"])
    assert which.returncode == 0, which.stderr
    paths = [line.strip() for line in which.stdout.splitlines() if line.strip()]
    assert paths == [str(_SHIM_DIR / "curl"), str(_SHIM_DIR / "runpodctl")]

    assert not sentinel.exists(), f"real binaries invoked:\n{sentinel.read_text()}"
    log = ""
    if _SHIM_LOG is not None and _SHIM_LOG.exists():
        log = _SHIM_LOG.read_text(encoding="utf-8")
    assert live_id not in log
    assert live_key not in log


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


def test_pod_up_refuses_short_sha() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", "deadbeef", "--dry-run"],
    )
    assert result.returncode != 0
    assert "40-character" in result.stderr


def test_pod_up_refuses_untagged_image() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_GPU_IMAGE": "ghcr.io/littlesadfox/climbing-coach-gpu"},
    )
    assert result.returncode != 0
    assert "tag" in result.stderr


def test_pod_up_keeps_caller_volume_id() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_RUNPOD_VOLUME_ID": "from-caller"},
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    assert payload["networkVolumeId"] == "from-caller"


def test_pod_up_registry_get_refuses_on_401(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "401", '{"error":"unauthorized"}')
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40],
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "containerregistryauth" in result.stderr
    assert "pod_id=" not in result.stdout


def test_wait_job_timeout_uses_ttl_plus_margin() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1", "CC_TTL_S": "100"},
    )
    assert result.returncode == 0, result.stderr
    assert "timeout_s=400" in result.stdout


def test_wait_job_passed_does_not_exit_zero_if_pod_remains(tmp_path: Path) -> None:
    aws = tmp_path / "aws"
    aws.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "s3" && "$2" == "cp" ]]; then
  printf 'passed\\n'
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"RUNNING"}')
    result = _run(
        [str(WAIT_JOB), "job-1", "--pod-id", "pod-abc"],
        env={
            "CC_VOLUME_ID": "vol-1",
            "CC_VOLUME_DC": "EU-RO-1",
            "CC_TTL_S": "60",
            "CC_WAIT_POLL_S": "1",
            "RUNPOD_API_KEY": "broken-key",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "still exists" in result.stderr or "still present" in result.stderr


def test_early_cleanup_keeps_passed_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "job-ok"
    run_dir.mkdir(parents=True)
    (run_dir / "status").write_text("passed\n", encoding="utf-8")
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_early_cleanup",
        ],
        env={"CC_VOLUME_DIR": str(tmp_path), "CC_JOB_ID": "job-ok"},
    )
    assert (run_dir / "status").read_text(encoding="utf-8").strip() == "passed"
    assert result.returncode == 0


def test_lib_curl_calls_set_max_time() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert text.count("--max-time") >= 3
    assert "cc_run_timeout 20 runpodctl" in text
    assert "cc_print_api_error" in text


def test_pod_up_omits_allowed_cuda_by_default() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    assert "allowedCudaVersions" not in payload


def test_pod_up_allowed_cuda_opt_in() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_ALLOWED_CUDA": "12.8,12.9,13.0"},
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    assert payload["allowedCudaVersions"] == ["12.8", "12.9", "13.0"]


def test_pod_up_missing_flag_value_does_not_swallow_next_flag() -> None:
    missing_job = _run([str(POD_UP), "--job", "--ref", SHA40, "--dry-run"])
    assert missing_job.returncode != 0
    assert "--job requires a value" in missing_job.stderr
    missing_ref = _run([str(POD_UP), "--job", "gpu_tests", "--ref", "--dry-run"])
    assert missing_ref.returncode != 0
    assert "--ref requires a value" in missing_ref.stderr
    missing_ttl = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--ttl", "--dry-run"],
    )
    assert missing_ttl.returncode != 0
    assert "--ttl requires a value" in missing_ttl.stderr
    missing_gpu = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--gpu", "--spot", "--dry-run"],
    )
    assert missing_gpu.returncode != 0
    assert "--gpu requires a value" in missing_gpu.stderr


def test_pod_gone_detects_404(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "404", '{"error":"not found"}')
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_gone pod-abc"],
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "missing" in result.stdout
    assert "unknown" not in result.stderr


def test_pod_gone_detects_terminated(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"TERMINATED"}')
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_gone pod-abc"],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "TERMINATED" in result.stdout


def test_s3_cp_retries_signature_mismatch(tmp_path: Path) -> None:
    aws = tmp_path / "aws"
    state = tmp_path / "aws-state"
    aws.write_text(
        f"""#!/usr/bin/env bash
n=0
if [[ -f "{state}" ]]; then
  n="$(cat "{state}")"
fi
n=$((n + 1))
printf '%s' "$n" > "{state}"
if [[ "$n" -lt 3 ]]; then
  echo "SignatureDoesNotMatch" >&2
  exit 1
fi
printf 'passed\\n'
exit 0
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_cp_stdout s3://vol/runs/job-1/status EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout
    assert state.read_text(encoding="utf-8") == "3"


def test_s3_cp_retries_headobject_403_forbidden(tmp_path: Path) -> None:
    aws = tmp_path / "aws"
    state = tmp_path / "aws-state"
    live_err = "An error occurred (403) when calling the HeadObject operation: Forbidden"
    aws.write_text(
        f"""#!/usr/bin/env bash
n=0
if [[ -f "{state}" ]]; then
  n="$(cat "{state}")"
fi
n=$((n + 1))
printf '%s' "$n" > "{state}"
if [[ "$n" -lt 3 ]]; then
  echo "{live_err}" >&2
  exit 1
fi
printf 'passed\\n'
exit 0
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_cp_stdout s3://vol/runs/job-1/status EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout
    assert state.read_text(encoding="utf-8") == "3"


def test_run_job_logs_redacted_clone_stderr(tmp_path: Path) -> None:
    token = "secret-repo-token-value"
    git = tmp_path / "git"
    git.write_text(
        f"""#!/usr/bin/env bash
echo "fatal: could not read Username for https://github.com with {token}" >&2
exit 1
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-clone",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": token,
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    log = tmp_path / "vol" / "runs" / "job-clone" / "log.txt"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert token not in text
    assert token not in result.stdout
    assert token not in result.stderr
    assert "REDACTED" in text
    assert "fatal:" in text


def test_interactive_sigterm_is_stopped_not_failed(tmp_path: Path) -> None:
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_early_cleanup",
        ],
        env={
            "CC_VOLUME_DIR": str(tmp_path),
            "CC_JOB_ID": "job-int",
            "CC_INTERACTIVE": "1",
            "CC_INTERACTIVE_READY": "1",
        },
    )
    status = tmp_path / "runs" / "job-int" / "status"
    assert status.is_file()
    assert status.read_text(encoding="utf-8").strip() == "stopped"
    assert result.returncode == 0
    interactive = LIB.read_text(encoding="utf-8").split("CC_INTERACTIVE_READY")[1]
    assert "exit 0" in interactive.split("cc_terminate_self")[1][:80]


def test_failed_status_rewrite_does_not_ping_webhook(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "job-fail"
    run_dir.mkdir(parents=True)
    (run_dir / "status").write_text("failed\n", encoding="utf-8")
    hits = tmp_path / "webhook.log"
    curl = tmp_path / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{hits}"
printf '200'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_early_cleanup",
        ],
        env={
            "CC_VOLUME_DIR": str(tmp_path),
            "CC_JOB_ID": "job-fail",
            "CC_WEBHOOK_URL": "https://example.invalid/hook",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0
    assert run_dir.joinpath("status").read_text(encoding="utf-8").strip() == "failed"
    assert not hits.exists()


def test_pod_ls_exits_3_when_pods_exist(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '[{"id":"pod-1","name":"n","desiredStatus":"RUNNING"}]')
    result = _run(
        [str(POD_LS)],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode == 3
    assert "pod-1" in result.stdout
    assert "no running pods" not in result.stdout
    assert "no pods" not in result.stdout


def test_run_job_skips_finished_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "job-done"
    run_dir.mkdir(parents=True)
    (run_dir / "status").write_text("passed\n", encoding="utf-8")
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-done",
            "CC_TTL_S": "60",
        },
    )
    assert "already passed" in result.stdout
    assert "Clone" not in result.stdout
    assert "RUNPOD_POD_ID is missing" in result.stderr


def test_entrypoint_early_failure_writes_status(tmp_path: Path) -> None:
    script = tmp_path / "entrypoint.sh"
    text = ENTRYPOINT.read_text(encoding="utf-8")
    patched = text.replace('LIB="/opt/cc/scripts/gpu/lib.sh"', f'LIB="{LIB}"')
    script.write_text(patched, encoding="utf-8")
    script.chmod(0o755)
    result = _run(
        [str(script)],
        env={"CC_VOLUME_DIR": str(tmp_path), "CC_JOB_ID": "job-early", "CC_JOB": "gpu_tests"},
    )
    assert result.returncode != 0
    status = tmp_path / "runs" / "job-early" / "status"
    assert status.is_file()
    assert status.read_text(encoding="utf-8").strip() == "failed"
    assert "RUNPOD_POD_ID is missing" in result.stderr


def test_wait_job_pod_id_requires_value() -> None:
    result = _run(
        [str(WAIT_JOB), "job-1", "--pod-id", "--dry-run"],
        env={"CC_VOLUME_ID": "vol-1", "CC_VOLUME_DC": "EU-RO-1", "CC_TTL_S": "60"},
    )
    assert result.returncode != 0
    assert "--pod-id requires a value" in result.stderr


def test_wait_job_timeout_must_be_positive() -> None:
    ok = _run(
        [str(WAIT_JOB), "job-1", "--dry-run"],
        env={
            "CC_VOLUME_ID": "vol-1",
            "CC_VOLUME_DC": "EU-RO-1",
            "CC_WAIT_TIMEOUT_S": "45",
        },
    )
    assert ok.returncode == 0, ok.stderr
    assert "timeout_s=45" in ok.stdout
    for value in ("0", "-1", "10s", "1.5", "abc"):
        result = _run(
            [str(WAIT_JOB), "job-1", "--dry-run"],
            env={
                "CC_VOLUME_ID": "vol-1",
                "CC_VOLUME_DC": "EU-RO-1",
                "CC_WAIT_TIMEOUT_S": value,
            },
        )
        assert result.returncode != 0, value
        assert "CC_WAIT_TIMEOUT_S must be a positive integer" in result.stderr


def test_pod_down_exited_after_failed_delete_is_not_gone(tmp_path: Path) -> None:
    _fake_curl_routes(
        tmp_path,
        {
            "DELETE": ("500", '{"error":"busy"}'),
            "GET": ("200", '{"id":"pod-abc","desiredStatus":"EXITED"}'),
        },
    )
    result = _run(
        [str(POD_DOWN), "pod-abc"],
        env={"RUNPOD_API_KEY": "broken-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "terminated=" not in result.stdout
    assert "still present" in result.stderr


def test_pod_gone_treats_exited_as_early_exit(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"EXITED"}')
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_gone pod-abc"],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "EXITED" in result.stdout


def test_pod_deleted_rejects_exited(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"EXITED"}')
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_deleted pod-abc"],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert result.returncode != 0


def test_pod_deleted_accepts_404_or_terminated(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "404", '{"error":"not found"}')
    missing = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_deleted pod-abc"],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert missing.returncode == 0, missing.stderr
    assert "missing" in missing.stdout
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"TERMINATED"}')
    gone = _run(
        ["bash", "-c", f"source {LIB} && cc_pod_deleted pod-abc"],
        env={"RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    assert gone.returncode == 0, gone.stderr
    assert "TERMINATED" in gone.stdout


def test_run_job_fails_fast_without_repo_token(tmp_path: Path) -> None:
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-notoken",
            "CC_TTL_S": "60",
        },
    )
    assert result.returncode != 0
    assert "CC_REPO_TOKEN is empty" in result.stderr
    log = tmp_path / "runs" / "job-notoken" / "log.txt"
    status = tmp_path / "runs" / "job-notoken" / "status"
    metrics = json.loads(
        (tmp_path / "runs" / "job-notoken" / "metrics.json").read_text(encoding="utf-8")
    )
    assert log.is_file()
    assert "CC_REPO_TOKEN is empty" in log.read_text(encoding="utf-8")
    assert status.read_text(encoding="utf-8").strip() == "failed"
    assert metrics["error"] == "CC_REPO_TOKEN is empty"
    assert "Clone" not in log.read_text(encoding="utf-8")


def test_run_job_empty_token_pings_webhook(tmp_path: Path) -> None:
    hits = tmp_path / "webhook.log"
    curl = tmp_path / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{hits}"
printf '200'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-hook",
            "CC_TTL_S": "60",
            "CC_WEBHOOK_URL": "https://example.invalid/hook",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert hits.is_file(), result.stderr
    body = hits.read_text(encoding="utf-8")
    assert "example.invalid/hook" in body
    assert "failed" in body
    status = tmp_path / "vol" / "runs" / "job-hook" / "status"
    assert status.read_text(encoding="utf-8").strip() == "failed"


def test_run_job_unresolved_token_pings_webhook(tmp_path: Path) -> None:
    hits = tmp_path / "webhook.log"
    curl = tmp_path / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{hits}"
printf '200'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-unresolved",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "{{ RUNPOD_SECRET_cc_repo_token }}",
            "CC_WEBHOOK_URL": "https://example.invalid/hook",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "CC_REPO_TOKEN was not resolved" in result.stderr
    assert "CC_REPO_TOKEN is empty" not in result.stderr
    log = tmp_path / "vol" / "runs" / "job-unresolved" / "log.txt"
    assert "CC_REPO_TOKEN was not resolved" in log.read_text(encoding="utf-8")
    assert "CC_REPO_TOKEN is empty" not in log.read_text(encoding="utf-8")
    assert hits.is_file(), result.stderr
    body = hits.read_text(encoding="utf-8")
    assert "example.invalid/hook" in body
    assert "failed" in body
    status = tmp_path / "vol" / "runs" / "job-unresolved" / "status"
    assert status.read_text(encoding="utf-8").strip() == "failed"


def test_run_logged_streams_before_exit(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    token = "StreamTokenSecret"
    cmd = tmp_path / "slow.sh"
    cmd.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'first-line {token}\\n'\n"
        "sleep 30\n"
        "printf 'second-line\\n'\n",
        encoding="utf-8",
    )
    cmd.chmod(0o755)
    proc = subprocess.Popen(
        ["bash", "-c", f"source {LIB} && cc_run_logged --wait {cmd}"],
        cwd=str(ROOT),
        env=_isolated_env({"CC_REPO_TOKEN": token, "CC_RUN_LOG": str(log)}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 8
    seen = ""
    while time.time() < deadline:
        if log.is_file():
            seen = log.read_text(encoding="utf-8")
            if "first-line" in seen:
                break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    else:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("log was not streamed before the command exited")
    assert "first-line" in seen
    assert token not in seen
    assert "REDACTED" in seen
    assert "second-line" not in seen
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_run_job_rerun_after_clone_reaches_ml_jobs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    git = tmp_path / "git"
    git.write_text(
        f"""#!/usr/bin/env bash
dest=""
if [[ "$1" == "init" ]]; then
  dest="$2"
elif [[ "$1" == "-C" ]]; then
  dest="$2"
fi
if [[ -n "$dest" ]]; then
  mkdir -p "$dest/scripts/gpu" "$dest/backend"
  cp "{RUN_JOB}" "$dest/scripts/gpu/run_job.sh"
  cp "{LIB}" "$dest/scripts/gpu/lib.sh"
  chmod +x "$dest/scripts/gpu/run_job.sh"
  for name in requirements-gpu.txt requirements-dev.txt requirements-nodeps.txt; do
    printf '# pin\\n' > "$dest/backend/$name"
  done
fi
exit 0
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    py = tmp_path / "python3"
    py.write_text(
        """#!/usr/bin/env bash
if [[ " $* " == *" -m pip "* ]]; then
  exit 0
fi
if [[ " $* " == *" -m ml.jobs "* ]]; then
  echo "ml.jobs reached"
  exit 0
fi
exec /usr/bin/python3 "$@"
""",
        encoding="utf-8",
    )
    py.chmod(0o755)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-rerun",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "clone-then-clear-token",
            "CC_SRC_DIR": str(src),
        },
        bin_dir=tmp_path,
    )
    log = tmp_path / "vol" / "runs" / "job-rerun" / "log.txt"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert result.returncode == 0, result.stderr + text
    assert "CC_REPO_TOKEN is empty" not in result.stderr
    assert "CC_REPO_TOKEN is empty" not in text
    assert "ml.jobs reached" in text
    status = tmp_path / "vol" / "runs" / "job-rerun" / "status"
    assert status.read_text(encoding="utf-8").strip() == "passed"


def test_exit_0_trap_runpodctl_fail_falls_back_to_rest(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-abc"}')
    runpodctl = tmp_path / "runpodctl"
    runpodctl.write_text(
        "#!/usr/bin/env bash\necho ctl-fail >&2\nexit 1\n",
        encoding="utf-8",
    )
    runpodctl.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && trap 'cc_terminate_self' EXIT && exit 0",
        ],
        env={"RUNPOD_POD_ID": "pod-abc", "RUNPOD_API_KEY": "ok-key"},
        bin_dir=tmp_path,
    )
    combined = result.stdout + result.stderr
    assert "terminate ok via curl" in combined
    assert "terminate ok via runpodctl" not in combined
    assert "runpodctl failed" in combined
    assert "ctl-fail" in combined


def test_run_logged_wait_preserves_exit_code() -> None:
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_run_logged --wait bash -c 'echo hi; exit 3'",
        ]
    )
    assert result.returncode == 3
    assert "hi" in result.stdout


def test_run_job_records_ml_jobs_exit_code(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "backend").mkdir(parents=True)
    for name in (
        "requirements-gpu.txt",
        "requirements-dev.txt",
        "requirements-nodeps.txt",
    ):
        (src / "backend" / name).write_text("# pin\n", encoding="utf-8")
    py = tmp_path / "python3"
    py.write_text(
        """#!/usr/bin/env bash
if [[ " $* " == *" -m pip "* ]]; then
  exit 0
fi
if [[ " $* " == *" -m ml.jobs "* ]]; then
  echo "pytest failed: 3 failed"
  exit 7
fi
exec /usr/bin/python3 "$@"
""",
        encoding="utf-8",
    )
    py.chmod(0o755)
    text = RUN_JOB.read_text(encoding="utf-8")
    assert "ec=0" in text
    assert "|| ec=$?" in text
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-ec",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "tok",
            "CC_RUN_JOB_READY": "1",
            "CC_SRC_DIR": str(src),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    metrics = json.loads(
        (tmp_path / "vol" / "runs" / "job-ec" / "metrics.json").read_text(encoding="utf-8")
    )
    assert metrics["exit_code"] == 7
    assert metrics["status"] == "failed"
    status = tmp_path / "vol" / "runs" / "job-ec" / "status"
    assert status.read_text(encoding="utf-8").strip() == "failed"
    log = tmp_path / "vol" / "runs" / "job-ec" / "log.txt"
    assert "pytest failed" in log.read_text(encoding="utf-8")


def test_redact_covers_token_b64_and_header_case(tmp_path: Path) -> None:
    import base64

    token = "Fake*Token?[x]"
    b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    log = tmp_path / "log.txt"
    logged = (
        f'printf "stdout {token}\\n"; '
        f'printf "authorization: basic {b64}\\n" >&2; '
        f'printf "AUTHORIZATION: BASIC {b64}\\n"; '
        f'printf "{b64}\\n"; '
        f'printf "[authorization: basic {b64}]\\n"'
    )
    result = _run(
        [
            "bash",
            "-c",
            f"""
source {LIB}
export CC_REPO_TOKEN='{token}'
export CC_RUN_LOG='{log}'
cc_git_auth_setup
cc_run_logged bash -c '{logged}'
""",
        ]
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr + log.read_text(encoding="utf-8")
    assert token not in combined
    assert b64 not in combined
    assert "authorization: basic redacted" in combined.lower()
    assert "[authorization: basic REDACTED]" in combined


def test_git_sanitize_unsets_trace_and_sets_prompt(tmp_path: Path) -> None:
    git = tmp_path / "git"
    seen = tmp_path / "env.txt"
    git.write_text(
        f"""#!/usr/bin/env bash
env | grep -E 'GIT_TRACE|GIT_CURL_VERBOSE|GIT_TERMINAL_PROMPT' > "{seen}" || true
exit 0
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_run_logged git status",
        ],
        env={
            "GIT_TRACE": "1",
            "GIT_TRACE_CURL": "1",
            "GIT_CURL_VERBOSE": "1",
            "GIT_TRACE_PACKET": "1",
            "GIT_TRACE_REDACT": "0",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    env_text = seen.read_text(encoding="utf-8")
    assert "GIT_TERMINAL_PROMPT=0" in env_text
    assert "GIT_TRACE_REDACT=1" in env_text
    assert "GIT_TRACE=" not in env_text.replace("GIT_TRACE_REDACT=1", "")
    assert "GIT_CURL_VERBOSE" not in env_text


def test_allowed_cuda_rejects_invalid_json() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_ALLOWED_CUDA": "[13.1"},
    )
    assert result.returncode != 0
    assert "CC_ALLOWED_CUDA" in result.stderr
    assert "CC_TTL_S" not in result.stderr or "missing CC_TTL_S" not in result.stderr


def test_allowed_cuda_rejects_out_of_enum() -> None:
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_ALLOWED_CUDA": "13.1,13.2"},
    )
    assert result.returncode != 0
    assert "CC_ALLOWED_CUDA" in result.stderr


def test_entrypoint_sleeps_in_background() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "sleep 3600 &" in text
    assert "wait $!" in text


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
