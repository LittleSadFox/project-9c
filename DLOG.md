# Development log

Record every meaningful change here.
Write in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

## 2026-10-21 — AGENTS.md

Add the self-contained bot rule file.
`coding_plan.md` is the plan authority.
Ryan approved the Phase 0 gate in pull request #1.

## 2026-10-21 — p0-repo-ci-docs

Add pin files, docs, and CI.

Pin files:

- `.python-version` → 3.12
- `.nvmrc` → 24
- `backend/requirements.txt` and `backend/requirements-gpu.txt` (same pins; ONNX Runtime package name is the only difference)
- `backend/requirements-nodeps.txt` → `rtmlib==0.0.16`
- `backend/requirements-dev.txt`
- `frontend/package.json` with the frontend pins from `AGENTS.md`

Docs:

- `README.md` with Mac setup, Runpod setup, commands, and per-phase checklists
- `ARCHITECTURE.md` with diagrams
- `DATA_MODEL.md`
- `TROUBLESHOOTING_LOG.md`
- this file
- `errors/` for daily `ERROR_YYYY-MM-DD.md` logs

CI:

- `.github/workflows/ci.yml`
- Jobs run on `ubuntu-24.04` and `macos-15`
- The Ubuntu job installs the pinned static ffmpeg 7.1.5 build
- The macOS job installs ffmpeg from Homebrew

Out of scope for this change:

- Backend and frontend application skeleton (`p0-skeleton`)
- Runpod runner, `docker/gpu`, and `gpu-image.yml` (`p0-runpod-runner`)
- Phase 4 `requirements-ml.txt`

## 2026-10-21 — CI ffmpeg version check

Accept BtbN's `n7.1.5` banner.
The Ubuntu check now matches `ffmpeg version n?[7-9].`.

## 2026-10-21 — p0-skeleton

Add the application skeleton.

Backend:

- Frozen `Settings` from `CC_*` with a clear error when a path is missing
- Error envelope, Host allow-list, and `/auth/launch` HttpOnly SameSite=Strict cookie
- Library paths, SQLite WAL, and `0001_init.sql`
- Two-lane job queue with a `noop` job and crash recovery
- `/health`, job routes, and SPA fallback
- `create_app(settings, media=..., estimator=...)` for test injection

Frontend:

- Vite app with Liquid Glass tokens and `DESIGN_GUIDELINES.md`
- `AppShell`, empty pages, API client, `useResource`, `useJobs`, job tray, and `t()`
- `build.target` is `["safari16", "chrome107"]`
- Vitest theme-token check and Playwright Chromium smoke

Scripts:

- `setup_mac.sh`, `check.sh`, `dev.sh`, `build.sh`, `run_mac.sh`, `download_models.py`

Out of scope:

- Runpod runner, `docker/gpu`, `scripts/gpu`, `gpu-image.yml`, `sync_volume.sh`, and `ml/jobs.py`

## 2026-10-21 — p0-skeleton pytest path

Set `pythonpath = . ..` in `backend/pytest.ini`.
CI collects tests with that file.
The repo-root `scripts` package is then visible.
`scripts/check.sh` now puts the repo root on `PYTHONPATH` as well.

## 2026-10-21 — SPA path confinement

`spa_target` joins under `frontend/dist` with `safe_join`.
A `..` or absolute path that leaves that folder returns 400.

## 2026-10-21 — p0-runpod-runner

Add the Phase 0 GPU runner.

- `docker/gpu/` builds `climbing-coach-gpu` from `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04`.
- The image has Python 3.12, `onnxruntime-gpu==1.23.2`, the CI static ffmpeg 7.1.5 build, sshd, git, curl, jq, and a TTL watchdog.
- The image has no PyTorch and no MMPose.
- `.github/workflows/gpu-image.yml` builds the image and pushes it to private GHCR.
- Tags are the git sha and, on `main`, `latest`.
- `scripts/gpu/` has `pod_up.sh`, `run_job.sh`, `wait_job.sh`, `pod_down.sh`, and `pod_ls.sh`.
- The scripts always set `CC_TTL_S`.
- The scripts refuse to copy the account API key into pod env.
- `ml/jobs.py` registers `gpu_tests`.
- `scripts/sync_volume.sh` and `scripts/export_labels.py` copy labels and new golden files.

Section 2.2 setup is complete.
AGENTS.md section 9.4 still applies.
Before every first `pod_up`, the Runpod bot must verify the GHCR registry credential.
A complete setup does not skip that check.
The first live `pod_up.sh --job gpu_tests` waits on this pull request merging and on green CI plus a green GPU image build.
After that, the Runpod bot runs it.
This change does not start a pod.

## 2026-10-21 — Runner review fixes

`gpu_tests` sets `CC_REQUIRE` only in the pytest subprocess.
Later tests in the same process keep their skip rules.

The GPU image does not generate SSH host keys at build time.
`entrypoint.sh` generates host keys at start-up, then starts sshd on every pod.

The GPU image workflow frees disk before buildx.
It does not load the image on the runner.
It pushes sha and `latest` only from `main`.

Pod scripts use Basic `x-access-token` git auth, the EU-RO-1 GPU list, and retry terminate.
`wait_job.sh --pod-id` fails if the pod exits before status is `passed`.
`--spot` is allowed only for `gpu_tests` and `pose_bench`.

Section 2.2 setup is complete.
AGENTS.md section 9.4 still applies.
Before every first `pod_up`, the Runpod bot must verify the GHCR registry credential.
A complete setup does not skip that check.
The first live `gpu_tests` pod waits on this pull request merging and on green CI plus a green GPU image build.

Live `pod_up` now GETs `/containerregistryauth/<id>` and refuses on a non-200.
The Dockerfile deletes `/etc/ssh/ssh_host_*` after apt install.
`entrypoint.sh` always generates new host keys.

I did not confirm that `onnxruntime-gpu==1.23.2` (CUDA 12) supports Blackwell `sm_120`.
The default GPU list omits RTX PRO 4500/4000 Blackwell and RTX 5090. ONNX Runtime has never been verified on sm_120 on a pod.

The create payload originally sent `allowedCudaVersions` `12.8`, `12.9`, `13.0`.
An early entrypoint failure writes `status=failed`, pings, and terminates the pod.
`run_job.sh` skips a finished job on restart and only retries terminate.
`--ref` must be a 40-character sha, or the bot box resolves it to one.

## 2026-10-21 — first live gpu_tests findings

The first live `gpu_tests` pod at `bd99ed3` reached `Clone LittleSadFox/project-9c at bd99ed3`, wrote `status=failed`, and self-terminated in about 40s. Safety paths worked.

`allowedCudaVersions` in the create payload made Runpod return 500 "no instances available" on all listed GPU types, even with stock showing. The field is now opt-in via `CC_ALLOWED_CUDA` (unset by default). The image CUDA driver guard (>=12.8, fail closed) is the real floor.

`run_job.sh` now writes redacted git/pip stderr into `runs/<id>/log.txt`.
`wait_job` detects a 404 or `TERMINATED` pod without losing `CC_LAST_HTTP_CODE`, and retries S3 status/metrics reads on transient `SignatureDoesNotMatch`/403.
`pod_up` errors if a flag is missing its value and does not swallow the next flag.
Interactive SIGTERM writes `stopped`, not `failed`.
`pod_down` treats `desiredStatus: TERMINATED` as gone.
A failed-status rewrite does not ping the webhook a second time.
`cc_terminate_self` times out `runpodctl`.

## 2026-10-21 — first live gpu_tests follow-up

The first live `gpu_tests` pod at `bd99ed3` printed `Clone LittleSadFox/project-9c at bd99ed3` and then failed. The pod console was deleted with the pod. The git error was not on the volume. The suspected cause was a bad hand-pasted `cc_repo_token`. On 2026-10-21 the Runpod bot re-set that secret from a verified token. That token passed `ls-remote` and a shallow fetch.

`run_job.sh` now fails fast when `CC_REPO_TOKEN` is empty and writes that error to `status` and `log.txt`. Git runs with `GIT_TERMINAL_PROMPT=0` and `GIT_TRACE_REDACT=1`. Clone stdout and stderr are redacted together. The raw token, the `x-access-token` base64, and basic/bearer header values do not go to the log.

`pod_down` treats only HTTP 404 or `desiredStatus: TERMINATED` as gone. `EXITED` still bills disk. `wait_job` may still treat `EXITED` as an early job exit, then `pod_down` must see 404 or `TERMINATED`.

See `TROUBLESHOOTING_LOG.md` for the allowedCudaVersions 500 and the clone failure.

## 2026-10-21 — second live gpu_tests deleted the checkout

The second live `gpu_tests` pod at `73be826` used an RTX 4090, driver 595.91.07, and CUDA 13.2. `CUDAExecutionProvider` was in use. Pytest reported 82 passed, 28 failed, and 1 skipped. The run folder is `s3://wguvx2347m/runs/cc-gpu_tests-73be8269-20261021T134455Z/`.

`test_run_job_logs_redacted_clone_stderr` ran the real `run_job.sh`. The test helper cleared `CC_*`, so `CC_SRC_DIR` was empty. `SRC` then defaulted to `/tmp/climbing-coach`. The script ran `rm -rf "$SRC"` and deleted the live checkout. Later tests that read repo files failed.

Tests now default `CC_SRC_DIR` and `CC_LIBRARY_DIR` under pytest `tmp_path`.
The default clone dir is `/tmp/cc-src`.
`run_job.sh` only removes a resolved path whose basename matches `cc-src`, whose parent is exactly `/tmp` or a trusted `$TMPDIR`, and that is not a symlink or a live checkout, volume, scratch, HOME, or working-directory path.
`$TMPDIR` is untrusted when it resolves inside the volume, scratch, repo, or HOME.
A wipe refusal also goes to `log.txt`.
The remaining check-to-rm race needs `/tmp` write access on the pod.
CI copies the repo to `/tmp/cc-src` and runs the `gpu_tests` pytest selection from there.

`wait_job` did not see `status=failed` from S3. `aws s3 cp ... -` returned `SignatureDoesNotMatch` on all four retries. `aws s3api get-object` with the same profile worked on the first try. The wait ended when the pod returned 404.

`cc_s3_cp_stdout` now uses `aws s3api get-object` into a temp file.
It retries 403 and `SignatureDoesNotMatch`.
It prints one summary line per poll with the error code and key.
`wait_job` prints `metrics.json` with `jq -c`.

The GPU image now includes `shellcheck`.
`AGENTS.md` and `coding_plan.md` do not name the clone dir, so they stay unchanged.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-21 — third live gpu_tests nested pytest

The third live `gpu_tests` pod at `1af17806` used an L4, driver 595.91.07, and CUDA 13.2. The run folder is `s3://wguvx2347m/runs/cc-gpu_tests-1af17806-20261021T152111Z/`. CUDA and the first script tests passed. Then `test_run_job_rerun_after_clone_reaches_ml_jobs` hung.

`run_job.sh` prefers `/opt/cc/venv/bin/python` when that file exists. The tests only stubbed `python3` on `PATH`, so the real `ml.jobs gpu_tests` ran pytest on `/tmp/cc-src` again. Processes nested about once every 7s.

Tests now set `CC_PYTHON` to the stub. `_run()` times out after 30s. `gpu_tests` sets `CC_IN_GPU_TESTS=1` in the pytest child only. `run_job.sh` and `python -m ml.jobs gpu_tests` refuse a nested `gpu_tests` when that flag is set. The CI pod-layout job installs a fake `/opt/cc/venv/bin/python`.

A second terminate after a successful first attempt is skipped. That avoids a later 401/403 on an expired pod token.

The default GPU list omits Blackwell. ONNX Runtime has never been verified on sm_120 on a pod.

See `TROUBLESHOOTING_LOG.md`.
