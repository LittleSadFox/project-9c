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

trap cc_early_cleanup EXIT
trap cc_early_cleanup INT
trap cc_early_cleanup TERM
trap cc_early_cleanup HUP

cc_require_ttl
cc_require_job_or_interactive
cc_setup_ssh

# Fresh host keys on every boot. The image must not ship any.
ssh_dir="${CC_SSH_DIR:-/etc/ssh}"
rm -f "${ssh_dir}"/ssh_host_*
if [[ "$ssh_dir" == "/etc/ssh" ]]; then
  ssh-keygen -A
  if [[ -x /usr/sbin/sshd ]]; then
    /usr/sbin/sshd
  fi
fi

if [[ -n "${CC_JOB_ID:-}" ]]; then
  mkdir -p "${CC_VOLUME_DIR:-/workspace}/runs/${CC_JOB_ID}"
  export CC_RUN_LOG="${CC_VOLUME_DIR:-/workspace}/runs/${CC_JOB_ID}/log.txt"
  cc_watchdog_start "${CC_VOLUME_DIR:-/workspace}/runs/${CC_JOB_ID}"
else
  cc_watchdog_start
fi

cc_require_cuda_driver

if [[ -n "${CC_JOB:-}" ]]; then
  echo "Start job ${CC_JOB} (ttl=${CC_TTL_S}s)"
  trap - EXIT INT TERM HUP
  exec /opt/cc/scripts/gpu/run_job.sh
fi

echo "Interactive pod. SSH is up. TTL is ${CC_TTL_S}s."
export CC_INTERACTIVE_READY=1
while true; do
  sleep 3600 &
  wait $! || true
done
