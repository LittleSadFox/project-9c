#!/usr/bin/env bash
# Poll runs/<job_id>/status through the volume S3 API.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

usage() {
  echo "Usage: scripts/gpu/wait_job.sh <job_id> [--dry-run]"
}

JOB_ID=""
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
      if [[ -z "$JOB_ID" ]]; then
        JOB_ID="$1"
        shift
      else
        cc_fail "Unknown argument: $1"
      fi
      ;;
  esac
done

[[ -n "$JOB_ID" ]] || cc_fail "Pass a job id."

VOLUME="$(cc_volume_id)"
ENDPOINT="$(cc_s3_endpoint)"
REGION="${CC_VOLUME_DC:-${CC_RUNPOD_DATACENTER:-}}"
KEY="runs/${JOB_ID}/status"
TIMEOUT="${CC_WAIT_TIMEOUT_S:-7200}"
SLEEP_S="${CC_WAIT_POLL_S:-15}"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "s3://${VOLUME}/${KEY}"
  echo "endpoint=${ENDPOINT}"
  echo "region=${REGION}"
  exit 0
fi

command -v aws >/dev/null 2>&1 || cc_fail "Install AWS CLI v2. wait_job.sh reads the volume through the S3 API."

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  if status="$(aws s3 cp "s3://${VOLUME}/${KEY}" - --region "$REGION" --endpoint-url "$ENDPOINT" 2>/dev/null)"; then
    status="$(printf '%s' "$status" | tr -d '[:space:]')"
    echo "status=${status}"
    case "$status" in
      passed) exit 0 ;;
      failed) exit 1 ;;
      running|"") ;;
      *) echo "Unknown status ${status@Q}" ;;
    esac
  fi
  sleep "$SLEEP_S"
done

cc_fail "Timed out after ${TIMEOUT}s waiting for ${JOB_ID}."
