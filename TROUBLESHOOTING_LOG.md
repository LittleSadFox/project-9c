# Troubleshooting log

Record each problem and its fix here.
Write in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

Do not put secrets in this file.
Do not put footage paths that identify private videos.

## Template

Copy this block for a new entry.

```text
### YYYY-MM-DD — short title

- Symptom:
- Where it failed: bot computer / CI / pod / Mac
- Cause:
- Fix:
- Prevention:
```

## Entries

### 2026-10-24 — review hotkeys behind a focused control or sheet

- Symptom: Enter accepted a proposal while a button, a link, or a confirm sheet had focus. Delete rejected behind a sheet.
- Where it failed: bot computer (Vitest)
- Cause: Hotkeys only skipped inputs, textareas, and contenteditable. They still read keys from buttons, links, and `role=button`. An open dialog did not disable the map.
- Fix: Treat button, link, and `role=button` as blocked targets. Skip every hotkey while `[role=dialog][aria-modal=true]` is open. The review page also passes `enabled=!sheet`.
- Prevention: Keep a test for a focused button, a focused link, and an open sheet.

### 2026-10-24 — Phase 2 e2e waits for D and E

- Symptom: A keyboard review against the live API 404s on `/proposals`, `/scene`, and pose edit routes until slices D and E merge.
- Where it failed: bot computer (Playwright)
- Cause: This slice ships in parallel with mocked `api/*` clients. The detect and skeleton backends are now on main after p2-A and p2-B.
- Fix: Run `e2e/phase2.keyboard.spec.js` against page-route mocks. Keep `e2e/phase2.spec.js` skipped unless `CC_E2E_BACKEND=1` and `CC_POSE_BACKEND=fixture`.
- Prevention: This rebase sits on main after p2-B (`f74166c4`). Run the backend e2e when those flags are set.

### 2026-10-24 — stale effective track after a pose re-run

- Symptom: An edit still showed the old climber after a new pose job.
- Where it failed: bot computer (design check)
- Cause: A cache keyed only by the edits hash can sit next to a replaced NPZ.
- Fix: Key the cache with the raw NPZ sha256 plus the edits hash. Store it next to the run file. A new run id writes a new path.
- Prevention: Never serve `*.effective.npz` when the raw file hash does not match.

### 2026-10-24 — 409 pose-busy test raced the live worker

- Symptom: `test_pose_edit_conflict_while_pose_job_runs` got 201 in pod-layout. Ubuntu and macOS passed.
- Where it failed: CI pod-layout /tmp/cc-src
- Cause: The test inserted a queued pose job. The compute worker claimed it, the missing proxy failed the job, and the 409 check no longer saw queued or running.
- Fix: Insert the fixture job as `running`. The worker only claims `queued` rows.
- Prevention: Do not leave a queued pose job for a live `JobQueue` unless the test wants the worker to run it.

### 2026-10-24 — two pose runs in the same second

- Symptom: A pose re-run in the same second still served the old run.
- Where it failed: bot computer
- Cause: `created_at` has one-second resolution. `ORDER BY created_at DESC` is not stable.
- Fix: Order by `created_at DESC, rowid DESC`.
- Prevention: Do not pick the latest row by a second-resolution stamp alone.

### 2026-10-24 — multi-track keypoint index used the filtered row

- Symptom: `GET /pose/keypoints` and POST edit `frames` showed zeros for the climber when a second person was present.
- Where it failed: bot computer
- Cause: The code enumerated `frame[mask]` and then read `keypoints[index]` from the full array.
- Fix: Zip `frame[mask]` with `keypoints[mask]`.
- Prevention: Do not mix a filtered index with an unfiltered pose array.

### 2026-10-24 — edit write during a live pose job

- Symptom: A POST edit can race a pose job and leave a partial row.
- Where it failed: bot computer (design check)
- Cause: A pre-read of `jobs` and a later INSERT are two transactions.
- Fix: Use `BEGIN IMMEDIATE`, then the busy SELECT, then the edit and feedback writes, then COMMIT.
- Prevention: Do not check the pose job in a separate read before the write.

### 2026-10-24 — floor sign flipped when a standing toe sat below the line

- Symptom: `leave_ground` on a clean synthetic clip was about 75 frames late.
- Where it failed: bot computer (unit tests)
- Cause: `to_floor_frame` flipped the axis when the first standing toe was slightly below the floor (`y=604.8` vs `y=600`). Height then grew while the climber stood.
- Fix: Keep the floor line left to right. Do not flip. Height above the floor is `floor_y - y`.
- Prevention: Test the auto floor on standing frames whose toes sit a few pixels off the line.

### 2026-10-24 — sit start hid behind toes on the floor

- Symptom: A sit-start clip produced no `leave_ground`.
- Where it failed: bot computer (unit tests)
- Cause: The lowest body point stayed on the toes. The hips dropped, but the toes stayed on the floor, so height never crossed 0.15 `s`.
- Fix: In the sit profile, drop the hips by 0.85 `s` and lift the feet onto the wall (1.15 `s`) until the labelled leave frame.
- Prevention: Keep sit-start coverage in `test_events.py` and in the eval fixture.

### 2026-10-24 — fall profile returned early

- Symptom: `ground_return` was about 19 frames early on the synthetic fall.
- Where it failed: bot computer (unit tests)
- Cause: The fall eased the feet down before the labelled land frame. The 0.10 `s` hold then started too soon.
- Fix: Keep foot lift at 0.45 `s` until the land frame.
- Prevention: Label leave and land as contact events, not as padded proposal windows.

### 2026-10-23 — invalid started_at hit expired TTL on a clock tick

- Symptom: Ubuntu CI failed `test_started_at_injection_does_not_run`. `cc_watchdog_start` exited 1 after `terminate ok`.
- Where it failed: CI ubuntu-24.04
- Cause: A non-numeric `started_at` was rewritten with `date +%s`, then `now` was read again. A 1s tick made `remain` 0 when `CC_TTL_S=1`.
- Fix: Read `now` once first. Rewrite an invalid stamp to that same `now` so `remain` is `CC_TTL_S`. A truly expired stamp still terminates in the foreground.
- Prevention: Do not take a second wall-clock read after rewriting `started`.

### 2026-10-22 — ffmpeg rejects `.mp4.tmp` as an output name

- Symptom: Ingest failed with `Unable to choose an output format for '.../proxy.mp4.tmp'`.
- Where it failed: bot computer (media tests)
- Cause: `FfmpegTool` wrote the atomic temp next to `proxy.mp4` as `proxy.mp4.tmp`. ffmpeg does not treat that suffix as MP4.
- Fix: Write the temp as `proxy.tmp.mp4` (`stem + ".tmp" + suffix`). Then `os.replace`.
- Prevention: Keep the real media extension on ffmpeg outputs.

### 2026-10-22 — display_rotation is an input option

- Symptom: `ffmpeg ... -display_rotation 90 dest.mp4` failed. The proxy stayed landscape.
- Where it failed: bot computer (media tests)
- Cause: In ffmpeg 7, `-display_rotation` is an input option. A rotate metadata tag on encode did not write a display matrix.
- Fix: Encode a base file. Remux with `-display_rotation 90 -i base -c copy dest`. Probe then sees `rotation=90`. `make_proxy` transposes, then scales.
- Prevention: Do not put `-display_rotation` after `-i` when you write a file.

### 2026-10-22 — iPhone -90 proxy rotation

- Symptom: A portrait iPhone clip (`rotation=-90`) came out 180° off in the proxy pixels. Players then rotated it again.
- Where it failed: Coder review of PR #19
- Cause: `-90` normalized to 270 and used `transpose=2`. `-noautorotate` also copied the display matrix onto the proxy.
- Fix: Use `transpose=1` for -90/270 and `transpose=2` for +90. Pass `-display_rotation 0` before `-i`. ffmpeg 7.1 ignores `-metadata:s:v rotate=0` for the display matrix.
- Prevention: Assert a corner marker on -90 and +90 fixtures. Assert ffprobe reports no rotation on the proxy.

### 2026-10-22 — lightweight rtmpose-s CUDA/CPU mean 1.053 px

- Symptom: After the clip and pairing fix, `pose_bench` at `9466729` compared 100 of 100 frames. Balanced (0.234 px) and performance (0.088 px) passed. Lightweight failed at 1.053 px.
- Where it failed: pod (RTX 4090)
- Cause: CPU and CUDA rtmlib paths match except the ONNX Runtime provider. rtmpose-s decodes SIMCC with `argmax` and `simcc_split_ratio=2.0`. Ampere TF32 can move that argmax by about 1 px. The all-keypoint mean includes low-score points.
- Fix: Keep the all-keypoint mean ≤ 1.0 px gate. Write per-frame, per-keypoint, and confident-mean numbers in `metrics.json`. Default `pose_bench` CUDA sessions to `use_tf32=0`. Do not change the app estimator.
- Prevention: Do not change what the gate measures without Ryan. Treat score filters and TF32 as diagnostics or bench-only options.

### 2026-10-22 — pose_bench parity compared the wrong clip

- Symptom: Pod `pose_bench` at `c5b5392` failed the 90% / 1 px gate. Lightweight and balanced compared 0 of 100 frames. Performance compared 21 of 100 with a 90.09 px mean.
- Where it failed: pod (RTX 4090)
- Cause: `_load_bench_frames` opened the first file in `/workspace/videos` (`mac-test2.mov`). OpenCV decoded the raw HEVC Main 10 Dolby Vision clip and ignored the rotation tag. `compare_keypoints` then zipped people by list order.
- Fix: Name the clip (`CC_BENCH_CLIP=sample1.mp4`). Decode it through the upright 8-bit proxy. Match people by frame index, then box IoU or centroid. Keep the 90% and 1 px limits.
- Prevention: Never pick the first file in the golden folder. Log clip name, size, sha256, codec, pixel format, and rotation in `metrics.json`.

### 2026-10-21 — GPU image build ran out of disk

- Symptom: `gpu-image.yml` failed at `importing to docker` with `no space left on device`.
- Where it failed: CI
- Cause: `load: true` stored the CUDA image in buildkit, a tarball, and the Docker store.
- Fix: Free disk before buildx. Set `PIP_NO_CACHE_DIR=1`. Build without load. Push only from `main`.
- Prevention: Keep `load: false` on pull requests. Push the sha tag from `main` so the Runpod bot can pull it after merge.

### 2026-10-21 — CC_REQUIRE leaked out of gpu_tests

- Symptom: Later pytest cases failed because a missing need became a hard fail.
- Where it failed: bot computer / CI
- Cause: `gpu_tests` wrote `CC_REQUIRE` into `os.environ` in its own process.
- Fix: Set `CC_REQUIRE` only in the subprocess `env`. Add a test that proves the parent process is unchanged.
- Prevention: Do not assign required markers on `os.environ` in job helpers.

### 2026-10-21 — allowedCudaVersions returned HTTP 500

- Symptom: Live `pod_up` failed with HTTP 500 `no instances available` on every listed GPU type. Stock still showed those types.
- Where it failed: pod create / Runpod REST
- Cause: The create payload sent `allowedCudaVersions`. The live API treated that filter as empty stock.
- Fix: Omit `allowedCudaVersions` by default. Set `CC_ALLOWED_CUDA` only when you opt in. The image CUDA driver guard (>=12.8, fail closed) is the real floor.
- Prevention: Do not send `allowedCudaVersions` unless the live API accepts the list and stock still matches.

### 2026-10-21 — first live gpu_tests clone failed

- Symptom: The first live `gpu_tests` pod at `bd99ed3` reached `Clone LittleSadFox/project-9c at bd99ed3`, wrote `status=failed`, and self-terminated in about 40s. The pod console was deleted with the pod, so the git error was not captured.
- Where it failed: pod
- Cause: The suspected cause was a bad `cc_repo_token` secret value. That value was hand-pasted. On 2026-10-21 the Runpod bot re-set the secret in place from a verified token. That token passed `ls-remote` and a shallow fetch.
- Fix: `run_job.sh` now fails fast when `CC_REPO_TOKEN` is empty, sets `GIT_TERMINAL_PROMPT=0`, and writes redacted git stderr to `runs/<id>/log.txt`.
- Prevention: Do not hand-paste the repo token. Confirm the secret with `ls-remote` before the next live pod.

### 2026-10-21 — live gpu_tests deleted /tmp/climbing-coach

- Symptom: The second live `gpu_tests` pod at `73be826` used CUDA and `CUDAExecutionProvider`. Pytest reported 82 passed, 28 failed, and 1 skipped. Many of the failures were missing repo files.
- Where it failed: pod
- Cause: `test_run_job_logs_redacted_clone_stderr` ran `run_job.sh` with `CC_SRC_DIR` unset. `SRC` defaulted to `/tmp/climbing-coach`. `rm -rf "$SRC"` deleted the live checkout.
- Fix: Tests now default `CC_SRC_DIR` and `CC_LIBRARY_DIR` under pytest `tmp_path`. The default clone dir is `/tmp/cc-src`. `run_job.sh` only removes a resolved path whose basename matches `cc-src`, whose parent is exactly `/tmp` or a trusted `$TMPDIR`, and that is not a symlink or a live checkout, volume, scratch, HOME, or working-directory path. `$TMPDIR` is untrusted when it resolves inside the volume, scratch, repo, HOME, `/tmp/cc-src`, or a sibling `/tmp/cc-src-*` path. CI copies the repo to `/tmp/cc-src` and runs the `gpu_tests` pytest selection from there.
- Prevention: Keep destructive paths on `tmp_path`. Do not run `run_job.sh` against the live checkout. The remaining check-to-rm race needs `/tmp` write access on the pod; do not give extra writers access to `/tmp` on a job pod.

### 2026-10-21 — live gpu_tests nested pytest through /opt/cc python

- Symptom: The third live `gpu_tests` pod at `1af17806` used an L4, CUDA 13.2, and `CUDAExecutionProvider`. Pytest never finished. `test_run_job_rerun_after_clone_reaches_ml_jobs` hung.
- Where it failed: pod
- Cause: `run_job.sh` used `/opt/cc/venv/bin/python` from the image. Tests only stubbed `python3` on `PATH`. The real `ml.jobs gpu_tests` ran pytest on `/tmp/cc-src` again. `_run()` had no timeout.
- Fix: Tests set `CC_PYTHON` to the stub. `_run()` starts a new session and kills the process group after 30s. `gpu_tests` sets `CC_IN_GPU_TESTS=1` on the pytest child. Tests keep that flag unless a case clears it. `run_job.sh` and `ml.jobs` refuse a nested `gpu_tests` before the EXIT trap and before mkdir. CI creates a fake `/opt/cc/venv/bin/python`. A second terminate after success is skipped only for this pod. Tests write stamps under `CC_TERMINATE_STAMP_DIR`. `pod_up` refuses a reused job id.
- Prevention: Do not let `run_job.sh` tests use `/opt/cc/venv/bin/python`. Keep `_run()` bounded. Do not store the terminate stamp on the volume. Do not reuse `CC_JOB_ID`.

### 2026-10-21 — wait_job S3 cp-to-stdout failed

- Symptom: `wait_job` did not read `runs/<id>/status`. It only stopped when the pod returned 404.
- Where it failed: bot computer / volume S3
- Cause: `aws s3 cp s3://... -` returned `SignatureDoesNotMatch` on all four retries against `https://s3api-eu-ro-1.runpod.io/`. `aws s3api get-object` with the same profile worked.
- Fix: Read objects with `aws s3api get-object`. Keep the 403 and `SignatureDoesNotMatch` retry. Print one summary line per poll.
- Prevention: Do not use `aws s3 cp ... -` against the Runpod S3 endpoint.

### 2026-10-22 — webhook ping returned 401 without a bearer

- Symptom: Live `gpu_tests` pods logged `webhook ping failed status=401`.
- Where it failed: pod / webhook
- Cause: The ping posted the URL only. The bot webhook requires `Authorization: Bearer`.
- Fix: Wire `CC_WEBHOOK_KEY={{ RUNPOD_SECRET_cc_webhook_key }}`. Write the header into the 0600 curl `--config` file. Keep the key off curl argv, the run folder, and the log.
- Prevention: Do not put the key on curl argv. Test a fake key and prove it is absent from the run folder.

### 2026-10-22 — loose S3 404 looked like a missing object

- Symptom: A 404 substring in any S3 error looked like a missing object.
- Where it failed: review
- Cause: `cc_s3_cp_stdout` and `cc_s3_object_exists` matched `NoSuchKey|Not Found|404`.
- Fix: Match only `\((NoSuchKey|404)\) when calling the (GetObject|HeadObject) operation`. Fail closed on any other error.
- Prevention: Keep the match on the AWS CLI phrase. Test the full GetObject and HeadObject lines. Test a loose `NoSuchKey` or `404`.

### 2026-10-22 — leading-zero TTL used octal

- Symptom: `cc_parse_ttl 010m` became 480s.
- Where it failed: review
- Cause: Bash `$((n * 60))` reads a leading zero as octal.
- Fix: Use `10#` in `cc_parse_ttl` and in the watchdog `started_at` math.
- Prevention: Keep a decimal test for `010m` and `010`.

### 2026-10-22 — unwritable log aborted terminate

- Symptom: A failed `tee -a` on `CC_RUN_LOG` could stop `cc_terminate_self` before the API call under `pipefail`. A failed watchdog `mkdir` or `started_at` write could exit the watchdog before `sleep`. A bad `started_at` read or parse could also kill the watchdog after a container restart.
- Where it failed: review
- Cause: `set -euo pipefail` treated a log write as fatal. The watchdog fed `started_at` into `$(( ))` without a digit check.
- Fix: Ignore a failed `tee -a` in `cc_log`. Add `|| true` to the watchdog `mkdir`, `started_at` write, and TTL `printf`. Accept only a short digit `started_at`. Clamp a future value to now.
- Prevention: Keep terminate after a log write failure. Test an unwritable log, an unwritable run dir, a 401 ping, and a bad `started_at`.

### 2026-10-21 — image shellcheck flagged SC2031

- Symptom: The fourth live `gpu_tests` pod at `2078682a` failed only `test_gpu_scripts_pass_shellcheck`. CI did not flag the same scripts.
- Where it failed: pod
- Cause: The image installed apt `shellcheck`. CI installed a different apt `shellcheck`. The watchdog subshell exported `CC_RUN_LOG`. That is SC2031.
- Fix: Stop exporting `CC_RUN_LOG` in the watchdog subshell. Pin shellcheck 0.11.0 in CI and in the GPU image.
- Prevention: Keep the same shellcheck tarball and sha256 in `.github/workflows/ci.yml` and `docker/gpu/Dockerfile`. Do not lower severity.

### 2026-10-21 — webhook ping hid HTTP failures

- Symptom: The fourth live `gpu_tests` webhook probably never arrived. The job log had no HTTP status.
- Where it failed: pod / webhook
- Cause: `curl` returned 0 for a non-2xx reply. The ping discarded stdout. Curl stderr can contain the host or the URL.
- Fix: Read `%{http_code}` and the curl exit. Log `webhook ping ok status=<code> curl_rc=<n>` only for HTTP 2xx. Log `webhook ping failed status=<code> curl_rc=<n>` otherwise. Discard curl stderr. Set `--max-time 15`.
- Prevention: Do not write curl stderr, the webhook URL, or the token to `log.txt` or the run folder.

### 2026-10-22 — Mac sync_volume multipart SignatureDoesNotMatch

- Symptom: Runpod S3 `CreateMultipartUpload` returned `SignatureDoesNotMatch` on a ~40MiB golden video.
- Where it failed: Mac / volume S3
- Cause: AWS CLI `s3 cp` uses multipart above 8MB. Runpod S3 rejects that signing path. A single `PutObject` works.
- Fix: `sync_volume.sh` uses `aws s3api put-object` and `get-object` only. It does not write a temp AWS config. It does not change `AWS_CONFIG_FILE`. It does not write `~/.aws/config`. It refuses files over 150MiB before any upload. Multipart is not supported yet. Runpod S3 EU-RO-1 rejects larger single PUTs.
- Prevention: Do not use `aws s3 cp` against the Runpod S3 endpoint. Do not export `AWS_CONFIG_FILE` from `sync_volume.sh`.

### 2026-10-22 — terminate stamp symlink and volume override

- Symptom: A planted `/tmp` symlink or `CC_TERMINATE_STAMP_DIR` on the volume could skip terminate after a restart.
- Where it failed: review
- Cause: `printf >stamp` follows a symlink. The stamp dir hook had no volume guard.
- Fix: Write the stamp with `O_NOFOLLOW` and `O_EXCL`. Refuse a symlink stamp. Allow the hook only under `/tmp` or a trusted `$TMPDIR`, never on the volume.
- Prevention: Keep stamps off the volume. Test a planted symlink and a volume stamp dir.

### 2026-10-22 — hung nvidia-smi and crash-loop TTL

- Symptom: A hung `nvidia-smi` could stall `run_job.sh`. A crash-looping hand-made pod without `CC_JOB_ID` reset `started_at` on every restart. An already-expired TTL still exec'd the job.
- Where it failed: review
- Cause: The name query had no timeout. The watchdog had no persisted clock without a job id. The expired branch returned 0.
- Fix: Time out the name query and log `gpu_name=unknown`. Persist `started_at` under `runs/.ttl-<pod>`. Terminate in the foreground when the TTL is already expired, then exit 1.
- Prevention: Keep the TTL backstop. Do not reset `started_at` on a container restart.

### 2026-10-22 — curl --config leftover, :latest image, and missing sha tag

- Symptom: A failed webhook ping could leave the 0600 curl `--config` file. `pod_up` defaulted to `:latest`. A later pin to `:sha` created pods when GHCR had no tag. Saving the caller's EXIT trap ran `cleanup` inside `$(cc_curl_post_json)`.
- Where it failed: review
- Cause: The config file used `rm` after curl only. `defaults.env` pinned `:latest`. Most shas have no image. `trap -p EXIT` in a command substitution prints the parent trap.
- Fix: Run `cc_curl_post_json` as a subshell with its own EXIT `rm`. Derive a git-sha tag from `CC_GIT_REF`. Refuse `:latest` unless `CC_GPU_IMAGE_ALLOW_LATEST=1`. Check the GHCR manifest before `POST /pods`. Fail closed when the check cannot run.
- Prevention: Do not put secrets on curl argv. Do not start a pod from `:latest` without an explicit override. Do not create a pod for a missing image tag.

### 2026-10-22 — timeout fallback group-kill

- Symptom: `kill -- -$pid` in the `cc_run_timeout` fallback could fail on macOS, or it could kill `run_job` or the watchdog.
- Where it failed: review
- Cause: Non-interactive bash does not put `cmd &` in a new process group. macOS has no `setsid`.
- Fix: Start the child with `perl setpgrp` or `set -m`. Read both pgids. Group-kill only when they differ. Kill only the child pid when they match.
- Prevention: Test that a grandchild `sleep` dies and the parent still logs after the timeout.

### 2026-10-22 — macOS nvidia-smi and watchdog test hangs

- Symptom: `test_run_job_nvidia_smi_timeout_logs_unknown` and `test_watchdog_without_job_id_persists_started_at` hit `_run` timeouts on macos-15.
- Where it failed: CI macos-15
- Cause: The runner has no `timeout` or `gtimeout`. The old fallback killed only the nvidia-smi pid, so `sleep 30` kept the `$(… | head)` pipe open. The watchdog then retried terminate with 2/4/6/8s sleeps and held stdout.
- Fix: Group-kill the timeout child after a pgid check. Force `CC_TIMEOUT_FALLBACK=1` in the nvidia-smi test. Set `CC_TERMINATE_NO_SLEEP=1` and a 200 curl stub in the watchdog persist test.
- Prevention: Keep the fallback group-kill. Do not let a disowned watchdog retry-sleep on a captured stdout pipe.

### 2026-10-21 — Shared SSH host keys in the GPU image

- Symptom: Every pod would have used the same SSH host private keys.
- Where it failed: image review
- Cause: The Dockerfile ran `ssh-keygen -A` at build time.
- Fix: Remove that step. Generate host keys in `entrypoint.sh` before sshd starts.
- Prevention: Do not bake host keys into the image.
