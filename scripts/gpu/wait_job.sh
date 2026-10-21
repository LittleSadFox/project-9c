#!/usr/bin/env bash
# Poll runs/<job_id>/status through the volume S3 API.
# Optional --pod-id fails early if the pod exits before status is passed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

usage() {
  echo "Usage: scripts/gpu/wait_job.sh <job_id> [--pod-id <pod_id>] [--dry-run]"
}

JOB_ID=""
POD_ID=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pod-id)
      POD_ID="${2:-}"
      shift 2
      ;;
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
if [[ -n "$POD_ID" ]] && ! cc_valid_pod_id "$POD_ID"; then
  cc_fail "Invalid pod id ${POD_ID}."
fi

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
  if [[ -n "$POD_ID" ]]; then
    echo "pod_id=${POD_ID}"
    echo "GET /pods/${POD_ID}"
  fi
  exit 0
fi

command -v aws >/dev/null 2>&1 || cc_fail "Install AWS CLI v2. wait_job.sh reads the volume through the S3 API."

read_status() {
  local status=""
  if status="$(aws s3 cp "s3://${VOLUME}/${KEY}" - --region "$REGION" --endpoint-url "$ENDPOINT" 2>/dev/null)"; then
    printf '%s' "$status" | tr -d '[:space:]'
    return 0
  fi
  return 1
}

pod_gone() {
  local body=""
  if [[ -z "$POD_ID" ]]; then
    return 1
  fi
  if body="$(cc_rest GET "/pods/${POD_ID}" 2>/dev/null)"; then
    local desired
    desired="$(jq -r '.desiredStatus // .status // empty' <<<"$body")"
    case "$desired" in
      EXITED|TERMINATED|DEAD)
        echo "$desired"
        return 0
        ;;
      *)
        return 1
        ;;
    esac
  fi
  echo "missing"
  return 0
}

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  if status="$(read_status)"; then
    echo "status=${status}"
    case "$status" in
      passed) exit 0 ;;
      failed) exit 1 ;;
      running|"") ;;
      *) echo "Unknown status ${status}" ;;
    esac
  fi
  if gone="$(pod_gone)"; then
    if status="$(read_status)"; then
      echo "status=${status}"
      case "$status" in
        passed) exit 0 ;;
        failed) exit 1 ;;
      esac
    fi
    cc_fail "Pod ${POD_ID} is ${gone} and runs/${JOB_ID}/status is not passed."
  fi
  sleep "$SLEEP_S"
done

cc_fail "Timed out after ${TIMEOUT}s waiting for ${JOB_ID}."
