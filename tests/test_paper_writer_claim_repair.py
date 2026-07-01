"""Tests for agent/paper_writer_claim_repair.py — Day 10.17 Fix B.

The repair pass must:
  1. Detect sentences citing tier-C / mechanistic receipts with causal
     verbs and no hedge → prepend "Evidence suggests that "
  2. Skip sentences with hedges already present
  3. Skip sentences only citing direct A1 receipts (no overclaim risk)
  4. Skip _Cited: markdown footers (citation metadata, not prose)
  5. Log every repair with original / repaired / receipt_ids / verb
  6. Be idempotent — running the repair pass twice doesn't double-fix
"""
from __future__ import annotations

from agent.paper_writer_claim_repair import (
    REPAIR_PREFIX,
    repair_abstract_claim_strength,
    repair_claim_strength,
)
from agent.synthesis_schemas import EffectDirection, ReceiptSummary


def _direct(rid: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text="thesis", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=f"NCT-{rid}",
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=(), population_summary="older adults",
    )


def _mech(rid: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text="thesis", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="C", directness="mechanistic",
        outcome_class="longevity", effect_direction="positive",
        p_values=(), population_summary="",
    )


# ============================================================
# Repair detection — load-bearing positives
# ============================================================


def test_abstract_repair_softens_live_overclaim_phrases() -> None:
    body = (
        "## Abstract\n\n"
        "Positive signals support biological plausibility for anti-aging effects. "
        "In a preclinical model, treatment attenuated frailty and modulated cytokines."
    )
    repaired, n = repair_abstract_claim_strength(body)
    assert n == 1
    assert "context-specific signals" in repaired
    assert "do not establish" in repaired
    assert "In preclinical evidence" in repaired
    assert "was reported to attenuate" in repaired


def test_abstract_repair_softens_broad_claim_strength_phrases() -> None:
    body = (
        "## Abstract\n\n"
        "Robust benefits demonstrated in preclinical models confirm the thesis. "
        "Selected clinical signals justify further targeted testing, so the "
        "intervention remains a bounded geroscience case."
    )
    repaired, n = repair_abstract_claim_strength(body)
    assert n == 1
    assert "context-dependent benefits" in repaired
    assert "suggested by preclinical models" in repaired
    assert "is consistent with the thesis" in repaired
    assert "can motivate further targeted testing" in repaired
    assert "bounded evidence hypothesis" in repaired


def test_abstract_repair_does_not_break_negative_establish_claims() -> None:
    body = (
        "## Abstract\n\n"
        "The existing clinical trial evidence does not yet establish definitive efficacy."
    )
    repaired, n = repair_abstract_claim_strength(body)
    assert n == 0
    assert "does not yet establish definitive efficacy" in repaired
    assert "does not yet is consistent with" not in repaired


def test_repair_fires_on_unhedged_causal_verb_citing_mechanistic_receipt() -> None:
    """The empirical 10.17 e2e bug: unhedged 'demonstrated' on tier-C
    evidence. Repair must prepend 'Evidence suggests that '."""
    accepted = [_direct("metformin-multi-001-cfab-c01"), _mech("metformin-multi-001-cfab-c04")]
    body = (
        "Metformin demonstrates a robust effect on longevity in "
        "model organisms (metformin-multi-001-cfab-c04)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert REPAIR_PREFIX in repaired, (
        f"repair prefix not inserted into: {repaired!r}"
    )
    assert "metformin demonstrates a robust effect" in repaired.lower(), (
        f"original sentence content not preserved: {repaired!r}"
    )
    assert len(log) == 1
    assert log[0].triggering_verb.lower() == "demonstrates"
    assert "metformin-multi-001-cfab-c04" in log[0].receipt_ids


def _direct_dir(rid: str, direction: EffectDirection) -> ReceiptSummary:
    # Direct + high-tier; caller sets the coded effect_direction. The old
    # weak_ids (tier-C / mechanistic only) ignored direction, so a
    # directional claim on a null-coded direct receipt shipped unhedged —
    # the dominant reviewer revise ask.
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text="thesis", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=f"NCT-{rid}",
        evidence_tier="A1", directness="direct",
        outcome_class="longevity", effect_direction=direction,
        p_values=(), population_summary="older adults",
    )


def test_repair_fires_on_direction_overclaim_against_null_coded_receipt() -> None:
    """A direct, A1 receipt coded effect_direction='null' must still hedge
    a causal/directional claim — prose cannot assert a direction the
    evidence table does not carry."""
    body = (
        "Metformin improves survival in older adults "
        "(metformin-multi-001-null-c07)."
    )
    repaired, log = repair_claim_strength(body, [_direct_dir("metformin-multi-001-null-c07", "null")])
    assert REPAIR_PREFIX in repaired, f"null-direction overclaim not hedged: {repaired!r}"
    assert len(log) == 1
    assert "metformin-multi-001-null-c07" in log[0].receipt_ids


def test_repair_fires_on_direction_overclaim_against_mixed_coded_receipt() -> None:
    """A 'mixed' receipt has findings in BOTH directions, so asserting a
    single direction is an overclaim and must hedge — same as null/unclear."""
    body = "Metformin improves survival (metformin-multi-001-mixed-c09)."
    repaired, log = repair_claim_strength(body, [_direct_dir("metformin-multi-001-mixed-c09", "mixed")])
    assert REPAIR_PREFIX in repaired, f"mixed-direction overclaim not hedged: {repaired!r}"
    assert len(log) == 1


def test_repair_does_not_fire_for_direct_positive_receipt() -> None:
    """Control: a direct receipt genuinely coded 'positive' is NOT an
    overclaim — the directional verb is faithful, so no hedge."""
    body = "Metformin improves survival (metformin-multi-001-pos-c01)."
    repaired, log = repair_claim_strength(body, [_direct_dir("metformin-multi-001-pos-c01", "positive")])
    assert REPAIR_PREFIX not in repaired
    assert log == []


def test_repair_fires_on_robust_adjective_citing_mechanistic_receipt() -> None:
    """The Q10 verb set includes 'robust' / 'potent' as overclaim
    adjectives. Repair must trigger on them too."""
    accepted = [_mech("metformin-multi-001-cfab-c04")]
    body = (
        "The preclinical longevity profile of metformin is robust "
        "across multiple species (metformin-multi-001-cfab-c04)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert REPAIR_PREFIX in repaired
    assert len(log) == 1
    assert log[0].triggering_verb.lower() == "robust"


# ============================================================
# Repair detection — load-bearing negatives (must NOT fire)
# ============================================================


def test_repair_does_not_fire_when_hedge_already_present() -> None:
    """Sentence already has 'may' — repair leaves it alone."""
    accepted = [_mech("metformin-multi-001-cfab-c04")]
    body = (
        "Metformin may demonstrate a robust effect on longevity "
        "in model organisms (metformin-multi-001-cfab-c04)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert repaired == body, "repair fired despite existing hedge"
    assert log == []


def test_repair_does_not_fire_for_direct_receipt_only() -> None:
    """Direct A1 receipt with causal verb is NOT an overclaim — direct
    clinical evidence can use direct verbs. Repair stays silent."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = (
        "Metformin demonstrates a robust suppression effect on muscle "
        "hypertrophy (metformin-multi-001-cfab-c01)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert repaired == body
    assert log == []


def test_repair_does_not_fire_when_no_tier_c_receipts_in_corpus() -> None:
    """Empty corpus of weak receipts → repair short-circuits to empty."""
    accepted = [_direct("metformin-multi-001-cfab-c01"), _direct("metformin-multi-001-cfab-c02")]
    body = (
        "Metformin demonstrates a robust effect (metformin-multi-001-cfab-c99). "
        "It improves outcomes."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert repaired == body
    assert log == []


def test_repair_does_not_fire_on_cited_footer_with_receipt_ids() -> None:
    """Markdown _Cited: footers contain receipt IDs but no prose.
    Repair must mask them during scan so the sentence regex doesn't
    absorb the footer into surrounding prose and false-fire on the
    receipt IDs inside (Phase 1.5 same fix)."""
    accepted = [_direct("metformin-multi-001-cfab-c01"), _mech("metformin-multi-001-cfab-c04")]
    body = (
        "First sentence ends here.\n"
        "  _Cited: `metformin-multi-001-cfab-c04`, `metformin-multi-001-cfab-c01`_\n\n"
        "Next paragraph has no overclaim ends here."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert repaired == body
    assert log == []
    # Footer must survive untouched.
    assert "_Cited: `metformin-multi-001-cfab-c04`, `metformin-multi-001-cfab-c01`_" in repaired


# ============================================================
# Repair log fidelity
# ============================================================


def test_repair_logs_every_violating_sentence_separately() -> None:
    """Two violations → two log entries, one per sentence."""
    accepted = [_mech("metformin-multi-001-cfab-c04"), _mech("metformin-multi-001-cfab-c05")]
    body = (
        "Metformin demonstrates a robust effect (metformin-multi-001-cfab-c04). "
        "It improves outcomes (metformin-multi-001-cfab-c05)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert len(log) == 2
    triggers = sorted(r.triggering_verb.lower() for r in log)
    assert "demonstrates" in triggers
    assert "improves" in triggers
    # Each repaired sentence has the prefix prepended.
    assert repaired.count(REPAIR_PREFIX) == 2


def test_repair_fires_on_healthspan_claim_geroprotective() -> None:
    """Day 10.17 Fix B v2: Q5 fires on healthspan-claim phrases like
    'geroprotective' that may have no Q10 causal verb. Q5's window
    is only 80 chars around the trigger, so the repair inserts
    '(potentially)' INLINE after the term — sentence-prefix wouldn't
    reach the window for long sentences."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = (
        "Metformin's geroprotective potential remains an open question "
        "in human aging research."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert "geroprotective (potentially)" in repaired
    assert len(log) == 1
    assert "geroprotective" in log[0].triggering_verb.lower()


def test_repair_fires_on_extends_lifespan_phrase() -> None:
    """Q5's 'extends lifespan' phrase must trigger repair even with
    no Q10 verb. Inline '(potentially)' insertion."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = "The hypothesis that metformin extends lifespan in humans is contested."
    repaired, log = repair_claim_strength(body, accepted)
    assert "extends lifespan (potentially)" in repaired
    assert len(log) == 1


def test_repair_healthspan_inline_passes_q5_window_check() -> None:
    """The reason for inline repair: Q5 only checks an 80-char window
    around the trigger. Sentence-prefix repair on a long sentence
    misses the window. Verify the inline strategy puts a Q5 hedge
    token within the window."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = (
        "This combination of clinical safety and biological "
        "plausibility makes it a compelling candidate for broader "
        "geroprotective application."
    )
    repaired, _ = repair_claim_strength(body, accepted)
    # Find geroprotective and check the 80-char window forward/back
    idx = repaired.find("geroprotective")
    window = repaired[max(0, idx - 80):idx + len("geroprotective") + 80]
    q5_hedges = ("may", "remains unproven", "indirect", "potentially",
                 "could", "suggests")
    assert any(h in window.lower() for h in q5_hedges), (
        f"no Q5 hedge in window: {window!r}"
    )


def test_repair_healthspan_handles_plural_form_without_dangling_s() -> None:
    """Reviewer-flagged Phase-0 bug: when the LLM writes 'longevity
    benefits' (plural), the pre-fix regex matched only 'longevity
    benefit' (singular) and the inline insertion produced
    'longevity benefit (potentially)s' — visibly broken prose with
    a dangling 's'. Fix: regex matches the full word with optional
    plural via word boundary, so 'longevity benefits' repairs to
    'longevity benefits (potentially)' cleanly."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = "The longevity benefits remain contested in human trials."
    repaired, log = repair_claim_strength(body, accepted)
    assert "(potentially)s" not in repaired, (
        f"dangling 's' artifact: {repaired!r}"
    )
    # Must repair the full plural form.
    assert "benefits (potentially)" in repaired
    assert len(log) == 1


def test_repair_extends_life_does_not_match_inside_lifespan() -> None:
    """Reviewer-flagged Phase-0 bug: 'extends life' regex matched
    inside 'extends lifespan' (no word boundary). Fix: \\bextends?\\s+life\\b
    only matches the full word 'life', not 'life' inside 'lifespan'."""
    accepted = [_direct("metformin-multi-001-cfab-c01")]
    body = "The hypothesis that metformin extends lifespan in humans is contested."
    repaired, log = repair_claim_strength(body, accepted)
    # 'extends lifespan' should match (the longer pattern).
    assert "extends lifespan (potentially)" in repaired
    # Must not produce a double-repair like 'extends life (potentially)span'
    assert "(potentially)span" not in repaired


def test_repair_preserves_acronym_case_after_prefix() -> None:
    """Reviewer pin: pre-fix lower-cased the first letter
    unconditionally, mangling acronyms like AMPK / mTOR / GDF15.
    The fix only down-cases when the second char is lowercase —
    'Metformin' → 'metformin' (after prefix) but 'AMPK' stays 'AMPK'."""
    accepted = [_mech("metformin-multi-001-cfab-c04")]
    body = (
        "AMPK demonstrates a robust effect on cellular energy "
        "(metformin-multi-001-cfab-c04)."
    )
    repaired, log = repair_claim_strength(body, accepted)
    assert len(log) == 1
    # Acronym preserved — must NOT be aMPK.
    assert "aMPK" not in repaired
    assert "AMPK" in repaired


def test_repair_idempotent_second_pass_produces_zero_repairs() -> None:
    """Running the repair pass twice must not double-fix. After the
    first pass, every violating sentence has 'Evidence suggests'
    which contains the 'suggests' Q10 hedge — second pass detects
    the hedge and skips."""
    accepted = [_mech("metformin-multi-001-cfab-c04")]
    body = (
        "Metformin demonstrates a robust effect on longevity "
        "(metformin-multi-001-cfab-c04)."
    )
    repaired_once, log_once = repair_claim_strength(body, accepted)
    repaired_twice, log_twice = repair_claim_strength(repaired_once, accepted)
    assert len(log_once) == 1
    assert len(log_twice) == 0, (
        f"second-pass repair fired (not idempotent): {log_twice}"
    )
    assert repaired_twice == repaired_once
