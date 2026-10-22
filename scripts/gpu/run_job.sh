#!/usr/bin/env bash
# Inside the pod: clone the sha, install pins, run ml/jobs.py, write the run folder, ping, terminate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${SCRIPT_DIR}/lib.sh" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/lib.sh"
elif [[ -f /opt/cc/scripts/gpu/lib.sh ]]; then
  # shellcheck disable=SC1091
  source /opt/cc/scripts/gpu/lib.sh
else
  echo "ERROR: cannot find scripts/gpu/lib.sh" >&2
  exit 1
fi

VOLUME="${CC_VOLUME_DIR:-/workspace}"
if [[ -n "${CC_JOB_ID:-}" ]]; then
  cc_require_job_id "$CC_JOB_ID"
fi
RUN_DIR="${VOLUME}/runs/${CC_JOB_ID:-unknown}"
SRC="${CC_SRC_DIR:-/tmp/cc-src}"
SCRATCH="${CC_LIBRARY_DIR:-/tmp/cc-library}"

FINISHED=0
STATUS="failed"
CLEANING=0

write_status() {
  printf '%s\n' "$1" >"$RUN_DIR/status"
}

ping_webhook() {
  local status="$1"
  if [[ -z "${CC_WEBHOOK_URL:-}" ]]; then
    echo "CC_WEBHOOK_URL is unset. Skip webhook ping."
    return 0
  fi
  if [[ "${CC_WEBHOOK_URL}" == *"{{"* ]]; then
    echo "CC_WEBHOOK_URL was not resolved. Skip webhook ping."
    return 0
  fi
  local summary="{}"
  if [[ -f "$RUN_DIR/metrics.json" ]]; then
    summary="$(jq -c '{job: .job, status: .status, pytest: .pytest, cuda: .cuda}' "$RUN_DIR/metrics.json" 2>/dev/null || echo '{}')"
  fi
  local body
  body="$(jq -nc --arg id "$CC_JOB_ID" --arg status "$status" --argjson metrics "$summary" \
    '{job_id: $id, status: $status, metrics: $metrics}')"
  local ping=""
  ping="$(cc_curl_post_json "$CC_WEBHOOK_URL" "$body")" || true
  cc_log_webhook_ping "$ping"
}

# Invoked from trap EXIT INT TERM HUP.
# shellcheck disable=SC2317,SC2329
cleanup() {
  local ec=$?
  if [[ "$CLEANING" == "1" ]]; then
    return 0
  fi
  CLEANING=1
  set +e
  if [[ "$FINISHED" != "1" ]]; then
    local existing=""
    if [[ -f "$RUN_DIR/status" ]]; then
      existing="$(tr -d '[:space:]' <"$RUN_DIR/status")"
    fi
    if [[ "$existing" == "failed" ]]; then
      STATUS="failed"
    elif [[ "$existing" == "passed" ]]; then
      STATUS="passed"
    else
      STATUS="failed"
      mkdir -p "$RUN_DIR/artifacts" 2>/dev/null
      write_status failed
      if [[ ! -f "$RUN_DIR/metrics.json" ]]; then
        jq -n --arg job "${CC_JOB:-unknown}" --arg err "run_job.sh exited before the job finished" \
          '{job: $job, status: "failed", error: $err}' >"$RUN_DIR/metrics.json"
      fi
      ping_webhook failed
    fi
  fi
  cc_terminate_self
  if [[ "$FINISHED" != "1" ]]; then
    trap - EXIT INT TERM HUP
    exit 1
  fi
  return 0
}

# Refuse before the EXIT trap and before mkdir. A nested gpu_tests
# must not write a run folder, mark an outer job failed, or ping twice.
cc_refuse_nested_gpu_tests

trap cleanup EXIT
trap cleanup INT
trap cleanup TERM
trap cleanup HUP

cc_require_ttl
[[ -n "${CC_JOB:-}" ]] || cc_fail "CC_JOB is required inside run_job.sh."
[[ -n "${CC_GIT_REF:-}" ]] || cc_fail "CC_GIT_REF is required. Pods run only pushed commits."
[[ -n "${CC_JOB_ID:-}" ]] || cc_fail "CC_JOB_ID is required."
cc_require_job_id "$CC_JOB_ID"
RUN_DIR="${VOLUME}/runs/${CC_JOB_ID}"

mkdir -p "$RUN_DIR/artifacts" "$VOLUME/models" "$VOLUME/cache/pip" "$SCRATCH"
CC_RUN_LOG="${RUN_DIR}/log.txt"
export CC_RUN_LOG
export GIT_TERMINAL_PROMPT=0
export GIT_TRACE_REDACT=1
cc_git_sanitize_env
if [[ -f "$RUN_DIR/status" ]]; then
  existing="$(tr -d '[:space:]' <"$RUN_DIR/status")"
  case "$existing" in
    passed|failed)
      echo "Job already ${existing}. Retry terminate only."
      FINISHED=1
      STATUS="$existing"
      cc_terminate_self
      trap - EXIT INT TERM HUP
      if [[ "$existing" == "passed" ]]; then
        exit 0
      fi
      exit 1
      ;;
  esac
fi
echo running >"$RUN_DIR/status"

gpu_name=""
if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_timeout="${CC_NVIDIA_SMI_TIMEOUT_S:-10}"
  if [[ ! "$gpu_timeout" =~ ^[1-9][0-9]*$ ]]; then
    gpu_timeout=10
  fi
  gpu_name="$(cc_run_timeout "$gpu_timeout" nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  gpu_name="$(cc_trim "$gpu_name")"
fi
{
  echo "job=${CC_JOB}"
  echo "job_id=${CC_JOB_ID}"
  echo "git_ref=${CC_GIT_REF}"
  echo "ttl_s=${CC_TTL_S}"
  echo "gpu_name=${gpu_name:-unknown}"
} | tee -a "$RUN_DIR/log.txt"

fail_repo_token() {
  local msg="$1"
  local err="$2"
  echo "ERROR: ${msg}" | tee -a "$RUN_DIR/log.txt" >&2
  if [[ ! -f "$RUN_DIR/metrics.json" ]]; then
    jq -n --arg job "${CC_JOB:-unknown}" --arg err "$err" \
      '{job: $job, status: "failed", error: $err}' >"$RUN_DIR/metrics.json"
  fi
  # Leave status as running so cleanup writes failed and pings the webhook.
  cc_fail "$msg"
}

if [[ "${CC_RUN_JOB_READY:-}" != "1" ]]; then
  if [[ -z "${CC_REPO_TOKEN:-}" ]]; then
    fail_repo_token \
      "CC_REPO_TOKEN is empty. The Runpod secret cc_repo_token is missing or blank." \
      "CC_REPO_TOKEN is empty"
  fi
  if [[ "${CC_REPO_TOKEN}" == *"{{"* ]]; then
    fail_repo_token \
      "CC_REPO_TOKEN was not resolved. The Runpod secret cc_repo_token is missing." \
      "CC_REPO_TOKEN was not resolved"
  fi
  echo "Clone LittleSadFox/project-9c at ${CC_GIT_REF}" | tee -a "$RUN_DIR/log.txt"
  SRC="$(cc_safe_wipe_dir "$SRC" "$SCRIPT_DIR" "$VOLUME" "$SCRATCH")" || cc_fail "Refuse to rm -rf ${SRC}."
  [[ -n "$SRC" ]] || cc_fail "Refuse to rm -rf an empty path."
  mkdir -p "$SRC"
  cc_run_logged git init "$SRC"
  cc_run_logged git -C "$SRC" remote add origin "https://github.com/LittleSadFox/project-9c.git"
  cc_git_auth_setup
  cc_run_logged git -C "$SRC" fetch --depth 1 origin "$CC_GIT_REF"
  cc_run_logged git -C "$SRC" checkout --detach FETCH_HEAD
  cc_git_auth_clear
  export CC_RUN_JOB_READY=1
  export CC_SRC_DIR="$SRC"
  if [[ -x "$SRC/scripts/gpu/run_job.sh" ]]; then
    trap - EXIT INT TERM HUP
    exec "$SRC/scripts/gpu/run_job.sh"
  fi
fi

export CC_LIBRARY_DIR="$SCRATCH"
export CC_MODELS_DIR="${CC_MODELS_DIR:-$VOLUME/models}"
export CC_GOLDEN_DIR="${CC_GOLDEN_DIR:-$VOLUME/videos}"
export CC_VOLUME_DIR="$VOLUME"
export PYTHONPATH="${SRC}/backend:${SRC}${PYTHONPATH:+:$PYTHONPATH}"

PY="$(cc_resolve_python)"
echo "python=${PY}" | tee -a "$RUN_DIR/log.txt"

echo "Install pins from cache" | tee -a "$RUN_DIR/log.txt"
cc_run_logged --wait "$PY" -m pip install --cache-dir "$VOLUME/cache/pip" -r "$SRC/backend/requirements-gpu.txt"
cc_run_logged --wait "$PY" -m pip install --cache-dir "$VOLUME/cache/pip" -r "$SRC/backend/requirements-dev.txt"
cc_run_logged --wait "$PY" -m pip install --cache-dir "$VOLUME/cache/pip" --no-deps -r "$SRC/backend/requirements-nodeps.txt"

echo "Run ml.jobs ${CC_JOB}" | tee -a "$RUN_DIR/log.txt"
ec=0
cc_run_logged --wait "$PY" -m ml.jobs "$CC_JOB" --run-dir "$RUN_DIR" || ec=$?

if [[ "$ec" -eq 0 ]]; then
  STATUS="passed"
else
  STATUS="failed"
fi
write_status "$STATUS"
if [[ ! -f "$RUN_DIR/metrics.json" ]]; then
  jq -n --arg job "$CC_JOB" --arg status "$STATUS" --argjson code "$ec" \
    '{job: $job, status: $status, exit_code: $code}' >"$RUN_DIR/metrics.json"
fi
ping_webhook "$STATUS"
FINISHED=1
exit "$ec"
