"""Tests for scripts/detect_unused_modules.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "detect_unused_modules.py"


def test_detector_runs_without_error():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "dead_modules" in data
    assert "count" in data
    assert isinstance(data["dead_modules"], list)


def test_schema_is_flagged():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    data = json.loads(result.stdout)
    assert "agent.schema" in data["dead_modules"]


def test_unpaywall_is_not_flagged():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    data = json.loads(result.stdout)
    assert "agent.sources.unpaywall" not in data["dead_modules"]


def test_active_modules_not_flagged():
    """Modules used by the agent pipeline should not appear in dead list."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    data = json.loads(result.stdout)
    active = [
        "agent.planner", "agent.drafter", "agent.extractor",
        "agent.provider", "agent.submit", "agent.entity_resolver",
        "agent.sources.pubmed", "agent.sources.openalex",
        "agent.sources.chembl", "agent.sources.rxiv",
        "agent.sources.unpaywall",
    ]
    for mod in active:
        assert mod not in data["dead_modules"], f"{mod} should not be dead"
