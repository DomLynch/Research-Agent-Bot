"""Fix #30 — append used background_literature entries to References.

When prose cites canonical clinical thresholds (e.g. 'Owen 2000',
'Anisimov 2008', 'ADA 2024'), the References bibliography MUST
include those canonical references. Pre-fix the prose used them but
References listed only the corpus receipts → public reader sees
'where's the citation for Owen 2000?'."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as orch  # noqa: E402
from agent.synthesis_schemas import ReceiptSummary  # noqa: E402


def _receipt(**kw: object) -> ReceiptSummary:
    base: dict = dict(
        receipt_id="Walton_2019_MASTERS", receipt_path="/tmp/x", topic="t",
        thesis_text="", spar_verdict="accept_clean", n_claims=1,
        n_failed_traces=0, canonical_trial_id=None, evidence_tier="A1",
        directness="direct", outcome_class="metabolic_health",
        effect_direction="positive", p_values=(), population_summary="",
        source_year=2019, source_title="Test Title", source_venue="Test Journal",
        source_doi="10.0000/test", source_pmid=None,
    )
    base.update(kw)
    return ReceiptSummary(**base)


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
        paper, [_receipt()], registry=None,
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
        paper, [_receipt()], registry=None,
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
        paper, [_receipt()], registry=None,
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
        paper, [_receipt()], registry=None,
    )
    bg_block = out.split("### Background References")[1]
    # Studenski's seed entry has 'Studenski et al. JAMA 2011' as the
    # canonical_reference (per docs/background_literature.json)
    assert "Studenski" in bg_block
    assert "JAMA" in bg_block or "2011" in bg_block


def test_methodological_reference_labeled_not_threshold() -> None:
    """#6: a kind='reference' entry (Ioannidis 2005) is annotated as a
    methodological reference, and the caption no longer claims every
    background entry is a 'clinical threshold'."""
    paper = (
        "## Discussion\n\n"
        "Surrogate associations do not guarantee hard-outcome validity "
        "(Ioannidis 2005).\n"
    )
    out = orch._append_references_block(paper, [_receipt()], registry=None)
    bg_block = out.split("### Background References")[1]
    assert "Ioannidis 2005" in bg_block
    assert "(methodological reference)" in bg_block
    # The mislabel ("clinical thresholds cited in prose") is gone.
    assert "clinical thresholds cited in prose" not in out.lower()


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


def test_used_background_lit_entries_excludes_appendix_only_citations() -> None:
    """Fix #16 guarantee: a background token appearing ONLY in the appended
    References/appendix (never cited in prose) must NOT be listed — else the
    'appears at least once in the body' claim is false (the Tinetti/Tancredi
    static-pack leak from a whole-document substring match)."""
    appendix_only = (
        "Walk speed matters in older adults.\n\n"
        "## References\n\n- **Studenski 2011.** Gait speed and survival.\n"
    )
    assert "Studenski 2011" not in [
        e.citation_token for e in orch._used_background_lit_entries(appendix_only)
    ]
    # the SAME token cited in body prose is still listed
    in_prose = (
        "Walk speed (Studenski 2011) predicts survival.\n\n"
        "## References\n\n- x\n"
    )
    assert "Studenski 2011" in [
        e.citation_token for e in orch._used_background_lit_entries(in_prose)
    ]
