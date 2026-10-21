#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

DATA_ROOT="${HOME}/Library/Application Support/ClimbingCoach"
LIB_DIR="${CC_LIBRARY_DIR:-$DATA_ROOT/library-dev}"
MODELS_DIR="${CC_MODELS_DIR:-$DATA_ROOT/models}"
GOLDEN_DIR="${CC_GOLDEN_DIR:-$DATA_ROOT/golden}"
mkdir -p "$LIB_DIR" "$MODELS_DIR" "$GOLDEN_DIR"
for name in originals proxies thumbs pose align clips renders models exports trash tmp; do
  mkdir -p "$LIB_DIR/$name"
done

TOKEN="${CC_LAUNCH_TOKEN:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export CC_LIBRARY_DIR="$LIB_DIR"
export CC_MODELS_DIR="$MODELS_DIR"
export CC_GOLDEN_DIR="$GOLDEN_DIR"
export CC_LAUNCH_TOKEN="$TOKEN"
export CC_DEV="${CC_DEV:-1}"
export CC_POSE_BACKEND="${CC_POSE_BACKEND:-fixture}"
export CC_HOST="${CC_HOST:-127.0.0.1}"
export CC_PORT="${CC_PORT:-8810}"
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
  if [[ -n "${BACK_PID:-}" ]]; then
    kill "$BACK_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONT_PID:-}" ]]; then
    kill "$FRONT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "Backend on ${CC_HOST}:${CC_PORT}"
uvicorn app.main:app_factory --factory --reload --host "$CC_HOST" --port "$CC_PORT" &
BACK_PID=$!

echo "Vite on 127.0.0.1:8811"
(cd frontend && npm run dev) &
FRONT_PID=$!

LAUNCH="http://127.0.0.1:8811/auth/launch?token=${TOKEN}"
echo "Open the launch URL:"
echo "  $LAUNCH"

wait
