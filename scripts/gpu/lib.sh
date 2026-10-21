#!/usr/bin/env bash
# Shared helpers for bot-side pod scripts and the pod entrypoint.
# Do not put secrets in this file.

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
  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    echo "$raw"
    return
  fi
  if [[ "$raw" =~ ^([0-9]+)([smh])$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2]}"
    case "$unit" in
      s) echo "$n" ;;
      m) echo $((n * 60)) ;;
      h) echo $((n * 3600)) ;;
    esac
    return
  fi
  cc_fail "TTL ${raw@Q} is not an integer second count or a value like 10m / 2h."
}

cc_require_ttl() {
  local ttl="${CC_TTL_S:-}"
  [[ -n "$ttl" ]] || cc_fail "CC_TTL_S is required. Never start a pod without a TTL."
  if [[ ! "$ttl" =~ ^[1-9][0-9]*$ ]]; then
    cc_fail "CC_TTL_S must be a positive integer number of seconds. Got ${ttl@Q}."
  fi
}

cc_secret_ref_repo_token() {
  printf '%s' '{{ RUNPOD_SECRET_cc_repo_token }}'
}

cc_secret_ref_webhook() {
  printf '%s' '{{ RUNPOD_SECRET_cc_webhook_url }}'
}

cc_assert_no_account_key() {
  local payload="$1"
  if printf '%s' "$payload" | grep -Eq '"RUNPOD_API_KEY"'; then
    cc_fail "Account API key must not go in the pod template or pod env."
  fi
  if [[ -n "${RUNPOD_API_KEY:-}" ]] && printf '%s' "$payload" | grep -F -q -- "$RUNPOD_API_KEY"; then
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
  if [[ "$interactive" != "1" ]]; then
    env="$(jq --arg job "$job" '. + {CC_JOB: $job}' <<<"$env")"
  fi
  cc_assert_no_account_key "$env"
  printf '%s\n' "$env"
}

cc_build_pod_payload() {
  local name="$1"
  local env_json="$2"
  local ttl="$3"
  local spot="$4"
  local gpu_csv="$5"
  command -v jq >/dev/null 2>&1 || cc_fail "Install jq. The pod scripts need it."

  local gpus="${gpu_csv:-NVIDIA GeForce RTX 4090,NVIDIA A40,NVIDIA RTX A5000}"
  local interruptible=false
  if [[ "$spot" == "1" ]]; then
    interruptible=true
  fi

  local payload
  payload="$(
    jq -n \
      --arg name "$name" \
      --argjson env "$env_json" \
      --argjson interruptible "$interruptible" \
      --arg gpus "$gpus" \
      --arg template "${CC_RUNPOD_TEMPLATE_ID:-}" \
      --arg volume "${CC_RUNPOD_VOLUME_ID:-}" \
      --arg image "${CC_GPU_IMAGE:-}" \
      --arg dc "${CC_RUNPOD_DATACENTER:-}" \
      --arg registry "${CC_RUNPOD_REGISTRY_AUTH_ID:-}" \
      --argjson disk 20 \
      '{
        name: $name,
        cloudType: "SECURE",
        computeType: "GPU",
        gpuCount: 1,
        gpuTypePriority: "custom",
        gpuTypeIds: ($gpus | split(",") | map(gsub("^ +| +$";""))),
        containerDiskInGb: $disk,
        volumeMountPath: "/workspace",
        ports: ["22/tcp"],
        interruptible: $interruptible,
        env: $env
      }
      + (if $template != "" then {templateId: $template} else {} end)
      + (if $volume != "" then {networkVolumeId: $volume} else {} end)
      + (if $image != "" then {imageName: $image} else {} end)
      + (if $dc != "" then {dataCenterIds: [$dc]} else {} end)
      + (if $registry != "" then {containerRegistryAuthId: $registry} else {} end)'
  )"
  cc_assert_no_account_key "$payload"
  if ! jq -e '.env.CC_TTL_S' >/dev/null <<<"$payload"; then
    cc_fail "Pod payload is missing CC_TTL_S."
  fi
  printf '%s\n' "$payload"
}

cc_require_bot_api_key() {
  [[ -n "${RUNPOD_API_KEY:-}" ]] || cc_fail "RUNPOD_API_KEY is missing on this computer. Ryan and the Runpod bot set it. Do not invent a value."
}

cc_rest() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  cc_require_bot_api_key
  command -v curl >/dev/null 2>&1 || cc_fail "Install curl. The pod scripts need it."
  local url="https://rest.runpod.io/v1${path}"
  local args=(-sS -X "$method" -H "Authorization: Bearer ${RUNPOD_API_KEY}" -H "Content-Type: application/json")
  if [[ -n "$body" ]]; then
    args+=(-d "$body")
  fi
  curl "${args[@]}" "$url"
}

cc_s3_endpoint() {
  local dc="${CC_VOLUME_DC:-${CC_RUNPOD_DATACENTER:-}}"
  [[ -n "$dc" ]] || cc_fail "Set CC_VOLUME_DC or CC_RUNPOD_DATACENTER to the volume datacenter."
  local lower
  lower="$(printf '%s' "$dc" | tr '[:upper:]' '[:lower:]')"
  printf 'https://s3api-%s.runpod.io' "$lower"
}

cc_volume_id() {
  local id="${CC_VOLUME_ID:-${CC_RUNPOD_VOLUME_ID:-}}"
  [[ -n "$id" ]] || cc_fail "Set CC_VOLUME_ID or CC_RUNPOD_VOLUME_ID."
  printf '%s' "$id"
}

cc_setup_ssh() {
  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  if [[ -n "${PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
  fi
}

cc_terminate_self() {
  if [[ -z "${RUNPOD_POD_ID:-}" ]]; then
    echo "No RUNPOD_POD_ID. Skip remote terminate."
    return 0
  fi
  if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "No pod-scoped RUNPOD_API_KEY. Cannot terminate this pod." >&2
    return 1
  fi
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" \
    >/dev/null || true
}

cc_watchdog_start() {
  cc_require_ttl
  (
    sleep "$CC_TTL_S"
    echo "TTL ${CC_TTL_S}s expired. Terminate the pod."
    cc_terminate_self
  ) &
  disown || true
}
