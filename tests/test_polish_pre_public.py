"""Fix #33-35 — pre-public polish: tier labels, SPAR scrub, refs.

Reviewer pass on the PhD repro run found these visible 'machine
artifact' leaks that the AAA harness missed but a human notices
immediately. These tests pin the fix behaviour so future
regressions are caught."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import apply_consistency_fixes as fixer  # noqa: E402
import final_consistency_audit as audit  # noqa: E402
import run_v06_synthesis as orch  # noqa: E402
from agent.paper_writer import (  # noqa: E402
    _build_user_prompt,
    _humanize_paper_tier,
)
from agent.paper_writer_prompts import (  # noqa: E402
    DISCUSSION_SYSTEM_PROMPT,
    LIMITATIONS_FULL_SYSTEM_PROMPT,
    RESULTS_SYSTEM_PROMPT,
)
from agent.synthesis_schemas import (  # noqa: E402
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisThesis,
    TensionMatrix,
)


def _r(
    rid: str = "Walton 2019", *,
    tier: str = "A1", directness: str = "direct",
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=10, n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=("p < 0.001",), population_summary="older adults, n=48",
    )


def _matrix(receipts) -> TensionMatrix:
    return TensionMatrix(receipts=tuple(receipts), pairs=())


def _thesis() -> SynthesisThesis:
    return SynthesisThesis(
        text="Metformin shows mixed evidence",
        receipt_ids_referenced=(), tensions_addressed=(),
        rejected_candidates=(), picker_rationale="test",
    )


# ============ Fix #33 — internal tier labels ===========================


def test_humanize_paper_tier_maps_canonical_internal_labels() -> None:
    """Each internal label maps to a human-readable phrase."""
    assert "randomized controlled trial" in _humanize_paper_tier("A1_clinical_RCT")
    assert "clinical/functional endpoint" not in _humanize_paper_tier("A1_clinical_RCT")
    assert "interpret endpoint and comparator fit from the source" in _humanize_paper_tier("A2_human_mechanistic")
    assert "review" in _humanize_paper_tier("B1_review")
    assert "preclinical" in _humanize_paper_tier("C1_preclinical")
    # Unknown labels pass through unchanged (defensive).
    assert _humanize_paper_tier("zzz_unknown") == "zzz_unknown"


def test_writer_prompt_no_longer_emits_internal_tier_labels() -> None:
    """The writer's user-prompt context now uses `study_design:`
    with a human-readable label instead of `paper_tier:` with an
    internal token. Prevents MiMo from copy-pasting the internal
    token verbatim into prose."""
    receipts = [
        _r("Walton 2019", tier="A1", directness="direct"),
        _r("Vujović 2026", tier="C1", directness="mechanistic"),
    ]
    prompt = _build_user_prompt(
        receipts, [], _matrix(receipts), _thesis(),
        topic="metformin",
    )
    # Internal labels MUST NOT appear in the prompt MiMo sees.
    for forbidden in (
        "A1_clinical_RCT", "A2_human_mechanistic",
        "B1_review", "C1_preclinical",
    ):
        assert forbidden not in prompt, (
            f"Internal label {forbidden!r} leaked into writer prompt"
        )
    # Human-readable form IS present.
    assert "randomized controlled trial" in prompt
    assert "preclinical" in prompt


def test_audit_flags_internal_tier_label_in_prose() -> None:
    """Defence-in-depth: if any internal label still leaks (e.g. via
    final-layer reviewer patches), Stage-2 C12 catches it as P2 auto-fixable."""
    paper = (
        "## Discussion\n\n"
        "The A1_clinical_RCT evidence from Walton 2019 demonstrates "
        "that metformin blunts muscle hypertrophy.\n"
    )
    issues = audit.run_audit(paper, {"receipts": []}, {"checks": []})
    c12 = [i for i in issues if i.id.startswith("C12-")]
    assert len(c12) == 1
    assert c12[0].issue_type == "internal_tier_label_in_prose"
    assert c12[0].auto_fixable is True


def test_apply_fixes_relabels_internal_tier_tokens() -> None:
    """Auto-fix replaces every internal label with its human form."""
    paper = (
        "The A1_clinical_RCT data from Walton 2019 contradicts the "
        "C1_preclinical evidence on lifespan extension.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    assert "A1_clinical_RCT" not in fixed
    assert "C1_preclinical" not in fixed
    assert "RCT (clinical)" in fixed
    assert "preclinical" in fixed
    relabel_logs = [
        e for e in log
        if e.get("fix_type") == "internal_tier_label_relabel"
    ]
    assert relabel_logs and relabel_logs[0]["n_changes"] == 2


# ============ Fix #34 — SPAR phrase scrub in prompts ==================


def test_results_prompt_does_not_request_spar_quarantine_paragraph() -> None:
    """The RESULTS prompt previously instructed MiMo to write a
    'quarantine paragraph' citing 'SPAR-rejected' receipts — that's
    why 'no SPAR-rejected canonical receipt was identified' kept
    leaking into prose. The cleaned prompt forbids those phrases."""
    # The OLD instruction text is gone
    assert "SPAR-rejected" not in RESULTS_SYSTEM_PROMPT or (
        # Allowed in the BAN-INSTRUCTION line ("NEVER use SPAR-...")
        "NEVER" in RESULTS_SYSTEM_PROMPT
        or "do NOT" in RESULTS_SYSTEM_PROMPT.lower()
    )
    # Negative-instruction style present (telling MiMo to AVOID)
    assert "do NOT use" in RESULTS_SYSTEM_PROMPT.replace("\n", " ") or (
        "NEVER mention" in RESULTS_SYSTEM_PROMPT
    )


def test_limitations_prompt_does_not_ask_for_spar_quarantine_topic() -> None:
    """The LIMITATIONS prompt previously had 'Receipts quarantined
    by SPAR' as a required topic — directly responsible for the
    'SPAR quarantine process' phrasing in the published paper.
    Cleaned prompt uses 'Corpus scope' framing instead."""
    assert "Corpus scope" in LIMITATIONS_FULL_SYSTEM_PROMPT
    assert "Receipts quarantined by SPAR" not in (
        LIMITATIONS_FULL_SYSTEM_PROMPT
    )


def test_discussion_prompt_no_internal_label_leaks() -> None:
    """Cleaned: discussion prompt no longer mentions
    `A1_clinical`, `A2_human_mechanistic`."""
    assert "A1_clinical and A2_human_mechanistic" not in (
        DISCUSSION_SYSTEM_PROMPT
    )


# ============ Fix #35 — reference formatting ==========================


def _reference_receipt() -> ReceiptSummary:
    return replace(_r(), source_year=2019, source_title="Test Study",
                   source_venue="Aging Cell", source_doi="10.1111/acel.13039")


def test_references_no_space_before_comma() -> None:
    """Pre-fix the ' '.join produced 'Aging Cell , 2019' with a
    stray space before the comma. Smart-join produces clean
    'Aging Cell, 2019.' formatting."""
    paper = "## Conclusion\n\nfinal sentence.\n"
    out = orch._append_references_block(
        paper, [_reference_receipt()], registry=None,
    )
    # No 'Word , Word' patterns in the References block
    refs_block = out.split("## References")[1]
    assert " , " not in refs_block, (
        f"stray space-before-comma in References:\n{refs_block[:300]}"
    )


def test_references_no_space_before_period() -> None:
    """Pre-fix 'DOI: 10.x .' had a stray space before the period."""
    paper = "## Conclusion\n\nfinal sentence.\n"
    out = orch._append_references_block(
        paper, [_reference_receipt()], registry=None,
    )
    refs_block = out.split("## References")[1]
    # Allow ' .' only at the very end of a line if any (should be 0)
    assert " ." not in refs_block.replace(".\n", ""), (
        f"stray space-before-period in References:\n{refs_block[:300]}"
    )


def test_clean_reference_title_de_hyphenates_soft_breaks() -> None:
    """PDF-parsed titles often have 'Anti- Aging' (soft break);
    clean_reference_title collapses to 'Anti-Aging'."""
    title = "A Critical Review of Anti- Aging Drugs and Lifespan"
    out = orch._clean_reference_title(title)
    assert out == "A Critical Review of Anti-Aging Drugs and Lifespan"


def test_clean_reference_title_collapses_double_spaces() -> None:
    """Double spaces in source titles → single space."""
    title = "Metformin   blunts  muscle hypertrophy"
    out = orch._clean_reference_title(title)
    assert out == "Metformin blunts muscle hypertrophy"


def test_clean_reference_title_strips_trailing_period() -> None:
    """Source titles sometimes end in '.', the renderer adds another
    '_TITLE_._' which would produce '_TITLE._.' Avoid double-period."""
    title = "Test Title."
    assert orch._clean_reference_title(title) == "Test Title"


def test_references_block_uses_cleaned_title() -> None:
    """End-to-end: a receipt with broken-hyphen title surfaces in
    References with the title cleaned."""
    receipt = replace(_r("Mohammed 2021"), source_year=2021,
                      source_title="A Critical Review of Anti- Aging Drugs", source_venue="Frontiers")
    out = orch._append_references_block(
        "## Conclusion\n", [receipt], registry=None,
    )
    assert "Anti-Aging" in out
    assert "Anti- Aging" not in out
