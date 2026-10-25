#!/usr/bin/env python3
"""Prepare golden videos for sync_volume.sh.

A file at or under 150 MiB is uploaded unchanged.
A larger video is transcoded to H.264 1080p at the source frame rate.
Rotation is applied. ffmpeg runs as an argument list from CC_FFMPEG_BIN.
The manifest stores original_sha256 and the uploaded sha256.
A matching original hash skips the transcode.
A transcoded file that is still over 150 MiB fails before any upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_PUT_BYTES = 150 * 1024 * 1024
LONG_SIDE_1080P = 1920
PROBE_TIMEOUT_S = 30.0
TRANSCODE_TIMEOUT_S = 3600.0
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc", ".3gp"}


class SyncVolumeError(Exception):
    """Raised when a golden file cannot be prepared for put-object."""


def ffmpeg_bin() -> str:
    raw = os.environ.get("CC_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg"
    return raw


def ffprobe_bin() -> str:
    raw = os.environ.get("CC_FFPROBE_BIN", "ffprobe").strip() or "ffprobe"
    return raw


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def listed_original_sha(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    raw = entry.get("original_sha256") or entry.get("sha256")
    if isinstance(raw, str) and raw:
        return raw
    return None


def iter_candidates(golden: Path) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    labels = golden / "labels" / "labels.json"
    if labels.is_file():
        candidates.append(("labels/labels.json", labels))
    if golden.is_dir():
        for path in sorted(golden.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            candidates.append((path.relative_to(golden).as_posix(), path))
    return candidates


def _float(value: object) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rate(value: object) -> float | None:
    if not isinstance(value, str) or not value or value == "0/0":
        return _float(value)
    if "/" not in value:
        return _float(value)
    num_s, den_s = value.split("/", 1)
    num = _float(num_s)
    den = _float(den_s)
    if num is None or den is None or den == 0:
        return None
    return num / den


def _norm_rotation(value: float) -> int:
    deg = int(round(value)) % 360  # noqa: RUF046
    if deg < 0:
        deg += 360
    if deg in {0, 90, 180, 270}:
        return deg
    return min((0, 90, 180, 270), key=lambda item: min(abs(item - deg), 360 - abs(item - deg)))


def _rotation(stream: dict[str, object]) -> int:
    side = stream.get("side_data_list")
    if isinstance(side, list):
        for item in side:
            if isinstance(item, dict) and "rotation" in item:
                raw = _float(item.get("rotation"))
                if raw is not None:
                    return _norm_rotation(raw)
    tags = stream.get("tags")
    if isinstance(tags, dict) and "rotate" in tags:
        raw = _float(tags.get("rotate"))
        if raw is not None:
            return _norm_rotation(raw)
    return 0


def _rotation_filter(degrees: int) -> str | None:
    deg = degrees % 360
    if deg < 0:
        deg += 360
    if deg == 270:
        return "transpose=1"
    if deg == 90:
        return "transpose=2"
    if deg == 180:
        return "hflip,vflip"
    return None


def _run_argv(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyncVolumeError(f"{argv[0]} timed out.") from exc
    except OSError as exc:
        raise SyncVolumeError(f"{argv[0]} could not start.") from exc


def probe_video(path: Path) -> dict[str, Any]:
    argv = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = _run_argv(argv, timeout=PROBE_TIMEOUT_S)
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise SyncVolumeError(err or f"ffprobe failed for {path.name}.")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncVolumeError(f"ffprobe json was not an object for {path.name}.") from exc
    if not isinstance(payload, dict):
        raise SyncVolumeError(f"ffprobe json was not an object for {path.name}.")
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise SyncVolumeError(f"{path.name} is not a video.")
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise SyncVolumeError(f"{path.name} is not a video.")
    fps = _rate(video.get("r_frame_rate")) or _rate(video.get("avg_frame_rate"))
    return {
        "width": int(_float(video.get("width")) or 0),
        "height": int(_float(video.get("height")) or 0),
        "fps": fps,
        "rotation": _rotation(video),
        "r_frame_rate": video.get("r_frame_rate"),
    }


def transcode_argv(src: Path, dest: Path, info: dict[str, Any] | None = None) -> list[str]:
    meta = info if info is not None else probe_video(src)
    rotate = int(meta.get("rotation") or 0)
    parts: list[str] = []
    rot_filter = _rotation_filter(rotate)
    if rot_filter:
        parts.append(rot_filter)
    parts.append(
        f"scale='if(gte(iw,ih),{LONG_SIDE_1080P},-2)':'if(gte(iw,ih),-2,{LONG_SIDE_1080P})'"
    )
    parts.append("setsar=1")
    fps = meta.get("fps")
    rate = meta.get("r_frame_rate")
    if isinstance(rate, str) and rate and rate != "0/0":
        parts.append(f"fps={rate}")
    elif isinstance(fps, (int, float)) and float(fps) > 0:
        parts.append(f"fps={float(fps):.6f}")
    argv = [
        ffmpeg_bin(),
        "-y",
        "-hide_banner",
        "-nostdin",
        "-noautorotate",
        "-display_rotation",
        "0",
        "-i",
        str(src),
        "-vf",
        ",".join(parts),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    return argv


def transcode_to_1080p(
    src: Path, dest: Path, info: dict[str, Any] | None = None
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.stem}.tmp{dest.suffix or '.mp4'}")
    meta = info if info is not None else probe_video(src)
    argv = transcode_argv(src, tmp, meta)
    try:
        result = _run_argv(argv, timeout=TRANSCODE_TIMEOUT_S)
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise SyncVolumeError(err or f"1080p transcode failed for {src.name}.")
        os.replace(tmp, dest)
    finally:
        if tmp.exists() and not dest.exists():
            tmp.unlink(missing_ok=True)
    return dest


def _safe_work_path(work: Path, key: str) -> Path:
    dest = (work / key).resolve()
    root = work.resolve()
    if dest != root and root not in dest.parents:
        raise SyncVolumeError(f"Refusing path {key}.")
    return dest


def _oversize_message(key: str, size: int, max_put: int, *, transcoded: bool) -> str:
    extra = " after 1080p transcode" if transcoded else ""
    return (
        f"{key} is {size} bytes{extra}. put-object refuses files over 150MiB "
        f"({max_put} bytes). Multipart is not supported yet."
    )


def prepare_uploads(
    golden: Path,
    manifest_files: dict[str, Any],
    work: Path,
    max_put: int = MAX_PUT_BYTES,
) -> dict[str, Any]:
    """Build the next manifest files dict and the put-object list.

    Transcode every new oversize video first. Fail if any upload body is
    still over max_put. Do not upload from this function.
    """
    files = dict(manifest_files)
    uploads: list[dict[str, Any]] = []
    errors: list[str] = []
    work.mkdir(parents=True, exist_ok=True)

    for key, path in iter_candidates(golden):
        original = digest(path)
        listed = listed_original_sha(files.get(key))
        if listed == original:
            print(f"skip {key}")
            entry = files.get(key)
            if isinstance(entry, dict) and "original_sha256" not in entry:
                files[key] = {
                    "sha256": entry.get("sha256", original),
                    "original_sha256": original,
                    "size": entry.get("size", path.stat().st_size),
                }
            continue

        upload_path = path
        transcoded = False
        is_video = path.suffix.lower() in VIDEO_SUFFIXES and key != "labels/labels.json"
        if is_video and path.stat().st_size > max_put:
            dest = _safe_work_path(work, key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            info = probe_video(path)
            print(
                f"transcode {key} {info.get('width')}x{info.get('height')} "
                f"rot={info.get('rotation')} fps={info.get('fps')}"
            )
            transcode_to_1080p(path, dest, info=info)
            upload_path = dest
            transcoded = True

        size = upload_path.stat().st_size
        if size > max_put:
            errors.append(_oversize_message(key, size, max_put, transcoded=transcoded))
            continue

        uploaded = digest(upload_path)
        files[key] = {
            "sha256": uploaded,
            "original_sha256": original,
            "size": size,
        }
        uploads.append(
            {
                "key": key,
                "path": str(upload_path),
                "original_sha256": original,
                "sha256": uploaded,
                "size": size,
                "transcoded": transcoded,
            }
        )

    if errors:
        raise SyncVolumeError("\n".join(errors))
    return {"files": files, "uploads": uploads}


def load_manifest_files(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(manifest, dict):
        return {}
    files = manifest.get("files")
    if not isinstance(files, dict):
        return {}
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare golden files for sync_volume.sh.")
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--max-put", type=int, default=MAX_PUT_BYTES)
    args = parser.parse_args(argv)
    try:
        plan = prepare_uploads(
            args.golden,
            load_manifest_files(args.manifest),
            args.work,
            max_put=args.max_put,
        )
    except SyncVolumeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    args.plan.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
