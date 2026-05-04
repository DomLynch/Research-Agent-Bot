"""Pytest configuration and shared fixtures.

Snapshot harness — stdlib only, no external snapshot library.

Snapshots live under tests/__snapshots__/<safe-test-name>.txt
Set UPDATE_SNAPSHOTS=1 to (re)write snapshots from current output.

Topic-default for tests
-----------------------
Production code (run_v06_synthesis.py main()) requires an explicit
--topic CLI arg; the orchestrator's module-level QUANT_DIR/PARSED_DIR
are sentinels until _set_topic() runs. The universal-fix-no-hardcoding
rule (2026-05-04) removed the metformin defaults from module-import
time so a missing topic configuration surfaces as an error instead of
silently using metformin papers.

For TEST collection / TEST runtime, however, many existing tests
exercise topic-aware logic (anaphoric-misread detection, change-value
overgroup detection, etc.) on metformin-style paper text without
explicitly setting up a topic context. Those tests rely on the corpus
paths pointing somewhere with real quant_claims data. Setting
TOPIC_DOMAIN=metformin and pre-calling orch._set_topic("metformin") at
conftest-load gives them the expected metformin context. Tests that
need a different topic call _set_topic() inside their own setup;
production code never reaches this fixture.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Test-only metformin context — see module docstring rationale. This
# only affects test collection + execution; production CLI runs always
# pass through run_v06_synthesis main() which sets TOPIC_DOMAIN from
# the --topic arg before any work.
os.environ.setdefault("TOPIC_DOMAIN", "metformin")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import run_v06_synthesis as _orch  # noqa: E402
    _orch._set_topic("metformin")
except (ImportError, FileNotFoundError, OSError):
    # Some test environments may not have full corpus on disk —
    # tests that need it will fail with a clear corpus-missing error.
    pass

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
        if not path.exists():
            if not UPDATE:
                raise AssertionError(
                    f"\nSnapshot missing: {path}\n"
                    f"Run with UPDATE_SNAPSHOTS=1 to create the baseline, "
                    f"then commit it.\n"
                    f"--- would-be content ---\n{rendered}\n"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            return
        if UPDATE:
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
