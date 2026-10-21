#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

echo "Check Python 3.12"
if command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  fail "Install Python 3.12 from python.org."
fi
PY_VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$PY_VER" == "3.12" ]] || fail "Python is $PY_VER. Install Python 3.12."

echo "Check Node 24"
command -v node >/dev/null 2>&1 || fail "Install Node 24 LTS from nodejs.org."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" == "24" ]] || fail "Node is $(node -v). Install Node 24 LTS."

echo "Check ffmpeg 7+"
FFMPEG_BIN="${CC_FFMPEG_BIN:-ffmpeg}"
command -v "$FFMPEG_BIN" >/dev/null 2>&1 || fail "Install ffmpeg 7 or later."
"$FFMPEG_BIN" -version | head -n 1 | grep -Eq 'ffmpeg version n?[7-9]\.' \
  || fail "ffmpeg must be version 7 or later."

echo "Check AWS CLI v2"
command -v aws >/dev/null 2>&1 || fail "Install AWS CLI v2 from the official installer."
aws --version 2>&1 | grep -Eq 'aws-cli/2\.' || fail "AWS CLI must be version 2."

echo "Create .venv"
"$PY" -m venv "$ROOT/.venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pip install -r backend/requirements-dev.txt
python -m pip install --no-deps -r backend/requirements-nodeps.txt

echo "Install frontend pins"
(cd frontend && npm ci)

echo "Install Playwright browsers"
if [[ "$(uname -s)" == "Darwin" ]]; then
  MAC_VER="$(sw_vers -productVersion | cut -d. -f1)"
  if [[ "$MAC_VER" -ge 15 ]]; then
    (cd frontend && npx playwright install --with-deps chromium webkit)
  else
    (cd frontend && npx playwright install --with-deps chromium)
  fi
else
  (cd frontend && npx playwright install --with-deps chromium)
fi

DATA_ROOT="${HOME}/Library/Application Support/ClimbingCoach"
echo "Create library folders in $DATA_ROOT"
mkdir -p "$DATA_ROOT/library" "$DATA_ROOT/library-dev" "$DATA_ROOT/models" \
  "$DATA_ROOT/golden" "$DATA_ROOT/reports"
for name in originals proxies thumbs pose align clips renders models exports trash tmp; do
  mkdir -p "$DATA_ROOT/library/$name" "$DATA_ROOT/library-dev/$name"
done

export CC_MODELS_DIR="${CC_MODELS_DIR:-$DATA_ROOT/models}"
echo "Download base ONNX weights into $CC_MODELS_DIR"
python scripts/download_models.py

echo "setup_mac.sh finished."
