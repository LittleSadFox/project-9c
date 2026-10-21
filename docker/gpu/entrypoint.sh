#!/usr/bin/env bash
# Pod entrypoint: host keys, sshd, TTL watchdog, then the job or an interactive wait.
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
cc_require_job_or_interactive
cc_setup_ssh

# New host keys on every pod. Do not bake keys into the image.
if ! compgen -G '/etc/ssh/ssh_host_*' >/dev/null; then
  ssh-keygen -A
fi
if [[ -x /usr/sbin/sshd ]]; then
  /usr/sbin/sshd
fi

if [[ -n "${CC_JOB_ID:-}" ]]; then
  cc_watchdog_start "${CC_VOLUME_DIR:-/workspace}/runs/${CC_JOB_ID}"
else
  cc_watchdog_start
fi

cc_require_cuda_driver

if [[ -n "${CC_JOB:-}" ]]; then
  echo "Start job ${CC_JOB} (ttl=${CC_TTL_S}s)"
  exec /opt/cc/scripts/gpu/run_job.sh
fi

echo "Interactive pod. SSH is up. TTL is ${CC_TTL_S}s."
while true; do
  sleep 3600
done
