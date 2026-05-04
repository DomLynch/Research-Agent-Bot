"""LOC budget enforcement.

Hard rules:
- agent/ runtime package must stay under TOTAL_LIMIT lines (excluding blanks
  and comment-only lines, mirroring `cloc` semantics).
- No single file inside agent/ may exceed PER_FILE_LIMIT lines.

These rules are the structural defense against drafter-style bloat. Raising
them requires a DECISIONS.md entry justifying the new ceiling.

Current ceiling: 14,000 LOC (raised 2026-05-04 from 13,500 by the
all-sources hardening pass + new adapters). Two waves:

Wave 1 — multi-topic refactor (12,000 → 13,500): added 9 source-client
adapters (biorxiv/semantic_scholar/crossref/unpaywall/core/doaj/openaire/
pmc_oai/chembl, ~700 cloc), SourceAggregator (~150 cloc), TopicPack v2
schema + bg-lit hoist (~100 cloc), manuscript_appendix.py (~250 cloc).

Wave 2 — bullet-proof source layer (13,500 → 14,000): adds arXiv +
medRxiv corpus adapters (~300 cloc), agent/enrichment/ subpackage with
iCite/RxNorm/RePORTER clients (~440 cloc), and safe_get_json /
safe_get_text helpers in _base.py (~50 cloc) which centralize fail-soft
policy across all 13 source adapters and replace duplicated
try/except/status-check blocks. Net ceiling rise: 500 cloc to support
the full 15-source registry + 3-client enrichment layer + bullet-proof
error handling. User explicitly authorized: "audit all data sources 2x
and harden all. bullet proof." (2026-05-04).

Wave 3 — universal Q9 structural fix (14,000 → 14,200): adds
agent/results_table.py (~150 cloc) — deterministic per-study
quantitative table built from corpus quant_claims. Replaces the
unreliable prompt-nudge path with structural numeric density (the
table contributes ~30-60 corpus-traced numerics in ~150 words,
reliably lifting Q9 without prompt fragility). User mandated this
as universal-not-topic-hack: "Do not prompt-hack aspirin/statins.
Add universal deterministic numeric table" (2026-05-04).

Every new line earns its life via generic-multi-topic capability or
hardening, not abstraction theater.
"""
from __future__ import annotations

from pathlib import Path

TOTAL_LIMIT = 14200
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
