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

### 2026-10-21 — Shared SSH host keys in the GPU image

- Symptom: Every pod would have used the same SSH host private keys.
- Where it failed: image review
- Cause: The Dockerfile ran `ssh-keygen -A` at build time.
- Fix: Remove that step. Generate host keys in `entrypoint.sh` before sshd starts.
- Prevention: Do not bake host keys into the image.
