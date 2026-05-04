"""LOC budget enforcement.

Hard rules:
- agent/ runtime package must stay under TOTAL_LIMIT lines (excluding blanks
  and comment-only lines, mirroring `cloc` semantics).
- No single file inside agent/ may exceed PER_FILE_LIMIT lines.

These rules are the structural defense against drafter-style bloat. Raising
them requires a DECISIONS.md entry justifying the new ceiling.

Current ceiling: 13,500 LOC (raised 2026-05-04 from 12,000 by the
multi-topic refactor — adds 9 new source-client adapters
(biorxiv/semantic_scholar/crossref/unpaywall/core/doaj/openaire/
pmc_oai/chembl, ~700 cloc), SourceAggregator (~150 cloc),
TopicPack v2 schema fields + bg-lit hoist (~100 cloc), and
manuscript_appendix.py (~250 cloc). Total expansion ~1,200 cloc to
make the agent generic across topics + databases. The user
explicitly approved this raise: "ADD ALL OF THESE" referring to
the 11-database expansion, plus "no hardcoding ... should be
scalable across multi topics" — every new line earns its life via
generic-multi-topic capability, not abstraction theater.
"""
from __future__ import annotations

from pathlib import Path

TOTAL_LIMIT = 13500
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
