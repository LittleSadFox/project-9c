"""SPA fallback must not serve files outside frontend/dist."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.main import spa_target
from app.storage import safe_join


def test_safe_join_rejects_parent_escape(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(AppError) as exc:
        safe_join(dist, "..", "secret.txt")
    assert exc.value.status == 400
    assert exc.value.code == "bad_path"


def test_spa_target_rejects_dotdot(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ok", encoding="utf-8")
    with pytest.raises(AppError) as exc:
        spa_target("../secret.txt", dist)
    assert exc.value.status == 400


def test_spa_target_rejects_absolute_escape(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    with pytest.raises(AppError) as exc:
        spa_target("/etc/passwd", dist)
    assert exc.value.status == 400


def test_spa_target_keeps_in_root_file(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    page = dist / "index.html"
    page.write_text("ok", encoding="utf-8")
    assert spa_target("", dist) == page.resolve()
    assert spa_target("index.html", dist) == page.resolve()
