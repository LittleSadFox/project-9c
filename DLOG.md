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

Tests now set `CC_PYTHON` to the stub. That hook is a test override. A pod uses `/opt/cc/venv/bin/python` unless that file is missing. `run_job.sh` writes `python=<path>` to `log.txt`.
`_run()` starts a new session and kills the process group after 30s.
`gpu_tests` sets `CC_IN_GPU_TESTS=1` in the pytest child only. Tests keep that flag unless a case clears it. `run_job.sh` and `python -m ml.jobs gpu_tests` refuse a nested `gpu_tests` when that flag is set. The refuse line goes to stderr and to the job `log.txt`. The CI pod-layout job installs a fake `/opt/cc/venv/bin/python`.

A second terminate after a successful first attempt is skipped only for the current pod. The stamp is `$CC_TERMINATE_STAMP_DIR/.cc_terminated.$RUNPOD_POD_ID`. Tests set that dir under pytest tmp. The default is `/tmp`. A volume stamp or a stamp for another pod does not skip terminate or the TTL watchdog.
`pod_up` refuses a caller job id when `runs/<id>` already exists on the volume or in S3.

The default GPU list omits Blackwell. ONNX Runtime has never been verified on sm_120 on a pod.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-21 — fourth live gpu_tests shellcheck and webhook

The fourth live `gpu_tests` pod at `2078682a` used an RTX 4090, driver 595.91.07, and CUDA 13.2. The run folder is `s3://wguvx2347m/runs/cc-gpu_tests-2078682a-20261021T163430Z/`. CUDA used `CUDAExecutionProvider`. Pytest reported 152 passed and 1 failed.

The fail was `test_gpu_scripts_pass_shellcheck`. The image apt `shellcheck` flagged SC2031 at `run_job.sh` `export CC_RUN_LOG=...`. CI used a different apt `shellcheck`. The watchdog subshell exported `CC_RUN_LOG`. That write does not change the parent value.

The watchdog no longer exports `CC_RUN_LOG`.
It inherits the parent value.
CI and the GPU image now install the same pinned shellcheck 0.11.0 tarball.
The shellcheck severity stays at the default.
`gpu_tests` writes `ort_providers=<list> used_cuda=<true|false>` to `log.txt`.

The webhook ping used to hide the HTTP code.
A non-2xx reply looked like success.
Curl stderr can contain the host or the URL.

The ping now uses `curl -sS --max-time 15 -o /dev/null -w '%{http_code}'`.
It discards curl stderr.
It logs `webhook ping ok status=<code> curl_rc=<n>` only for HTTP 2xx.
It logs `webhook ping failed status=<code> curl_rc=<n>` for any other code or curl exit.
The log does not store the URL, the token, or curl error text.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-22 — watchdog terminate must survive a bad log

An unwritable job log or run dir must not skip `cc_terminate_self`.
`cc_log` now ignores a failed `tee -a` under `pipefail`.
The watchdog treats `mkdir`, `started_at`, and the TTL `printf` as best effort.
A bad `started_at` read must not kill the watchdog.
Only a digit timestamp enters arithmetic.
A 401 webhook ping still reaches terminate.

## 2026-10-22 — p0-followups-1 S3 match and watchdog tests

Treat an S3 object as missing only on the AWS CLI phrase
`\((NoSuchKey|404)\) when calling the (GetObject|HeadObject) operation`.
Any other error fails closed.
`cc_parse_ttl` and the watchdog use `10#` so a leading zero is decimal.
`run_job.sh` writes `gpu_name=<nvidia-smi name>` in the log header.
`gpu_tests` writes `ort_providers=` before a CUDA `JobError`.
The webhook Authorization header is not in this change.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-22 — p0-runner-fixes-5 webhook Authorization

The live webhook requires a bearer token.
`pod_up` now sets `CC_WEBHOOK_KEY={{ RUNPOD_SECRET_cc_webhook_key }}`.
`cc_curl_post_json` writes `Authorization: Bearer` into the 0600 curl `--config` file.
The key does not go on curl argv.
The ping log still writes only `status=` and `curl_rc=`.
The run folder does not store the key.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-22 — p0-followups-2 S3 upload and stamp safety

`sync_volume.sh` uploads with `aws s3api put-object`.
It pins `s3.multipart_threshold` to 128MB in a temp AWS config.
It does not use `aws s3 cp`.
`cc_s3_object_exists` uses `head-object`.
S3 error summaries redact AWS access-key patterns.
Tests keep a default failing `aws` shim on PATH.
The terminate stamp write refuses a symlink and uses `O_NOFOLLOW` / `O_EXCL`.
`CC_TERMINATE_STAMP_DIR` must not point at the volume.
An empty `RUNPOD_POD_ID` fails loudly and still reaches terminate.
`$TMPDIR` at `/tmp/cc-src-*` is untrusted.
The entrypoint unsets `CC_IN_GPU_TESTS` before it execs `run_job.sh`.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-22 — p0-followups-3 curl trap, image pin, sync_volume

The webhook curl `--config` file uses EXIT and RETURN traps.
The file stays mode 0600.
A failure still removes it.
The key stays off the log.

`run_job.sh` times out a hung `nvidia-smi` name query.
It logs `gpu_name=unknown` after the timeout.

`pod_up`, `run_job`, `wait_job`, and the entrypoint refuse an invalid job id.
A job id must match `[A-Za-z0-9._-]`.
It must be 1-64 characters.
It must not start with a dot or a dash.

A hand-made or interactive pod without `CC_JOB_ID` writes `started_at` under `runs/.ttl-<pod>`.
A restart does not reset the TTL clock.
An already-expired TTL terminates in the foreground.

`pod_up` pins the GPU image to a git-sha tag or digest.
It derives the tag from `CC_GIT_REF` when `CC_GPU_IMAGE` is unset.
It refuses `:latest` unless `CC_GPU_IMAGE_ALLOW_LATEST=1`.
The Runpod template is unchanged.

`sync_volume.sh` no longer writes a temp AWS config.
It does not change `AWS_CONFIG_FILE`.
It does not write `~/.aws/config`.
It refuses files over 5GB before any upload.
`--prefix` defaults to `videos`.
A prefix other than `videos` does not write `videos/manifest.json`.

The Library hint button has space under the card copy.
`httpx.ASGITransport` in the pinned httpx 0.28.1 is async only.
The Starlette TestClient warning is filtered in `pytest.ini`.
A move to `httpx2` would need a new pin, so it is skipped.
The Playwright smoke test stubs `/health` and `/api/jobs`.

See `TROUBLESHOOTING_LOG.md`.
