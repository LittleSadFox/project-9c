"""Library folder paths and safe file helpers."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.errors import AppError

LIBRARY_SUBDIRS = (
    "originals",
    "proxies",
    "thumbs",
    "pose",
    "align",
    "clips",
    "renders",
    "models",
    "exports",
    "trash",
    "tmp",
)


@dataclass(frozen=True)
class LibraryPaths:
    """Resolved paths under one library folder."""

    root: Path

    @property
    def db(self) -> Path:
        return self.root / "library.sqlite3"

    @property
    def originals(self) -> Path:
        return self.root / "originals"

    @property
    def proxies(self) -> Path:
        return self.root / "proxies"

    @property
    def thumbs(self) -> Path:
        return self.root / "thumbs"

    @property
    def pose(self) -> Path:
        return self.root / "pose"

    @property
    def align(self) -> Path:
        return self.root / "align"

    @property
    def clips(self) -> Path:
        return self.root / "clips"

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def trash(self) -> Path:
        return self.root / "trash"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    def ensure(self) -> None:
        """Create the library folder and its subfolders."""
        self.root.mkdir(parents=True, exist_ok=True)
        for name in LIBRARY_SUBDIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def clear_tmp(self) -> None:
        """Remove leftover files from tmp/."""
        if not self.tmp.exists():
            self.tmp.mkdir(parents=True, exist_ok=True)
            return
        for child in self.tmp.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def original_path(self, video_id: str, ext: str) -> Path:
        return safe_join(self.originals, f"{video_id}.{safe_ext(ext)}")

    def proxy_path(self, video_id: str) -> Path:
        return safe_join(self.proxies, f"{video_id}.mp4")

    def thumb_dir(self, video_id: str) -> Path:
        return safe_join(self.thumbs, video_id)

    def thumb_path(self, video_id: str, index: int) -> Path:
        return safe_join(self.thumb_dir(video_id), f"{int(index)}.jpg")

    def clip_path(self, attempt_id: str, version: int) -> Path:
        return safe_join(self.clips, f"{attempt_id}_v{int(version)}.mp4")

    def trash_item_dir(self, trash_id: str) -> Path:
        return safe_join(self.trash, trash_id)


def safe_join(root: Path, *parts: str) -> Path:
    """Join path parts and reject any result that leaves root."""
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AppError("bad_path", 400, "The path is not allowed.") from exc
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    """Write to path.tmp and then replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def move_to_trash(path: Path, trash_dir: Path) -> Path:
    """Move a file or folder into trash/ under a new UUID name."""
    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / f"{uuid4().hex}{path.suffix if path.is_file() else ''}"
    if path.exists():
        shutil.move(str(path), str(dest))
    return dest


def safe_ext(ext: str) -> str:
    """Keep only a short alphanumeric extension."""
    cleaned = ext.lstrip(".").lower()
    if not cleaned or len(cleaned) > 8 or not cleaned.isalnum():
        raise AppError("bad_filename", 400, "The file extension is not allowed.")
    return cleaned


def move_into(src: Path, dest: Path) -> None:
    """Move src to dest. Create the dest folder first."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(src), str(dest))
