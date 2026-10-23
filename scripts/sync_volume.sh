#!/usr/bin/env bash
# Copy new golden videos and labels.json to the Runpod volume.
# Copy file by file. Skip files already listed in <prefix>/manifest.json.
# Do not invent credentials. Read ids and the S3 endpoint from the environment.
# Do not change AWS_CONFIG_FILE. Do not write ~/.aws/config.
# put-object is the only upload path. Refuse files over 150MiB before any upload.
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
      echo "put-object refuses files over 150MiB. Multipart is not supported yet."
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

# Refuse oversize files before any S3 call. Do not touch AWS_CONFIG_FILE.
python3 - "$GOLDEN" "$MAX_PUT_BYTES" <<'PY'
import sys
from pathlib import Path

golden = Path(sys.argv[1])
max_put = int(sys.argv[2])
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc", ".3gp"}
too_big: list[tuple[str, int]] = []

def check(rel: str, path: Path) -> None:
    size = path.stat().st_size
    if size > max_put:
        too_big.append((rel, size))

labels = golden / "labels" / "labels.json"
if labels.is_file():
    check("labels/labels.json", labels)
if golden.is_dir():
    for path in sorted(golden.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        check(path.relative_to(golden).as_posix(), path)

if too_big:
    for rel, size in too_big:
        sys.stderr.write(
            f"ERROR: {rel} is {size} bytes. put-object refuses files over 150MiB ({max_put} bytes). Multipart is not supported yet.\n"
        )
    sys.exit(1)
PY

MANIFEST_LOCAL="$(mktemp)"
NEW_MANIFEST="$(mktemp)"
trap 'rm -f "$MANIFEST_LOCAL" "$NEW_MANIFEST"' EXIT
if cc_s3_cp_stdout "s3://${VOLUME}/${PREFIX}/manifest.json" "$REGION" "$ENDPOINT" \
  >"$MANIFEST_LOCAL"; then
  :
else
  echo '{"files":{}}' >"$MANIFEST_LOCAL"
fi

python3 - "$MANIFEST_LOCAL" "$NEW_MANIFEST" "$GOLDEN" "$VOLUME" "$PREFIX" "$REGION" "$ENDPOINT" "$MAX_PUT_BYTES" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

manifest_path, new_path, golden_s, volume, prefix, region, endpoint, max_put_s = sys.argv[1:9]
max_put = int(max_put_s)
golden = Path(golden_s)
try:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
except json.JSONDecodeError:
    manifest = {}
files = manifest.get("files")
if not isinstance(files, dict):
    files = {}

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc", ".3gp"}

def digest(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

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

candidates: list[tuple[str, Path]] = []
labels = golden / "labels" / "labels.json"
if labels.is_file():
    candidates.append(("labels/labels.json", labels))
if golden.is_dir():
    for path in sorted(golden.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        rel = path.relative_to(golden).as_posix()
        candidates.append((rel, path))

for key, path in candidates:
    size = path.stat().st_size
    if size > max_put:
        print(
            f"ERROR: {key} is {size} bytes. put-object refuses files over 150MiB ({max_put} bytes). Multipart is not supported yet.",
            file=sys.stderr,
        )
        sys.exit(1)

for key, path in candidates:
    actual = digest(path)
    listed = files.get(key)
    listed_sha = listed.get("sha256") if isinstance(listed, dict) else None
    if listed_sha == actual:
        print(f"skip {key}")
        continue
    print(f"upload {key}")
    aws_put(path, key)
    files[key] = {"sha256": actual, "size": path.stat().st_size}

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
