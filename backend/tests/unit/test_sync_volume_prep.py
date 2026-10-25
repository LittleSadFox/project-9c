"""1080p prep uses CC_FFMPEG_BIN as an argv list and records both hashes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts.sync_volume_prep import (
    MAX_PUT_BYTES,
    SyncVolumeError,
    prepare_uploads,
    transcode_argv,
    transcode_to_1080p,
)

from tests.unit.test_sync_volume import _file_sha256, _media_stubs


def test_transcode_argv_uses_cc_ffmpeg_bin_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, _log = _media_stubs(tmp_path, out_size=64)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    src = tmp_path / "in.mp4"
    dest = tmp_path / "out.mp4"
    src.write_bytes(b"src")
    argv = transcode_argv(src, dest)
    assert argv[0] == str(ffmpeg)
    assert argv[0] != "ffmpeg"
    assert "-i" in argv
    assert argv[argv.index("-i") + 1] == str(src)
    assert argv[-1] == str(dest)
    vf = argv[argv.index("-vf") + 1]
    assert "1920" in vf
    assert "transpose=1" in vf
    assert "fps=60/1" in vf
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert "-noautorotate" in argv
    assert argv[argv.index("-display_rotation") + 1] == "0"
    assert all(isinstance(item, str) for item in argv)


def test_prepare_uploads_skips_small_file_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, log = _media_stubs(tmp_path, out_size=64)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    golden = tmp_path / "golden"
    golden.mkdir()
    clip = golden / "clip.mp4"
    clip.write_bytes(b"clip-bytes")
    plan = prepare_uploads(golden, {}, tmp_path / "work")
    assert not log.exists()
    entry = plan["files"]["clip.mp4"]
    digest = _file_sha256(clip)
    assert entry["original_sha256"] == digest
    assert entry["sha256"] == digest
    assert plan["uploads"][0]["path"] == str(clip)
    assert plan["uploads"][0]["transcoded"] is False


def test_prepare_uploads_transcodes_oversize_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, log = _media_stubs(tmp_path, out_size=64)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    golden = tmp_path / "golden"
    golden.mkdir()
    huge = golden / "huge.mp4"
    huge.touch()
    os.truncate(huge, MAX_PUT_BYTES + 1)
    work = tmp_path / "work"
    plan = prepare_uploads(golden, {}, work)
    original = _file_sha256(huge)
    uploaded_path = Path(plan["uploads"][0]["path"])
    assert uploaded_path != huge
    assert uploaded_path.is_file()
    uploaded = _file_sha256(uploaded_path)
    assert plan["files"]["huge.mp4"]["original_sha256"] == original
    assert plan["files"]["huge.mp4"]["sha256"] == uploaded
    assert original != uploaded
    argv = json.loads(log.read_text(encoding="utf-8"))
    assert argv[0] == str(ffmpeg)


def test_prepare_uploads_skips_matching_original_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, log = _media_stubs(tmp_path, out_size=64)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    golden = tmp_path / "golden"
    golden.mkdir()
    huge = golden / "huge.mp4"
    huge.touch()
    os.truncate(huge, MAX_PUT_BYTES + 1)
    original = _file_sha256(huge)
    plan = prepare_uploads(
        golden,
        {
            "huge.mp4": {
                "original_sha256": original,
                "sha256": "already-uploaded",
                "size": 64,
            }
        },
        tmp_path / "work",
    )
    assert plan["uploads"] == []
    assert plan["files"]["huge.mp4"]["sha256"] == "already-uploaded"
    assert not log.exists()


def test_prepare_uploads_refuses_labels_over_150mib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, log = _media_stubs(tmp_path, out_size=64)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    huge = labels / "labels.json"
    huge.write_bytes(b"{}")
    os.truncate(huge, MAX_PUT_BYTES + 1)
    with pytest.raises(SyncVolumeError, match="labels/labels.json") as err:
        prepare_uploads(golden, {}, tmp_path / "work")
    assert "150MiB" in str(err.value)
    assert "Multipart is not supported yet" in str(err.value)
    assert "after 1080p transcode" not in str(err.value)
    assert not log.exists()


def test_prepare_uploads_refuses_transcode_still_over_150mib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, _log = _media_stubs(tmp_path, out_size=MAX_PUT_BYTES + 1)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    golden = tmp_path / "golden"
    golden.mkdir()
    huge = golden / "huge.mp4"
    huge.touch()
    os.truncate(huge, MAX_PUT_BYTES + 1)
    with pytest.raises(SyncVolumeError, match="after 1080p transcode") as err:
        prepare_uploads(golden, {}, tmp_path / "work")
    assert "huge.mp4" in str(err.value)
    assert "150MiB" in str(err.value)


def test_transcode_to_1080p_writes_stub_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe, log = _media_stubs(tmp_path, out_size=32)
    monkeypatch.setenv("CC_FFMPEG_BIN", str(ffmpeg))
    monkeypatch.setenv("CC_FFPROBE_BIN", str(ffprobe))
    src = tmp_path / "in.mp4"
    dest = tmp_path / "out.mp4"
    src.write_bytes(b"src")
    transcode_to_1080p(src, dest)
    assert dest.stat().st_size == 32
    argv = json.loads(log.read_text(encoding="utf-8"))
    assert argv[0] == str(ffmpeg)
    assert all(isinstance(item, str) for item in argv)
