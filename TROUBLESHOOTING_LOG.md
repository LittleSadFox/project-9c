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
- Fix: Tests now default `CC_SRC_DIR` and `CC_LIBRARY_DIR` under pytest `tmp_path`. The default clone dir is `/tmp/cc-src`. `run_job.sh` only removes a resolved path whose basename matches `cc-src`, whose parent is exactly `/tmp` or a trusted `$TMPDIR`, and that is not a symlink or a live checkout, volume, scratch, HOME, or working-directory path. `$TMPDIR` is untrusted when it resolves inside the volume, scratch, repo, HOME, or `/tmp/cc-src`. CI copies the repo to `/tmp/cc-src` and runs the `gpu_tests` pytest selection from there.
- Prevention: Keep destructive paths on `tmp_path`. Do not run `run_job.sh` against the live checkout. The remaining check-to-rm race needs `/tmp` write access on the pod; do not give extra writers access to `/tmp` on a job pod.

### 2026-10-21 — live gpu_tests nested pytest through /opt/cc python

- Symptom: The third live `gpu_tests` pod at `1af17806` used an L4, CUDA 13.2, and `CUDAExecutionProvider`. Pytest never finished. `test_run_job_rerun_after_clone_reaches_ml_jobs` hung.
- Where it failed: pod
- Cause: `run_job.sh` used `/opt/cc/venv/bin/python` from the image. Tests only stubbed `python3` on `PATH`. The real `ml.jobs gpu_tests` ran pytest on `/tmp/cc-src` again. `_run()` had no timeout.
- Fix: Tests set `CC_PYTHON` to the stub. `_run()` starts a new session and kills the process group after 30s. `gpu_tests` sets `CC_IN_GPU_TESTS=1` on the pytest child. Tests keep that flag unless a case clears it. `run_job.sh` and `ml.jobs` refuse a nested `gpu_tests`. The refuse line goes to the job `log.txt`. CI creates a fake `/opt/cc/venv/bin/python`. A second terminate after success is skipped only for this pod. The stamp lives at `/tmp/.cc_terminated.$RUNPOD_POD_ID`.
- Prevention: Do not let `run_job.sh` tests use `/opt/cc/venv/bin/python`. Keep `_run()` bounded. Do not store the terminate stamp on the volume.

### 2026-10-21 — wait_job S3 cp-to-stdout failed

- Symptom: `wait_job` did not read `runs/<id>/status`. It only stopped when the pod returned 404.
- Where it failed: bot computer / volume S3
- Cause: `aws s3 cp s3://... -` returned `SignatureDoesNotMatch` on all four retries against `https://s3api-eu-ro-1.runpod.io/`. `aws s3api get-object` with the same profile worked.
- Fix: Read objects with `aws s3api get-object`. Keep the 403 and `SignatureDoesNotMatch` retry. Print one summary line per poll.
- Prevention: Do not use `aws s3 cp ... -` against the Runpod S3 endpoint.

### 2026-10-21 — Shared SSH host keys in the GPU image

- Symptom: Every pod would have used the same SSH host private keys.
- Where it failed: image review
- Cause: The Dockerfile ran `ssh-keygen -A` at build time.
- Fix: Remove that step. Generate host keys in `entrypoint.sh` before sshd starts.
- Prevention: Do not bake host keys into the image.
