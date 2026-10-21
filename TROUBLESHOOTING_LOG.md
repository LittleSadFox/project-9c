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

### 2026-10-21 — Shared SSH host keys in the GPU image

- Symptom: Every pod would have used the same SSH host private keys.
- Where it failed: image review
- Cause: The Dockerfile ran `ssh-keygen -A` at build time.
- Fix: Remove that step. Generate host keys in `entrypoint.sh` before sshd starts.
- Prevention: Do not bake host keys into the image.
