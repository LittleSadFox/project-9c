"""Pod scripts enforce TTL and refuse account-key injection."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
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
    nvidia = _SHIM_DIR / "nvidia-smi"
    nvidia.write_text(
        f"""#!/usr/bin/env bash
printf '%s %s\\n' nvidia-smi "$*" >> "{log}"
echo "ERROR: shim nvidia-smi blocked GPU" >&2
exit 1
""",
        encoding="utf-8",
    )
    nvidia.chmod(0o755)
    return _SHIM_DIR


def _payload(stdout: str) -> dict[str, object]:
    start = stdout.index("{")
    end = stdout.rindex("}")
    data = json.loads(stdout[start : end + 1])
    if not isinstance(data, dict):
        raise AssertionError("pod_up dry-run must print a JSON object")
    return data


_BASETEMP: Path | None = None
_ISOLATION_ROOT: Path | None = None
_TMP_CC_SRC_DIRS: list[Path] = []


@pytest.fixture(autouse=True)
def _cc_isolation_root(tmp_path_factory: pytest.TempPathFactory) -> None:
    global _BASETEMP, _ISOLATION_ROOT
    _BASETEMP = Path(tmp_path_factory.getbasetemp()).resolve()
    _ISOLATION_ROOT = tmp_path_factory.mktemp("cc-isolate")
    created = _TMP_CC_SRC_DIRS
    created.clear()
    yield
    for path in created:
        shutil.rmtree(path, ignore_errors=True)
    created.clear()
    _ISOLATION_ROOT = None
    _BASETEMP = None


def _job_dirs(tmp_path: Path, src: Path | None = None) -> dict[str, str]:
    if src is None:
        src = Path(tempfile.mkdtemp(prefix="cc-src-", dir="/tmp"))
        _TMP_CC_SRC_DIRS.append(src)
    else:
        src.mkdir(parents=True, exist_ok=True)
    library = tmp_path / "cc-lib"
    library.mkdir(parents=True, exist_ok=True)
    return {"CC_SRC_DIR": str(src), "CC_LIBRARY_DIR": str(library)}


def _webhook_curl(tmp_path: Path) -> Path:
    hits = tmp_path / "webhook.log"
    curl = tmp_path / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf 'argv=%s\\n' "$*" >> "{hits}"
url=""
body=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      url="$(sed -n 's/^url = \"\\(.*\\)\"$/\\1/p' "$2")"
      shift 2
      ;;
    -d)
      body="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'url=%s body=%s\\n' "$url" "$body" >> "{hits}"
printf '200'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return hits


_FORBIDDEN_JOB_DIRS = {
    "/tmp/climbing-coach",
    "/tmp/climbing-coach/",
    "/tmp/cc-library",
    "/workspace",
}


def _is_tmp_cc_src(resolved: Path) -> bool:
    tmp_root = Path("/tmp").resolve()
    if resolved.parent != tmp_root:
        return False
    if resolved.name == "cc-src":
        return False
    return bool(re.fullmatch(r"cc-src-[A-Za-z0-9._-]+", resolved.name))


def _require_isolated_job_dirs(extra: dict[str, str]) -> dict[str, str]:
    if _ISOLATION_ROOT is None or _BASETEMP is None:
        raise AssertionError("pytest isolation root is not bound")
    root = _ISOLATION_ROOT
    extra.setdefault("CC_SRC_DIR", str(root / "cc-src"))
    extra.setdefault("CC_LIBRARY_DIR", str(root / "cc-lib"))
    extra.setdefault("CC_VOLUME_DIR", str(root / "cc-vol"))
    extra.setdefault("CC_SSH_DIR", str(root / "ssh"))
    extra.setdefault("CC_SSH_HOME", str(root / "ssh-home"))
    for key in (
        "CC_SRC_DIR",
        "CC_LIBRARY_DIR",
        "CC_VOLUME_DIR",
        "CC_SSH_DIR",
        "CC_SSH_HOME",
    ):
        raw = extra[key]
        if not raw or raw.rstrip("/") in {p.rstrip("/") for p in _FORBIDDEN_JOB_DIRS}:
            raise AssertionError(f"{key} must be an isolated tmp_path directory")
        resolved = Path(raw).resolve()
        home = Path.home().resolve()
        if resolved == Path("/") or resolved == home:
            raise AssertionError(f"{key} must not be / or HOME")
        repo = ROOT.resolve()
        if resolved == repo or repo.is_relative_to(resolved):
            raise AssertionError(f"{key} must not be the live checkout or a parent of it")
        under_base = resolved.is_relative_to(_BASETEMP)
        if not under_base and not (key == "CC_SRC_DIR" and _is_tmp_cc_src(resolved)):
            raise AssertionError(f"{key} must be under pytest basetemp")
        Path(raw).mkdir(parents=True, exist_ok=True)
    return extra


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
    extra = _require_isolated_job_dirs(extra)
    if extra.get("CC_PYTHON"):
        resolved = Path(extra["CC_PYTHON"]).resolve()
        if "/opt/cc/" in str(resolved):
            raise AssertionError("CC_PYTHON must not be /opt/cc")
        if _BASETEMP is not None and not resolved.is_relative_to(_BASETEMP):
            raise AssertionError("CC_PYTHON must be under pytest basetemp")
    else:
        if _ISOLATION_ROOT is None:
            raise AssertionError("pytest isolation root is not bound")
        stub = _ISOLATION_ROOT / "cc-python"
        if not stub.exists():
            stub.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'ERROR: isolated CC_PYTHON stub' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
        extra["CC_PYTHON"] = str(stub)
    merged.update(extra)
    return merged


_RUN_TIMEOUT_S = 30


def _run(
    args: list[str],
    env: dict[str, str] | None = None,
    *,
    bin_dir: Path | None = None,
    cwd: str | Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    extra = dict(env) if env else {}
    _require_isolated_job_dirs(extra)
    for arg in args:
        if "/opt/cc/" in str(arg) or str(arg).rstrip("/") == "/opt/cc":
            raise AssertionError(f"tests must not exec /opt/cc: {arg}")
    limit = _RUN_TIMEOUT_S if timeout is None else timeout
    try:
        return subprocess.run(
            args,
            cwd=str(cwd or ROOT),
            env=_isolated_env(env, bin_dir=bin_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=limit,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"_run timed out after {limit}s: {args}") from exc


def _wipe(
    tmp_path: Path,
    target: str,
    *,
    env: dict[str, str] | None = None,
    script_dir: str | None = None,
    volume: str | None = None,
    scratch: str | None = None,
    wipe: bool = False,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    extra = {
        "CC_VOLUME_DIR": str(tmp_path / "cc-vol"),
        "CC_LIBRARY_DIR": str(tmp_path / "cc-lib"),
    }
    if env:
        extra.update(env)
    cmd = "cc_safe_wipe_dir" if wipe else "cc_assert_safe_wipe_dir"
    sd = script_dir or str(tmp_path / "fake-repo" / "scripts" / "gpu")
    Path(sd).mkdir(parents=True, exist_ok=True)
    vol = volume or extra.get("CC_VOLUME_DIR") or str(tmp_path / "cc-vol")
    lib = scratch or extra.get("CC_LIBRARY_DIR") or str(tmp_path / "cc-lib")
    Path(vol).mkdir(parents=True, exist_ok=True)
    Path(lib).mkdir(parents=True, exist_ok=True)
    return _run(
        [
            "bash",
            "-c",
            f'source {LIB} && {cmd} "$1" "$2" "$3" "$4"',
            "wipe",
            target,
            sd,
            vol,
            lib,
        ],
        env=extra,
        cwd=cwd or tmp_path,
    )


@pytest.fixture
def tmp_cc_src() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="cc-src-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _fake_aws_get_object(
    tmp_path: Path,
    *,
    body: str = "passed\n",
    metrics_body: str | None = None,
    fail_first: int = 0,
    fail_msg: str = "SignatureDoesNotMatch",
    expected_bucket: str = "vol",
    expected_keys: tuple[str, ...] = ("runs/job-1/status", "runs/job-1/metrics.json"),
    expected_region: str = "EU-RO-1",
    expected_endpoint: str = "https://s3api-eu-ro-1.runpod.io",
) -> Path:
    aws = tmp_path / "aws"
    keys = " ".join(expected_keys)
    body_file = tmp_path / "aws-body"
    body_file.write_text(body, encoding="utf-8")
    metrics_file = tmp_path / "aws-metrics"
    metrics_file.write_text(metrics_body if metrics_body is not None else body, encoding="utf-8")
    aws.write_text(
        f"""#!/usr/bin/env bash
[[ "$1" == "s3api" && "$2" == "get-object" ]] || {{
  echo "expected s3api get-object" >&2
  exit 1
}}
shift 2
bucket=""
key=""
region=""
endpoint=""
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket) bucket="$2"; shift 2 ;;
    --key) key="$2"; shift 2 ;;
    --region) region="$2"; shift 2 ;;
    --endpoint-url) endpoint="$2"; shift 2 ;;
    --profile) shift 2 ;;
    *)
      out="$1"
      shift
      ;;
  esac
done
if [[ "$bucket" != "{expected_bucket}" ]]; then
  echo "unexpected aws bucket=$bucket" >&2
  exit 1
fi
if [[ "$region" != "{expected_region}" || "$endpoint" != "{expected_endpoint}" ]]; then
  echo "unexpected aws region=$region endpoint=$endpoint" >&2
  exit 1
fi
ok=0
for allowed in {keys}; do
  if [[ "$key" == "$allowed" ]]; then
    ok=1
  fi
done
if [[ "$ok" != "1" ]]; then
  echo "unexpected aws key=$key" >&2
  exit 1
fi
n=0
state="{tmp_path}/aws-state"
if [[ -f "$state" ]]; then
  n="$(cat "$state")"
fi
n=$((n + 1))
printf '%s' "$n" > "$state"
if [[ "$n" -le {fail_first} ]]; then
  echo "{fail_msg}" >&2
  exit 1
fi
if [[ -z "$out" || "$out" == "-" ]]; then
  echo "missing get-object outfile" >&2
  exit 1
fi
if [[ "$key" == *metrics.json ]]; then
  cat "{metrics_file}" > "$out"
else
  cat "{body_file}" > "$out"
fi
exit 0
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    return aws


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
    assert gpus == EXPECTED_GPUS
    assert "NVIDIA A40" not in gpus
    assert "NVIDIA RTX A5000" not in gpus
    assert "NVIDIA RTX PRO 4500 Blackwell" not in gpus
    assert "NVIDIA RTX PRO 4000 Blackwell" not in gpus
    assert "NVIDIA GeForce RTX 5090" not in gpus


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
        env={"CC_VOLUME_DIR": str(tmp_path), **_job_dirs(tmp_path)},
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
        env={"CC_VOLUME_DIR": str(tmp_path / "vol"), **_job_dirs(tmp_path)},
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
    _fake_aws_get_object(
        tmp_path,
        body="passed\n",
        metrics_body='{\n  "job": "gpu_tests",\n  "status": "passed"\n}\n',
        expected_bucket="vol-1",
    )
    _fake_curl(tmp_path, "200", '{"id":"pod-abc","desiredStatus":"RUNNING"}')
    result = _run(
        [str(WAIT_JOB), "job-1", "--pod-id", "pod-abc"],
        env={
            "CC_VOLUME_ID": "vol-1",
            "CC_VOLUME_DC": "EU-RO-1",
            "CC_TTL_S": "60",
            "CC_WAIT_TIMEOUT_S": "20",
            "CC_WAIT_POLL_S": "1",
            "RUNPOD_API_KEY": "broken-key",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "still exists" in result.stderr or "still present" in result.stderr
    metrics_lines = [line for line in result.stdout.splitlines() if line.startswith("metrics=")]
    assert metrics_lines
    assert all("\n" not in line for line in metrics_lines)
    assert '"job":"gpu_tests"' in metrics_lines[0]


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
    _fake_aws_get_object(tmp_path, fail_first=2)
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
    assert (tmp_path / "aws-state").read_text(encoding="utf-8") == "3"


def test_s3_cp_retries_headobject_403_forbidden(tmp_path: Path) -> None:
    live_err = "An error occurred (403) when calling the HeadObject operation: Forbidden"
    _fake_aws_get_object(tmp_path, fail_first=2, fail_msg=live_err)
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
    assert (tmp_path / "aws-state").read_text(encoding="utf-8") == "3"
    assert "SignatureDoesNotMatch" not in result.stderr
    assert result.stderr.count("ERROR: S3 get-object") == 0


def test_s3_get_object_summarizes_retry_failure(tmp_path: Path) -> None:
    _fake_aws_get_object(tmp_path, fail_first=4)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_cp_stdout s3://vol/runs/job-1/status EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert result.stderr.count("ERROR: S3 get-object") == 1
    assert "after 4 attempts" in result.stderr
    assert "code=SignatureDoesNotMatch" in result.stderr
    assert "key=runs/job-1/status" in result.stderr
    assert result.stderr.count("code=SignatureDoesNotMatch") == 1


def test_s3_get_object_logs_first_line_on_nonretry(tmp_path: Path) -> None:
    _fake_aws_get_object(
        tmp_path,
        fail_first=1,
        fail_msg="An error occurred (InvalidAccessKeyId) when calling GetObject: nope",
    )
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_cp_stdout s3://vol/runs/job-1/status EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert result.stderr.count("ERROR: S3 get-object") == 1
    assert "after 4 attempts" not in result.stderr
    assert "code=InvalidAccessKeyId" in result.stderr
    assert "key=runs/job-1/status" in result.stderr
    assert "nope" in result.stderr


def test_s3_uri_parts_require_bucket_and_key() -> None:
    ok = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_uri_parts s3://vol/runs/job-1/status",
        ]
    )
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.splitlines() == ["vol", "runs/job-1/status"]
    for uri in ("s3://vol", "s3://", "http://vol/key", "vol/key"):
        bad = _run(
            ["bash", "-c", f"source {LIB} && cc_s3_uri_parts {uri}"],
        )
        assert bad.returncode != 0, uri
        assert "s3://bucket/key" in bad.stderr


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
            **_job_dirs(tmp_path),
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
            f"source {LIB} && cc_early_cleanup && echo CONTINUED",
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
    assert "CONTINUED" not in result.stdout
    assert result.returncode != 0
    assert "terminate failed after interactive stop" in result.stderr
    assert "RUNPOD_POD_ID is missing" in result.stderr


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
            **_job_dirs(tmp_path),
        },
    )
    assert "already passed" in result.stdout
    assert "Clone" not in result.stdout
    assert "RUNPOD_POD_ID is missing" in result.stderr


def test_entrypoint_early_failure_writes_status(tmp_path: Path) -> None:
    stub_job = tmp_path / "run_job.sh"
    stub_job.write_text("#!/usr/bin/env bash\necho STUB_JOB\nexit 1\n", encoding="utf-8")
    stub_job.chmod(0o755)
    nvidia = tmp_path / "nvidia-smi"
    nvidia.write_text(
        "#!/usr/bin/env bash\necho 'ERROR: nvidia-smi shim fail' >&2\nexit 1\n",
        encoding="utf-8",
    )
    nvidia.chmod(0o755)
    script = tmp_path / "entrypoint.sh"
    text = ENTRYPOINT.read_text(encoding="utf-8")
    patched = text.replace('LIB="/opt/cc/scripts/gpu/lib.sh"', f'LIB="{LIB}"')
    patched = patched.replace(
        'source "$LIB"\nelse',
        'source "$LIB"\ncc_watchdog_start() { :; }\nelse',
    )
    patched = patched.replace(
        "exec /opt/cc/scripts/gpu/run_job.sh",
        f"exec {stub_job}",
    )
    assert "/opt/cc/" not in patched
    script.write_text(patched, encoding="utf-8")
    script.chmod(0o755)
    ssh_dir = tmp_path / "ssh"
    ssh_dir.mkdir()
    isolated_key = ssh_dir / "ssh_host_test"
    isolated_key.write_text("probe\n", encoding="utf-8")
    etc_before = sorted(p.name for p in Path("/etc/ssh").glob("ssh_host_*"))
    started = time.monotonic()
    result = _run(
        [str(script)],
        env={
            "CC_VOLUME_DIR": str(tmp_path),
            "CC_JOB_ID": "job-early",
            "CC_JOB": "gpu_tests",
            "CC_TTL_S": "60",
            "CC_SSH_DIR": str(ssh_dir),
            **_job_dirs(tmp_path),
        },
        bin_dir=tmp_path,
    )
    assert time.monotonic() - started < 20
    assert result.returncode != 0
    status = tmp_path / "runs" / "job-early" / "status"
    assert status.is_file()
    assert status.read_text(encoding="utf-8").strip() == "failed"
    assert not isolated_key.exists(), result.stdout + result.stderr
    assert sorted(p.name for p in Path("/etc/ssh").glob("ssh_host_*")) == etc_before
    assert "STUB_JOB" not in result.stdout
    assert "nvidia-smi" in result.stderr or "nvidia-smi" in result.stdout


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
            **_job_dirs(tmp_path),
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
    hits = _webhook_curl(tmp_path)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-hook",
            "CC_TTL_S": "60",
            "CC_WEBHOOK_URL": "https://example.invalid/hook",
            **_job_dirs(tmp_path),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert hits.is_file(), result.stderr
    logged = hits.read_text(encoding="utf-8")
    assert logged.count("url=") == 1, logged
    assert "example.invalid/hook" in logged
    assert "failed" in logged
    for line in logged.splitlines():
        if line.startswith("argv="):
            assert "example.invalid/hook" not in line
    status = tmp_path / "vol" / "runs" / "job-hook" / "status"
    assert status.read_text(encoding="utf-8").strip() == "failed"


def test_run_job_unresolved_token_pings_webhook(tmp_path: Path) -> None:
    hits = _webhook_curl(tmp_path)
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
            **_job_dirs(tmp_path),
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
    logged = hits.read_text(encoding="utf-8")
    assert logged.count("url=") == 1, logged
    assert "example.invalid/hook" in logged
    assert "failed" in logged
    for line in logged.splitlines():
        if line.startswith("argv="):
            assert "example.invalid/hook" not in line
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
        start_new_session=True,
    )
    deadline = time.time() + 8
    seen = ""
    try:
        while time.time() < deadline:
            if log.is_file():
                seen = log.read_text(encoding="utf-8")
                if "first-line" in seen:
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("log was not streamed before the command exited")
        assert "first-line" in seen
        assert token not in seen
        assert "REDACTED" in seen
        assert "second-line" not in seen
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


def _ml_jobs_python(tmp_path: Path, *, message: str = "ml.jobs reached", code: int = 0) -> Path:
    py = tmp_path / "cc-python"
    py.write_text(
        f"""#!/usr/bin/env bash
echo STUB_CC_PYTHON
if [[ " $* " == *" -m pip "* ]]; then
  exit 0
fi
if [[ " $* " == *" -m ml.jobs "* ]]; then
  echo {message}
  exit {code}
fi
exec /usr/bin/python3 "$@"
""",
        encoding="utf-8",
    )
    py.chmod(0o755)
    return py


def test_run_job_rerun_after_clone_reaches_ml_jobs(tmp_cc_src: Path, tmp_path: Path) -> None:
    src = tmp_cc_src
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
    py = _ml_jobs_python(tmp_path)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-rerun",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "clone-then-clear-token",
            **_job_dirs(tmp_path),
            "CC_SRC_DIR": str(src),
            "CC_PYTHON": str(py),
        },
        bin_dir=tmp_path,
    )
    log = tmp_path / "vol" / "runs" / "job-rerun" / "log.txt"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert result.returncode == 0, result.stderr + text
    assert "CC_REPO_TOKEN is empty" not in result.stderr
    assert "CC_REPO_TOKEN is empty" not in text
    assert "ml.jobs reached" in text
    assert "STUB_CC_PYTHON" in text
    assert "OPT_CC_PYTHON" not in text
    status = tmp_path / "vol" / "runs" / "job-rerun" / "status"
    assert status.read_text(encoding="utf-8").strip() == "passed"


def test_run_job_uses_cc_python_even_if_opt_cc_venv_exists(
    tmp_cc_src: Path, tmp_path: Path
) -> None:
    src = tmp_cc_src
    (src / "backend").mkdir(parents=True)
    for name in (
        "requirements-gpu.txt",
        "requirements-dev.txt",
        "requirements-nodeps.txt",
    ):
        (src / "backend" / name).write_text("# pin\n", encoding="utf-8")
    py = _ml_jobs_python(tmp_path)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-python",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "tok",
            "CC_RUN_JOB_READY": "1",
            **_job_dirs(tmp_path),
            "CC_SRC_DIR": str(src),
            "CC_PYTHON": str(py),
        },
        bin_dir=tmp_path,
    )
    log = tmp_path / "vol" / "runs" / "job-python" / "log.txt"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert result.returncode == 0, result.stderr + text
    assert "STUB_CC_PYTHON" in text
    assert "ml.jobs reached" in text
    assert "OPT_CC_PYTHON" not in text + result.stderr
    assert "fake /opt/cc" not in text + result.stderr


def test_run_job_refuses_nested_gpu_tests(tmp_path: Path) -> None:
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-nested",
            "CC_TTL_S": "60",
            "CC_IN_GPU_TESTS": "1",
            **_job_dirs(tmp_path),
        },
    )
    assert result.returncode != 0
    assert "Refuse to start nested gpu_tests" in result.stderr
    assert "CC_IN_GPU_TESTS is already set" in result.stderr


def test_resolve_python_requires_absolute_executable(tmp_path: Path) -> None:
    missing = _run(
        ["bash", "-c", f"source {LIB} && cc_resolve_python"],
        env={"CC_PYTHON": str(tmp_path / "no-such-python")},
    )
    assert missing.returncode != 0
    assert "not an executable file" in missing.stderr
    relative = _run(
        ["bash", "-c", f"source {LIB} && CC_PYTHON=python3 cc_resolve_python"],
    )
    assert relative.returncode != 0
    assert "absolute path" in relative.stderr
    stub = _ml_jobs_python(tmp_path)
    ok = _run(
        ["bash", "-c", f"source {LIB} && cc_resolve_python"],
        env={"CC_PYTHON": str(stub)},
    )
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == str(stub)


def test_terminate_skips_second_attempt_after_success(tmp_path: Path) -> None:
    hits = tmp_path / "curl.hits"
    _fake_curl(tmp_path, "200", '{"id":"pod-abc"}')
    curl = tmp_path / "curl"
    original = curl.read_text(encoding="utf-8")
    curl.write_text(
        f'printf "%s\\n" curl >> "{hits}"\n' + original,
        encoding="utf-8",
    )
    curl.chmod(0o755)
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_terminate_self && cc_terminate_self",
        ],
        env={
            "RUNPOD_POD_ID": "pod-abc",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB_ID": "job-term",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert hits.read_text(encoding="utf-8").count("curl") == 1
    assert (tmp_path / "vol" / "runs" / "job-term" / ".cc_terminated").is_file()
    assert result.stdout.count("terminate ok") == 1


def test_run_times_out(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="timed out"):
        _run(["bash", "-c", "sleep 5"], env=_job_dirs(tmp_path), timeout=0.2)


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


def test_runpodctl_failure_redacts_key_hook_and_newlines(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-abc"}')
    key = "pod-scoped-secret-key"
    hook = "https://example.invalid/cc-hook"
    shaped = "rp" + "a_" + "TestToken123"
    runpodctl = tmp_path / "runpodctl"
    runpodctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n%s\\n%s\\n' '{key}' '{hook}' '{shaped}'\n"
        "printf 'x%.0s' {1..500}\n"
        "printf '\\n'\n"
        "exit 1\n",
        encoding="utf-8",
    )
    runpodctl.chmod(0o755)
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_terminate_self"],
        env={
            "RUNPOD_POD_ID": "pod-abc",
            "RUNPOD_API_KEY": key,
            "CC_WEBHOOK_URL": hook,
        },
        bin_dir=tmp_path,
    )
    combined = result.stdout + result.stderr
    assert key not in combined
    assert hook not in combined
    assert shaped not in combined
    assert "REDACTED" in combined
    failed_lines = [line for line in combined.splitlines() if "runpodctl failed" in line]
    assert failed_lines
    assert len(failed_lines[0]) <= 480
    assert "\n" not in failed_lines[0].replace("runpodctl failed", "")


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
    py = _ml_jobs_python(tmp_path, message="pytest failed: 3 failed", code=7)
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
            **_job_dirs(tmp_path),
            "CC_SRC_DIR": str(src),
            "CC_PYTHON": str(py),
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


def test_safe_wipe_refuses_empty_relative_and_tmp(tmp_path: Path) -> None:
    empty = _wipe(tmp_path, "")
    assert empty.returncode != 0
    assert "empty path" in empty.stderr
    spaces = _wipe(tmp_path, "  ")
    assert spaces.returncode != 0
    assert "empty path" in spaces.stderr
    slash = _wipe(tmp_path, "/")
    assert slash.returncode != 0
    assert "rm -rf /" in slash.stderr
    relative = _wipe(tmp_path, "backend")
    assert relative.returncode != 0
    assert "relative path" in relative.stderr
    tmp = _wipe(tmp_path, "/tmp")
    assert tmp.returncode != 0
    assert "/tmp" in tmp.stderr
    nested = tmp_path / "nested" / "cc-src"
    nested.mkdir(parents=True)
    parent = _wipe(tmp_path, str(nested))
    assert parent.returncode != 0
    assert "Parent must be /tmp" in parent.stderr


def test_safe_wipe_refuses_workspace_home_and_checkout(tmp_path: Path) -> None:
    workspace = _wipe(tmp_path, "/workspace")
    assert workspace.returncode != 0
    home = _wipe(tmp_path, str(Path.home()))
    assert home.returncode != 0
    home_parent = _wipe(tmp_path, str(Path.home().parent))
    assert home_parent.returncode != 0
    usr = _wipe(tmp_path, "/usr")
    assert usr.returncode != 0
    backend = _wipe(tmp_path, str(ROOT / "backend"))
    assert backend.returncode != 0
    repo = _wipe(tmp_path, str(ROOT), script_dir=str(LIB.parent))
    assert repo.returncode != 0
    if ROOT.resolve() == Path("/tmp/cc-src").resolve():
        assert "It is the checkout" in repo.stderr
    parent = _wipe(tmp_path, str(ROOT.parent))
    assert parent.returncode != 0
    dash = _wipe(tmp_path, "-cc-src")
    assert dash.returncode != 0


def test_safe_wipe_refuses_home_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "keep").write_text("home\n", encoding="utf-8")
    result = _wipe(tmp_path, str(tmp_cc_src), env={"HOME": str(tmp_cc_src)})
    assert result.returncode != 0
    assert "It is HOME" in result.stderr
    assert (tmp_cc_src / "keep").is_file()


def test_safe_wipe_refuses_home_when_empty(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "keep").write_text("home\n", encoding="utf-8")
    getent = tmp_path / "getent"
    getent.write_text(
        f"""#!/usr/bin/env bash
if [[ "$1" == "passwd" ]]; then
  printf '%s\\n' "user:x:1000:1000::{tmp_cc_src}:"
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    getent.chmod(0o755)
    (tmp_path / "fake-repo" / "scripts" / "gpu").mkdir(parents=True)
    (tmp_path / "cc-vol").mkdir()
    (tmp_path / "cc-lib").mkdir()
    result = _run(
        [
            "bash",
            "-c",
            f'source {LIB} && cc_assert_safe_wipe_dir "$1" "$2" "$3" "$4"',
            "wipe",
            str(tmp_cc_src),
            str(tmp_path / "fake-repo" / "scripts" / "gpu"),
            str(tmp_path / "cc-vol"),
            str(tmp_path / "cc-lib"),
        ],
        env={"HOME": ""},
        bin_dir=tmp_path,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "It is HOME" in result.stderr
    assert (tmp_cc_src / "keep").is_file()


def test_safe_wipe_refuses_volume_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "keep").write_text("vol\n", encoding="utf-8")
    result = _wipe(tmp_path, str(tmp_cc_src), volume=str(tmp_cc_src))
    assert result.returncode != 0
    assert "It is the volume" in result.stderr
    assert (tmp_cc_src / "keep").is_file()


def test_safe_wipe_refuses_scratch_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "keep").write_text("lib\n", encoding="utf-8")
    result = _wipe(tmp_path, str(tmp_cc_src), scratch=str(tmp_cc_src))
    assert result.returncode != 0
    assert "It is scratch" in result.stderr
    assert (tmp_cc_src / "keep").is_file()


def test_safe_wipe_refuses_checkout_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    gpu = tmp_cc_src / "scripts" / "gpu"
    gpu.mkdir(parents=True)
    (tmp_cc_src / "KEEP").write_text("checkout-alive\n", encoding="utf-8")
    result = _wipe(tmp_path, str(tmp_cc_src), script_dir=str(gpu), wipe=True)
    assert result.returncode != 0
    assert "It is the checkout" in result.stderr
    assert (tmp_cc_src / "KEEP").read_text(encoding="utf-8") == "checkout-alive\n"


def test_safe_wipe_refuses_working_directory_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "keep").write_text("cwd\n", encoding="utf-8")
    result = _wipe(tmp_path, str(tmp_cc_src), cwd=tmp_cc_src)
    assert result.returncode != 0
    assert "It is the working directory" in result.stderr
    assert (tmp_cc_src / "keep").is_file()


def test_safe_wipe_refuses_tmpdir_under_tmp_cc_src(tmp_path: Path) -> None:
    target = tmp_path / "inner-tmp" / "cc-src"
    target.mkdir(parents=True)
    (target / "keep").write_text("clone\n", encoding="utf-8")
    result = _wipe(tmp_path, str(target), env={"TMPDIR": "/tmp/cc-src"})
    assert result.returncode != 0
    assert "Parent must be /tmp" in result.stderr
    assert (target / "keep").is_file()


def test_safe_wipe_refuses_tmpdir_inside_volume(tmp_path: Path) -> None:
    volume = tmp_path / "workspace"
    target = volume / "cc-src"
    target.mkdir(parents=True)
    (target / "keep").write_text("vol\n", encoding="utf-8")
    result = _wipe(
        tmp_path,
        str(target),
        volume=str(volume),
        env={"TMPDIR": str(volume)},
    )
    assert result.returncode != 0
    assert "Parent must be /tmp" in result.stderr
    assert (target / "keep").is_file()


def test_safe_wipe_refuses_symlinked_parent(tmp_cc_src: Path, tmp_path: Path) -> None:
    alias = tmp_path / "alias-tmp"
    alias.symlink_to(Path("/tmp"))
    target = alias / tmp_cc_src.name
    result = _wipe(tmp_path, str(target))
    assert result.returncode != 0
    assert "Parent is a symlink" in result.stderr
    assert tmp_cc_src.is_dir()


def test_safe_wipe_refuses_symlink_and_trailing_slash_link(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("keep\n", encoding="utf-8")
    link = tmp_path / "srclink"
    link.symlink_to(outside)
    slashed = _wipe(tmp_path, f"{link}/")
    assert slashed.returncode != 0
    assert "symlink" in slashed.stderr
    assert (outside / "secret").read_text(encoding="utf-8") == "keep\n"
    named = tmp_path / "cc-src"
    named.symlink_to(ROOT)
    repo_link = _wipe(tmp_path, str(named))
    assert repo_link.returncode != 0
    assert (ROOT / "scripts" / "gpu" / "run_job.sh").is_file()


def test_safe_wipe_allows_tmp_cc_src(tmp_cc_src: Path, tmp_path: Path) -> None:
    (tmp_cc_src / "old").write_text("gone\n", encoding="utf-8")
    slashed = _wipe(tmp_path, f"{tmp_cc_src}/")
    assert slashed.returncode == 0, slashed.stderr
    assert slashed.stdout.strip() == str(tmp_cc_src.resolve())
    wiped = _wipe(tmp_path, str(tmp_cc_src), wipe=True)
    assert wiped.returncode == 0, wiped.stderr
    assert not (tmp_cc_src / "old").exists()


def test_safe_wipe_default_src_when_unset(tmp_path: Path) -> None:
    assert 'SRC="${CC_SRC_DIR:-/tmp/cc-src}"' in RUN_JOB.read_text(encoding="utf-8")
    result = _run(
        [
            "bash",
            "-c",
            (
                f"source {LIB} && unset CC_SRC_DIR && "
                'SRC="${CC_SRC_DIR:-/tmp/cc-src}" && printf "%s\\n" "$SRC"'
            ),
        ]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/tmp/cc-src"
    fake_scripts = tmp_path / "fake-repo" / "scripts" / "gpu"
    fake_scripts.mkdir(parents=True)
    volume = tmp_path / "cc-vol"
    scratch = tmp_path / "cc-lib"
    volume.mkdir()
    scratch.mkdir()
    # Assert-only. Never add wipe=True: /tmp/cc-src may be the live checkout in pod-layout.
    allowed = _run(
        [
            "bash",
            "-c",
            (
                f"source {LIB} && unset CC_SRC_DIR && "
                'SRC="${CC_SRC_DIR:-/tmp/cc-src}" && '
                'cc_assert_safe_wipe_dir "$SRC" "$1" "$2" "$3"'
            ),
            "wipe",
            str(fake_scripts),
            str(volume),
            str(scratch),
        ],
        cwd=tmp_path,
    )
    assert allowed.returncode == 0, allowed.stderr


def test_safe_wipe_parent_swap_does_not_follow_new_link(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("keep\n", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix="cc-wipe-stage-", dir="/tmp"))
    src = stage / "cc-src"
    src.mkdir()
    fake_scripts = tmp_path / "fake-repo" / "scripts" / "gpu"
    fake_scripts.mkdir(parents=True)
    volume = tmp_path / "cc-vol"
    scratch = tmp_path / "cc-lib"
    volume.mkdir()
    scratch.mkdir()
    try:
        result = _run(
            [
                "bash",
                "-c",
                f"""
source {LIB}
target="$1"
outside="$2"
scripts="$3"
volume="$4"
scratch="$5"
export TMPDIR="$(dirname "$target")"
resolved="$(cc_assert_safe_wipe_dir "$target" "$scripts" "$volume" "$scratch")" || exit 1
rm -rf "$(dirname "$target")"
ln -s "$outside" "$(dirname "$target")"
if cc_safe_wipe_dir "$target" "$scripts" "$volume" "$scratch"; then
  echo WIPED
  exit 0
fi
echo REFUSED
exit 1
""",
                "swap",
                str(src),
                str(outside),
                str(fake_scripts),
                str(volume),
                str(scratch),
            ],
            env={
                "CC_VOLUME_DIR": str(volume),
                "CC_LIBRARY_DIR": str(scratch),
                "TMPDIR": str(stage),
            },
            cwd=tmp_path,
        )
        assert "secret" not in (result.stdout + result.stderr)
        assert (outside / "secret").read_text(encoding="utf-8") == "keep\n"
        assert result.returncode != 0
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage, ignore_errors=True)
        elif stage.is_symlink():
            stage.unlink(missing_ok=True)


def test_run_job_refuses_to_wipe_cc_src_checkout(tmp_cc_src: Path, tmp_path: Path) -> None:
    assert 'SRC="${CC_SRC_DIR:-/tmp/cc-src}"' in RUN_JOB.read_text(encoding="utf-8")
    pod = tmp_cc_src
    gpu = pod / "scripts" / "gpu"
    gpu.mkdir(parents=True)
    shutil.copy2(RUN_JOB, gpu / "run_job.sh")
    shutil.copy2(LIB, gpu / "lib.sh")
    copied = (gpu / "run_job.sh").read_text(encoding="utf-8")
    (gpu / "run_job.sh").write_text(
        copied.replace(
            'SRC="${CC_SRC_DIR:-/tmp/cc-src}"',
            f'SRC="${{CC_SRC_DIR:-{pod}}}"',
        ),
        encoding="utf-8",
    )
    (gpu / "run_job.sh").chmod(0o755)
    marker = pod / "KEEP_ME"
    marker.write_text("checkout-alive\n", encoding="utf-8")
    result = _run(
        [str(gpu / "run_job.sh")],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-wipe",
            "CC_TTL_S": "60",
            "CC_REPO_TOKEN": "tok",
            "CC_SRC_DIR": str(pod),
            "CC_LIBRARY_DIR": str(tmp_path / "cc-lib"),
        },
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Refuse to rm -rf" in result.stderr
    assert "It is the checkout" in result.stderr
    log = (tmp_path / "vol" / "runs" / "job-wipe" / "log.txt").read_text(encoding="utf-8")
    assert "Refuse to rm -rf" in log
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8") == "checkout-alive\n"
    assert (ROOT / "scripts" / "gpu" / "run_job.sh").is_file()
    assert "Clone" in log


def test_isolation_defaults_job_dirs_under_basetemp(tmp_path: Path) -> None:
    result = _run(
        [
            "bash",
            "-c",
            'printf "src=%s\\nlib=%s\\nvol=%s\\n" "$CC_SRC_DIR" "$CC_LIBRARY_DIR" "$CC_VOLUME_DIR"',
        ]
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert _BASETEMP is not None
    for key in ("src", "lib", "vol"):
        resolved = Path(values[key]).resolve()
        assert resolved.is_relative_to(_BASETEMP)
        assert resolved.name.startswith("cc-")
    with pytest.raises(AssertionError, match="isolated"):
        _run(
            [str(RUN_JOB)],
            env={
                "CC_VOLUME_DIR": str(tmp_path),
                "CC_TTL_S": "60",
                "CC_SRC_DIR": "/tmp/climbing-coach",
                "CC_LIBRARY_DIR": str(tmp_path / "cc-lib"),
            },
        )


def test_s3_cp_stdout_does_not_leak_return_trap(tmp_path: Path) -> None:
    _fake_aws_get_object(tmp_path)
    result = _run(
        [
            "bash",
            "-c",
            f"""
source {LIB}
outer() {{
  err="$(mktemp)"
  echo KEEP >"$err"
  printf '%s\\n' "$err"
  cc_s3_cp_stdout s3://vol/runs/job-1/status EU-RO-1 \\
    https://s3api-eu-ro-1.runpod.io >/dev/null || true
}}
path="$(outer)"
if [[ -f "$path" ]]; then
  echo "outer_kept=$(cat "$path")"
else
  echo "outer_missing"
fi
trap -p RETURN || true
""",
        ],
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "outer_kept=KEEP" in result.stdout
    assert "RETURN" not in result.stdout


def test_cc_fail_redacts_log_txt(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    token = "rpa_secretlogtoken"
    result = _run(
        [
            "bash",
            "-c",
            f'source {LIB} && cc_fail "token={token} key=$RUNPOD_API_KEY"',
        ],
        env={
            "CC_RUN_LOG": str(log),
            "RUNPOD_API_KEY": token,
        },
    )
    assert result.returncode != 0
    text = log.read_text(encoding="utf-8")
    assert token not in text
    assert "REDACTED" in text


def test_run_rejects_opt_cc_paths(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="/opt/cc"):
        _run(["/opt/cc/scripts/gpu/run_job.sh"], env=_job_dirs(tmp_path))


def test_s3_get_object_is_used_not_cp_stdout() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert "s3api get-object" in text
    assert "aws s3 cp" not in text


def test_run_logged_fifo_uses_mktemp_dir() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert 'fifo_dir="$(mktemp -d)"' in text
    assert "mktemp -u" not in text
    assert "cc_redact_oneline" in text
    assert "trap 'rm -f" not in text
    assert "jq -c" in WAIT_JOB.read_text(encoding="utf-8")
    curl_fn = LIB.read_text(encoding="utf-8").split("cc_curl_post_json()")[1]
    curl_fn = curl_fn.split("cc_realpath")[0]
    assert "return 1" in curl_fn
    assert "cc_fail" not in curl_fn


def test_webhook_url_stays_off_curl_argv() -> None:
    for path in (LIB, RUN_JOB):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "curl " in line:
                assert "CC_WEBHOOK_URL" not in line
                assert "WEBHOOK_URL" not in line


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
