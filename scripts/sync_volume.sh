#!/usr/bin/env bash
# Copy new golden videos and labels.json to the Runpod volume.
# Copy file by file. Skip files already listed in <prefix>/manifest.json.
# Do not invent credentials. Read ids and the S3 endpoint from the environment.
# Do not change AWS_CONFIG_FILE. Do not write ~/.aws/config.
# put-object is the only upload path. Multipart is not used.
# A video over 150MiB is transcoded to H.264 1080p first (CC_FFMPEG_BIN argv).
# Refuse a file that is still over 150MiB before any upload.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cc_valid_sync_prefix() {
  local prefix="$1"
  [[ -n "$prefix" ]] || return 1
  [[ "$prefix" != /* ]] || return 1
  [[ "$prefix" != */ ]] || return 1
  [[ "$prefix" != *..* ]] || return 1
  [[ "$prefix" != *//* ]] || return 1
  [[ "$prefix" != . && "$prefix" != */. ]] || return 1
  [[ "$prefix" != */./* ]] || return 1
  [[ "$prefix" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,126}$ ]]
}

DRY_RUN=0
PREFIX="videos"
MAX_PUT_BYTES=$((150 * 1024 * 1024))

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --prefix)
      cc_require_optarg "$1" "${2:-}"
      PREFIX="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: scripts/sync_volume.sh [--dry-run] [--prefix <path>]"
      echo "Default prefix is videos."
      echo "A prefix other than videos does not write videos/manifest.json."
      echo "A video over 150MiB is transcoded to H.264 1080p first."
      echo "put-object refuses a file that is still over 150MiB. Multipart is not supported yet."
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

cc_valid_sync_prefix "$PREFIX" || fail "Invalid --prefix. Use a relative path of [A-Za-z0-9._/-] without .. or a leading slash."

if [ -n "${CC_GOLDEN_DIR:-}" ]; then
  GOLDEN="$CC_GOLDEN_DIR"
else
  GOLDEN="${HOME}/Library/Application Support/ClimbingCoach/golden"
fi

VOLUME="$(cc_volume_id)"
ENDPOINT="$(cc_s3_endpoint)"
REGION="${CC_VOLUME_DC:-${CC_RUNPOD_DATACENTER:-}}"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "volume=${VOLUME}"
  echo "endpoint=${ENDPOINT}"
  echo "region=${REGION}"
  echo "golden=${GOLDEN}"
  echo "prefix=${PREFIX}"
  exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "Python 3 is required."
if [ ! -d "$GOLDEN" ]; then
  mkdir -p "$GOLDEN"
fi

echo "Export labels"
python3 "$ROOT/scripts/export_labels.py" --golden-dir "$GOLDEN"

command -v aws >/dev/null 2>&1 || fail "Install AWS CLI v2 from the official installer."
if [ -n "${CC_AWS_PROFILE:-}" ]; then
  export AWS_PROFILE="$CC_AWS_PROFILE"
fi

MANIFEST_LOCAL="$(mktemp)"
NEW_MANIFEST="$(mktemp)"
PLAN="$(mktemp)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK" "$MANIFEST_LOCAL" "$NEW_MANIFEST" "$PLAN"' EXIT
if cc_s3_cp_stdout "s3://${VOLUME}/${PREFIX}/manifest.json" "$REGION" "$ENDPOINT" \
  >"$MANIFEST_LOCAL"; then
  :
else
  echo '{"files":{}}' >"$MANIFEST_LOCAL"
fi

# Transcode oversize videos before any put-object. Fail if a body is still over 150MiB.
python3 "$ROOT/scripts/sync_volume_prep.py" \
  --golden "$GOLDEN" \
  --manifest "$MANIFEST_LOCAL" \
  --plan "$PLAN" \
  --work "$WORK" \
  --max-put "$MAX_PUT_BYTES"

# Do not touch AWS_CONFIG_FILE.
python3 - "$PLAN" "$NEW_MANIFEST" "$VOLUME" "$PREFIX" "$REGION" "$ENDPOINT" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

plan_path, new_path, volume, prefix, region, endpoint = sys.argv[1:7]
plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
files = plan.get("files")
if not isinstance(files, dict):
    files = {}
uploads = plan.get("uploads")
if not isinstance(uploads, list):
    uploads = []

def aws_put(path: Path, key: str) -> None:
    cmd = [
        "aws",
        "s3api",
        "put-object",
        "--bucket",
        volume,
        "--key",
        f"{prefix}/{key}",
        "--body",
        str(path),
        "--region",
        region,
        "--endpoint-url",
        endpoint,
    ]
    profile = os.environ.get("CC_AWS_PROFILE") or os.environ.get("AWS_PROFILE")
    if profile:
        cmd.extend(["--profile", profile])
    subprocess.run(cmd, check=True)

for item in uploads:
    if not isinstance(item, dict):
        print("ERROR: upload plan is invalid.", file=sys.stderr)
        sys.exit(1)
    key = item.get("key")
    raw_path = item.get("path")
    if not isinstance(key, str) or not isinstance(raw_path, str):
        print("ERROR: upload plan is invalid.", file=sys.stderr)
        sys.exit(1)
    path = Path(raw_path)
    print(f"upload {key}")
    aws_put(path, key)

Path(new_path).write_text(json.dumps({"files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

# Write the manifest only under the chosen prefix.
# A prefix other than videos never touches videos/manifest.json.
# shellcheck disable=SC2046
aws s3api put-object \
  --bucket "$VOLUME" \
  --key "${PREFIX}/manifest.json" \
  --body "$NEW_MANIFEST" \
  --region "$REGION" \
  --endpoint-url "$ENDPOINT" \
  $(cc_aws_args) >/dev/null
echo "sync_volume.sh finished."
