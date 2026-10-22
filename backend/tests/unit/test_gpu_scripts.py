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
    before_stamps = set(Path("/tmp").glob(".cc_terminated.*"))
    yield
    for path in created:
        shutil.rmtree(path, ignore_errors=True)
    created.clear()
    after_stamps = set(Path("/tmp").glob(".cc_terminated.*"))
    leaked = after_stamps - before_stamps
    if leaked:
        raise AssertionError(f"tests wrote real /tmp terminate stamps: {leaked}")
    _ISOLATION_ROOT = None
    _BASETEMP = None


_REAL_STAMP_DIR = Path("/tmp").resolve()


def _is_real_terminate_stamp(path: Path) -> bool:
    resolved = path.resolve()
    return (
        resolved.parent == _REAL_STAMP_DIR
        and resolved.name.startswith(".cc_terminated.")
    )


def _terminate_stamp_dir(extra: dict[str, str] | None = None) -> Path:
    if _ISOLATION_ROOT is None or _BASETEMP is None:
        raise AssertionError("pytest isolation root is not bound")
    raw = (extra or {}).get("CC_TERMINATE_STAMP_DIR")
    if raw:
        resolved = Path(raw).expanduser().resolve()
    else:
        resolved = (_ISOLATION_ROOT / "term-stamps").resolve()
    if resolved == _REAL_STAMP_DIR:
        raise AssertionError("CC_TERMINATE_STAMP_DIR must not be /tmp")
    if not resolved.is_relative_to(_BASETEMP):
        raise AssertionError("CC_TERMINATE_STAMP_DIR must be under pytest basetemp")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _stamp_path(pod: str, extra: dict[str, str] | None = None) -> Path:
    path = _terminate_stamp_dir(extra) / f".cc_terminated.{pod}"
    if _is_real_terminate_stamp(path):
        raise AssertionError(f"tests must not write {path}")
    return path


def _pid_state(pid: int) -> str | None:
    proc = Path(f"/proc/{pid}")
    if Path("/proc").is_dir():
        if not proc.exists():
            return None
        try:
            stat = (proc / "stat").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        rparen = stat.rfind(")")
        if rparen == -1:
            return None
        parts = stat[rparen + 2 :].split()
        return parts[0] if parts else None
    listed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        return None
    state = listed.stdout.strip()
    return state or None


def _pid_is_dead(pid: int) -> bool:
    state = _pid_state(pid)
    return state is None or state.startswith("Z")


def _job_dirs(tmp_path: Path, src: Path | None = None) -> dict[str, str]:
    if src is None:
        src = Path(tempfile.mkdtemp(prefix="cc-src-", dir="/tmp"))
        _TMP_CC_SRC_DIRS.append(src)
    else:
        src.mkdir(parents=True, exist_ok=True)
    library = tmp_path / "cc-lib"
    library.mkdir(parents=True, exist_ok=True)
    return {"CC_SRC_DIR": str(src), "CC_LIBRARY_DIR": str(library)}


def _webhook_curl(
    tmp_path: Path,
    *,
    http: str = "200",
    exit_code: int = 0,
    stderr: str = "",
) -> Path:
    hits = tmp_path / "webhook.log"
    err_file = tmp_path / "curl.stderr"
    if stderr:
        err_file.write_text(stderr, encoding="utf-8")
    curl = tmp_path / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
printf 'argv=%s\\n' "$*" >> "{hits}"
url=""
body=""
method=GET
has_config=0
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      has_config=1
      url="$(sed -n 's/^url = \"\\(.*\\)\"$/\\1/p' "$2")"
      if grep -q '^header = "Authorization: Bearer ' "$2"; then
        printf 'auth=1\\n' >> "{hits}"
      else
        printf 'auth=0\\n' >> "{hits}"
      fi
      shift 2
      ;;
    -d)
      body="$2"
      shift 2
      ;;
    -X)
      method="$2"
      shift 2
      ;;
    -o)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [[ "$has_config" == "1" ]]; then
  printf 'url=%s body=%s\\n' "$url" "$body" >> "{hits}"
  if [[ -f "{err_file}" ]]; then
    cat "{err_file}" >&2
  fi
  printf '%s' "{http}"
  exit {exit_code}
fi
if [[ "$method" == "DELETE" ]]; then
  if [[ -n "$out" && "$out" != "/dev/null" ]]; then
    printf '%s\\n' '{{"id":"pod"}}' >"$out"
  fi
  printf '200'
  exit 0
fi
printf '500'
exit 0
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return hits


def _run_job_webhook(
    tmp_path: Path,
    job_id: str,
    *,
    pod: str | None = None,
    api_key: str | None = None,
    webhook_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "CC_VOLUME_DIR": str(tmp_path / "vol"),
        "CC_JOB": "gpu_tests",
        "CC_GIT_REF": SHA40,
        "CC_JOB_ID": job_id,
        "CC_TTL_S": "60",
        "CC_IN_GPU_TESTS": "",
        "CC_WEBHOOK_URL": "https://example.invalid/hook",
        **_job_dirs(tmp_path),
    }
    if pod:
        env["RUNPOD_POD_ID"] = pod
    if api_key:
        env["RUNPOD_API_KEY"] = api_key
    if webhook_key:
        env["CC_WEBHOOK_KEY"] = webhook_key
    return _run([str(RUN_JOB)], env=env, bin_dir=tmp_path)


def _watchdog_errexit(
    tmp_path: Path,
    run_dir: Path,
    *,
    pod: str,
    unset_log: bool = True,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    unset_cmd = "unset CC_RUN_LOG; " if unset_log else ""
    env = {
        "RUNPOD_POD_ID": pod,
        "RUNPOD_API_KEY": "ok-key",
        "CC_VOLUME_DIR": str(tmp_path / "vol"),
        "CC_TTL_S": "1",
    }
    if extra:
        env.update(extra)
    return _run(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {LIB}; unset CC_JOB_ID; "
            f"{unset_cmd}cc_watchdog_start {run_dir}; sleep 2",
        ],
        env=env,
        bin_dir=tmp_path,
        timeout=5,
    )


def _run_dir_text(run_dir: Path) -> str:
    chunks: list[str] = []
    if not run_dir.exists():
        return ""
    for path in run_dir.rglob("*"):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


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
    extra["CC_TERMINATE_STAMP_DIR"] = str(_terminate_stamp_dir(extra))
    if "CC_IN_GPU_TESTS" not in extra:
        inherited = os.environ.get("CC_IN_GPU_TESTS")
        if inherited:
            extra["CC_IN_GPU_TESTS"] = inherited
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
    proc = subprocess.Popen(
        args,
        cwd=str(cwd or ROOT),
        env=_isolated_env(env, bin_dir=bin_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        raise AssertionError(f"_run timed out after {limit}s: {args}") from exc
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


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


S3_NOT_FOUND_GET = (
    "An error occurred (NoSuchKey) when calling the GetObject operation: "
    "The specified key does not exist."
)
S3_NOT_FOUND_HEAD = (
    "An error occurred (404) when calling the HeadObject operation: Not Found"
)
S3_NOT_FOUND_RE = (
    r"\((NoSuchKey|404)\) when calling the (GetObject|HeadObject) operation"
)


def _fake_aws_err(tmp_path: Path, msg: str) -> Path:
    err = tmp_path / "aws-err.txt"
    err.write_text(msg + "\n", encoding="utf-8")
    aws = tmp_path / "aws"
    aws.write_text(
        f"#!/usr/bin/env bash\ncat '{err}' >&2\nexit 1\n",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    return aws


def _s3_cp(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_cp_stdout s3://vol/runs/job-1/status "
            "EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )


def _s3_exists(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_object_exists s3://vol/runs/job-1/status "
            "EU-RO-1 https://s3api-eu-ro-1.runpod.io",
        ],
        bin_dir=tmp_path,
    )


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
[[ "$1" == "s3api" ]] || {{
  echo "expected s3api" >&2
  exit 1
}}
op="$2"
[[ "$op" == "get-object" || "$op" == "head-object" ]] || {{
  echo "expected s3api get-object or head-object" >&2
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
if [[ "$op" == "head-object" ]]; then
  exit 0
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
    assert env["CC_WEBHOOK_KEY"] == "{{ RUNPOD_SECRET_cc_webhook_key }}"
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


def test_pod_up_refuses_existing_job_id_on_volume(tmp_path: Path) -> None:
    vol = tmp_path / "vol"
    existing = vol / "runs" / "job-reuse"
    existing.mkdir(parents=True)
    (existing / "started_at").write_text("1\n", encoding="utf-8")
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={"CC_JOB_ID": "job-reuse", "CC_VOLUME_DIR": str(vol)},
    )
    assert result.returncode != 0
    assert "Refuse to reuse job id job-reuse" in result.stderr
    assert "already exists on the volume" in result.stderr


def test_pod_up_refuses_existing_job_id_in_s3(tmp_path: Path) -> None:
    _fake_aws_get_object(
        tmp_path,
        body="running\n",
        expected_bucket="wguvx2347m",
        expected_keys=("runs/job-s3/status",),
    )
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={
            "CC_JOB_ID": "job-s3",
            "CC_VOLUME_DIR": str(tmp_path / "empty-vol"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "Refuse to reuse job id job-s3" in result.stderr
    assert "already exists in S3" in result.stderr


def test_pod_up_allows_unused_job_id(tmp_path: Path) -> None:
    _fake_aws_err(
        tmp_path,
        "An error occurred (NoSuchKey) when calling the GetObject operation: "
        "The specified key does not exist.",
    )
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={
            "CC_JOB_ID": "job-fresh",
            "CC_VOLUME_DIR": str(tmp_path / "empty-vol"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "job_id=job-fresh" in result.stdout


def test_s3_not_found_match_is_strict() -> None:
    text = LIB.read_text(encoding="utf-8")
    helper = text.split("cc_s3_is_not_found()")[1].split("cc_s3_err_summary()")[0]
    assert S3_NOT_FOUND_RE in helper
    cp_fn = text.split("cc_s3_cp_stdout()")[1].split("cc_rest()")[0]
    exists_fn = text.split("cc_s3_object_exists()")[1].split("cc_s3_run_exists()")[0]
    assert "cc_s3_is_not_found" in cp_fn
    assert "cc_s3_is_not_found" in exists_fn
    assert "s3api head-object" in exists_fn
    assert "NoSuchKey|Not Found|404" not in cp_fn
    assert "NoSuchKey|Not Found|404" not in exists_fn


@pytest.mark.parametrize(
    "msg",
    [
        S3_NOT_FOUND_GET,
        S3_NOT_FOUND_HEAD,
        "An error occurred (NoSuchKey) when calling the HeadObject operation: x",
        "An error occurred (404) when calling the GetObject operation: x",
    ],
)
def test_s3_is_not_found_accepts_aws_phrase(tmp_path: Path, msg: str) -> None:
    err = tmp_path / "err.txt"
    err.write_text(msg + "\n", encoding="utf-8")
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_s3_is_not_found {err}"],
        env=_job_dirs(tmp_path),
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "msg",
    [
        "NoSuchKey",
        "404",
        "Not Found",
        "HTTP 404",
        "An error occurred (AccessDenied) when calling the GetObject operation: x",
        "An error occurred (NoSuchKey) when calling the ListObjects operation: x",
    ],
)
def test_s3_is_not_found_fails_closed(tmp_path: Path, msg: str) -> None:
    err = tmp_path / "err.txt"
    err.write_text(msg + "\n", encoding="utf-8")
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_s3_is_not_found {err}"],
        env=_job_dirs(tmp_path),
    )
    assert result.returncode != 0


def test_s3_cp_treats_strict_not_found_as_missing(tmp_path: Path) -> None:
    _fake_aws_err(tmp_path, S3_NOT_FOUND_GET)
    result = _s3_cp(tmp_path)
    assert result.returncode == 1
    assert "ERROR: S3" not in result.stderr
    _fake_aws_err(tmp_path, S3_NOT_FOUND_HEAD)
    result = _s3_cp(tmp_path)
    assert result.returncode == 1
    assert "ERROR: S3" not in result.stderr


def test_s3_object_exists_treats_strict_not_found_as_missing(tmp_path: Path) -> None:
    _fake_aws_err(tmp_path, S3_NOT_FOUND_GET)
    result = _s3_exists(tmp_path)
    assert result.returncode == 1
    assert "ERROR: S3" not in result.stderr
    assert "Could not check" not in result.stderr
    _fake_aws_err(tmp_path, S3_NOT_FOUND_HEAD)
    result = _s3_exists(tmp_path)
    assert result.returncode == 1
    assert "ERROR: S3" not in result.stderr
    assert "Could not check" not in result.stderr


@pytest.mark.parametrize("msg", ["NoSuchKey", "404", "Not Found"])
def test_s3_cp_fails_closed_on_loose_404(tmp_path: Path, msg: str) -> None:
    _fake_aws_err(tmp_path, msg)
    result = _s3_cp(tmp_path)
    assert result.returncode != 0
    assert "ERROR: S3 get-object" in result.stderr


@pytest.mark.parametrize("msg", ["NoSuchKey", "404", "Not Found"])
def test_s3_err_summary_redacts_aws_key_pattern(tmp_path: Path) -> None:
    access = "A" + "KIA" + "TESTFAKEKEY12345"
    err = tmp_path / "err.txt"
    err.write_text(
        "An error occurred (SignatureDoesNotMatch) when calling the PutObject "
        f"operation: credential {access} aws_access_key_id={access}\n",
        encoding="utf-8",
    )
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_s3_err_summary {err} videos/sample1.mp4"],
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert access not in combined
    assert "REDACTED" in combined
    assert "code=SignatureDoesNotMatch" in combined
    assert "key=videos/sample1.mp4" in combined


def test_default_aws_shim_blocks_real_bucket() -> None:
    if _SHIM_LOG is not None and _SHIM_LOG.exists():
        _SHIM_LOG.write_text("", encoding="utf-8")
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && cc_s3_object_exists "
            "s3://wguvx2347m/runs/job-shim/status EU-RO-1 "
            "https://s3api-eu-ro-1.runpod.io",
        ]
    )
    assert result.returncode != 0
    assert "Could not check" in result.stderr or "blocked" in result.stderr
    assert _SHIM_LOG is not None and _SHIM_LOG.is_file()
    log = _SHIM_LOG.read_text(encoding="utf-8")
    assert "aws " in log
    assert "s3api" in log


def test_s3_object_exists_fails_closed_on_loose_404(tmp_path: Path, msg: str) -> None:
    _fake_aws_err(tmp_path, msg)
    result = _s3_exists(tmp_path)
    assert result.returncode != 0
    assert "Could not check" in result.stderr


def test_pod_up_fails_closed_on_loose_s3_404(tmp_path: Path) -> None:
    _fake_aws_err(tmp_path, "NoSuchKey")
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", SHA40, "--dry-run"],
        env={
            "CC_JOB_ID": "job-loose",
            "CC_VOLUME_DIR": str(tmp_path / "empty-vol"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "job_id=job-loose" not in result.stdout
    assert "Could not check" in result.stderr or "S3 head-object" in result.stderr


def test_parse_ttl_leading_zero_is_decimal() -> None:
    cases = (("010", "10"), ("010s", "10"), ("010m", "600"), ("08", "8"))
    for raw, want in cases:
        result = _run(["bash", "-c", f"source {LIB} && cc_parse_ttl {raw}"])
        assert result.returncode == 0, f"{raw}: {result.stderr}"
        assert result.stdout.strip() == want, raw


def test_terminate_stamp_dir_must_not_be_tmp(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="must not be /tmp"):
        _run(
            ["bash", "-c", f"source {LIB} && cc_terminate_stamp"],
            env={"RUNPOD_POD_ID": "pod-x", "CC_TERMINATE_STAMP_DIR": "/tmp"},
        )


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


def test_sync_volume_uses_s3api_and_pins_multipart() -> None:
    text = SYNC.read_text(encoding="utf-8")
    assert "s3api" in text
    assert "put-object" in text
    assert "cc_aws_export_multipart_config" in text
    assert "aws s3 cp" not in text
    assert "s3 cp -" not in text
    lib = LIB.read_text(encoding="utf-8")
    assert "multipart_threshold = 128MB" in lib
    helper = lib.split("cc_aws_export_multipart_config()")[1].split("cc_setup_ssh()")[0]
    assert "AWS_CONFIG_FILE" in helper
    assert "~/.aws/config" not in helper or "Do not edit ~/.aws/config" in helper


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


def test_terminate_self_fails_on_empty_pod_id_and_still_runs(tmp_path: Path) -> None:
    hits = tmp_path / "curl.hits"
    _fake_curl(tmp_path, "200", '{"id":"pod"}')
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
            f"source {LIB} && cc_terminate_self",
        ],
        env={
            "RUNPOD_POD_ID": "",
            "RUNPOD_API_KEY": "pod-scoped-key",
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "RUNPOD_POD_ID is missing" in result.stderr
    assert not hits.exists() or hits.read_text(encoding="utf-8").count("curl") == 0
    trapped = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "RUNPOD_POD_ID": "",
            "RUNPOD_API_KEY": "pod-scoped-key",
            **_job_dirs(tmp_path),
        },
        bin_dir=tmp_path,
    )
    assert trapped.returncode != 0
    assert "RUNPOD_POD_ID is missing" in trapped.stderr


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
    refuse_at = text.index("cc_refuse_nested_gpu_tests")
    trap_at = text.index("trap cleanup EXIT")
    require_at = text.index("cc_require_ttl")
    mkdir_at = text.index('mkdir -p "$RUN_DIR/artifacts" "$VOLUME/models"')
    assert refuse_at < trap_at < require_at < mkdir_at
    assert "trap cleanup INT" in text
    assert "trap cleanup TERM" in text
    assert "trap cleanup HUP" in text
    assert "set +e" in text.split("cleanup()")[1].split("cc_terminate_self")[0]


def test_entrypoint_unsets_in_gpu_tests_before_exec() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "unset CC_IN_GPU_TESTS" in text
    assert text.index("unset CC_IN_GPU_TESTS") < text.index(
        "exec /opt/cc/scripts/gpu/run_job.sh"
    )


def test_refuse_nested_gpu_tests_clears_after_unset() -> None:
    result = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && unset CC_IN_GPU_TESTS && "
            "CC_JOB=gpu_tests cc_refuse_nested_gpu_tests && echo cleared",
        ],
        env={"CC_IN_GPU_TESTS": "1", "CC_JOB": "gpu_tests"},
    )
    assert result.returncode == 0, result.stderr
    assert "cleared" in result.stdout
    assert "already set" not in result.stderr


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


def test_pod_up_accepts_uppercase_sha() -> None:
    upper = SHA40.upper()
    result = _run(
        [str(POD_UP), "--job", "gpu_tests", "--ref", upper, "--dry-run"],
    )
    assert result.returncode == 0, result.stderr
    payload = _payload(result.stdout)
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["CC_GIT_REF"] == upper


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
            "CC_IN_GPU_TESTS": "",
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
            "CC_IN_GPU_TESTS": "",
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
            "CC_IN_GPU_TESTS": "",
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
    text = log.read_text(encoding="utf-8")
    assert "job=gpu_tests" in text
    assert "gpu_name=unknown" in text


def test_run_job_header_includes_nvidia_smi_gpu_name(tmp_path: Path) -> None:
    nvidia = tmp_path / "nvidia-smi"
    nvidia.write_text(
        "#!/usr/bin/env bash\necho 'NVIDIA GeForce RTX 4090'\n",
        encoding="utf-8",
    )
    nvidia.chmod(0o755)
    result = _run(
        [str(RUN_JOB)],
        env={
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB": "gpu_tests",
            "CC_GIT_REF": SHA40,
            "CC_JOB_ID": "job-gpu-name",
            "CC_TTL_S": "60",
            "CC_IN_GPU_TESTS": "",
            **_job_dirs(tmp_path),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    text = (tmp_path / "vol" / "runs" / "job-gpu-name" / "log.txt").read_text(
        encoding="utf-8"
    )
    assert "job=gpu_tests" in text
    assert "job_id=job-gpu-name" in text
    assert f"git_ref={SHA40}" in text
    assert "ttl_s=60" in text
    assert "gpu_name=NVIDIA GeForce RTX 4090" in text
    header = RUN_JOB.read_text(encoding="utf-8")
    assert "--query-gpu=name" in header
    assert "gpu_name=${gpu_name:-unknown}" in header


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
            "CC_IN_GPU_TESTS": "",
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
    log = tmp_path / "vol" / "runs" / "job-hook" / "log.txt"
    text = log.read_text(encoding="utf-8")
    assert "webhook ping ok status=200 curl_rc=0" in text
    assert "example.invalid" not in text
    assert "https://" not in text


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
            "CC_IN_GPU_TESTS": "",
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
    text = log.read_text(encoding="utf-8")
    assert "webhook ping ok status=200 curl_rc=0" in text
    assert "example.invalid" not in text
    assert "https://" not in text


def test_webhook_ping_ok_on_2xx(tmp_path: Path) -> None:
    _webhook_curl(tmp_path, http="204", exit_code=0)
    result = _run_job_webhook(tmp_path, "job-hook-204")
    assert result.returncode != 0
    log = tmp_path / "vol" / "runs" / "job-hook-204" / "log.txt"
    text = log.read_text(encoding="utf-8")
    assert "webhook ping ok status=204 curl_rc=0" in text
    assert "webhook ping failed" not in text
    assert "example.invalid" not in text + result.stdout + result.stderr
    assert "https://" not in text


def test_webhook_ping_failed_on_non_2xx(tmp_path: Path) -> None:
    _webhook_curl(tmp_path, http="500", exit_code=0)
    pod = "pod-hook-500"
    result = _run_job_webhook(
        tmp_path, "job-hook-500", pod=pod, api_key="ok-key"
    )
    assert result.returncode != 0
    log = tmp_path / "vol" / "runs" / "job-hook-500" / "log.txt"
    text = log.read_text(encoding="utf-8")
    assert "webhook ping failed status=500 curl_rc=0" in text
    assert "webhook ping ok" not in text
    assert "example.invalid" not in text + result.stdout + result.stderr
    assert "https://" not in text
    assert _stamp_path(pod).is_file()
    assert not Path(f"/tmp/.cc_terminated.{pod}").exists()


def test_webhook_ping_failed_on_curl_error(tmp_path: Path) -> None:
    _webhook_curl(tmp_path, http="000", exit_code=7)
    pod = "pod-hook-curl7"
    result = _run_job_webhook(
        tmp_path, "job-hook-curl7", pod=pod, api_key="ok-key"
    )
    assert result.returncode != 0
    log = tmp_path / "vol" / "runs" / "job-hook-curl7" / "log.txt"
    text = log.read_text(encoding="utf-8")
    assert "webhook ping failed status=000 curl_rc=7" in text
    assert "webhook ping ok" not in text
    assert "example.invalid" not in text + result.stdout + result.stderr
    assert "https://" not in text
    assert _stamp_path(pod).is_file()
    assert not Path(f"/tmp/.cc_terminated.{pod}").exists()


def test_webhook_curl_stderr_url_does_not_leak_into_log(tmp_path: Path) -> None:
    leak = "https://secret-webhook.example.invalid/hook?token=leak-me"
    _webhook_curl(
        tmp_path,
        http="000",
        exit_code=7,
        stderr=f"curl: (7) Failed to connect to {leak}\n",
    )
    result = _run_job_webhook(tmp_path, "job-hook-leak")
    assert result.returncode != 0
    run_dir = tmp_path / "vol" / "runs" / "job-hook-leak"
    dumped = _run_dir_text(run_dir)
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "webhook ping failed status=000 curl_rc=7" in log
    assert leak not in dumped
    assert "secret-webhook" not in dumped
    assert "leak-me" not in dumped
    assert leak not in result.stdout
    assert leak not in result.stderr
    assert "https://" not in log
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert leak not in path.name


def test_webhook_key_never_appears_in_run_folder(tmp_path: Path) -> None:
    key = "whk_test_not_a_real_secret"
    hits = _webhook_curl(tmp_path)
    result = _run_job_webhook(tmp_path, "job-hook-key", webhook_key=key)
    assert result.returncode != 0
    run_dir = tmp_path / "vol" / "runs" / "job-hook-key"
    dumped = _run_dir_text(run_dir)
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "webhook ping ok status=200 curl_rc=0" in log
    assert "auth=1" in hits.read_text(encoding="utf-8")
    assert key not in dumped
    assert key not in result.stdout
    assert key not in result.stderr
    assert "Authorization" not in log
    assert "Bearer" not in log
    assert "CC_WEBHOOK_KEY" not in log
    for line in hits.read_text(encoding="utf-8").splitlines():
        if line.startswith("argv="):
            assert key not in line
            assert "Authorization" not in line
            assert "Bearer" not in line
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert key not in path.name


def test_webhook_key_in_curl_stderr_does_not_leak(tmp_path: Path) -> None:
    key = "whk_stderr_not_a_real_secret"
    _webhook_curl(
        tmp_path,
        http="000",
        exit_code=7,
        stderr=f"curl: (7) Failed to connect Authorization: Bearer {key}\n",
    )
    result = _run_job_webhook(tmp_path, "job-hook-key-stderr", webhook_key=key)
    assert result.returncode != 0
    run_dir = tmp_path / "vol" / "runs" / "job-hook-key-stderr"
    dumped = _run_dir_text(run_dir)
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    assert "webhook ping failed status=000 curl_rc=7" in log
    assert key not in dumped
    assert key not in result.stdout
    assert key not in result.stderr
    assert "Authorization" not in log
    assert "Bearer" not in log


def test_unresolved_webhook_key_is_not_sent(tmp_path: Path) -> None:
    unresolved = "{{ RUNPOD_SECRET_cc_webhook_key }}"
    hits = _webhook_curl(tmp_path)
    result = _run_job_webhook(
        tmp_path, "job-hook-key-unresolved", webhook_key=unresolved
    )
    assert result.returncode != 0
    logged = hits.read_text(encoding="utf-8")
    assert "auth=0" in logged
    assert "auth=1" not in logged
    dumped = _run_dir_text(tmp_path / "vol" / "runs" / "job-hook-key-unresolved")
    assert unresolved not in dumped
    assert "cc_webhook_key" not in dumped
    assert unresolved not in result.stdout
    assert unresolved not in result.stderr


def test_cc_redact_redacts_webhook_key(tmp_path: Path) -> None:
    key = "whk_redact_not_a_real_secret"
    result = _run(
        [
            "bash",
            "-c",
            f'source {LIB} && cc_redact_oneline "Authorization: Bearer {key} extra={key}"',
        ],
        env={"CC_WEBHOOK_KEY": key},
    )
    assert result.returncode == 0, result.stderr
    assert key not in result.stdout
    assert "REDACTED" in result.stdout


def test_webhook_ping_failed_on_401_still_terminates(tmp_path: Path) -> None:
    curl = tmp_path / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
has_config=0
method=GET
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      has_config=1
      shift 2
      ;;
    -X)
      method="$2"
      shift 2
      ;;
    -o)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [[ "$has_config" == "1" ]]; then
  printf '401'
  exit 0
fi
if [[ "$method" == "DELETE" ]]; then
  if [[ -n "$out" && "$out" != "/dev/null" ]]; then
    printf '%s\\n' '{"id":"pod-hook-401"}' >"$out"
  fi
  printf '200'
  exit 0
fi
printf '500'
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
            "CC_JOB_ID": "job-hook-401",
            "CC_TTL_S": "60",
            "CC_IN_GPU_TESTS": "",
            "CC_WEBHOOK_URL": "https://example.invalid/hook",
            "RUNPOD_POD_ID": "pod-hook-401",
            "RUNPOD_API_KEY": "ok-key",
            **_job_dirs(tmp_path),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode != 0
    log = tmp_path / "vol" / "runs" / "job-hook-401" / "log.txt"
    text = log.read_text(encoding="utf-8")
    assert "webhook ping failed status=401 curl_rc=0" in text
    assert "webhook ping ok" not in text
    assert "example.invalid" not in text + result.stdout + result.stderr
    assert _stamp_path("pod-hook-401").is_file()
    assert not Path("/tmp/.cc_terminated.pod-hook-401").exists()


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
            "CC_IN_GPU_TESTS": "",
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
            "CC_IN_GPU_TESTS": "",
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
    assert f"python={py}" in text
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
    assert result.stderr.count("Refuse to start nested gpu_tests") == 1
    assert "CC_IN_GPU_TESTS is already set" in result.stderr
    assert not (tmp_path / "vol" / "runs" / "job-nested").exists()
    assert "Webhook ping" not in result.stdout
    assert "Webhook ping" not in result.stderr
    assert "webhook ping" not in result.stdout
    assert "webhook ping" not in result.stderr


def test_nested_gpu_tests_guard_inherits_and_uses_real_ml_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CC_IN_GPU_TESTS", "1")
    marker = tmp_path / "pytest-stub"
    py = tmp_path / "cc-python"
    py.write_text(
        f"""#!/usr/bin/env bash
echo STUB_CC_PYTHON
if [[ " $* " == *" -m pip "* ]]; then
  exit 0
fi
if [[ " $* " == *" -m pytest "* ]]; then
  echo PYTEST_STUB
  printf 'hit\\n' > "{marker}"
  exit 0
fi
export PYTHONPATH="{ROOT / "backend"}:{ROOT}${{PYTHONPATH:+:$PYTHONPATH}}"
exec /usr/bin/python3 "$@"
""",
        encoding="utf-8",
    )
    py.chmod(0o755)
    src = tmp_path / "src"
    (src / "backend").mkdir(parents=True)
    for name in (
        "requirements-gpu.txt",
        "requirements-dev.txt",
        "requirements-nodeps.txt",
    ):
        (src / "backend" / name).write_text("# pin\n", encoding="utf-8")
    job_env = {
        "CC_VOLUME_DIR": str(tmp_path / "vol"),
        "CC_JOB": "gpu_tests",
        "CC_GIT_REF": SHA40,
        "CC_JOB_ID": "job-e2e",
        "CC_TTL_S": "60",
        "CC_REPO_TOKEN": "tok",
        "CC_RUN_JOB_READY": "1",
        **_job_dirs(tmp_path, src=src),
        "CC_PYTHON": str(py),
    }
    refused = _run([str(RUN_JOB)], env=job_env, bin_dir=tmp_path)
    assert refused.returncode != 0
    assert "Refuse to start nested gpu_tests" in refused.stderr
    assert not (tmp_path / "vol" / "runs" / "job-e2e").exists()
    assert not marker.exists()

    run_dir = tmp_path / "vol" / "runs" / "job-ml"
    run_dir.mkdir(parents=True)
    direct = _run(
        [str(py), "-m", "ml.jobs", "gpu_tests", "--run-dir", str(run_dir)],
        env={"CC_PYTHON": str(py)},
        bin_dir=tmp_path,
    )
    assert direct.returncode == 1, direct.stderr + direct.stdout
    assert "Refuse to start nested gpu_tests" in direct.stderr
    assert not marker.exists()
    assert "PYTEST_STUB" not in direct.stdout
    assert "PYTEST_STUB" not in direct.stderr


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
    assert _stamp_path("pod-abc").is_file()
    assert not Path("/tmp/.cc_terminated.pod-abc").exists()
    assert not (tmp_path / "vol" / "runs" / "job-term" / ".cc_terminated").exists()
    assert result.stdout.count("terminate ok") == 1


def _count_curl_hits(path: Path) -> int:
    if not path.is_file():
        return 0
    return path.read_text(encoding="utf-8").count("curl")


def test_terminate_stamp_other_pod_or_unset_job_does_not_suppress(
    tmp_path: Path,
) -> None:
    hits = tmp_path / "curl.hits"
    _fake_curl(tmp_path, "200", '{"id":"pod-new"}')
    curl = tmp_path / "curl"
    original = curl.read_text(encoding="utf-8")
    curl.write_text(
        f'printf "%s\\n" curl >> "{hits}"\n' + original,
        encoding="utf-8",
    )
    curl.chmod(0o755)
    _stamp_path("other-pod").write_text("ok\n", encoding="utf-8")
    unknown = tmp_path / "vol" / "runs" / "unknown"
    unknown.mkdir(parents=True)
    (unknown / ".cc_terminated").write_text("ok\n", encoding="utf-8")
    reused = tmp_path / "vol" / "runs" / "job-reused"
    reused.mkdir(parents=True)
    (reused / ".cc_terminated").write_text("ok\n", encoding="utf-8")

    unset_job = _run(
        ["bash", "-c", f"source {LIB} && unset CC_JOB_ID && cc_terminate_self"],
        env={
            "RUNPOD_POD_ID": "pod-new",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
        },
        bin_dir=tmp_path,
    )
    assert unset_job.returncode == 0, unset_job.stderr
    assert _count_curl_hits(hits) == 1
    assert _stamp_path("pod-new").is_file()
    assert not Path("/tmp/.cc_terminated.pod-new").exists()
    _stamp_path("pod-new").unlink()

    reused_job = _run(
        ["bash", "-c", f"source {LIB} && cc_terminate_self"],
        env={
            "RUNPOD_POD_ID": "pod-reused",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_JOB_ID": "job-reused",
        },
        bin_dir=tmp_path,
    )
    assert reused_job.returncode == 0, reused_job.stderr
    assert _count_curl_hits(hits) == 2
    assert _stamp_path("pod-reused").is_file()
    assert not Path("/tmp/.cc_terminated.pod-reused").exists()
    _stamp_path("pod-reused").unlink()

    run_dir = tmp_path / "vol" / "runs" / "job-wd"
    run_dir.mkdir(parents=True)
    started = str(int(time.time()) - 120)
    (run_dir / "started_at").write_text(f"{started}\n", encoding="utf-8")
    watchdog = _run(
        [
            "bash",
            "-c",
            f"source {LIB} && unset CC_JOB_ID && cc_watchdog_start {run_dir} && sleep 2",
        ],
        env={
            "RUNPOD_POD_ID": "pod-wd",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
            "CC_TTL_S": "1",
        },
        bin_dir=tmp_path,
        timeout=5,
    )
    assert watchdog.returncode == 0, watchdog.stderr
    assert _count_curl_hits(hits) >= 3
    assert _stamp_path("pod-wd").is_file()
    assert not Path("/tmp/.cc_terminated.pod-wd").exists()
    assert "TTL 1s expired" in watchdog.stdout


def test_terminate_refuses_symlink_stamp_and_still_terminates(tmp_path: Path) -> None:
    hits = tmp_path / "curl.hits"
    _fake_curl(tmp_path, "200", '{"id":"pod-link"}')
    curl = tmp_path / "curl"
    original = curl.read_text(encoding="utf-8")
    curl.write_text(
        f'printf "%s\\n" curl >> "{hits}"\n' + original,
        encoding="utf-8",
    )
    curl.chmod(0o755)
    planted = tmp_path / "vol" / "planted-stamp"
    planted.write_text("ok\n", encoding="utf-8")
    stamp = _stamp_path("pod-link")
    stamp.symlink_to(planted)
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_terminate_self"],
        env={
            "RUNPOD_POD_ID": "pod-link",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert hits.read_text(encoding="utf-8").count("curl") == 1
    assert stamp.is_symlink()
    assert planted.read_text(encoding="utf-8") == "ok\n"
    assert "terminate ok" in result.stdout


def test_terminate_stamp_dir_refuses_volume_path(tmp_path: Path) -> None:
    volume = tmp_path / "vol"
    volume.mkdir(parents=True, exist_ok=True)
    hits = tmp_path / "curl.hits"
    _fake_curl(tmp_path, "200", '{"id":"pod-vol"}')
    curl = tmp_path / "curl"
    original = curl.read_text(encoding="utf-8")
    curl.write_text(
        f'printf "%s\\n" curl >> "{hits}"\n' + original,
        encoding="utf-8",
    )
    curl.chmod(0o755)
    result = _run(
        ["bash", "-c", f"source {LIB} && cc_terminate_self"],
        env={
            "RUNPOD_POD_ID": "pod-vol",
            "RUNPOD_API_KEY": "ok-key",
            "CC_VOLUME_DIR": str(volume),
            "CC_TERMINATE_STAMP_DIR": str(volume / "stamps"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert hits.read_text(encoding="utf-8").count("curl") == 1
    assert not (volume / "stamps" / ".cc_terminated.pod-vol").exists()
    assert "terminate ok" in result.stdout


def test_unwritable_run_log_still_terminates(tmp_path: Path) -> None:
    if not Path("/dev/full").exists():
        pytest.skip("/dev/full is not available")
    _fake_curl(tmp_path, "200", '{"id":"pod-ro-log"}')
    result = _run(
        [
            "bash",
            "-c",
            f"set -euo pipefail; source {LIB}; cc_terminate_self",
        ],
        env={
            "RUNPOD_POD_ID": "pod-ro-log",
            "RUNPOD_API_KEY": "ok-key",
            "CC_RUN_LOG": "/dev/full",
            "CC_VOLUME_DIR": str(tmp_path / "vol"),
        },
        bin_dir=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert _stamp_path("pod-ro-log").is_file()
    assert not Path("/tmp/.cc_terminated.pod-ro-log").exists()
    assert "terminate ok" in result.stdout


def test_unwritable_watchdog_run_dir_still_terminates(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-ro-wd"}')
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("file\n", encoding="utf-8")
    result = _watchdog_errexit(tmp_path, blocked, pod="pod-ro-wd")
    assert result.returncode == 0, result.stderr
    assert _stamp_path("pod-ro-wd").is_file()
    assert not Path("/tmp/.cc_terminated.pod-ro-wd").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout


def test_unwritable_watchdog_run_log_still_terminates(tmp_path: Path) -> None:
    if not Path("/dev/full").exists():
        pytest.skip("/dev/full is not available")
    _fake_curl(tmp_path, "200", '{"id":"pod-ro-wd-log"}')
    run_dir = tmp_path / "vol" / "runs" / "job-ro-wd-log"
    run_dir.mkdir(parents=True)
    started = str(int(time.time()) - 120)
    (run_dir / "started_at").write_text(f"{started}\n", encoding="utf-8")
    result = _watchdog_errexit(
        tmp_path,
        run_dir,
        pod="pod-ro-wd-log",
        unset_log=False,
        extra={"CC_RUN_LOG": "/dev/full"},
    )
    assert result.returncode == 0, result.stderr
    assert _stamp_path("pod-ro-wd-log").is_file()
    assert not Path("/tmp/.cc_terminated.pod-ro-wd-log").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout


def test_watchdog_started_at_read_is_fail_safe() -> None:
    text = LIB.read_text(encoding="utf-8")
    fn = text.split("cc_watchdog_start()")[1].split("cc_require_repo_token()")[0]
    assert '-e "${run_dir}/started_at"' in fn
    assert '-f "${run_dir}/started_at"' not in fn
    assert "2>/dev/null || true" in fn
    assert "10#$started" in fn
    ttl = text.split("cc_parse_ttl()")[1].split("cc_require_ttl()")[0]
    assert "10#$raw" in ttl
    assert "10#$n" in ttl


def test_unreadable_started_at_still_terminates(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-wd-unread"}')
    run_dir = tmp_path / "vol" / "runs" / "job-wd-unread"
    run_dir.mkdir(parents=True)
    (run_dir / "started_at").mkdir()
    result = _watchdog_errexit(tmp_path, run_dir, pod="pod-wd-unread")
    assert result.returncode == 0, result.stderr
    assert _stamp_path("pod-wd-unread").is_file()
    assert not Path("/tmp/.cc_terminated.pod-wd-unread").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout
    watchdog = LIB.read_text(encoding="utf-8").split("cc_watchdog_start()")[1]
    watchdog = watchdog.split("cc_require_repo_token()")[0]
    assert '-e "${run_dir}/started_at"' in watchdog
    assert "2>/dev/null || true" in watchdog


@pytest.mark.parametrize(
    ("value", "pod"),
    [
        ("abc", "pod-wd-abc"),
        ("1.5", "pod-wd-1p5"),
        ("17e9", "pod-wd-17e9"),
        ("089", "pod-wd-089"),
        ("0999", "pod-wd-0999"),
    ],
)
def test_non_numeric_started_at_still_terminates(
    tmp_path: Path, value: str, pod: str
) -> None:
    _fake_curl(tmp_path, "200", f'{{"id":"{pod}"}}')
    run_dir = tmp_path / "vol" / "runs" / pod
    run_dir.mkdir(parents=True)
    (run_dir / "started_at").write_text(f"{value}\n", encoding="utf-8")
    result = _watchdog_errexit(tmp_path, run_dir, pod=pod)
    assert result.returncode == 0, result.stderr
    assert _stamp_path(pod).is_file()
    assert not Path(f"/tmp/.cc_terminated.{pod}").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout


def test_started_at_injection_does_not_run(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-wd-inj"}')
    run_dir = tmp_path / "vol" / "runs" / "job-wd-inj"
    run_dir.mkdir(parents=True)
    marker = tmp_path / "pwned"
    (run_dir / "started_at").write_text(
        f"PATH[$(touch {marker})]\n",
        encoding="utf-8",
    )
    result = _watchdog_errexit(tmp_path, run_dir, pod="pod-wd-inj")
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert _stamp_path("pod-wd-inj").is_file()
    assert not Path("/tmp/.cc_terminated.pod-wd-inj").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout


def test_future_started_at_still_terminates(tmp_path: Path) -> None:
    _fake_curl(tmp_path, "200", '{"id":"pod-wd-future"}')
    run_dir = tmp_path / "vol" / "runs" / "job-wd-future"
    run_dir.mkdir(parents=True)
    (run_dir / "started_at").write_text("9999999999\n", encoding="utf-8")
    result = _watchdog_errexit(tmp_path, run_dir, pod="pod-wd-future")
    assert result.returncode == 0, result.stderr
    assert _stamp_path("pod-wd-future").is_file()
    assert not Path("/tmp/.cc_terminated.pod-wd-future").exists()
    assert "TTL 1s expired" in result.stdout
    assert "terminate ok" in result.stdout


def test_run_times_out(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="timed out"):
        _run(["bash", "-c", "sleep 5"], env=_job_dirs(tmp_path), timeout=0.2)


def test_run_times_out_kills_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    script = (
        f"sleep 60 &\n"
        f"echo $! > '{pidfile}'\n"
        "wait\n"
    )
    with pytest.raises(AssertionError, match="timed out"):
        _run(["bash", "-c", script], env=_job_dirs(tmp_path), timeout=0.4)
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _pid_is_dead(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"grandchild {pid} still running")


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
            "CC_IN_GPU_TESTS": "",
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


def test_safe_wipe_refuses_tmpdir_sibling_cc_src_alt(tmp_path: Path) -> None:
    # TMPDIR=/tmp/cc-src-alt is a sibling cc-src-* path. Distrust it.
    # Do not create /tmp/cc-src-alt.
    nest = Path("/tmp/cc-src-alt")
    target = nest / "cc-src"
    assert not nest.exists()
    result = _wipe(tmp_path, str(target), env={"TMPDIR": str(nest)})
    assert result.returncode != 0
    assert "Parent must be /tmp" in result.stderr
    assert not nest.exists()
    assert not target.exists()


def test_safe_wipe_refuses_tmpdir_under_tmp_cc_src(tmp_path: Path) -> None:
    # Parent is $TMPDIR, so a trusted TMPDIR would allow the wipe.
    # TMPDIR is under /tmp/cc-src, so the new rule must clear it.
    # The path must not exist. Do not create anything under /tmp/cc-src.
    nest = Path("/tmp/cc-src/cc-missing-tmpdir")
    target = nest / "cc-src"
    assert not nest.exists()
    result = _wipe(tmp_path, str(target), env={"TMPDIR": str(nest)})
    assert result.returncode != 0
    assert "Parent must be /tmp" in result.stderr
    assert not nest.exists()
    assert not target.exists()


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
            "CC_IN_GPU_TESTS": "",
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
    exists_fn = text.split("cc_s3_object_exists()")[1].split("cc_s3_run_exists()")[0]
    assert "s3api head-object" in exists_fn
    assert "s3api get-object" not in exists_fn
    assert "aws s3 cp" not in text


def test_run_logged_fifo_uses_mktemp_dir() -> None:
    text = LIB.read_text(encoding="utf-8")
    assert 'fifo_dir="$(mktemp -d)"' in text
    assert "mktemp -u" not in text
    logged = text.split("cc_run_logged()")[1].split("cc_run_timeout()")[0]
    assert "cc_redact_stream <\"$fifo\" | tee -a" in logged
    assert "wait \"$reader\"" in logged
    assert "cc_redact_oneline" in text
    assert "trap 'rm -f" not in text
    assert "jq -c" in WAIT_JOB.read_text(encoding="utf-8")
    curl_fn = LIB.read_text(encoding="utf-8").split("cc_curl_post_json()")[1]
    curl_fn = curl_fn.split("cc_log_webhook_ping")[0]
    assert "return 1" in curl_fn
    assert "cc_fail" not in curl_fn
    assert "--max-time 15" in curl_fn
    assert "-o /dev/null" in curl_fn
    assert "-w '%{http_code}'" in curl_fn
    assert "2>/dev/null" in curl_fn


def test_webhook_url_stays_off_curl_argv() -> None:
    for path in (LIB, RUN_JOB):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "curl " in line:
                assert "CC_WEBHOOK_URL" not in line
                assert "WEBHOOK_URL" not in line
                assert "CC_WEBHOOK_KEY" not in line
                assert "WEBHOOK_KEY" not in line
                assert "Authorization" not in line
                assert "Bearer" not in line
    text = LIB.read_text(encoding="utf-8")
    assert "RUNPOD_SECRET_cc_webhook_key" in text
    assert "header = \\\"Authorization: Bearer" in text
    curl_fn = text.split("cc_curl_post_json()")[1].split("cc_log_webhook_ping")[0]
    assert "--config" in curl_fn
    assert "chmod 600" in curl_fn


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
