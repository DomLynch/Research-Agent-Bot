"""Fix #30 — append used background_literature entries to References.

When prose cites canonical clinical thresholds (e.g. 'Owen 2000',
'Anisimov 2008', 'ADA 2024'), the References bibliography MUST
include those canonical references. Pre-fix the prose used them but
References listed only the corpus receipts → public reader sees
'where's the citation for Owen 2000?'."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as orch  # noqa: E402


@dataclass(frozen=True)
class _Receipt:
    receipt_id: str = "Walton_2019_MASTERS"
    source_year: int | None = 2019
    source_title: str | None = "Test Title"
    source_venue: str | None = "Test Journal"
    source_doi: str | None = "10.0000/test"
    source_pmid: str | None = None


def test_background_refs_subsection_appears_when_citation_in_prose() -> None:
    """Prose uses 'Studenski 2011' (a known background_literature
    citation_token). References must include a Background References
    subsection listing that canonical reference."""
    paper = (
        "## Discussion\n\n"
        "Walk-speed below 0.8 m/s indicates frailty risk "
        "(Studenski 2011).\n\n"
    )
    out = orch._append_references_block(
        paper, [_Receipt()], registry=None,
    )
    assert "## References" in out
    assert "### Background References" in out
    assert "Studenski 2011" in out


def test_background_refs_omitted_when_no_bglit_in_prose() -> None:
    """If no background_literature citation_tokens appear in the
    paper, the Background References subsection is suppressed
    (cleaner output for runs that only use corpus citations)."""
    paper = (
        "## Discussion\n\n"
        "Pure corpus content. No background-lit tokens here.\n\n"
    )
    out = orch._append_references_block(
        paper, [_Receipt()], registry=None,
    )
    assert "## References" in out
    assert "### Background References" not in out


def test_background_refs_de_duplicate_by_token() -> None:
    """Two background entries with the SAME citation_token should
    appear in the bibliography only once (avoid duplicate Studenski 2011
    rows when multiple registry entries reuse a citation)."""
    paper = (
        "## Discussion\n\n"
        "Frailty cutoff 0.8 m/s (Studenski 2011); severe frailty "
        "0.6 m/s (Cesari 2009).\n\n"
    )
    out = orch._append_references_block(
        paper, [_Receipt()], registry=None,
    )
    # Each unique citation_token in the prose appears EXACTLY once
    # in the Background References list (avoid duplication when the
    # SAME token is referenced by multiple registry entries — e.g.
    # ADA 2024 covers both 7% HbA1c and 6.5% intensive HbA1c).
    bg_block = out.split("### Background References")[1]
    assert bg_block.count("Studenski 2011") == 1
    assert bg_block.count("Cesari 2009") == 1


def test_background_refs_include_canonical_reference_text() -> None:
    """Each Background Reference entry surfaces the canonical
    bibliographic reference (Author. Year. Title. Journal.) so the
    reader sees the full citation."""
    paper = (
        "## Discussion\n\n"
        "Walk-speed below 0.8 m/s (Studenski 2011) signals frailty.\n"
    )
    out = orch._append_references_block(
        paper, [_Receipt()], registry=None,
    )
    bg_block = out.split("### Background References")[1]
    # Studenski's seed entry has 'Studenski et al. JAMA 2011' as the
    # canonical_reference (per docs/background_literature.json)
    assert "Studenski" in bg_block
    assert "JAMA" in bg_block or "2011" in bg_block


def test_used_background_lit_entries_helper_returns_used_only() -> None:
    """The helper used by _append_references_block returns the
    entries whose citation_token appears in the paper. Pure
    deterministic — no I/O beyond reading the seed registry."""
    paper = "Walk-speed (Studenski 2011) is a marker."
    used = orch._used_background_lit_entries(paper)
    cites = [e.citation_token for e in used]
    assert "Studenski 2011" in cites
    # Cesari 2009 NOT in paper → should not appear
    assert "Cesari 2009" not in cites
