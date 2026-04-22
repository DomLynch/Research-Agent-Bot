#!/usr/bin/env python3
"""Detect modules in agent/ that are never imported by anything else.

Used in CI as a warning-only gate: flags modules that may be candidates for
removal or that are only exercised via external scripts/tests.

Usage:
    python scripts/detect_unused_modules.py [--json]

Exit 0 with warnings on stdout if dead modules found.
Exit 1 on internal errors.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def _collect_imports(src_dir: Path) -> set[str]:
    """Return set of module names imported across agent/."""
    imported: set[str] = set()
    for py in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("agent"):
                        imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("agent"):
                    imported.add(node.module)
    return imported


def _collect_modules(src_dir: Path) -> dict[str, Path]:
    """Return {dotted.module.name: path} for every .py in agent/."""
    modules: dict[str, Path] = {}
    for py in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        rel = py.relative_to(src_dir.parent)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        dotted = ".".join(parts)
        modules[dotted] = py
    return modules


def detect_dead_modules(repo_root: Path) -> list[str]:
    """Return sorted list of dead module dotted names."""
    src_dir = repo_root / "agent"
    all_modules = _collect_modules(src_dir)
    imported = _collect_imports(src_dir)

    dead = sorted(name for name in all_modules if name not in imported)
    return dead


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    dead = detect_dead_modules(repo_root)

    use_json = "--json" in sys.argv
    if use_json:
        print(json.dumps({"dead_modules": dead, "count": len(dead)}))
    else:
        if dead:
            for m in dead:
                print(f"::warning::Dead module detected: {m}")
        else:
            print("No dead modules found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
