"""CI guard: agent/ must never import from agent_legacy/.

The legacy package is preserved for git archaeology only. Importing from it
in the new system would defeat the rebuild and reintroduce coupling to the
drafter-monolith bug class.
"""
from __future__ import annotations

import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
LEGACY_PATTERNS = (
    re.compile(r"^\s*from\s+agent_legacy(\.|\s)"),
    re.compile(r"^\s*import\s+agent_legacy(\.|\s|$)"),
)


def test_agent_does_not_import_from_legacy():
    offenders: list[str] = []
    for path in AGENT_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.match(line) for p in LEGACY_PATTERNS):
                offenders.append(f"{path.relative_to(AGENT_DIR.parent)}:{lineno}: {line.strip()}")
    assert not offenders, "agent/ must not import from agent_legacy:\n" + "\n".join(offenders)
