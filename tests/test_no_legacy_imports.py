"""CI guard: agent/ must never import from agent_legacy/ or agent_archived/.

Both packages are preserved for git archaeology only. Importing from either
in the new system would defeat the rebuild and reintroduce coupling to dead
or known-broken architectures (drafter-monolith bug class for agent_legacy;
LLM-in-the-spine bug class for agent_archived/proof001).

If a refactor genuinely needs to consult an archived module, copy the
relevant logic forward into a properly-named new module — never import.
"""
from __future__ import annotations

import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"

# Block both archive directories. Pattern matches both `from X.foo import` and
# `import X.foo` and bare `import X`.
BANNED_PACKAGES = ("agent_legacy", "agent_archived")
BANNED_PATTERNS = tuple(
    re.compile(rf"^\s*from\s+{pkg}(\.|\s)")
    for pkg in BANNED_PACKAGES
) + tuple(
    re.compile(rf"^\s*import\s+{pkg}(\.|\s|$)")
    for pkg in BANNED_PACKAGES
)


def _scan_for_offenders(banned: tuple[re.Pattern[str], ...]) -> list[str]:
    offenders: list[str] = []
    for path in AGENT_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1,
        ):
            if any(p.match(line) for p in banned):
                offenders.append(
                    f"{path.relative_to(AGENT_DIR.parent)}:{lineno}: {line.strip()}"
                )
    return offenders


def test_agent_does_not_import_from_legacy_or_archived() -> None:
    """The blanket guard — combined catch covers both packages."""
    offenders = _scan_for_offenders(BANNED_PATTERNS)
    assert not offenders, (
        "agent/ must not import from agent_legacy/ or agent_archived/:\n"
        + "\n".join(offenders)
    )


def test_agent_legacy_specifically_blocked() -> None:
    """Targeted check — easier to read in CI output if only one rule trips."""
    legacy_only = tuple(
        p for p in BANNED_PATTERNS if "agent_legacy" in p.pattern
    )
    offenders = _scan_for_offenders(legacy_only)
    assert not offenders, (
        "agent/ must not import from agent_legacy/:\n" + "\n".join(offenders)
    )


def test_agent_archived_specifically_blocked() -> None:
    """Targeted check — agent_archived was added 2026-04-27 (Day 0 archive
    of V1.1 LLM-coupled spine). New code must never import from it.
    """
    archived_only = tuple(
        p for p in BANNED_PATTERNS if "agent_archived" in p.pattern
    )
    offenders = _scan_for_offenders(archived_only)
    assert not offenders, (
        "agent/ must not import from agent_archived/:\n" + "\n".join(offenders)
    )
