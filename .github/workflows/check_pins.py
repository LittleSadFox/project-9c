"""Check that installed pins match AGENTS.md / coding_plan.md."""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

EXPECTED_PY = {
    "numpy": "2.5.4",
    "onnxruntime": "1.23.2",
    "fastapi": "0.156.6",
    "starlette": "1.8.0",
    "uvicorn": "0.54.0",
    "pydantic": "2.14.1",
    "opencv-python-headless": "4.14.0.94",
    "tqdm": "4.70.1",
    "rtmlib": "0.0.16",
    "pytest": "9.1.1",
    "pytest-cov": "7.1.0",
    "httpx": "0.28.1",
    "ruff": "0.17.1",
    "mypy": "2.4.0",
}

EXPECTED_JS = {
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "react-router": "8.5.0",
    "vite": "8.3.5",
    "@vitejs/plugin-react": "6.1.2",
    "vitest": "5.0.5",
    "@testing-library/react": "16.3.3",
    "jsdom": "30.1.3",
    "@playwright/test": "1.64.1",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def requirement_pins(path: Path) -> list[str]:
    pins: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pins.append(line)
    return pins


def check_python_version() -> None:
    if sys.version_info[:2] != (3, 12):
        fail(f"Python is {sys.version}; expected 3.12")
    pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    if pin != "3.12":
        fail(f".python-version is {pin!r}; expected '3.12'")


def check_installed_python() -> None:
    for name, version in EXPECTED_PY.items():
        have = metadata.version(name)
        if have != version:
            fail(f"{name} is {have}; expected {version}")


def check_gpu_requirements_lockstep() -> None:
    cpu = requirement_pins(BACKEND / "requirements.txt")
    gpu = requirement_pins(BACKEND / "requirements-gpu.txt")
    cpu_swapped = [
        line.replace("onnxruntime==", "onnxruntime-gpu==", 1) for line in cpu
    ]
    if cpu_swapped != gpu:
        fail("requirements-gpu.txt must match requirements.txt except onnxruntime-gpu")
    if "onnxruntime==1.23.2" not in cpu:
        fail("requirements.txt must pin onnxruntime==1.23.2")
    if "onnxruntime-gpu==1.23.2" not in gpu:
        fail("requirements-gpu.txt must pin onnxruntime-gpu==1.23.2")
    if any(line.startswith("rtmlib==") for line in cpu):
        fail("rtmlib must live in requirements-nodeps.txt, not requirements.txt")
    nodeps = requirement_pins(BACKEND / "requirements-nodeps.txt")
    if nodeps != ["rtmlib==0.0.16"]:
        fail("requirements-nodeps.txt must pin only rtmlib==0.0.16")
    if (BACKEND / "requirements-ml.txt").exists():
        fail("requirements-ml.txt is Phase 4 only")


def check_frontend_pins() -> None:
    nvmrc = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
    if nvmrc != "24":
        fail(f".nvmrc is {nvmrc!r}; expected '24'")
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    declared = {}
    declared.update(package.get("dependencies", {}))
    declared.update(package.get("devDependencies", {}))
    for name, version in EXPECTED_JS.items():
        have = declared.get(name)
        if have != version:
            fail(f"package.json {name} is {have!r}; expected {version!r}")


def main() -> None:
    check_python_version()
    check_installed_python()
    check_gpu_requirements_lockstep()
    check_frontend_pins()
    print("Pins match AGENTS.md.")


if __name__ == "__main__":
    main()
