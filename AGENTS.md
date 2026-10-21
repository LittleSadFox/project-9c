# AGENTS.md

This file is the only rule set for bots in this repo.
The bot sees no other rules.
Follow this file.
Write in ASD-STE100 Simplified Technical English: short sentences, active voice, one instruction per sentence.

## 1. Plan authority

`coding_plan.md` is the build plan.
`coding_plan.md` wins over `architect_plan.md` where they conflict.
Do not follow `architect_plan.md` when the two plans disagree.

Do not use these `architect_plan.md` items:

- The Phase 0 GPU image has no PyTorch and no MMPose. The train image is Phase 6.
- Pose storage is NPZ. Do not use Parquet.
- Do not use rtmlib `PoseTracker`. Call rtmlib `YOLOX` and `RTMPose` directly. Track people in our code.
- Pins are Python 3.12, Node 24 LTS, and `onnxruntime` / `onnxruntime-gpu` 1.23.2. Do not use Python 3.11, Node 20, or a later ONNX Runtime.
- The account Runpod API key never goes in the pod template or in pod env. A pod uses only the pod-scoped key that Runpod injects.

## 2. Repo identity

The GitHub repo is `LittleSadFox/project-9c`.
Do not treat `climbing_coach` as the GitHub name.
A Mac clone at `~/dev/climbing_coach/` is an optional local path only.

## 3. Version pins

Pin these versions exactly.
Until pin files exist, this file is the pin source.
After the later Phase 0 skeleton work, keep the same numbers in the files below.

Runtime and backend:

- Python 3.12. Pin file: `.python-version`.
- `numpy==2.5.4`. Pin file: `backend/requirements.txt`.
- `onnxruntime==1.23.2`. Pin file: `backend/requirements.txt`. This is the last release with `macosx_13_0_arm64` wheels.
- `onnxruntime-gpu==1.23.2` on pods only (CUDA 12, cuDNN 9). Pin file: `backend/requirements-gpu.txt`. That file must match `requirements.txt` except for the ONNX Runtime package name.
- `fastapi==0.156.6`.
- `starlette==1.8.0` (`FileResponse` must serve byte ranges).
- `uvicorn[standard]==0.54.0`.
- pydantic 2.
- `rtmlib==0.0.16`. Install with `pip install --no-deps`. Pin file: `backend/requirements-nodeps.txt`.
- `opencv-python-headless==4.14.0.94`. Stay on OpenCV 4.x. rtmlib reads `cv2.dnn` constants at import time.
- `tqdm` (needed with rtmlib).
- ffmpeg and ffprobe 7.0+.
- SQLite through the stdlib `sqlite3` module in WAL mode.

Frontend:

- Node 24 LTS. Pin file: `.nvmrc`.
- `vite@8.3.5` and `@vitejs/plugin-react`.
- `react@19.3.1`.
- `react-router@8.5.0` (route, link, and params APIs only).
- `vitest@5.0.5`, `@testing-library/react`, jsdom.
- `@playwright/test@1.64.1`.
- Vite `build.target`: `["safari16", "chrome107"]`.
- Pin file for frontend versions: `frontend/package.json`.

Dev tools:

- pytest, pytest-cov, httpx, ruff, mypy. Pin file: `backend/requirements-dev.txt`.

Phase 4 only (do not add before Phase 4):

- `scikit-learn==1.9.1`, `scipy==1.18.1`, `skl2onnx==1.20.0`. Pin file: `backend/requirements-ml.txt`.

GPU images:

- Phase 0 image `climbing-coach-gpu`: `nvidia/cuda` 12.x + cuDNN 9 on Ubuntu 24.04, Python 3.12, `onnxruntime-gpu==1.23.2`, static ffmpeg 7, sshd, git, curl, jq. No PyTorch. No MMPose.
- Phase 6 image `climbing-coach-train`: PyTorch, MMCV 2.2, MMPose 1.3, NumPy 1.26. Do not put those in the Phase 0 image.
- CI runners: `ubuntu-24.04` and `macos-15`.

## 4. Stack rules

Choose ONNX Runtime providers at run time in this order: CUDA, then CoreML, then CPU.
`CC_DEVICE` can force one provider (`auto`, `cuda`, `mps`, or `cpu`).
The Mac and CI install `onnxruntime`.
Pods install `onnxruntime-gpu` of the same version.

Do not use rtmlib `PoseTracker`.
Call rtmlib `YOLOX` and `RTMPose` directly.
Track people in our code.
Skip a frame when the detector returns no boxes. `RTMPose` otherwise falls back to the whole image.

Store pose tracks as NPZ files.
Do not store pose tracks as Parquet.

Learned models are ONNX plus JSON only.
The app never loads a pickle or joblib file.

Mac-only code (pywebview, PyInstaller, `open -R`) lives in `launcher/` or behind `sys.platform == "darwin"`.
`backend/app` never imports Mac-only code at module level.

The Mac toolchain is Python 3.12, Node 24 LTS, ffmpeg 7+, and AWS CLI v2.
Playwright WebKit needs macOS 15+. On older Macs, run end-to-end tests in Chromium and check Safari by hand.

## 5. Layering

Backend layers:

1. `routes` — HTTP only.
2. `services` — use cases. Services own transactions.
3. `core`, `pose`, `media`, `learning`, `repo`, `storage`.

Routes call services.
Services call `core`, `pose`, `media`, `learning`, `repo`, and `storage`.
Routes never run SQL.
Routes never touch files.

`core/` imports only numpy and the Python standard library.
A layering test must enforce that rule.

`media/` sits behind a `MediaTool` protocol (`probe`, `make_proxy`, `cut_clip`, `extract_frame`, `thumbnails`, `render`).
API tests use `FakeMediaTool`. They do not need ffmpeg.

`pose/` sits behind a `PoseEstimator` protocol.
`RtmlibEstimator` is the real backend (YOLOX + RTMPose).
`FixtureEstimator` is the test backend (`CC_POSE_BACKEND=fixture`).

`create_app(settings, media=..., estimator=...)` takes both dependencies so tests can inject the fakes.

## 6. Test markers and fakes

Pytest markers: unmarked, `media`, `model`, `gpu`, `macos`, `golden`, `slow`.
Pin the marker list in `backend/pytest.ini` when that file exists.

Skip a marked test with a printed reason when its need is missing.
Do not fail a skip unless `CC_REQUIRE` lists that need.

Needs:

- Unmarked (pure logic and API tests with fakes): every machine, including the bot computer.
- `media`: ffmpeg 7+.
- `model`: ONNX weights.
- `gpu`: `CUDAExecutionProvider`. Pods only.
- `macos`: CoreML or VideoToolbox on real Mac hardware. The Mac only.
- `golden`: labelled footage. Pods and the Mac. Never the bot computer.
- `slow`: omit from the default run. Include on pods and in `check.sh --all`.

Keep the API testable without ffmpeg or models:

- `FakeMediaTool` behind `MediaTool`.
- `FixtureEstimator` behind `PoseEstimator`.

The bot computer and CI must stay green on portable tests with these fakes before any pod starts.

## 7. Never-commit list

Never commit these paths or artifacts:

- Model weights (including `.onnx` files).
- Videos and golden footage.
- Library folders.
- `.venv`.
- `node_modules`.
- `frontend/dist`.

Also keep reports and local library data out of git.
Nothing persistent lives in the repo.

## 8. Three-tier workflow

Verify work in this order. Do not skip a tier.

1. Bot computer and CI: lint, build, and portable tests with fakes. This tier must be green before anything goes to a pod.
2. Runpod GPU pods: Linux with CUDA, real ffmpeg and HEVC, `onnxruntime-gpu`, pose and metrics on labelled footage, Phase 4 training, and Phase 6 fine-tuning.
3. Mac pass: CoreML speed and parity, VideoToolbox, Safari playback and sync, Liquid Glass look, the pywebview window, and the `.app`.

Hand a phase over when CI and that phase's pod checks are green.
A phase is done when the Mac pass is green too.

The bot computer is Debian Linux x86_64 with CPU only.
It has no CoreML, no VideoToolbox, no Safari, no model weights, and no sample videos.

Pods run only pushed commits.
Push first.
Then the Runpod bot starts the pod with that sha.

CI (when it exists) runs on every push and pull request: `ubuntu-24.04` and `macos-15`.

## 9. Runpod credentials and cost

These rules are mandatory.
A missing rule is a hard fail.

### 9.1 Owner on the shared bot computer

The dedicated Grok Bot teammate named Runpod owns the project Runpod credentials.
The Runpod bot holds this project's Runpod API key, this project's S3 API key, and this project's SSH key on the shared bot computer.
The dedicated Runpod account holds only this project.
Do not put cloud root credentials on the bot computer.
Do not put GitHub admin tokens on the bot computer.
Every bot on that computer can see the keys.
Other bots must not touch those secrets except through coordination with the Runpod bot or the Orchestrator.
Rotate the keys when a bot is removed.

Ryan and the Runpod bot configure these keys.
Do not invent key values.
Do not write example credentials.

### 9.2 What a pod may hold

A pod gets only:

- the pod-scoped key that Runpod injects
- Runpod secret `cc_repo_token` (read-only GitHub access to this repo's contents)
- Runpod secret `cc_webhook_url` (the completion webhook)

The account API key never goes in the pod template.
The account API key never goes in pod env.
Do not copy the account key into a pod.

The Runpod bot owns `cc_webhook_url`.
`cc_webhook_url` is a routine completion webhook.
Anyone who has the URL can wake the Runpod bot.
Ryan and the Runpod bot configure the webhook URL.
Do not invent a webhook URL.
Do not write the URL in this file.

### 9.3 Start and stop rules

Only the Runpod bot starts pods.
Other bots must not start pods except through coordination with the Runpod bot or the Orchestrator.

Never start a pod without `CC_TTL_S`.
Never start a pod without `CC_JOB` or `--interactive`.
Run `pod_down` after every interactive session.
Run `pod_ls` at the start of each work session.
Run `pod_ls` at the end of each work session.

The spending limit is the backstop.
The volume bills continuously, but it is small.

### 9.4 GHCR before the first pod

The GPU image `climbing-coach-gpu` is private.
Before the first `pod_up`, the Runpod account must have a registry credential with GitHub `read:packages`.
The Runpod bot must not start a pod if that credential is missing.

## 10. Footage and models

These rules are mandatory.
A missing rule is a hard fail.

The bot never handles footage.
The bot reads run folders and metrics only.

Run folders hold logs, metrics, and model files only.
Run folders never hold frames or clips.

Models from the volume are ONNX plus JSON only.
Refuse pickle.
Refuse joblib.
Check each file's sha256 against `metrics.json`.

Golden videos stay off-repo.
The user uploads them with `sync_volume.sh`.
Originals stay on the Mac.
The volume is a working copy.

## 11. Phase 0 sample footage

Phase 0 needs only a small sample upload.
One or two videos are enough.
Upload them with `sync_volume.sh`.

The golden set of at least 10 videos and at least 30 attempts is a post–Phase 1 todo.
That set is not a Phase 0 blocker.

## 12. Docs conventions

Write docs in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

Record every meaningful change in `DLOG.md`.
Record problems and fixes in `TROUBLESHOOTING_LOG.md`.
Log errors each day in `errors/ERROR_YYYY-MM-DD.md`.

Do not add those files in the first Phase 0 `AGENTS.md` pull request.
Add them in the later Phase 0 docs task.

## 13. Phase 0 gate

This file is the gate before application code.
Do not add application code, CI workflows, Docker files, or other Phase 0 skeleton files until Ryan approves this file.

See `coding_plan.md` Phase 0 — Foundations.
