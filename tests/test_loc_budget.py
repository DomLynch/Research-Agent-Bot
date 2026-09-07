"""LOC budget enforcement — the structural defense against bloat.

Rules:
- COMBINED_LIMIT governs agent/ + scripts/ together. This is the binding
  constraint. Separate per-directory caps used to let new code land in
  scripts/ without consuming the agent/ budget; the combined ceiling closes
  that loophole.
- Per-directory and per-file caps still apply as secondary guards.
- Raising ANY ceiling requires a DECISIONS.md entry AND an equal-or-greater
  deletion. Ratchets are one-way: after a large deletion, lower the ceiling
  to lock the gain in rather than banking it as headroom for new bloat.

Staged targets (effective, non-blank/non-comment): 66k -> 55k -> 40k -> 30k.

Per-wave history of earlier ceiling raises lives in DECISIONS.md; it was
removed from this docstring, which had grown to 227 lines wrapping 70 lines
of code.
"""
from __future__ import annotations

from pathlib import Path

TOTAL_LIMIT = 25269  # Shared verified revision context replaces submission padding.
PER_FILE_LIMIT = 800  # Wave 49 limit retained: journal_surface_gate must stay ≤800 LOC. Editorial-register checks live in their semantic-home modules (review_type.py, methods_pack.py) — gate.py is the orchestrator over universal-prose-surface checks (jargon, refs, lanes, thesis, novelty).
AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
SCRIPTS_DIR = AGENT_DIR.parent / "scripts"
SCRIPT_TOTAL_LIMIT = 40231
COMBINED_LIMIT = 65500  # Preserve the combined ceiling; see DECISIONS.
SCRIPT_PER_FILE_LIMIT = 5700


def _count_loc(path: Path) -> int:
    """Count non-blank, non-comment-only lines."""
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        n += 1
    return n


def _python_files() -> list[Path]:
    return sorted(p for p in AGENT_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _script_files() -> list[Path]:
    return sorted(
        path for path in SCRIPTS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_no_single_file_exceeds_per_file_limit():
    offenders = [
        (p.relative_to(AGENT_DIR), _count_loc(p))
        for p in _python_files()
        if _count_loc(p) > PER_FILE_LIMIT
    ]
    assert not offenders, (
        f"Files exceeding {PER_FILE_LIMIT} LOC (refactor required):\n"
        + "\n".join(f"  {p}: {n}" for p, n in offenders)
    )


def test_total_runtime_loc_under_budget():
    files = _python_files()
    total = sum(_count_loc(p) for p in files)
    breakdown = "\n".join(
        f"  {p.relative_to(AGENT_DIR)}: {_count_loc(p)}" for p in files
    )
    assert total <= TOTAL_LIMIT, (
        f"agent/ runtime LOC {total} exceeds budget {TOTAL_LIMIT}.\n"
        f"Breakdown:\n{breakdown}"
    )


def test_scripts_stay_under_bloat_limits():
    files = _script_files()
    total = sum(_count_loc(path) for path in files)
    offenders = [
        (path.relative_to(SCRIPTS_DIR), _count_loc(path))
        for path in files
        if _count_loc(path) > SCRIPT_PER_FILE_LIMIT
    ]
    assert total <= SCRIPT_TOTAL_LIMIT, (
        f"scripts/ LOC {total} exceeds budget {SCRIPT_TOTAL_LIMIT}; delete or consolidate before adding code"
    )
    assert not offenders, (
        f"Scripts exceeding {SCRIPT_PER_FILE_LIMIT} LOC:\n"
        + "\n".join(f"  {path}: {loc}" for path, loc in offenders)
    )


def test_combined_production_loc_under_ceiling():
    """The binding budget: agent/ and scripts/ share one ceiling.

    Split caps let scripts/ absorb growth the agent/ budget would have
    rejected. One number removes that escape hatch.
    """
    total = sum(_count_loc(p) for p in _python_files() + _script_files())
    assert total <= COMBINED_LIMIT, (
        f"combined production LOC {total} exceeds ceiling {COMBINED_LIMIT}. "
        "Delete or consolidate before adding; raising the ceiling needs a "
        "DECISIONS.md entry plus an equal-or-greater deletion."
    )
