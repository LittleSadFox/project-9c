#!/usr/bin/env bash
# Create one GPU pod for a job or an interactive session.
# Only the Runpod bot should run this without --dry-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/gpu/pod_up.sh --job <name> --ref <sha> [--gpu <csv>] [--spot] [--ttl <dur>] [--dry-run]
  scripts/gpu/pod_up.sh --interactive [--ref <sha>] [--gpu <csv>] [--ttl <dur>] [--dry-run]

CC_TTL_S is always sent to the pod.
The account API key never goes in pod env.
Do not invent credentials.
Do not start a live pod from a coding agent. The Runpod bot owns the first live gpu_tests run.
EOF
}

JOB=""
REF=""
INTERACTIVE=0
SPOT=0
TTL_RAW=""
DRY_RUN=0
GPU_CSV=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job)
      cc_require_optarg "$1" "${2:-}"
      JOB="$2"
      shift 2
      ;;
    --ref)
      cc_require_optarg "$1" "${2:-}"
      REF="$2"
      shift 2
      ;;
    --interactive)
      INTERACTIVE=1
      shift
      ;;
    --spot)
      SPOT=1
      shift
      ;;
    --ttl)
      cc_require_optarg "$1" "${2:-}"
      TTL_RAW="$2"
      shift 2
      ;;
    --gpu)
      cc_require_optarg "$1" "${2:-}"
      GPU_CSV="$2"
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
      cc_fail "Unknown argument: $1"
      ;;
  esac
done

if [[ "$INTERACTIVE" == "1" && -n "$JOB" ]]; then
  cc_fail "Use --job or --interactive, not both."
fi
if [[ "$INTERACTIVE" != "1" && -z "$JOB" ]]; then
  cc_fail "Never start a pod without CC_JOB or --interactive."
fi
if [[ "$INTERACTIVE" != "1" ]]; then
  cc_is_known_job "$JOB" || cc_fail "Unknown job ${JOB}. Known jobs: $(cc_known_jobs | tr '\n' ' ')"
fi
if [[ -z "$REF" ]]; then
  if [[ "$INTERACTIVE" == "1" ]]; then
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      REF="$(git rev-parse HEAD)"
    else
      cc_fail "--ref <sha> is required for an interactive pod outside a git work tree."
    fi
  else
    cc_fail "--ref <sha> is required for a job pod. Pods run only pushed commits."
  fi
fi
if [[ "$SPOT" == "1" ]]; then
  if [[ "$INTERACTIVE" == "1" ]] || ! cc_spot_allowed "$JOB"; then
    cc_fail "--spot is allowed only for gpu_tests and pose_bench."
  fi
fi

REF="$(cc_resolve_ref "$REF")"

if [[ -n "$TTL_RAW" ]]; then
  CC_TTL_S="$(cc_parse_ttl "$TTL_RAW")"
elif [[ -n "${CC_TTL_S:-}" ]]; then
  CC_TTL_S="$(cc_parse_ttl "$CC_TTL_S")"
else
  CC_TTL_S="$(cc_default_ttl_s "$JOB" "$INTERACTIVE")"
fi
export CC_TTL_S
cc_require_ttl

JOB_ID="${CC_JOB_ID:-}"
if [[ -z "$JOB_ID" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  short="$(printf '%s' "$REF" | tr -cd 'a-fA-F0-9' | cut -c1-8)"
  kind="$JOB"
  if [[ "$INTERACTIVE" == "1" ]]; then
    kind="interactive"
  fi
  JOB_ID="cc-${kind}-${short:-noref}-${stamp}"
fi

NAME="$JOB_ID"
cc_require_image_tag
ENV_JSON="$(cc_build_pod_env_json "$JOB" "$REF" "$JOB_ID" "$CC_TTL_S" "$INTERACTIVE")"
PAYLOAD="$(cc_build_pod_payload "$NAME" "$ENV_JSON" "$SPOT" "$GPU_CSV")"

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "$PAYLOAD"
  echo "pod_id=DRY_RUN"
  echo "job_id=${JOB_ID}"
  if [[ -n "${CC_RUNPOD_REGISTRY_AUTH_ID:-}" ]]; then
    echo "GET /containerregistryauth/${CC_RUNPOD_REGISTRY_AUTH_ID}"
  fi
  exit 0
fi

if [[ -z "${CC_RUNPOD_TEMPLATE_ID:-}" && -z "${CC_GPU_IMAGE:-}" ]]; then
  cc_fail "Set CC_RUNPOD_TEMPLATE_ID or CC_GPU_IMAGE."
fi
if [[ -z "${CC_RUNPOD_VOLUME_ID:-}" ]]; then
  cc_fail "Set CC_RUNPOD_VOLUME_ID."
fi
cc_require_registry_auth

cc_require_bot_api_key
cc_verify_registry_auth
RESPONSE="$(cc_rest POST /pods "$PAYLOAD")"
POD_ID="$(jq -r '.id // .podId // empty' <<<"$RESPONSE")"
if [[ -z "$POD_ID" || "$POD_ID" == "null" ]]; then
  echo "$RESPONSE" >&2
  cc_fail "Runpod did not return a pod id."
fi
echo "pod_id=${POD_ID}"
echo "job_id=${JOB_ID}"
