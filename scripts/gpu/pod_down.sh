#!/usr/bin/env bash
# Terminate one pod by id.
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
cc_rest DELETE "/pods/${POD_ID}" >/dev/null
echo "terminated=${POD_ID}"
