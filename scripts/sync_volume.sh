#!/usr/bin/env bash
# Copy new golden videos and labels.json to the Runpod volume.
# Copy file by file. Skip files already listed in videos/manifest.json.
# Do not invent credentials. Read ids and the S3 endpoint from the environment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      echo "Usage: scripts/sync_volume.sh [--dry-run]"
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

if [ -n "${CC_GOLDEN_DIR:-}" ]; then
  GOLDEN="$CC_GOLDEN_DIR"
else
  GOLDEN="${HOME}/Library/Application Support/ClimbingCoach/golden"
fi

VOLUME="$(cc_volume_id)"
ENDPOINT="$(cc_s3_endpoint)"
REGION="${CC_VOLUME_DC:-${CC_RUNPOD_DATACENTER:-}}"
PREFIX="videos"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "volume=${VOLUME}"
  echo "endpoint=${ENDPOINT}"
  echo "region=${REGION}"
  echo "golden=${GOLDEN}"
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
trap 'rm -f "$MANIFEST_LOCAL" "$NEW_MANIFEST"' EXIT
# shellcheck disable=SC2046
if aws s3 cp "s3://${VOLUME}/${PREFIX}/manifest.json" "$MANIFEST_LOCAL" \
  --region "$REGION" --endpoint-url "$ENDPOINT" $(cc_aws_args) >/dev/null 2>&1; then
  :
else
  echo '{"files":{}}' >"$MANIFEST_LOCAL"
fi

python3 - "$MANIFEST_LOCAL" "$NEW_MANIFEST" "$GOLDEN" "$VOLUME" "$PREFIX" "$REGION" "$ENDPOINT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

manifest_path, new_path, golden_s, volume, prefix, region, endpoint = sys.argv[1:8]
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
    actual = digest(path)
    listed = files.get(key)
    listed_sha = listed.get("sha256") if isinstance(listed, dict) else None
    if listed_sha == actual:
        print(f"skip {key}")
        continue
    dest = f"s3://{volume}/{prefix}/{key}"
    print(f"upload {key}")
    subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            str(path),
            dest,
            "--region",
            region,
            "--endpoint-url",
            endpoint,
        ],
        check=True,
    )
    files[key] = {"sha256": actual, "size": path.stat().st_size}

Path(new_path).write_text(json.dumps({"files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

# shellcheck disable=SC2046
aws s3 cp "$NEW_MANIFEST" "s3://${VOLUME}/${PREFIX}/manifest.json" \
  --region "$REGION" --endpoint-url "$ENDPOINT" $(cc_aws_args)
echo "sync_volume.sh finished."
