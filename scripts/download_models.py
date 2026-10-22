#!/usr/bin/env python3
"""Fetch base ONNX weights. Refuse pickle and joblib files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REFUSED_SUFFIXES = (".pkl", ".pickle", ".joblib")
ALLOWED_SUFFIXES = (".onnx", ".json", ".zip")

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path(__file__).resolve().parent / "models.lock.json"


class DownloadError(Exception):
    """Raised when a download or import fails a safety check."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock() -> list[dict[str, object]]:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise DownloadError("models.lock.json must contain a models list.")
    return models


def dest_root() -> Path:
    raw = os.environ.get("CC_MODELS_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Library" / "Application Support" / "ClimbingCoach" / "models"


def expected_sha256(entry: dict[str, object], *, allow_unpinned: bool) -> str | None:
    name = str(entry["name"])
    raw = entry.get("sha256")
    if raw is None or raw == "":
        if not allow_unpinned:
            raise DownloadError(
                f"{name}: sha256 is null. Pass --allow-unpinned to fetch an unpinned model."
            )
        return None
    return str(raw)


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def download_temp_path(
    dest: Path, *, pid: int | None = None, job: str | None = None, token: str | None = None
) -> Path:
    """Unique sibling temp name so two pods on one volume do not collide."""
    process = os.getpid() if pid is None else pid
    job_id = job if job is not None else os.environ.get("CC_JOB_ID") or os.environ.get("CC_JOB") or "local"
    stamp = token if token is not None else uuid.uuid4().hex[:8]
    return dest.with_name(f"{dest.name}.{process}.{job_id}.{stamp}.tmp")


def download_one(
    entry: dict[str, object],
    models_dir: Path,
    *,
    allow_unpinned: bool = False,
) -> Path:
    name = str(entry["name"])
    url = str(entry["url"])
    dest = models_dir / str(entry["dest"])
    expected = expected_sha256(entry, allow_unpinned=allow_unpinned)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expected:
        actual = sha256_file(dest)
        if actual != expected:
            dest.unlink()
            raise DownloadError(f"{name} sha256 is {actual}, expected {expected}.")
        print(f"{name}: already present")
        return dest
    if dest.exists() and expected is None:
        print(f"{name}: already present (unpinned)")
        return dest
    tmp = download_temp_path(dest)
    print(f"{name}: download {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        _delete_if_exists(tmp)
        raise DownloadError(f"{name}: download failed: {exc}") from exc
    actual = sha256_file(tmp)
    if expected and actual != expected:
        _delete_if_exists(tmp)
        _delete_if_exists(dest)
        raise DownloadError(f"{name} sha256 is {actual}, expected {expected}.")
    os.replace(tmp, dest)
    if expected is None:
        print(f"{name}: sha256 {actual} (add this digest to models.lock.json)")
    else:
        print(f"{name}: ok")
    return dest


def refuse_if_unsafe(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in REFUSED_SUFFIXES:
        raise DownloadError(f"Refuse {path.name}: pickle and joblib files are not allowed.")
    if suffix not in ALLOWED_SUFFIXES and path.name != "metrics.json":
        raise DownloadError(f"Refuse {path.name}: only ONNX, JSON, and zip files are allowed.")


def import_from_volume(run_id: str, models_dir: Path) -> Path:
    volume = Path(os.environ.get("CC_VOLUME_DIR", "/workspace"))
    src = volume / "runs" / run_id
    if not src.is_dir():
        raise DownloadError(f"Run folder is missing: {src}")
    metrics_path = src / "metrics.json"
    if not metrics_path.is_file():
        raise DownloadError("metrics.json is missing from the run folder.")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    files = metrics.get("files")
    if not isinstance(files, dict) or not files:
        raise DownloadError("metrics.json must list file sha256 digests under files.")
    dest_dir = models_dir / "from-volume" / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in files.items():
        source = src / str(name)
        if not source.is_file():
            artifact = src / "artifacts" / str(name)
            source = artifact if artifact.is_file() else source
        if not source.is_file():
            raise DownloadError(f"Missing file {name} in run {run_id}.")
        refuse_if_unsafe(source)
        actual = sha256_file(source)
        if actual != str(expected):
            raise DownloadError(f"{name} sha256 is {actual}, expected {expected}.")
        target = dest_dir / Path(str(name)).name
        shutil.copy2(source, target)
    shutil.copy2(metrics_path, dest_dir / "metrics.json")
    print(f"Imported run {run_id} into {dest_dir}")
    return dest_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download or import ONNX models.")
    parser.add_argument(
        "--from-volume",
        metavar="RUN_ID",
        help="Import a pod-trained model from the network volume.",
    )
    parser.add_argument(
        "--allow-unpinned",
        action="store_true",
        help="Allow a lock entry with a null sha256.",
    )
    args = parser.parse_args(argv)
    models_dir = dest_root()
    models_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.from_volume:
            import_from_volume(args.from_volume, models_dir)
        else:
            for entry in load_lock():
                download_one(entry, models_dir, allow_unpinned=args.allow_unpinned)
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
