#!/usr/bin/env bash
# Poll runs/<job_id>/status through the volume S3 API.
# Optional --pod-id fails early if the pod exits before status is passed,
# and calls pod_down.sh when the wait ends.
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
      cc_require_optarg "$1" "${2:-}"
      POD_ID="$2"
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

resolve_ttl() {
  if [[ -n "${CC_WAIT_TIMEOUT_S:-}" || -n "${CC_TTL_S:-}" ]]; then
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    cc_fail "CC_TTL_S is required for wait_job. It will not default to 3600."
  fi
  local body ttl log tmp
  if [[ -n "$POD_ID" ]]; then
    tmp="$(mktemp)"
    if cc_rest GET "/pods/${POD_ID}" >"$tmp"; then
      body="$(cat "$tmp")"
      rm -f "$tmp"
      ttl="$(cc_ttl_from_pod_body "$body")"
      if [[ -n "$ttl" ]]; then
        CC_TTL_S="$ttl"
        export CC_TTL_S
        return 0
      fi
    else
      rm -f "$tmp"
    fi
  fi
  if log="$(cc_s3_cp_stdout "s3://${VOLUME}/runs/${JOB_ID}/log.txt" "$REGION" "$ENDPOINT")"; then
    ttl="$(printf '%s\n' "$log" | sed -n 's/^ttl_s=//p' | head -n 1)"
    if [[ -n "$ttl" ]]; then
      CC_TTL_S="$ttl"
      export CC_TTL_S
      return 0
    fi
  fi
  cc_fail "CC_TTL_S is required for wait_job. Pass it, or use --pod-id / a run log that records ttl_s."
}

resolve_ttl
TIMEOUT="$(cc_wait_timeout_s)"
SLEEP_S="${CC_WAIT_POLL_S:-15}"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "s3://${VOLUME}/${KEY}"
  echo "endpoint=${ENDPOINT}"
  echo "region=${REGION}"
  echo "timeout_s=${TIMEOUT}"
  if [[ -n "${CC_AWS_PROFILE:-}" ]]; then
    echo "aws_profile=${CC_AWS_PROFILE}"
  fi
  if [[ -n "$POD_ID" ]]; then
    echo "pod_id=${POD_ID}"
    echo "GET /pods/${POD_ID}"
    echo "pod_down=${POD_ID}"
  fi
  exit 0
fi

command -v aws >/dev/null 2>&1 || cc_fail "Install AWS CLI v2. wait_job.sh reads the volume through the S3 API."

aws_cp_status() {
  local raw
  if raw="$(cc_s3_cp_stdout "s3://${VOLUME}/${KEY}" "$REGION" "$ENDPOINT")"; then
    printf '%s' "$raw" | tr -d '[:space:]'
    return 0
  fi
  return 1
}

aws_cp_metrics() {
  cc_s3_cp_stdout "s3://${VOLUME}/runs/${JOB_ID}/metrics.json" "$REGION" "$ENDPOINT" || true
}

pod_gone() {
  if [[ -z "$POD_ID" ]]; then
    return 1
  fi
  cc_pod_gone "$POD_ID"
}

finish_wait() {
  local ec="$1"
  if [[ -n "$POD_ID" ]]; then
    if ! "$ROOT/scripts/gpu/pod_down.sh" "$POD_ID"; then
      echo "ERROR: pod ${POD_ID} still exists after pod_down." >&2
      if (( ec == 0 )); then
        ec=1
      fi
    fi
  fi
  exit "$ec"
}

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  if status="$(aws_cp_status)"; then
    echo "status=${status}"
    case "$status" in
      passed)
        aws_cp_metrics >/dev/null
        finish_wait 0
        ;;
      failed)
        aws_cp_metrics >/dev/null
        finish_wait 1
        ;;
      running|"") ;;
      *) echo "Unknown status ${status}" ;;
    esac
  fi
  if gone="$(pod_gone)"; then
    if status="$(aws_cp_status)"; then
      echo "status=${status}"
      case "$status" in
        passed) finish_wait 0 ;;
        failed) finish_wait 1 ;;
      esac
    fi
    echo "ERROR: Pod ${POD_ID} is ${gone} and runs/${JOB_ID}/status is not passed." >&2
    finish_wait 1
  fi
  sleep "$SLEEP_S"
done

echo "ERROR: Timed out after ${TIMEOUT}s waiting for ${JOB_ID}." >&2
finish_wait 2
