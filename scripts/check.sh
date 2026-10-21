#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ALL=0
if [[ "${1:-}" == "--all" ]]; then
  ALL=1
fi

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

export PYTHONPATH="$ROOT/backend:$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$ALL" == "1" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    export CC_REQUIRE="${CC_REQUIRE:-media,model,macos}"
  else
    export CC_REQUIRE="${CC_REQUIRE:-media,model}"
  fi
  PYTEST_MARK=""
else
  PYTEST_MARK='not model and not gpu and not macos and not golden and not slow'
fi

echo "Ruff"
ruff check backend ml scripts/export_labels.py scripts/download_models.py

if command -v shellcheck >/dev/null 2>&1; then
  echo "Shellcheck"
  shellcheck -x scripts/gpu/*.sh scripts/sync_volume.sh docker/gpu/entrypoint.sh
fi

echo "Mypy"
mypy --config-file backend/pyproject.toml backend/app ml

echo "Pytest"
if [[ -n "$PYTEST_MARK" ]]; then
  pytest backend/tests -m "$PYTEST_MARK"
else
  pytest backend/tests
fi

echo "Vitest"
(cd frontend && npm test)

echo "Frontend build"
(cd frontend && npm run build)

echo "Playwright Chromium"
(cd frontend && npx playwright test --project=chromium)

if [[ "$(uname -s)" == "Darwin" ]]; then
  MAC_VER="$(sw_vers -productVersion | cut -d. -f1)"
  if [[ "$MAC_VER" -ge 15 ]]; then
    echo "Playwright WebKit"
    (cd frontend && npx playwright test --project=webkit)
  fi
fi

echo "check.sh finished."
