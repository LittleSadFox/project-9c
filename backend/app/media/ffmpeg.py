"""FfmpegTool: probe, proxy, cut, frame, and thumbnails through argument lists."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.media.tool import MediaError

PROBE_TIMEOUT_S = 30.0
ENCODE_TIMEOUT_S = 600.0
ENCODER_TEST_TIMEOUT_S = 15.0
THUMB_COUNT = 5


class FfmpegTool:
    """Real MediaTool. Call ffmpeg and ffprobe with argument lists."""

    def __init__(self, ffmpeg_bin: str, ffprobe_bin: str) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.proxy_fps = 30.0
        self.proxy_long_side = 1280
        self.timeout_s = ENCODE_TIMEOUT_S
        self._h264_encoder: str | None = None

    def probe(self, path: Path) -> dict[str, object]:
        if not path.is_file():
            raise MediaError("not_video", "This file is not a video.")
        payload = self._ffprobe_json(path)
        streams = payload.get("streams")
        if not isinstance(streams, list):
            raise MediaError("not_video", "This file is not a video.")
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not isinstance(video, dict):
            raise MediaError("not_video", "This file is not a video.")
        fmt = payload.get("format")
        fmt_dict = fmt if isinstance(fmt, dict) else {}
        duration = _float(video.get("duration"))
        if duration is None:
            duration = _float(fmt_dict.get("duration"))
        fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or 0.0
        r_fps = _rate(video.get("r_frame_rate"))
        is_vfr = bool(fps and r_fps and abs(fps - r_fps) / max(r_fps, 1e-6) > 0.02)
        n_frames = _int(video.get("nb_frames"))
        if n_frames is None and duration is not None and fps:
            n_frames = int(round(duration * fps))
        width = _int(video.get("width")) or 0
        height = _int(video.get("height")) or 0
        return {
            "duration_s": duration if duration is not None else 0.0,
            "fps": fps,
            "width": width,
            "height": height,
            "codec": str(video.get("codec_name") or ""),
            "is_vfr": is_vfr,
            "rotation": _rotation(video),
            "n_frames": n_frames,
            "recorded_at": _recorded_at(fmt_dict, video),
        }

    def make_proxy(self, src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_media_path(dest)
        long_side = int(self.proxy_long_side)
        fps = float(self.proxy_fps)
        info = self.probe(src)
        rot_raw = info.get("rotation")
        rotate = int(rot_raw) if isinstance(rot_raw, (int, float)) else 0
        parts: list[str] = []
        rot_filter = _rotation_filter(rotate)
        if rot_filter:
            parts.append(rot_filter)
        parts.append(
            f"scale='if(gte(iw,ih),{long_side},-2)':'if(gte(iw,ih),-2,{long_side})'"
        )
        parts.extend(["setsar=1", f"fps={fps}"])
        encoder = self.h264_encoder()
        argv = [
            self.ffmpeg_bin,
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
            encoder,
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-bf",
            "0",
            "-g",
            "15",
            "-keyint_min",
            "15",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
        if encoder == "libx264":
            argv.extend(["-sc_threshold", "0"])
        argv.extend(["-progress", "pipe:2", str(tmp)])
        try:
            self._run(argv, timeout=self.timeout_s)
            os.replace(tmp, dest)
        finally:
            if tmp.exists() and not dest.exists():
                tmp.unlink(missing_ok=True)

    def cut_clip(self, src: Path, dest: Path, start_s: float, end_s: float) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_media_path(dest)
        duration = max(0.0, float(end_s) - float(start_s))
        encoder = self.h264_encoder()
        argv = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-nostdin",
            "-i",
            str(src),
            "-ss",
            f"{start_s:.6f}",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            encoder,
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        try:
            self._run(argv, timeout=self.timeout_s)
            os.replace(tmp, dest)
        finally:
            if tmp.exists() and not dest.exists():
                tmp.unlink(missing_ok=True)

    def extract_frame(self, src: Path, frame: int) -> bytes:
        argv = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-nostdin",
            "-i",
            str(src),
            "-vf",
            f"select=eq(n\\,{int(frame)})",
            "-vframes",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        result = self._run(argv, timeout=PROBE_TIMEOUT_S, capture_stdout=True)
        if not result.stdout:
            raise MediaError("no_frame", "The frame is not in this file.")
        return result.stdout

    def thumbnails(self, src: Path, dest_dir: Path) -> list[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        info = self.probe(src)
        n_frames = _int(info.get("n_frames")) or 1
        count = min(THUMB_COUNT, max(1, n_frames))
        paths: list[Path] = []
        for index in range(count):
            if count == 1:
                frame = 0
            else:
                frame = int(round(index * (n_frames - 1) / (count - 1)))
            jpeg = self.extract_frame(src, frame)
            dest = dest_dir / f"{index}.jpg"
            dest.write_bytes(jpeg)
            paths.append(dest)
        return paths

    def render(self, frames_iter: object, dest: Path) -> None:
        del frames_iter, dest
        raise MediaError("not_implemented", "Render is not in Phase 1.")

    def h264_encoder(self) -> str:
        if self._h264_encoder:
            return self._h264_encoder
        if sys.platform == "darwin" and self._test_encoder("h264_videotoolbox"):
            self._h264_encoder = "h264_videotoolbox"
            return self._h264_encoder
        self._h264_encoder = "libx264"
        return self._h264_encoder

    def _test_encoder(self, encoder: str) -> bool:
        argv = [
            self.ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:r=1:d=0.1",
            "-c:v",
            encoder,
            "-f",
            "null",
            "-",
        ]
        try:
            self._run(argv, timeout=ENCODER_TEST_TIMEOUT_S)
        except MediaError:
            return False
        return True

    def _ffprobe_json(self, path: Path) -> dict[str, object]:
        argv = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = self._run(
            argv, timeout=PROBE_TIMEOUT_S, capture_stdout=True, binary=self.ffprobe_bin
        )
        try:
            raw_out = result.stdout
            text = raw_out.decode("utf-8") if isinstance(raw_out, bytes) else raw_out
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MediaError("not_video", "This file is not a video.") from exc
        if not isinstance(payload, dict):
            raise MediaError("not_video", "This file is not a video.")
        return payload

    def _run(
        self,
        argv: list[str],
        *,
        timeout: float,
        capture_stdout: bool = False,
        binary: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            name = binary or self.ffmpeg_bin
            raise MediaError("timeout", f"{name} timed out.") from exc
        except OSError as exc:
            name = binary or self.ffmpeg_bin
            raise MediaError("spawn_failed", f"{name} could not start.") from exc
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            lines = [line.strip() for line in err.splitlines() if line.strip()]
            snippet = " ".join(lines[-6:])[:400]
            raise MediaError("ffmpeg_failed", snippet or "The media tool failed.")
        return result


def _tmp_media_path(dest: Path) -> Path:
    return dest.with_name(f"{dest.stem}.tmp{dest.suffix}")


def _float(value: object) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
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


def _norm_rotation(value: float) -> int:
    deg = int(round(value)) % 360
    if deg < 0:
        deg += 360
    if deg in {0, 90, 180, 270}:
        return deg
    closest = min((0, 90, 180, 270), key=lambda item: min(abs(item - deg), 360 - abs(item - deg)))
    return closest


def _rotation_filter(degrees: int) -> str | None:
    """Stand pixels up from a display-matrix rotation.

    ffprobe reports iPhone portrait as -90, which normalizes to 270.
    That needs a clockwise 90° transpose. +90 needs counter-clockwise.
    """
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


def _recorded_at(fmt: dict[str, object], stream: dict[str, object]) -> str | None:
    for block in (fmt.get("tags"), stream.get("tags")):
        if not isinstance(block, dict):
            continue
        raw = block.get("creation_time") or block.get("com.apple.quicktime.creationdate")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None
