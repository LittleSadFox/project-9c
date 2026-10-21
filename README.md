# Climbing Coach

Climbing Coach is a local app for bouldering video.
The app imports your videos.
It estimates a 26-keypoint skeleton.
It helps you cut attempts, compare them, and rate them.
It logs your corrections so the detectors can learn.

The GitHub repo is `LittleSadFox/project-9c`.
A Mac clone at `~/dev/climbing_coach/` is an optional local path only.

Write in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

`coding_plan.md` is the build plan.
`coding_plan.md` wins over `architect_plan.md` where they conflict.
Follow `AGENTS.md` for every bot rule.

## 1. Pins

Pin these versions exactly.

| Item | Version |
| --- | --- |
| Python | 3.12 (`.python-version`) |
| Node | 24 LTS (`.nvmrc`) |
| `numpy` | 2.5.4 |
| `onnxruntime` / `onnxruntime-gpu` | 1.23.2 |
| `fastapi` | 0.156.6 |
| `starlette` | 1.8.0 |
| `uvicorn[standard]` | 0.54.0 |
| `pydantic` | 2.14.1 |
| `rtmlib` | 0.0.16 (`pip install --no-deps`) |
| `opencv-python-headless` | 4.14.0.94 |
| `vite` | 8.3.5 |
| `react` | 19.3.1 |
| `react-router` | 8.5.0 |
| `vitest` | 5.0.5 |
| `@playwright/test` | 1.64.1 |
| ffmpeg / ffprobe | 7.0+ |

Phase 4 adds `scikit-learn==1.9.1`, `scipy==1.18.1`, and `skl2onnx==1.20.0`.
Do not add those pins before Phase 4.

## 2. Three-tier workflow

Verify work in this order.
Do not skip a tier.

1. Bot computer and CI: lint, build, and portable tests with fakes.
2. Runpod GPU pods: CUDA, real ffmpeg, and labelled footage.
3. Mac pass: CoreML, VideoToolbox, Safari, and the visual checklist.

Hand a phase over when CI and that phase's pod checks are green.
A phase is done when the Mac pass is green too.

## 3. Mac setup

Do this on an Apple Silicon Mac with macOS 13 or later.

### 3.1 Install the toolchain

1. Install Python 3.12 from python.org.
   Homebrew Python is also fine on macOS 15 or later.
2. Install Node 24 LTS from nodejs.org.
   Node 24 needs macOS 13.5 or later.
3. Install ffmpeg 7 or later.
   On macOS 15 or later, run `brew install ffmpeg`.
   On macOS 13 or 14, Homebrew has no bottles.
   On those versions, use a static arm64 ffmpeg 7 build.
   Set `CC_FFMPEG_BIN` and `CC_FFPROBE_BIN` to that build.
4. Install AWS CLI v2 from the official installer.
   The volume scripts need it.

### 3.2 Clone and install

```text
git clone git@github.com:LittleSadFox/project-9c.git ~/dev/climbing_coach
cd ~/dev/climbing_coach
scripts/setup_mac.sh
```

`scripts/setup_mac.sh` checks the toolchain, creates `.venv`, installs the pins, downloads weights, and creates the library folders.

### 3.3 Library folders

The default root is `~/Library/Application Support/ClimbingCoach/`.

| Folder | Use |
| --- | --- |
| `library/` | Your library |
| `library-dev/` | Dev library for `scripts/dev.sh` |
| `models/` | Base ONNX weights |
| `golden/` | Your labelled test footage |
| `reports/` | Golden metrics |

Override paths with `CC_LIBRARY_DIR`, `CC_MODELS_DIR`, and `CC_GOLDEN_DIR`.
Do not put these folders in git.

### 3.4 First Mac pass

After `git pull`:

1. Run `scripts/setup_mac.sh` once on a new clone.
2. Run `scripts/check.sh --all`.
3. Run the phase checklist in this file.
4. Report results as GitHub issues.
   Attach the logs.

Playwright WebKit needs macOS 15 or later.
On older Macs, run end-to-end tests in Chromium.
Then check Safari by hand.

## 4. Runpod setup

Do this before Phase 0 ends.
Ryan and the Runpod bot configure the keys.
Do not invent key values.
Do not write example credentials.

1. Create a Runpod account that you use only for this project.
2. Set a spending limit.
3. Set low-balance alerts.
4. Create an API key for the Runpod bot computer.
5. Create an S3 API key.
   The access key is your `user_...` id.
   The secret is shown only once.
6. Add the bot computer's SSH public key to the account.
7. Add a container registry credential in Runpod.
   Use a GitHub token with only `read:packages`.
   Pods need this token to pull the private GHCR image.
8. Create two Runpod secrets.
   The pod template will reference them as `{{ RUNPOD_SECRET_<name> }}`.
   - `cc_repo_token`: a fine-grained GitHub token with read-only access to this repo's contents.
   - `cc_webhook_url`: the Runpod bot's routine webhook.
     Anyone who has the URL can wake the Runpod bot.
9. Create one network volume.
   Start at 100 GB.
   A volume can grow.
   A volume cannot shrink.
   Network volumes exist only in Secure Cloud.
   Create the volume in a datacenter that supports the S3 API.
   Examples: `EU-RO-1`, `EUR-IS-1`, `US-KS-2`, `US-CA-2`.
   See the Runpod S3 API docs for the full list.
   Pick a datacenter with good RTX 4090, A40, and A100 availability.

The account API key never goes in a pod.
A pod uses only the pod-scoped key that Runpod injects, plus the two secrets.

The runner files are in the tree: `docker/gpu/`, `scripts/gpu/`, `ml/jobs.py`, and `.github/workflows/gpu-image.yml`.

Do not start a live pod from a coding agent.
Only the Runpod bot starts pods.
The first live `scripts/gpu/pod_up.sh --job gpu_tests` waits on Ryan and the Runpod bot.
They must finish the section 2.2 setup and add the GHCR `read:packages` credential.

Phase 0 needs only a small sample upload.
One or two videos are enough.
Upload them with `scripts/sync_volume.sh` after the volume exists.
The golden set of at least 10 videos is a post–Phase 1 todo.

## 5. Commands

This table is the command map.

| Command | What it does |
| --- | --- |
| `scripts/setup_mac.sh` | Checks the toolchain. Creates `.venv`. Installs pins. Downloads weights. Creates library folders. |
| `scripts/check.sh` | Runs ruff, mypy, pytest, vitest, the frontend build, and Playwright. |
| `scripts/check.sh --all` | Adds slow tests. Sets `CC_REQUIRE` so a missing need fails. |
| `scripts/dev.sh` | Starts the backend on `127.0.0.1:8810` and Vite on `8811` with `library-dev`. |
| `scripts/build.sh` | Runs `npm ci` and `vite build` into `frontend/dist`. |
| `scripts/run_mac.sh` | Starts uvicorn with your library and opens the launch URL. |
| `scripts/download_models.py` | Fetches base ONNX weights. `--from-volume` imports a pod-trained model. |
| `scripts/export_labels.py` | Writes golden labels from the dev library. |
| `scripts/sync_volume.sh` | Copies new golden videos and labels to the Runpod volume. |
| `scripts/export_dataset.sh` | Uploads a Phase 4 or Phase 6 dataset. |
| `scripts/gpu/pod_up.sh` | Creates a GPU pod for a job or an interactive session. Use `--dry-run` to print the payload. |
| `scripts/gpu/run_job.sh` | Runs inside the pod. Clone, install, run `ml/jobs.py`, write the run folder, ping, terminate. |
| `scripts/gpu/wait_job.sh` | Polls `runs/<id>/status` through the S3 API. |
| `scripts/gpu/pod_down.sh` | Terminates a pod. |
| `scripts/gpu/pod_ls.sh` | Lists running pods and their age. |

Only the Runpod bot starts pods.
Never start a pod without `CC_TTL_S`.
Never start a pod without `CC_JOB` or `--interactive`.
The account API key never goes in the pod template or in pod env.
A job pod terminates itself with the pod-scoped key that Runpod injects.

## 6. Environment variables

The app reads these `CC_*` variables.
The frozen `Settings` object holds them.

| Name | Default | Meaning |
| --- | --- | --- |
| `CC_LIBRARY_DIR` | `~/Library/Application Support/ClimbingCoach/library/` | Library folder |
| `CC_MODELS_DIR` | `~/Library/Application Support/ClimbingCoach/models/` | Base ONNX weights |
| `CC_GOLDEN_DIR` | `~/Library/Application Support/ClimbingCoach/golden/` | Labelled footage |
| `CC_FFMPEG_BIN` | `ffmpeg` on `PATH` | ffmpeg binary |
| `CC_FFPROBE_BIN` | `ffprobe` on `PATH` | ffprobe binary |
| `CC_HOST` | `127.0.0.1` | Bind address |
| `CC_PORT` | `8810` | Bind port |
| `CC_LAUNCH_TOKEN` | set by the launcher | Per-launch session token |
| `CC_DEV` | unset | Enables `/docs` and the DEV badge |
| `CC_MAX_UPLOAD_GB` | `8` | Upload size limit |
| `CC_DEVICE` | `auto` | `auto`, `cuda`, `mps`, or `cpu` |
| `CC_POSE_BACKEND` | `rtmlib` | `rtmlib` or `fixture` |
| `CC_REQUIRE` | unset | Needs that must not skip |

On pods, set `CC_MODELS_DIR=/workspace/models` and `CC_GOLDEN_DIR=/workspace/videos`.
Point `CC_LIBRARY_DIR` at a scratch folder on the container disk.

Pod scripts also read these names.
Ryan and the Runpod bot set the values.
Do not invent the values.

| Name | Meaning |
| --- | --- |
| `CC_TTL_S` | Required lifetime backstop in seconds |
| `CC_JOB` | Job name. Empty for `--interactive` |
| `CC_GIT_REF` | Pushed commit sha |
| `CC_JOB_ID` | Run folder name under `/workspace/runs/` |
| `CC_REPO_TOKEN` | Runpod secret `cc_repo_token`. Do not set this by hand |
| `CC_WEBHOOK_URL` | Runpod secret `cc_webhook_url`. Do not set this by hand |
| `RUNPOD_API_KEY` | Account key on the bot computer only. Never copy it into a pod |
| `CC_RUNPOD_TEMPLATE_ID` | Pod template id |
| `CC_RUNPOD_VOLUME_ID` / `CC_VOLUME_ID` | Network volume id |
| `CC_RUNPOD_DATACENTER` / `CC_VOLUME_DC` | Volume datacenter |
| `CC_GPU_IMAGE` | GHCR image name when the template does not set it |

Do not put secrets in this file.
Do not commit `.env` files that hold tokens.

## 7. Never-commit list

Never commit these items:

- Model weights, including `.onnx` files
- Videos and golden footage
- Library folders
- `.venv`
- `node_modules`
- `frontend/dist`
- Reports and local library data

## 8. Docs

| File | Use |
| --- | --- |
| `AGENTS.md` | Bot rules |
| `ARCHITECTURE.md` | System design and diagrams |
| `DATA_MODEL.md` | SQLite tables and columns |
| `DLOG.md` | Meaningful changes |
| `TROUBLESHOOTING_LOG.md` | Problems and fixes |
| `errors/ERROR_YYYY-MM-DD.md` | Daily error log |

Record every meaningful change in `DLOG.md`.
Record problems and fixes in `TROUBLESHOOTING_LOG.md`.
Log errors each day in `errors/ERROR_YYYY-MM-DD.md`.

## 9. Phase checklists

Use these lists after `git pull`.
Report a fail as a GitHub issue.
Attach the logs.

### Phase 0 — Foundations

Bot and CI

- [ ] `AGENTS.md` is approved.
- [ ] Pin files match `AGENTS.md`.
- [ ] Both CI jobs are green: `ubuntu-24.04` and `macos-15`.
- [ ] Portable pytest cases pass with fakes.
- [ ] `npm run build` and Vitest pass.
- [ ] A Playwright Chromium smoke test opens the shell.

Pod (after Runpod credentials exist)

The first live `pod_up.sh --job gpu_tests` waits on Ryan and the Runpod bot.
They must finish the section 2.2 setup.
This repo change does not start a pod.

- [ ] `pod_up.sh --job gpu_tests` clones the commit and runs the suite with real ffmpeg.
- [ ] A tiny ONNX model runs on `CUDAExecutionProvider`.
- [ ] `runs/<id>/metrics.json` appears.
- [ ] The webhook ping wakes the Runpod bot.
- [ ] `pod_ls.sh` shows no pod afterwards.
- [ ] An interactive pod with `--ttl 10m` terminates itself.

Mac pass

- [ ] `scripts/setup_mac.sh` finishes on a clean clone and downloads the weights.
- [ ] `scripts/check.sh --all` is green.
- [ ] `scripts/run_mac.sh` opens the shell in Safari.
- [ ] The theme passes the visual checklist in dark and light mode.
- [ ] Reduced transparency, increased contrast, and reduced motion look correct.
- [ ] `scripts/sync_volume.sh` uploads one or two sample videos.

### Phase 1 — Library, import, pose, playback, manual cut

Bot and CI

- [ ] Proxy tests pass: constant frame rate and `n_frames = round(duration × fps) ± 1`.
- [ ] A source with `display_rotation=90` comes out upright.
- [ ] VFR and HEVC sources import.
- [ ] A cut's first and last frame codes match the request ± 1.
- [ ] `Range: bytes=0-99` returns 206 with 100 bytes.
- [ ] The same file twice returns 409.
- [ ] A text file returns 415 and leaves `tmp/` empty.

Pod

- [ ] Sample iPhone HEVC videos import.
- [ ] Pose runs on every video.
- [ ] `pose_bench` records CUDA frames per second in `DLOG.md`.
- [ ] CUDA and CPU keypoints differ by ≤ 1 px on average over 100 frames.

Mac pass

- [ ] Real iPhone HEVC videos import.
- [ ] On 2–3 videos, the climber track covers ≥ 95 % of on-wall frames.
- [ ] `pytest -m "model and macos"`: CoreML and CPU keypoints differ by ≤ 1 px on average over 100 frames.
- [ ] Overlay sync and manual cuts look right in Safari.
- [ ] A 1 GB upload raises server memory by less than 100 MB.

### Phase 2 — Review tools

Bot and CI

- [ ] Start and end land within ±2 frames on clean synthetic data.
- [ ] Start and end land within ±5 frames with noise.
- [ ] A standing-only sequence gives 0 proposals.
- [ ] Each review action writes exactly one feedback row.
- [ ] You can review a whole video with the keyboard only.

Pod

- [ ] `eval` on the golden set meets the rule-v1 targets in `coding_plan.md`.

Mac pass

- [ ] Review real footage in Safari with the keyboard.
- [ ] Corrections appear in `feedback_events`.
- [ ] `pytest -m golden` agrees with the pod `eval` within 2 percentage points.

### Phase 3 — Compare

Bot and CI

- [ ] Identical inputs give the diagonal DTW path and zero cost.
- [ ] Anchors are met exactly.
- [ ] The path is always monotone.
- [ ] A scripted 30° left-knee difference ranks first.

Pod

- [ ] The compare pipeline and a rendered MP4 run on two real attempts of one boulder.

Mac pass

- [ ] DTW for 2 × 60 s at 30 fps takes ≤ 300 ms.
- [ ] Follower drift stays ≤ 3 frames during Safari playback.
- [ ] The rendered MP4 plays in Safari.
- [ ] Ranked differences and the pacing list make sense to you.

### Phase 4 — Learning and progress

Bot and CI

- [ ] Training is deterministic with fixed seeds.
- [ ] The ONNX model matches scikit-learn probabilities within 1e-5.
- [ ] `download_models.py` refuses a `.pkl` file and a sha256 mismatch.
- [ ] A candidate never activates by itself.

Pod

- [ ] `train_events`, `tune_align`, and `eval` write `metrics.json`.

Mac pass

- [ ] After readiness thresholds, export a dataset and import the candidate.
- [ ] The candidate appears inactive on the Models page.
- [ ] Progress charts look sensible for one boulder.

### Phase 5 — Mac app

Bot and CI

- [ ] Launcher logic that needs no macOS is unit-tested.
- [ ] The `macos-15` job runs `package_mac.sh` and uploads the `.app`.

Mac pass

- [ ] On a clean macOS 13 machine, the `.app` starts with a double-click.
- [ ] The app needs no system Python, Node, or ffmpeg.
- [ ] Smoke test on macOS 15 and 26.
- [ ] The accessibility checklist in `frontend/DESIGN_GUIDELINES.md` passes.

### Phase 6 — Pose fine-tune

Bot and CI

- [ ] The COCO export validates against its schema.
- [ ] The trainer image builds.

Pod

- [ ] A 50-iteration smoke run passes.
- [ ] The full run completes.
- [ ] Candidate PCK@0.05 beats the base model on held-out corrected frames.

Mac pass

- [ ] CoreML parity passes for the new ONNX.
- [ ] The Models page A/B agrees with the pod numbers.

## 10. CI

GitHub Actions runs on every push and pull request.

- `ubuntu-24.04`: install pins, ruff, mypy, pytest (unmarked + `media` when those tests exist), Vitest, `npm run build`, and Playwright Chromium.
- `macos-15`: the same, plus Playwright WebKit when end-to-end tests exist.

The macOS job proves that every pinned wheel installs on Apple Silicon.

`gpu-image.yml` builds `climbing-coach-gpu` and pushes it to private GHCR.
It runs when `docker/gpu/` or `requirements*.txt` change.
Tags are the git sha and, on `main`, `latest`.
The image is private.
Add a Runpod registry credential with GitHub `read:packages` before the first pod.

## 11. Licence

See `LICENSE`.
Check the licences of the RTMPose and YOLOX weights before any public distribution.
