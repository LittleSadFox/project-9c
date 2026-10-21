#!/usr/bin/env bash
# Shared helpers for bot-side pod scripts and the pod entrypoint.
# Do not put secrets in this file.

# shellcheck disable=SC2034

cc_fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cc_known_jobs() {
  printf '%s\n' gpu_tests pose_bench eval train_events tune_align finetune_pose
}

cc_is_known_job() {
  local name="$1"
  local job
  for job in $(cc_known_jobs); do
    if [[ "$job" == "$name" ]]; then
      return 0
    fi
  done
  return 1
}

cc_spot_allowed() {
  case "${1:-}" in
    gpu_tests|pose_bench) return 0 ;;
    *) return 1 ;;
  esac
}

cc_max_ttl_s() {
  echo 43200
}

cc_default_ttl_s() {
  local job="${1:-}"
  local interactive="${2:-0}"
  if [[ "$interactive" == "1" ]]; then
    echo 7200
    return
  fi
  case "$job" in
    gpu_tests|pose_bench) echo 3600 ;;
    eval|train_events|tune_align) echo 14400 ;;
    finetune_pose) echo 43200 ;;
    *) echo 3600 ;;
  esac
}

cc_parse_ttl() {
  local raw="${1:-}"
  [[ -n "$raw" ]] || cc_fail "TTL is empty. Set CC_TTL_S or pass --ttl."
  local seconds=""
  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    seconds="$raw"
  elif [[ "$raw" =~ ^([0-9]+)([smh])$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2]}"
    case "$unit" in
      s) seconds="$n" ;;
      m) seconds=$((n * 60)) ;;
      h) seconds=$((n * 3600)) ;;
    esac
  else
    cc_fail "TTL ${raw} is not an integer second count or a value like 10m / 2h."
  fi
  if [[ ! "$seconds" =~ ^[1-9][0-9]*$ ]]; then
    cc_fail "CC_TTL_S must be a positive integer number of seconds. Got ${seconds}."
  fi
  local max
  max="$(cc_max_ttl_s)"
  if (( seconds > max )); then
    cc_fail "CC_TTL_S ${seconds} is above the cap of ${max}s."
  fi
  echo "$seconds"
}

cc_require_ttl() {
  local ttl="${CC_TTL_S:-}"
  [[ -n "$ttl" ]] || cc_fail "CC_TTL_S is required. Never start a pod without a TTL."
  CC_TTL_S="$(cc_parse_ttl "$ttl")"
  export CC_TTL_S
}

cc_require_job_or_interactive() {
  if [[ -n "${CC_JOB:-}" ]]; then
    return 0
  fi
  if [[ "${CC_INTERACTIVE:-}" == "1" ]]; then
    return 0
  fi
  cc_fail "Set CC_JOB or CC_INTERACTIVE=1."
}

cc_secret_ref_repo_token() {
  printf '%s' '{{ RUNPOD_SECRET_cc_repo_token }}'
}

cc_secret_ref_webhook() {
  printf '%s' '{{ RUNPOD_SECRET_cc_webhook_url }}'
}

cc_default_gpu_csv() {
  printf '%s' "NVIDIA L4,NVIDIA RTX 2000 Ada Generation,NVIDIA GeForce RTX 4090,NVIDIA A100 80GB PCIe,NVIDIA RTX PRO 4500 Blackwell,NVIDIA RTX PRO 4000 Blackwell,NVIDIA GeForce RTX 5090"
}

cc_allowed_cuda_versions() {
  # Opt-in via CC_ALLOWED_CUDA (CSV or JSON). Unset by default.
  # Sending allowedCudaVersions made the live API return 500
  # "no instances available" on every listed GPU, even with stock showing.
  # The image CUDA driver guard (>=12.8, fail closed) is the real floor.
  # If a filter is needed again and it excludes 13.x hosts, drop the field.
  local raw="${CC_ALLOWED_CUDA:-}"
  [[ -n "$raw" ]] || return 1
  command -v jq >/dev/null 2>&1 || cc_fail "Install jq. The pod scripts need it."
  local json
  if [[ "$raw" == "["* ]]; then
    json="$raw"
  else
    json="$(jq -nc --arg s "$raw" '$s | split(",") | map(gsub("^ +| +$";"")) | map(select(length > 0))')"
  fi
  if ! jq -e 'type == "array"' >/dev/null 2>&1 <<<"$json"; then
    cc_fail "CC_ALLOWED_CUDA is not a JSON array of version strings. Got ${raw}."
  fi
  if ! jq -e --argjson allowed '["11.8","12.0","12.1","12.2","12.3","12.4","12.5","12.6","12.7","12.8","12.9","13.0"]' '
    length > 0
    and all(.[]; type == "string")
    and all(.[]; . as $v | ($allowed | index($v)) != null)
  ' >/dev/null 2>&1 <<<"$json"; then
    cc_fail "CC_ALLOWED_CUDA must be a non-empty list of 11.8 or 12.0-13.0 strings. Got ${raw}."
  fi
  printf '%s' "$json"
}

cc_load_defaults() {
  local here file line key val
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  file="${here}/defaults.env"
  if [[ -f "$file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in
        ''|\#*) continue ;;
      esac
      key="${line%%=*}"
      val="${line#*=}"
      if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [[ -z "${!key:-}" ]]; then
        export "${key}=${val}"
      fi
    done <"$file"
  fi
  if [[ -n "${CC_VOLUME_ID:-}" ]]; then
    CC_RUNPOD_VOLUME_ID="$CC_VOLUME_ID"
  fi
  if [[ -n "${CC_VOLUME_DC:-}" ]]; then
    CC_RUNPOD_DATACENTER="$CC_VOLUME_DC"
  fi
  : "${CC_RUNPOD_VOLUME_ID:=}"
  : "${CC_RUNPOD_DATACENTER:=}"
  : "${CC_RUNPOD_REGISTRY_AUTH_ID:=}"
  : "${CC_GPU_IMAGE:=}"
  export CC_RUNPOD_VOLUME_ID CC_RUNPOD_DATACENTER CC_RUNPOD_REGISTRY_AUTH_ID CC_GPU_IMAGE
}

cc_assert_no_account_key() {
  local payload="$1"
  if printf '%s' "$payload" | grep -Eq '"RUNPOD_API_KEY"'; then
    cc_fail "Account API key must not go in the pod template or pod env."
  fi
}

cc_build_pod_env_json() {
  local job="$1"
  local ref="$2"
  local job_id="$3"
  local ttl="$4"
  local interactive="$5"
  command -v jq >/dev/null 2>&1 || cc_fail "Install jq. The pod scripts need it."

  local env
  env="$(
    jq -n \
      --arg ttl "$ttl" \
      --arg ref "$ref" \
      --arg job_id "$job_id" \
      --arg models "/workspace/models" \
      --arg golden "/workspace/videos" \
      --arg token "$(cc_secret_ref_repo_token)" \
      --arg hook "$(cc_secret_ref_webhook)" \
      '{
        CC_TTL_S: $ttl,
        CC_GIT_REF: $ref,
        CC_JOB_ID: $job_id,
        CC_MODELS_DIR: $models,
        CC_GOLDEN_DIR: $golden,
        CC_REPO_TOKEN: $token,
        CC_WEBHOOK_URL: $hook
      }'
  )"
  if [[ "$interactive" == "1" ]]; then
    env="$(jq '. + {CC_INTERACTIVE: "1"}' <<<"$env")"
  else
    env="$(jq --arg job "$job" '. + {CC_JOB: $job}' <<<"$env")"
  fi
  cc_assert_no_account_key "$env"
  printf '%s\n' "$env"
}

cc_build_pod_payload() {
  local name="$1"
  local env_json="$2"
  local spot="$3"
  local gpu_csv="$4"
  command -v jq >/dev/null 2>&1 || cc_fail "Install jq. The pod scripts need it."

  local gpus="${gpu_csv:-$(cc_default_gpu_csv)}"
  local interruptible=false
  if [[ "$spot" == "1" ]]; then
    interruptible=true
  fi
  local dc="${CC_RUNPOD_DATACENTER:-EU-RO-1}"
  local cuda_json=""
  if [[ -n "${CC_ALLOWED_CUDA:-}" ]]; then
    cuda_json="$(cc_allowed_cuda_versions)" || cc_fail "Could not build the pod payload. Check CC_ALLOWED_CUDA."
  fi

  local payload
  if ! payload="$(
    jq -n \
      --arg name "$name" \
      --argjson env "$env_json" \
      --argjson interruptible "$interruptible" \
      --arg gpus "$gpus" \
      --arg template "${CC_RUNPOD_TEMPLATE_ID:-}" \
      --arg volume "${CC_RUNPOD_VOLUME_ID:-}" \
      --arg image "${CC_GPU_IMAGE:-}" \
      --arg dc "$dc" \
      --arg registry "${CC_RUNPOD_REGISTRY_AUTH_ID:-}" \
      --arg cuda "$cuda_json" \
      --argjson disk 20 \
      '{
        name: $name,
        cloudType: "SECURE",
        computeType: "GPU",
        gpuCount: 1,
        gpuTypePriority: "custom",
        gpuTypeIds: ($gpus | split(",") | map(gsub("^ +| +$";""))),
        containerDiskInGb: $disk,
        volumeInGb: 0,
        volumeMountPath: "/workspace",
        dataCenterIds: [$dc],
        ports: ["22/tcp"],
        interruptible: $interruptible,
        env: $env
      }
      + (if $template != "" then {templateId: $template} else {} end)
      + (if $volume != "" then {networkVolumeId: $volume} else {} end)
      + (if $image != "" then {imageName: $image} else {} end)
      + (if $registry != "" then {containerRegistryAuthId: $registry} else {} end)
      + (if $cuda != "" then {allowedCudaVersions: ($cuda | fromjson)} else {} end)'
  )"; then
    cc_fail "Could not build the pod payload. Check CC_ALLOWED_CUDA."
  fi
  cc_assert_no_account_key "$payload"
  if ! jq -e '.env.CC_TTL_S' >/dev/null <<<"$payload"; then
    cc_fail "Pod payload is missing CC_TTL_S."
  fi
  printf '%s\n' "$payload"
}

cc_require_bot_api_key() {
  [[ -n "${RUNPOD_API_KEY:-}" ]] || cc_fail "RUNPOD_API_KEY is missing on this computer. Ryan and the Runpod bot set it. Do not invent a value."
}

cc_require_registry_auth() {
  if [[ -n "${CC_GPU_IMAGE:-}" && -z "${CC_RUNPOD_REGISTRY_AUTH_ID:-}" ]]; then
    cc_fail "CC_GPU_IMAGE needs CC_RUNPOD_REGISTRY_AUTH_ID. The image is private."
  fi
}

cc_require_image_tag() {
  local image="${CC_GPU_IMAGE:-}"
  if [[ -n "$image" && "$image" != *:* ]]; then
    cc_fail "CC_GPU_IMAGE must include a tag. Use a sha tag after the GHCR push."
  fi
}

cc_verify_registry_auth() {
  local id="${CC_RUNPOD_REGISTRY_AUTH_ID:-}"
  [[ -n "$id" ]] || cc_fail "CC_RUNPOD_REGISTRY_AUTH_ID is missing."
  if ! cc_rest GET "/containerregistryauth/${id}" >/dev/null; then
    cc_fail "Section 9.4: GET /containerregistryauth/${id} failed. Do not start a pod."
  fi
}

cc_ttl_from_pod_body() {
  local body="$1"
  jq -r '
    if (.env | type) == "object" then .env.CC_TTL_S // empty
    elif (.env | type) == "array" then
      [
        .env[]
        | select((.key // .name // "") == "CC_TTL_S")
        | .value // empty
      ]
      | first // empty
    else empty end
  ' <<<"$body"
}

cc_wait_timeout_s() {
  if [[ -n "${CC_WAIT_TIMEOUT_S:-}" ]]; then
    if [[ ! "${CC_WAIT_TIMEOUT_S}" =~ ^[1-9][0-9]*$ ]]; then
      cc_fail "CC_WAIT_TIMEOUT_S must be a positive integer. Got ${CC_WAIT_TIMEOUT_S}."
    fi
    printf '%s' "$CC_WAIT_TIMEOUT_S"
    return 0
  fi
  [[ -n "${CC_TTL_S:-}" ]] || cc_fail "CC_TTL_S is required for wait_job. It will not default to 3600."
  local ttl
  ttl="$(cc_parse_ttl "$CC_TTL_S")"
  printf '%s' "$((ttl + 300))"
}

cc_early_cleanup() {
  local ec=$?
  if [[ "${CC_EARLY_CLEANING:-}" == "1" ]]; then
    return 0
  fi
  CC_EARLY_CLEANING=1
  export CC_EARLY_CLEANING
  set +e
  local volume="${CC_VOLUME_DIR:-/workspace}"
  local run_dir="${volume}/runs/${CC_JOB_ID:-unknown}"
  mkdir -p "${run_dir}/artifacts"
  local existing=""
  if [[ -f "${run_dir}/status" ]]; then
    existing="$(tr -d '[:space:]' <"${run_dir}/status")"
  fi
  if [[ "${CC_INTERACTIVE:-}" == "1" && "${CC_INTERACTIVE_READY:-}" == "1" ]]; then
    if [[ "$existing" != "passed" && "$existing" != "failed" && "$existing" != "stopped" ]]; then
      printf 'stopped\n' >"${run_dir}/status"
    fi
    cc_terminate_self
    exit 0
  fi
  if [[ "$existing" == "passed" || "$existing" == "failed" || "$existing" == "stopped" ]]; then
    cc_terminate_self
    return 0
  fi
  printf 'failed\n' >"${run_dir}/status"
  if [[ ! -f "${run_dir}/metrics.json" ]]; then
    jq -n --arg job "${CC_JOB:-unknown}" --arg err "entrypoint failed before the job started" \
      '{job: $job, status: "failed", error: $err}' >"${run_dir}/metrics.json"
  fi
  if [[ -n "${CC_WEBHOOK_URL:-}" && "${CC_WEBHOOK_URL}" != *"{{"* ]]; then
    curl -sS --max-time 15 -X POST -H "Content-Type: application/json" \
      -d "{\"job_id\":\"${CC_JOB_ID:-unknown}\",\"status\":\"failed\"}" \
      "$CC_WEBHOOK_URL" >/dev/null || true
  fi
  cc_terminate_self
  return 0
}

cc_print_api_error() {
  local file="$1"
  [[ -s "$file" ]] || return 0
  python3 - "$file" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"(authorization:\s*)(basic|bearer)\s+\S+", r"\1\2 REDACTED", text, flags=re.I)
text = re.sub(r"(?i)(api[_-]?key|token|secret)(\"?\s*[:=]\s*\"?)[^\"\s]+", r"\1REDACTED", text)
text = text.replace("\n", " ")
if len(text) > 400:
    text = text[:400] + "…"
sys.stderr.write(text + "\n")
PY
}

cc_valid_pod_id() {
  local id="$1"
  [[ "$id" =~ ^[A-Za-z0-9_-]{4,64}$ ]]
}

cc_require_optarg() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    cc_fail "${flag} requires a value."
  fi
}

cc_pod_lookup_desired() {
  local pod_id="$1"
  local dest="$2"
  cc_rest GET "/pods/${pod_id}" >"$dest"
}

cc_pod_gone() {
  # wait_job early-exit: the job cannot still be running.
  local pod_id="$1"
  local tmp desired
  [[ -n "$pod_id" ]] || return 1
  tmp="$(mktemp)"
  if cc_pod_lookup_desired "$pod_id" "$tmp"; then
    desired="$(jq -r '.desiredStatus // .status // empty' <"$tmp")"
    rm -f "$tmp"
    case "$desired" in
      EXITED|TERMINATED)
        printf '%s\n' "$desired"
        return 0
        ;;
      *)
        return 1
        ;;
    esac
  fi
  rm -f "$tmp"
  if [[ "${CC_LAST_HTTP_CODE:-}" == "404" ]]; then
    echo "missing"
    return 0
  fi
  echo "ERROR: pod lookup HTTP ${CC_LAST_HTTP_CODE:-unknown}." >&2
  return 1
}

cc_pod_deleted() {
  # pod_down: EXITED still bills disk. Only 404 or TERMINATED is gone.
  local pod_id="$1"
  local tmp desired
  [[ -n "$pod_id" ]] || return 1
  tmp="$(mktemp)"
  if cc_pod_lookup_desired "$pod_id" "$tmp"; then
    desired="$(jq -r '.desiredStatus // .status // empty' <"$tmp")"
    rm -f "$tmp"
    if [[ "$desired" == "TERMINATED" ]]; then
      echo "TERMINATED"
      return 0
    fi
    return 1
  fi
  rm -f "$tmp"
  if [[ "${CC_LAST_HTTP_CODE:-}" == "404" ]]; then
    echo "missing"
    return 0
  fi
  echo "ERROR: pod lookup HTTP ${CC_LAST_HTTP_CODE:-unknown}." >&2
  return 1
}

cc_redact_stream() {
  command -v python3 >/dev/null 2>&1 || cc_fail "python3 is required to redact git logs."
  # Line-by-line so a hang or TTL kill still leaves output on the volume.
  python3 -u -c '
import base64
import os
import re
import sys

token = os.environ.get("CC_REPO_TOKEN") or ""
header = os.environ.get("GIT_CONFIG_VALUE_0") or ""
b64 = ""
b64_nopad = ""
if token:
    b64 = base64.b64encode(("x-access-token:" + token).encode("utf-8")).decode("ascii")
    b64_nopad = b64.rstrip("=")

def redact(text):
    text = re.sub(
        r"(authorization:\s*)(basic|bearer)\s+[^\s\]]+",
        r"\1\2 REDACTED",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"(\[authorization:\s*)(basic|bearer)\s+[^]\s]+",
        r"\1\2 REDACTED",
        text,
        flags=re.I,
    )
    if token:
        text = re.sub(re.escape(token), "REDACTED", text, flags=re.I)
        if b64:
            text = text.replace(b64, "REDACTED")
            text = text.replace(b64_nopad, "REDACTED")
    if header:
        text = re.sub(re.escape(header), "AUTHORIZATION: basic REDACTED", text, flags=re.I)
    return text

for line in sys.stdin:
    sys.stdout.write(redact(line))
    sys.stdout.flush()
'
}

cc_redact_text() {
  printf '%s' "$1" | cc_redact_stream
}

cc_git_sanitize_env() {
  export GIT_TERMINAL_PROMPT=0
  export GIT_TRACE_REDACT=1
  unset GIT_CURL_VERBOSE
  local key
  if command -v compgen >/dev/null 2>&1; then
    for key in $(compgen -e GIT_TRACE || true); do
      if [[ "$key" != "GIT_TRACE_REDACT" ]]; then
        unset "$key"
      fi
    done
  else
    unset GIT_TRACE GIT_TRACE_CURL GIT_TRACE_PACKET GIT_TRACE2 \
      GIT_TRACE2_EVENT GIT_TRACE2_PERF GIT_TRACE_SETUP GIT_TRACE_SHALLOW
  fi
}

cc_run_logged() {
  local wait_bg=0
  if [[ "${1:-}" == "--wait" ]]; then
    wait_bg=1
    shift
  fi
  cc_git_sanitize_env
  local fifo reader ec
  fifo="$(mktemp -u)"
  mkfifo "$fifo"
  cc_redact_stream <"$fifo" | tee -a "${CC_RUN_LOG:-/dev/null}" &
  reader=$!
  set +e
  if [[ "$wait_bg" == "1" ]]; then
    "$@" >"$fifo" 2>&1 &
    wait $!
    ec=$?
  else
    "$@" >"$fifo" 2>&1
    ec=$?
  fi
  set -e
  wait "$reader" || true
  rm -f "$fifo"
  return "$ec"
}

cc_run_timeout() {
  local secs="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout --signal=KILL "$secs" "$@"
    return $?
  fi
  "$@"
  return $?
}

cc_s3_cp_stdout() {
  local uri="$1"
  local region="$2"
  local endpoint="$3"
  local err attempt delay out
  command -v aws >/dev/null 2>&1 || cc_fail "Install AWS CLI v2."
  err="$(mktemp)"
  for attempt in 1 2 3 4; do
    # shellcheck disable=SC2046
    if out="$(aws s3 cp "$uri" - --region "$region" --endpoint-url "$endpoint" $(cc_aws_args) 2>"$err")"; then
      rm -f "$err"
      printf '%s' "$out"
      return 0
    fi
    if grep -qiE 'NoSuchKey|Not Found|404' "$err"; then
      rm -f "$err"
      return 1
    fi
    if grep -qiE 'SignatureDoesNotMatch|403 Forbidden|Status Code: 403|HTTPStatusCode: 403|\(403\)' "$err"; then
      if (( attempt >= 4 )); then
        break
      fi
      delay=$((attempt * 2))
      echo "S3 transient error attempt=${attempt}; sleep ${delay}s" >&2
      cat "$err" >&2 || true
      if [[ "${CC_TERMINATE_NO_SLEEP:-}" != "1" ]]; then
        sleep "$delay"
      fi
      continue
    fi
    echo "ERROR: aws s3 cp failed for ${uri}." >&2
    cat "$err" >&2 || true
    rm -f "$err"
    return 1
  done
  echo "ERROR: aws s3 cp failed for ${uri} after retries." >&2
  cat "$err" >&2 || true
  rm -f "$err"
  return 1
}

cc_rest() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  cc_require_bot_api_key
  command -v curl >/dev/null 2>&1 || cc_fail "Install curl. The pod scripts need it."
  local url="https://rest.runpod.io/v1${path}"
  local hdr tmp code
  hdr="$(mktemp)"
  tmp="$(mktemp)"
  printf 'Authorization: Bearer %s\n' "${RUNPOD_API_KEY}" >"$hdr"
  chmod 600 "$hdr"
  # Bash 3.2 + set -u cannot expand an empty array.
  if [[ -n "$body" ]]; then
    code="$(
      curl -sS --max-time 30 --fail-with-body -o "$tmp" -w '%{http_code}' -X "$method" \
        -H "@${hdr}" -H "Content-Type: application/json" \
        -d "$body" "$url" || true
    )"
  else
    code="$(
      curl -sS --max-time 30 --fail-with-body -o "$tmp" -w '%{http_code}' -X "$method" \
        -H "@${hdr}" -H "Content-Type: application/json" \
        "$url" || true
    )"
  fi
  rm -f "$hdr"
  CC_LAST_HTTP_CODE="$code"
  export CC_LAST_HTTP_CODE
  if [[ ! "$code" =~ ^2[0-9][0-9]$ ]]; then
    echo "ERROR: Runpod ${method} ${path} returned HTTP ${code}." >&2
    cc_print_api_error "$tmp"
    rm -f "$tmp"
    return 1
  fi
  cat "$tmp"
  rm -f "$tmp"
  return 0
}

cc_s3_endpoint() {
  local dc="${CC_RUNPOD_DATACENTER:-}"
  [[ -n "$dc" ]] || cc_fail "Set CC_RUNPOD_DATACENTER to the volume datacenter."
  local lower
  lower="$(printf '%s' "$dc" | tr '[:upper:]' '[:lower:]')"
  printf 'https://s3api-%s.runpod.io' "$lower"
}

cc_volume_id() {
  local id="${CC_RUNPOD_VOLUME_ID:-}"
  [[ -n "$id" ]] || cc_fail "Set CC_RUNPOD_VOLUME_ID."
  printf '%s' "$id"
}

cc_aws_args() {
  if [[ -n "${CC_AWS_PROFILE:-}" ]]; then
    printf '%s\n' --profile "$CC_AWS_PROFILE"
  fi
}

cc_setup_ssh() {
  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  if [[ -n "${PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
  fi
}

cc_pods_from_response() {
  local response="$1"
  local items
  items="$(
    jq -c '
      if type == "array" then .
      elif ((.pods // empty) | type) == "array" then .pods
      elif ((.data // empty) | type) == "array" then .data
      else empty
      end
    ' <<<"$response"
  )"
  if [[ -z "$items" || "$items" == "null" ]]; then
    echo "$response" >&2
    cc_fail "Runpod /pods did not return an array."
  fi
  printf '%s\n' "$items"
}

cc_require_cuda_driver() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    if [[ -n "${CC_JOB:-}" ]]; then
      cc_fail "nvidia-smi is required on a job pod."
    fi
    echo "nvidia-smi is not available. Skip the driver check."
    return 0
  fi
  local ver driver
  ver="$(nvidia-smi | sed -n 's/.*CUDA Version: \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)"
  driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '[:space:]')"
  cc_log "nvidia_driver=${driver:-unknown}"
  cc_log "cuda_version=${ver:-unknown}"
  [[ -n "$ver" ]] || cc_fail "Could not read the CUDA version from nvidia-smi."
  local major minor
  major="${ver%%.*}"
  minor="${ver#*.}"
  minor="${minor%%.*}"
  if (( major < 12 )) || { (( major == 12 )) && (( minor < 8 )); }; then
    cc_fail "CUDA driver is ${ver}. Need 12.8 or later."
  fi
}

cc_log() {
  if [[ -n "${CC_RUN_LOG:-}" ]]; then
    printf '%s\n' "$*" | tee -a "$CC_RUN_LOG"
  else
    printf '%s\n' "$*"
  fi
}

cc_terminate_self() {
  if [[ -z "${RUNPOD_POD_ID:-}" ]]; then
    echo "ERROR: RUNPOD_POD_ID is missing. Cannot terminate this pod." >&2
    return 1
  fi
  if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "ERROR: No pod-scoped RUNPOD_API_KEY. Cannot terminate this pod." >&2
    return 1
  fi
  local attempt delay ctl
  for attempt in 1 2 3 4; do
    if command -v runpodctl >/dev/null 2>&1; then
      ctl=""
      if ctl="$(cc_run_timeout 20 runpodctl remove pod "$RUNPOD_POD_ID" 2>&1)" \
        || ctl="$(cc_run_timeout 20 runpodctl pod delete "$RUNPOD_POD_ID" 2>&1)"; then
        cc_log "terminate ok via runpodctl attempt=${attempt}"
        return 0
      fi
      cc_log "runpodctl failed attempt=${attempt}: ${ctl}"
    fi
    if cc_rest DELETE "/pods/${RUNPOD_POD_ID}" >/dev/null; then
      cc_log "terminate ok via curl attempt=${attempt}"
      return 0
    fi
    delay=$((attempt * 2))
    cc_log "terminate attempt ${attempt} failed; sleep ${delay}s"
    if [[ "${CC_TERMINATE_NO_SLEEP:-}" != "1" ]]; then
      sleep "$delay"
    fi
  done
  cc_log "terminate failed after retries"
  return 1
}

cc_watchdog_start() {
  local run_dir="${1:-}"
  cc_require_ttl
  (
    local started now remain
    if [[ -n "$run_dir" && -f "${run_dir}/started_at" ]]; then
      started="$(cat "${run_dir}/started_at")"
    else
      started="$(date +%s)"
      if [[ -n "$run_dir" ]]; then
        mkdir -p "$run_dir"
        printf '%s\n' "$started" >"${run_dir}/started_at"
      fi
    fi
    now="$(date +%s)"
    remain=$((CC_TTL_S - (now - started)))
    if (( remain < 1 )); then
      remain=1
    fi
    sleep "$remain"
    echo "TTL ${CC_TTL_S}s expired. Terminate the pod."
    if [[ -n "$run_dir" ]]; then
      export CC_RUN_LOG="${run_dir}/log.txt"
    fi
    cc_terminate_self
  ) &
  disown || true
}

cc_require_repo_token() {
  if [[ -z "${CC_REPO_TOKEN:-}" ]]; then
    cc_fail "CC_REPO_TOKEN is empty. The Runpod secret cc_repo_token is missing or blank."
  fi
  if [[ "${CC_REPO_TOKEN}" == *"{{"* ]]; then
    cc_fail "CC_REPO_TOKEN was not resolved. The Runpod secret cc_repo_token is missing."
  fi
}

cc_git_auth_setup() {
  cc_require_repo_token
  cc_git_sanitize_env
  local b64
  b64="$(printf 'x-access-token:%s' "$CC_REPO_TOKEN" | base64 | tr -d '\n')"
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="http.extraHeader"
  export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic ${b64}"
}

cc_git_auth_clear() {
  unset CC_REPO_TOKEN
  unset GIT_CONFIG_COUNT
  unset GIT_CONFIG_KEY_0
  unset GIT_CONFIG_VALUE_0
}

cc_resolve_ref() {
  local ref="$1"
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s' "$ref"
    return 0
  fi
  local resolved=""
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    resolved="$(git rev-parse --verify "${ref}^{commit}" 2>/dev/null || true)"
  fi
  if [[ "$resolved" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s' "$resolved"
    return 0
  fi
  cc_fail "--ref must be a 40-character commit sha. Got ${ref}."
}

cc_load_defaults
