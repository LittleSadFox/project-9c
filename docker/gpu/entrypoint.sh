#!/usr/bin/env bash
# Pod entrypoint: sshd, TTL watchdog, then run_job.sh or an interactive wait.
set -euo pipefail

LIB="/opt/cc/scripts/gpu/lib.sh"
if [[ -f "$LIB" ]]; then
  # shellcheck disable=SC1090
  source "$LIB"
else
  echo "ERROR: missing $LIB" >&2
  exit 1
fi

cc_require_ttl
cc_setup_ssh
cc_watchdog_start

if [[ -n "${CC_JOB:-}" ]]; then
  echo "Start job ${CC_JOB} (ttl=${CC_TTL_S}s)"
  exec /opt/cc/scripts/gpu/run_job.sh
fi

echo "Interactive pod. SSH is up. TTL is ${CC_TTL_S}s."
if command -v /usr/sbin/sshd >/dev/null 2>&1; then
  /usr/sbin/sshd
fi
# Wait until the watchdog terminates the pod.
while true; do
  sleep 3600
done
