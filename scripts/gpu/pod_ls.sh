#!/usr/bin/env bash
# List pods and their age. EXITED pods can still bill disk.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/gpu/lib.sh"

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      echo "Usage: scripts/gpu/pod_ls.sh [--dry-run]"
      exit 0
      ;;
    *)
      cc_fail "Unknown argument: $1"
      ;;
  esac
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo "GET /pods"
  exit 0
fi

cc_require_bot_api_key
RESPONSE="$(cc_rest GET '/pods')"
ITEMS="$(cc_pods_from_response "$RESPONSE")"
NOW="$(date -u +%s)"
printf '%s\n' "$ITEMS" | jq -r --argjson now "$NOW" '
  if length==0 then "no running pods" else
    .[] | [
      (.id // .podId // "-"),
      (.name // "-"),
      (.desiredStatus // .status // "-"),
      (
        (.lastStartedAt // .createdAt // empty) as $raw
        | if $raw == "" then "-"
          else
            (($raw | sub("\\.[0-9]+Z$"; "Z") | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) as $c
             | (($now - $c) | tostring) + "s")
          end
      )
    ] | @tsv
  end
'
