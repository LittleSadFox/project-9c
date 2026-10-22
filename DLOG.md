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

## 2026-10-22 — coding_plan.md Ryan decisions

`coding_plan.md` synced with Ryan's decisions: single put-object with a 150 MiB cap, a 1080p transcode pre-step before the golden-set sync, Phase 0 visual checks waived.

## 2026-10-22 — CI push on main only

A pull-request push ran CI twice: once for `push` and once for `pull_request`.
macOS minutes count 10x on this private repo.

Limit the `push` trigger in `.github/workflows/ci.yml` to `main`.
Keep the `pull_request` trigger unchanged.
Pull requests still run `ubuntu-24.04`, `macos-15`, and `pod-layout` once.
Direct pushes to `main` still run the full matrix.

Both `ci.yml` and `gpu-image.yml` use this concurrency group:
`ci-${{ github.workflow }}-${{ github.ref }}`.
Cancel in-progress runs only on `pull_request`.
Do not cancel a run on `main`.

## 2026-10-22 — p0-followups-3 curl trap, image pin, sync_volume

`cc_curl_post_json` is a subshell with `trap 'rm -f -- "$cfg"' EXIT`.
It does not save or restore the caller's EXIT trap.
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
An already-expired TTL terminates in the foreground and exits 1.

`wait_job` runs `pod_down` for the `--pod-id` value after a timeout.
It does not look up a pod by name or job id.
The default wait timeout stays `CC_TTL_S` plus 300 seconds.

`pod_up` pins the GPU image to a git-sha tag or digest.
It derives the tag from `CC_GIT_REF` when `CC_GPU_IMAGE` is unset.
It refuses `:latest` unless `CC_GPU_IMAGE_ALLOW_LATEST=1`.
A live create checks the GHCR manifest before `POST /pods`.
It uses `docker manifest inspect`, or a registry HEAD with an existing token.
A missing tag refuses the create.
It never falls back to `:latest`.
`defaults.env` does not pin a digest.
The Runpod template is unchanged.

`sync_volume.sh` no longer writes a temp AWS config.
It does not change `AWS_CONFIG_FILE`.
It does not write `~/.aws/config`.
It refuses files over 150MiB before any upload.
Multipart is not supported yet.
`--prefix` defaults to `videos`.
It refuses `.` and empty path segments.
A prefix other than `videos` does not write `videos/manifest.json`.

The Library hint button has space under the card copy.
`httpx.ASGITransport` in the pinned httpx 0.28.1 is async only.
The Starlette TestClient warning is filtered by message in `pytest.ini`.
A move to `httpx2` would need a new pin, so it is skipped.
The Playwright smoke test stubs `/health` and `/api/jobs`.

The `cc_run_timeout` fallback starts the child in a new process group.
It uses `perl setpgrp` or `set -m`.
It group-kills only when the child pgid differs from this shell.
It never kills the caller group.
A test times out a grandchild `sleep` and checks the parent still logs.
The nvidia-smi hang test forces that fallback so Linux matches macOS.
The no-job-id watchdog test sets `CC_TERMINATE_NO_SLEEP=1` and a 200 curl stub.

See `TROUBLESHOOTING_LOG.md`.

## 2026-10-22 — p1-A backend media and library

Add Phase 1 slice A: library CRUD, streaming upload, ingest, media endpoints, trash, manual attempts, and cut.

- Routes except pose. `routes/__init__.py` mounts them. Slice B adds one pose line.
- Services: `library`, `ingest`, `attempts`. Ingest enqueues pose by job kind.
- `FfmpegTool` calls ffmpeg and ffprobe with argument lists. `FakeMediaTool` stays for API tests.
- Upload writes chunks to `tmp/` and bounds memory. A fixture generator builds the frame-code video for cut tests.
- No 0002 migration. Schema stays `0001_init.sql`.
- Do not start a pod. Do not touch `scripts/gpu/`, `docker/`, `AGENTS.md`, or `coding_plan.md`.
- Local checks (ffmpeg 7.1.5 static build): ruff clean, mypy clean, pytest `not model and not gpu and not macos and not golden and not slow` → 227 passed, 1 skipped, 1 deselected.

## 2026-10-22 — p1-A trash path and media skip

`empty_trash` and `restore_trash` resolve the stored path with `safe_join(paths.trash, ...)`.
A row whose path leaves `trash/` raises `bad_path` and deletes nothing.
The `media` marker skips when `ffmpeg` or `ffprobe` is missing from PATH.

## 2026-10-22 — p1-A rotation, restore, and trash root

`make_proxy` maps display-matrix -90/270 to `transpose=1` and +90 to `transpose=2`.
It writes `-display_rotation 0` as an input option so the proxy keeps no rotation metadata.
A video restore brings back only the attempts stored in that trash payload.
A stored trash path that resolves to `trash/` itself, or above it, raises `bad_path`.

## 2026-10-23 — VFR fixture uses fps_mode

`write_vfr_video` now uses `-fps_mode vfr`.
Homebrew ffmpeg on macos-15 rejects `-vsync`.
The pinned 7.1.5 static build accepts `-fps_mode` and still marks the clip as VFR.

## 2026-10-22 — p1-B pose

Add the Phase 1 pose slice.

- `core/halpe26.py`, `core/tracking.py`, `core/climber.py`, and `core/smoothing.py` stay numpy-only.
- `RtmlibEstimator` calls rtmlib `YOLOX` and `RTMPose` from local ONNX files. It does not use `PoseTracker`.
- `FixtureEstimator` feeds prepared boxes to tests. `CC_POSE_BACKEND=fixture` selects it.
- Skip the pose call when the detector returns no boxes.
- The detector runs every `det_every` frames. In-between frames use keypoint boxes.
- Store tracks as `pose/<video_id>/<run_id>.npz`. The effective cache key is an edits hash.
- `media/frames.py` is the OpenCV `FrameReader` over the proxy.
- The pose job runs on the compute lane. A's ingest enqueues it.
- Phase 1 routes: `GET /pose`, `GET /pose/keypoints` (gzip), and `GET /pose/persons`.
- Scene edits, `PUT /pose/climber`, and the review queue stay in Phase 2.
- `ml/jobs.py` registers `pose_bench`. It measures fps per mode and CUDA vs CPU mean error.
- ONNX weights come from `download_models.py` into `CC_MODELS_DIR`. Do not commit them. On a pod that path is `/workspace/models`. Fetch the weights once before the first `pose_bench`.

Out of scope:

- Pod `pose_bench` run (Runpod bot, after merge)
- 1080p transcode
- Slice A media and library routes

## 2026-10-22 — p1-B stream pose frames

`handle_pose_job` no longer calls `list(reader.iter_frames())`.
`process_frames` walks the iterator once.
The frame count comes from the video row.
A 2-minute 1280 proxy no longer sits in RAM as one list.

`RtmlibEstimator` ignores `import-not-found` and `import-untyped` for rtmlib.
`models.lock.json` pins YOLOX tiny/m/x and RTMPose s/m/x Halpe26 zip sha256 values.
`download_models.py` checks the digest on the temp file before it replaces dest.
A mismatch deletes the file and exits 1.
A null digest is refused unless `--allow-unpinned` is set.

A failed pose job rolls back the run transaction.
No track rows stay.
The run is written again as `failed`.
Partial NPZ and `.tmp` files are removed.
`GET /pose` serves only a `done` run.

`pose_bench` loops `lightweight`, `balanced`, and `performance`.
It passes `mode` into the estimator.
Before a real bench it runs `download_models.py` into `CC_MODELS_DIR`.
A present file with a matching sha256 is skipped.
A mismatch deletes the file and fails the job.
It stops reading the golden clip after `n_frames`.
Parity fails when fewer than 90% of frames compare, or when the mean is above 1 px.
`metrics.json` records `frames_total`, detection counts, and `frames_compared`.
The next pod command is `python -m ml.jobs pose_bench --run-dir "$RUN_DIR"`.

`current_estimator` keys the cache on mode.
A pose job that changes `pose_mode` builds a new estimator.
`pose_bench` does not use that cache. It builds one estimator per mode.

Zip extract writes a unique sibling temp folder, then replaces the dest.
A reused folder is checked against zip member sizes and re-extracted on a mismatch.
Download temps include the pid and job id so two pods do not collide.

## 2026-10-22 — p1-B pose_bench clip and pairing

`pose_bench` no longer opens the first `.mp4`/`.mov` in `CC_GOLDEN_DIR`.
It takes a filename in `CC_BENCH_CLIP` or `--clip`.
The name goes through `safe_join` and `safe_ext` under `CC_GOLDEN_DIR`.
A path, `..`, or a file outside that folder is refused.
The default name is `sample1.mp4`.
`CC_BENCH_START` / `--start-frame` sets the first proxy frame.

The bench transcodes that clip with `make_upright_u8_proxy`.
ffmpeg applies the rotation tag and writes 8-bit `yuv420p` H.264.
OpenCV then reads the proxy, not the raw 10-bit `.mov`.

`compare_keypoints` matches people in one frame by box IoU, then by nearest centroid.
It does not zip people by list order.

Debug numbers are on by default.
`--no-debug` or `CC_POSE_BENCH_DEBUG=0` turns them off.
The debug block writes clip name, size, sha256, codecs, pixel formats, rotation, frame shape, dtype, BGR channel means, and boxes.
It does not write a frame or a drawn image.

The upright 8-bit proxy is written to a pod-local temp folder.
`pose_bench` does not pass `run_dir/artifacts`.
A `finally` block deletes the proxy after the frames are in memory.

`pod_up.sh` passes `CC_BENCH_CLIP` and `CC_BENCH_START` for `pose_bench`.
The default is `sample1.mp4` and start frame `0`.

The 90% compared-frame rule and the 1 px mean stay in place.

A committed `testsrc` clip (`backend/tests/fixtures/pose/rotated_10bit_testsrc.mp4`) is HEVC Main 10 with a −90° display matrix.
Tests that need ffmpeg use the `media` marker.

The code default is `sample1.mp4` and start frame `0`.
Env and args only override those defaults.
The default name still goes through `safe_join` and `safe_ext`.
`python -m ml.jobs pose_bench --run-dir "$RUN_DIR"` with no extra flags uses `sample1.mp4`, start frame 0, 100 frames, `min-compared-frac` 0.9, and debug on.

Ubuntu CI sets `CC_REQUIRE_MEDIA=1`.
A skipped `media` test then fails when ffmpeg is missing or too old.
The macOS CI job and `pod-layout` leave that flag unset.

Rerun on a pod launched from main's `pod_up.sh`:

```text
python -m ml.jobs pose_bench --run-dir "$RUN_DIR"
```

## 2026-10-22 — pose_bench diagnostics and TF32 off

The parity gate stays the all-keypoint mean.
`parity_ok` is true only when that mean is ≤ 1.0 px and at least 90% of frames compare.
The gate does not filter by score.
The gate does not use a kept-fraction floor.

Each CUDA mode block in `metrics.json` now also records numbers only:

- per-frame error: median, p95, max, and the five worst frames
- each of the 26 Halpe names: mean error, mean CPU score, mean CUDA score
- `mean_abs_px_confident` over keypoints with score ≥ `SCORE_THR` (0.3) on both devices
- `keypoints_kept` and `keypoints_dropped`

`pose_bench` CUDA sessions set `use_tf32=0`.
The CPU and CUDA rtmlib paths match except the ONNX Runtime provider.
Both use the same pose size, ImageNet BGR mean/std, float32 input, and `simcc_split_ratio=2.0`.
rtmlib creates `InferenceSession(..., providers=[name])` with no session options.
Ampere TF32 can move the SIMCC argmax on rtmpose-s by about 1 px.

## 2026-10-22 — shared CUDA provider options

`cuda_providers()` returns
`[("CUDAExecutionProvider", {device_id: 0, use_tf32: 0}), "CPUExecutionProvider"]`.
`RtmlibEstimator` and `pose_bench` both call that helper.
rtmlib 0.0.16 builds the provider list from `device` alone.
The estimator builds YOLOX and RTMPose as usual, then on CUDA replaces
`tool.session` with `InferenceSession(onnx_path, providers=cuda_providers())`.
CPU sessions stay as rtmlib built them.
It does not swap `ort.InferenceSession`.
`pose_bench` reads `use_tf32` from the live det and pose sessions.
It writes those values under `cuda_provider_options`.
`tf32_off_confirmed` is true only when both sessions report `"0"`.
A mismatch writes a WARNING line. It does not change the parity gate.
`pose_bench` fails a mode when det or pose `get_providers()[0]` is not
`CUDAExecutionProvider`. That stops a silent CPU fallback from passing parity.

The plain command is unchanged:

```text
python -m ml.jobs pose_bench --run-dir "$RUN_DIR"
```

It still uses `sample1.mp4`, start frame 0, 100 frames, `min-compared-frac` 0.9, and debug on.
