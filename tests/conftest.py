"""Pytest configuration and shared fixtures.

Snapshot harness — stdlib only, no external snapshot library.

Snapshots live under tests/__snapshots__/<safe-test-name>.txt
Set UPDATE_SNAPSHOTS=1 to (re)write snapshots from current output.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def _snapshot_path(node_id: str, name: str | None) -> Path:
    """Translate a pytest node id into a stable on-disk filename."""
    safe = node_id.replace("::", "__").replace("/", "_").replace(".py", "")
    if name:
        safe = f"{safe}__{name}"
    return SNAPSHOT_DIR / f"{safe}.txt"


def _serialize(actual: object) -> str:
    if isinstance(actual, str):
        return actual
    return json.dumps(actual, indent=2, sort_keys=True, default=str)


@pytest.fixture
def snapshot(request: pytest.FixtureRequest):
    """Compare a value against a stored snapshot file.

    Usage:
        def test_foo(snapshot):
            snapshot(some_string)
            snapshot(some_dict, name="case1")  # optional label for multiple snapshots
    """

    def _check(actual: object, name: str | None = None) -> None:
        path = _snapshot_path(request.node.nodeid, name)
        rendered = _serialize(actual)
        if UPDATE or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            return
        expected = path.read_text(encoding="utf-8")
        assert rendered == expected, (
            f"\nSnapshot mismatch: {path}\n"
            f"Run with UPDATE_SNAPSHOTS=1 to refresh.\n"
            f"--- expected ---\n{expected}\n"
            f"--- actual ---\n{rendered}\n"
        )

    return _check


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to tests/fixtures/ — for raw captured API responses."""
    return Path(__file__).parent / "fixtures"
