#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

DATA_ROOT="${HOME}/Library/Application Support/ClimbingCoach"
LIB_DIR="${CC_LIBRARY_DIR:-$DATA_ROOT/library}"
MODELS_DIR="${CC_MODELS_DIR:-$DATA_ROOT/models}"
GOLDEN_DIR="${CC_GOLDEN_DIR:-$DATA_ROOT/golden}"
mkdir -p "$LIB_DIR" "$MODELS_DIR" "$GOLDEN_DIR"
for name in originals proxies thumbs pose align clips renders models exports trash tmp; do
  mkdir -p "$LIB_DIR/$name"
done

if [[ ! -d "$ROOT/frontend/dist" ]]; then
  echo "Build the frontend first: scripts/build.sh"
  "$ROOT/scripts/build.sh"
fi

TOKEN="${CC_LAUNCH_TOKEN:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export CC_LIBRARY_DIR="$LIB_DIR"
export CC_MODELS_DIR="$MODELS_DIR"
export CC_GOLDEN_DIR="$GOLDEN_DIR"
export CC_LAUNCH_TOKEN="$TOKEN"
export CC_HOST="${CC_HOST:-127.0.0.1}"
export CC_PORT="${CC_PORT:-8810}"
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

LAUNCH="http://${CC_HOST}:${CC_PORT}/auth/launch?token=${TOKEN}"
echo "Open the launch URL:"
echo "  $LAUNCH"

if [[ "$(uname -s)" == "Darwin" ]]; then
  open "$LAUNCH"
fi

exec uvicorn app.main:app_factory --factory --host "$CC_HOST" --port "$CC_PORT"
