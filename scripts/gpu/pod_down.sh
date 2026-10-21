#!/usr/bin/env bash
# Terminate one pod by id and wait until it is gone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

usage() {
  echo "Usage: scripts/gpu/pod_down.sh <pod_id> [--dry-run]"
}

POD_ID=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$POD_ID" ]]; then
        POD_ID="$1"
        shift
      else
        cc_fail "Unknown argument: $1"
      fi
      ;;
  esac
done

[[ -n "$POD_ID" ]] || cc_fail "Pass a pod id."
cc_valid_pod_id "$POD_ID" || cc_fail "Invalid pod id ${POD_ID}."

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DELETE /pods/${POD_ID}"
  exit 0
fi

cc_require_bot_api_key

deleted=0
if command -v runpodctl >/dev/null 2>&1; then
  if cc_run_timeout 20 runpodctl remove pod "$POD_ID" >/dev/null 2>&1 \
    || cc_run_timeout 20 runpodctl pod delete "$POD_ID" >/dev/null 2>&1; then
    deleted=1
  fi
fi
if [[ "$deleted" != "1" ]]; then
  cc_rest DELETE "/pods/${POD_ID}" >/dev/null || true
fi

delay=2
if [[ "${CC_TERMINATE_NO_SLEEP:-}" == "1" ]]; then
  delay=0
fi
attempt=0
while [[ "$attempt" -lt 8 ]]; do
  attempt=$((attempt + 1))
  if gone="$(cc_pod_deleted "$POD_ID")"; then
    echo "terminated=${POD_ID}"
    echo "pod_state=${gone}"
    exit 0
  fi
  if (( delay > 0 )); then
    sleep "$delay"
  fi
done
cc_fail "Pod ${POD_ID} is still present after delete."
