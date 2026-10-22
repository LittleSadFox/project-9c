"""sync_volume.sh must not touch AWS config and must refuse oversize files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SYNC = ROOT / "scripts" / "sync_volume.sh"
LIB = ROOT / "scripts" / "gpu" / "lib.sh"

MAX_PUT = 150 * 1024 * 1024
S3_NOT_FOUND = (
    "An error occurred (NoSuchKey) when calling the GetObject operation: "
    "The specified key does not exist."
)


def _aws_stub(tmp_path: Path) -> tuple[Path, Path, bytes]:
    log = tmp_path / "aws.log"
    store = tmp_path / "s3-store"
    store.mkdir()
    videos_manifest = store / "videos" / "manifest.json"
    videos_manifest.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"files":{"keep":true}}\n'
    videos_manifest.write_bytes(original)
    aws = tmp_path / "aws"
    aws.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'AWS_CONFIG_FILE=%s\\n' "${{AWS_CONFIG_FILE-<unset>}}" >> "{log}"
printf 'HOME=%s\\n' "${{HOME-<unset>}}" >> "{log}"
printf 'argv=%s\\n' "$*" >> "{log}"
cmd=""
key=""
body=""
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    s3api)
      cmd="$2"
      shift 2
      ;;
    --key)
      key="$2"
      shift 2
      ;;
    --body)
      body="$2"
      shift 2
      ;;
    --bucket|--region|--endpoint-url|--profile)
      shift 2
      ;;
    *)
      if [[ -z "$out" && "$1" != --* ]]; then
        out="$1"
      fi
      shift
      ;;
  esac
done
printf 'cmd=%s key=%s\\n' "$cmd" "$key" >> "{log}"
if [[ "$cmd" == "get-object" || "$cmd" == "head-object" ]]; then
  echo "{S3_NOT_FOUND}" >&2
  exit 254
fi
if [[ "$cmd" == "put-object" ]]; then
  dest="{store}/$key"
  mkdir -p "$(dirname "$dest")"
  if [[ -n "$body" && -f "$body" ]]; then
    cp "$body" "$dest"
  else
    printf '{{}}\\n' >"$dest"
  fi
  exit 0
fi
echo "ERROR: unexpected aws command" >&2
exit 1
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)
    return aws, log, original


def _home_aws_config(tmp_path: Path) -> tuple[Path, Path, bytes]:
    home = tmp_path / "home"
    aws_dir = home / ".aws"
    aws_dir.mkdir(parents=True)
    cfg = aws_dir / "config"
    payload = (
        b"[profile keep]\n"
        b"region = eu-west-1\n"
        b"output = json\n"
    )
    cfg.write_bytes(payload)
    return home, cfg, payload


def _sync_env(
    tmp_path: Path,
    home: Path,
    golden: Path,
    library: Path,
    caller_cfg: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CC_") or key.startswith("RUNPOD_"):
            env.pop(key, None)
    env["HOME"] = str(home)
    env["AWS_CONFIG_FILE"] = str(caller_cfg)
    env["CC_GOLDEN_DIR"] = str(golden)
    env["CC_LIBRARY_DIR"] = str(library)
    env["CC_VOLUME_ID"] = "vol-1"
    env["CC_VOLUME_DC"] = "EU-RO-1"
    env["CC_RUNPOD_VOLUME_ID"] = "vol-1"
    env["CC_RUNPOD_DATACENTER"] = "EU-RO-1"
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run_sync(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_sync_volume_source_and_run_leave_aws_config_untouched(tmp_path: Path) -> None:
    home, home_cfg, home_bytes = _home_aws_config(tmp_path)
    caller_cfg = tmp_path / "caller-aws-config"
    caller_bytes = b"[profile caller]\nregion = us-east-1\n"
    caller_cfg.write_bytes(caller_bytes)
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    (golden / "clip.mp4").write_bytes(b"clip-bytes")
    _aws, log, original = _aws_stub(tmp_path)
    env = _sync_env(tmp_path, home, golden, library, caller_cfg)
    after_file = tmp_path / "after-aws-config-file"
    wrapper = tmp_path / "source_sync.sh"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
set -uo pipefail
export AWS_CONFIG_FILE="{caller_cfg}"
trap 'printf "%s\\n" "${{AWS_CONFIG_FILE-<unset>}}" > "{after_file}"' DEBUG
source "{SYNC}" --prefix scratch
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = _run_sync([str(wrapper)], env)
    assert result.returncode == 0, result.stderr
    assert after_file.read_text(encoding="utf-8").strip() == str(caller_cfg)
    assert caller_cfg.read_bytes() == caller_bytes
    assert home_cfg.read_bytes() == home_bytes
    logged = log.read_text(encoding="utf-8")
    assert f"AWS_CONFIG_FILE={caller_cfg}" in logged
    assert str(home_cfg) not in logged
    assert "videos/manifest.json" not in logged
    assert (tmp_path / "s3-store" / "videos" / "manifest.json").read_bytes() == original


def test_sync_volume_prefix_scratch_never_touches_videos_manifest(
    tmp_path: Path,
) -> None:
    home, home_cfg, home_bytes = _home_aws_config(tmp_path)
    caller_cfg = tmp_path / "caller-aws-config"
    caller_cfg.write_text("[profile caller]\nregion = us-east-1\n", encoding="utf-8")
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    (golden / "clip.mp4").write_bytes(b"clip-bytes")
    _aws, log, original = _aws_stub(tmp_path)
    env = _sync_env(tmp_path, home, golden, library, caller_cfg)
    result = _run_sync([str(SYNC), "--prefix", "scratch"], env)
    assert result.returncode == 0, result.stderr
    logged = log.read_text(encoding="utf-8")
    assert "key=scratch/clip.mp4" in logged
    assert "key=scratch/manifest.json" in logged
    assert "key=videos/manifest.json" not in logged
    assert f"AWS_CONFIG_FILE={caller_cfg}" in logged
    assert (tmp_path / "s3-store" / "videos" / "manifest.json").read_bytes() == original
    assert (tmp_path / "s3-store" / "scratch" / "manifest.json").is_file()
    assert (tmp_path / "s3-store" / "scratch" / "clip.mp4").read_bytes() == b"clip-bytes"
    assert home_cfg.read_bytes() == home_bytes
    assert caller_cfg.read_text(encoding="utf-8") == (
        "[profile caller]\nregion = us-east-1\n"
    )


def test_sync_volume_refuses_file_over_150mib_before_upload(tmp_path: Path) -> None:
    home, home_cfg, home_bytes = _home_aws_config(tmp_path)
    caller_cfg = tmp_path / "caller-aws-config"
    caller_cfg.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    (golden / "ok.mp4").write_bytes(b"small")
    huge = golden / "huge.mp4"
    huge.touch()
    os.truncate(huge, MAX_PUT + 1)
    _aws, log, original = _aws_stub(tmp_path)
    env = _sync_env(tmp_path, home, golden, library, caller_cfg)
    result = _run_sync([str(SYNC)], env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "huge.mp4" in combined
    assert "150MiB" in combined
    assert str(MAX_PUT) in combined
    assert "Multipart is not supported yet" in combined
    assert not log.exists() or "put-object" not in log.read_text(encoding="utf-8")
    assert (tmp_path / "s3-store" / "videos" / "manifest.json").read_bytes() == original
    assert home_cfg.read_bytes() == home_bytes
    assert caller_cfg.read_text(encoding="utf-8") == "[default]\nregion = us-east-1\n"


@pytest.mark.parametrize(
    "prefix",
    ["videos/.", "a//b", "..", "/abs", "trail/", ".", "videos/./x"],
)
def test_sync_volume_refuses_unsafe_prefix(tmp_path: Path, prefix: str) -> None:
    home, home_cfg, home_bytes = _home_aws_config(tmp_path)
    caller_cfg = tmp_path / "caller-aws-config"
    caller_cfg.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    _aws_stub(tmp_path)
    env = _sync_env(tmp_path, home, golden, library, caller_cfg)
    result = _run_sync([str(SYNC), "--prefix", prefix], env)
    assert result.returncode != 0
    assert "Invalid --prefix" in result.stderr
    assert home_cfg.read_bytes() == home_bytes
    assert caller_cfg.read_text(encoding="utf-8") == "[default]\nregion = us-east-1\n"


def test_sync_volume_dry_run_prefix_scratch_prints_prefix(tmp_path: Path) -> None:
    home, _home_cfg, _home_bytes = _home_aws_config(tmp_path)
    caller_cfg = tmp_path / "caller-aws-config"
    caller_cfg.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    golden = tmp_path / "golden"
    library = tmp_path / "library"
    golden.mkdir()
    library.mkdir()
    env = _sync_env(tmp_path, home, golden, library, caller_cfg)
    result = _run_sync([str(SYNC), "--dry-run", "--prefix", "scratch"], env)
    assert result.returncode == 0, result.stderr
    assert "prefix=scratch" in result.stdout
    assert "videos/manifest.json" not in result.stdout


def test_sync_volume_script_never_assigns_aws_config_file() -> None:
    text = SYNC.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "export AWS_CONFIG_FILE" not in code
    assert "AWS_CONFIG_FILE=" not in code
    assert "cc_aws_export_multipart_config" not in code
    assert "~/.aws/config" not in code
    assert "--prefix" in text
    assert "150MiB" in text
    assert "157286400" in text or "150 * 1024 * 1024" in text
    assert "BASH_SOURCE[0]" in text
    lib = LIB.read_text(encoding="utf-8")
    assert "cc_aws_export_multipart_config" not in lib
    assert "export AWS_CONFIG_FILE" not in lib
