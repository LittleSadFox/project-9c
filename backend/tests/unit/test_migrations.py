"""Running migrations twice must change nothing."""

from __future__ import annotations

from pathlib import Path

from app.db import apply_migrations, connect


def test_migrations_twice_are_noops(tmp_path: Path) -> None:
    db_path = tmp_path / "library.sqlite3"
    conn = connect(db_path)
    apply_migrations(conn)
    first = [
        str(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    apply_migrations(conn)
    second = [
        str(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    tables_again = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert first == ["0001_init", "0002_event_rule_v1"]
    assert first == second
    assert "jobs" in tables
    assert tables == tables_again
    rule = conn.execute(
        "SELECT family, version, active FROM model_versions WHERE id = ?",
        ("c0ffee00-0002-4000-8000-000000000002",),
    ).fetchone()
    assert rule is not None
    assert rule["family"] == "event"
    assert rule["version"] == "rule-v1"
    assert int(rule["active"]) == 1
    keys = {str(row["key"]) for row in conn.execute("SELECT key FROM settings")}
    assert "leave_ground_height_s" in keys
    assert "top_grow_s" in keys
    conn.close()
