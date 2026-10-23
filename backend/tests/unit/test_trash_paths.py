"""Trash restore and empty stay strictly inside trash/."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import AppError
from app.repo import trash as trash_repo
from app.services import library
from app.storage import LibraryPaths


@pytest.mark.parametrize("bad_path", ["../x", "a/..", ".", ""])
def test_escape_trash_path_is_refused_and_nothing_is_deleted(
    db_conn: sqlite3.Connection, tmp_settings: Settings, bad_path: str
) -> None:
    paths = LibraryPaths(tmp_settings.library_dir)
    paths.ensure()

    inside = paths.root / "x"
    inside.write_text("keep-inside", encoding="utf-8")
    outside = paths.root.parent / "outside.txt"
    outside.write_text("keep-outside", encoding="utf-8")

    legit_dir = paths.trash_item_dir("legit-item")
    legit_dir.mkdir(parents=True, exist_ok=True)
    marker = legit_dir / "keep.txt"
    marker.write_text("keep-legit", encoding="utf-8")

    trash_repo.insert(
        db_conn,
        kind="video",
        entity_id="vid-legit",
        payload="{}",
        path="trash/legit-item",
    )
    bad = trash_repo.insert(
        db_conn,
        kind="video",
        entity_id="vid-escape",
        payload="{}",
        path=bad_path,
    )

    with pytest.raises(AppError) as emptied:
        library.empty_trash(db_conn, paths)
    assert emptied.value.code == "bad_path"
    assert emptied.value.status == 400
    _assert_sentinels(inside, outside, marker)
    assert trash_repo.get(db_conn, str(bad["id"])) is not None
    assert len(trash_repo.list_items(db_conn)) == 2

    with pytest.raises(AppError) as restored:
        library.restore_trash(db_conn, paths, str(bad["id"]))
    assert restored.value.code == "bad_path"
    assert restored.value.status == 400
    _assert_sentinels(inside, outside, marker)
    assert trash_repo.get(db_conn, str(bad["id"])) is not None


def _assert_sentinels(inside: Path, outside: Path, marker: Path) -> None:
    assert inside.read_text(encoding="utf-8") == "keep-inside"
    assert outside.read_text(encoding="utf-8") == "keep-outside"
    assert marker.read_text(encoding="utf-8") == "keep-legit"
