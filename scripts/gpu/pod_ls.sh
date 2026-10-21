#!/usr/bin/env bash
# List running pods and their age.
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
  echo "GET /pods?desiredStatus=RUNNING"
  exit 0
fi

cc_require_bot_api_key
RESPONSE="$(cc_rest GET '/pods?desiredStatus=RUNNING')"
NOW="$(date -u +%s)"
printf '%s\n' "$RESPONSE" | jq -r --argjson now "$NOW" '
  (if type=="array" then . else (.pods // .data // []) end)
  | if length==0 then "no running pods" else
      .[] | [
        (.id // .podId // "-"),
        (.name // "-"),
        (.desiredStatus // .status // "-"),
        (if .createdAt then
            (((.createdAt | sub("\\.[0-9]+Z$"; "Z") | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) ) as $c
             | (($now - $c) | tostring) + "s")
          else "-" end)
      ] | @tsv
    end
'
