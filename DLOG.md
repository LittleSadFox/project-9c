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
