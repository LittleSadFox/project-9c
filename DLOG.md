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
The default GPU list keeps RTX PRO 4500/4000 Blackwell and RTX 5090 at the end.

The create payload sends `allowedCudaVersions` `12.8`, `12.9`, `13.0`. The live API rejects `13.1` and `13.2`. The image CUDA driver guard (>=12.8, fail closed) is the real floor. If the filter excludes 13.x hosts in practice, drop the field.
An early entrypoint failure writes `status=failed`, pings, and terminates the pod.
`run_job.sh` skips a finished job on restart and only retries terminate.
`--ref` must be a 40-character sha, or the bot box resolves it to one.
