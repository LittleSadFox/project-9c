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
    conn.close()
    assert first == ["0001_init"]
    assert first == second
    assert "jobs" in tables
    assert tables == tables_again
