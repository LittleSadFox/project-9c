"""core/ may import only numpy and the Python standard library."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / "app" / "core"
ALLOWED_ROOTS = set(sys.stdlib_module_names) | {"numpy"}


def _imported_roots(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                roots.append(node.module.split(".")[0])
    return roots


def test_core_imports_only_numpy_and_stdlib() -> None:
    files = list(CORE_DIR.rglob("*.py"))
    assert files, "core/ must exist"
    for path in files:
        for root in _imported_roots(path):
            assert root in ALLOWED_ROOTS, f"{path} imports {root}, which core/ must not import"
