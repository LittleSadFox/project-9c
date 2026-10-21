#!/usr/bin/env bash
# List pods and their age. EXITED pods can still bill disk.
# Exit 3 when any pod exists so leftover pods fail the Phase 0 gate.
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
RESPONSE=""
if ! RESPONSE="$(cc_rest GET '/pods')"; then
  if command -v runpodctl >/dev/null 2>&1; then
    runpodctl get pod || runpodctl pod list
  fi
  cc_fail "Runpod GET /pods failed."
fi
ITEMS="$(cc_pods_from_response "$RESPONSE")"
COUNT="$(jq 'length' <<<"$ITEMS")"
NOW="$(date -u +%s)"
if [[ "$COUNT" -eq 0 ]]; then
  echo "no pods"
  exit 0
fi
printf '%s\n' "$ITEMS" | jq -r --argjson now "$NOW" '
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
'
exit 3
