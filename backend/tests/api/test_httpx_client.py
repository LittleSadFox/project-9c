"""Starlette TestClient still uses httpx. httpx2 would need a new pin."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_starlette_warning_is_filtered_in_pytest_ini() -> None:
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "StarletteDeprecationWarning" in text
    assert "starlette.testclient" in text
    backend_ini = (ROOT / "backend" / "pytest.ini").read_text(encoding="utf-8")
    assert "StarletteDeprecationWarning" in backend_ini
    dev = (ROOT / "backend" / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "httpx2" not in dev
