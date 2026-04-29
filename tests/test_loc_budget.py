"""LOC budget enforcement.

Hard rules:
- agent/ runtime package must stay under TOTAL_LIMIT lines (excluding blanks
  and comment-only lines, mirroring `cloc` semantics).
- No single file inside agent/ may exceed PER_FILE_LIMIT lines.

These rules are the structural defense against drafter-style bloat. Raising
them requires a DECISIONS.md entry justifying the new ceiling.

Current ceiling: 10,000 LOC (set by DECISIONS.md 2026-04-29 Day 10.16 —
the user-facing deliverable expansion from a ~1k-word structured
brief to a 5–15k-word full research paper added ~1,000 cloc for the
new paper_writer.py + paper_writer_prompts.py + tiered validation +
cross-domain tension detection. 10,000 covers Day 10.16 fully with
~600 cloc headroom for the rule fixes in Phase 3 and the audit
extensions in Phase 4.
"""
from __future__ import annotations

from pathlib import Path

TOTAL_LIMIT = 10000
PER_FILE_LIMIT = 600
AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"


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
