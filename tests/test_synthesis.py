"""Tests for agent/synthesis.py — Day 10.2 deterministic tension matrix.

Discriminating test (per playbook Rule 13): a synthetic 7-receipt
corpus shaped like the metformin Quality Reference Corpus must
produce the right tension classifications:

  - MASTERS (direct A1, muscle, negative) +
    Konopka (direct A1, cardiometabolic, negative)  → orthogonal
    (different outcome classes)

  - MASTERS (direct A1, muscle, negative) +
    a synthetic muscle-mechanism receipt (mechanism, unclear)
    → indirectness_gap (same outcome, different directness)

  - MASTERS (direct A1, muscle, negative) +
    MET-PREVENT-style (direct A1, frailty, null) → orthogonal
    (different outcome classes)

  - two muscle-direct receipts agreeing  → agreement

  - two muscle-direct receipts opposite  → disagreement

  - one muscle-null + one muscle-negative → null_vs_positive

These tests pin the per-pair classification logic. If the logic
silently changes (e.g. someone weakens "agreement" to also accept
unclear+unclear), the discriminating tests catch it.
"""
from __future__ import annotations

from agent.synthesis import (
    MIN_UNIQUE_TRIALS_FOR_SYNTHESIS,
    build_receipt_summary,
    build_tension_matrix,
    dedupe_receipts,
    detect_effect_direction,
    detect_outcome_class,
    unique_evidence_key,
)
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
)


def _summary(
    rid: str,
    *,
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    directness: str = "direct",
    tier: str = "A1",
    n_claims: int = 4,
    p_values: tuple[str, ...] = (),
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=n_claims, n_failed_traces=0,
        canonical_trial_id="NCT-test",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome,
        effect_direction=direction,
        p_values=p_values,
        population_summary="older adults",
    )


# ============================================================
# detect_outcome_class — keyword classification
# ============================================================


def test_outcome_class_muscle_function_from_hypertrophy_keyword() -> None:
    text = "Metformin blunts muscle hypertrophy in response to PRT."
    assert detect_outcome_class(text) == "muscle_function"


def test_outcome_class_cardiometabolic_from_vo2max() -> None:
    text = "Metformin attenuated VO2max gains during aerobic training."
    assert detect_outcome_class(text) == "cardiometabolic"


def test_outcome_class_frailty_from_walk_speed() -> None:
    text = "4-m walk speed did not differ between metformin and placebo."
    assert detect_outcome_class(text) == "frailty"


def test_outcome_class_immune_from_rti() -> None:
    text = "RTB101 reduced laboratory-confirmed RTIs in older adults."
    assert detect_outcome_class(text) == "immune"


def test_outcome_class_ophthalmologic_from_amd() -> None:
    text = "Metformin and AMD progression — propensity score matched cohort."
    assert detect_outcome_class(text) == "ophthalmologic"


def test_outcome_class_mechanism_from_ampk() -> None:
    text = "Metformin engages AMPK/mTOR pathways in murine fibroblasts."
    assert detect_outcome_class(text) == "mechanism"


def test_outcome_class_falls_back_when_no_keyword_match() -> None:
    """No keyword from any class → falls back to the explicit fallback."""
    text = "Some random sentence with no clinical-outcome marker."
    assert detect_outcome_class(text, fallback="other") == "other"


def test_outcome_class_priority_muscle_over_mechanism() -> None:
    """When both muscle_function and mechanism keywords appear, the
    more-specific clinical outcome (muscle_function) wins because
    it's listed first. This is the load-bearing decision for MASTERS-
    style abstracts that mention both hypertrophy AND AMPK."""
    text = "Metformin blunts muscle hypertrophy AND engages AMPK signaling."
    assert detect_outcome_class(text) == "muscle_function"


# ============================================================
# detect_effect_direction — verb + p-value heuristic
# ============================================================


def test_effect_direction_negative_from_blunted() -> None:
    text = "Metformin blunted hypertrophy gains during PRT."
    assert detect_effect_direction(text) == "negative"


def test_effect_direction_negative_from_attenuated() -> None:
    text = "Metformin attenuated VO2max gains by approximately 50%."
    assert detect_effect_direction(text) == "negative"


def test_effect_direction_positive_from_improved() -> None:
    text = "Lean tissue mass improved significantly for women on rapamycin."
    assert detect_effect_direction(text) == "positive"


def test_effect_direction_null_from_did_not_improve() -> None:
    text = "Metformin did not improve 4-m walk speed."
    assert detect_effect_direction(text) == "null"


def test_effect_direction_null_from_p_value_when_no_verb() -> None:
    """Pure p-value-based fallback when no verb signal."""
    text = "The cohort showed change in outcome."
    assert detect_effect_direction(text, p_values=("p=0.08",)) == "null"


def test_effect_direction_unclear_for_mechanism_outcome() -> None:
    """Rule 1 priority: mechanism outcomes always return unclear."""
    text = "Metformin blunted AMPK activation in vitro."
    assert detect_effect_direction(text, outcome_class="mechanism") == "unclear"


def test_effect_direction_unclear_when_no_signal() -> None:
    text = "Some neutral sentence about the drug."
    assert detect_effect_direction(text) == "unclear"


# ============================================================
# build_tension_matrix — discriminating test cases
# ============================================================


def test_tension_orthogonal_when_outcome_classes_differ() -> None:
    """MASTERS (muscle) vs MET-PREVENT (frailty): different outcome
    classes → orthogonal regardless of effect direction."""
    masters = _summary("masters", outcome="muscle_function", direction="negative")
    metprevent = _summary("met-prevent", outcome="frailty", direction="null")
    matrix = build_tension_matrix([masters, metprevent])
    assert len(matrix.pairs) == 1
    assert matrix.pairs[0].kind == "orthogonal"
    assert matrix.pairs[0].severity == 0


def test_tension_agreement_when_same_outcome_same_signed_direction() -> None:
    """Two RCTs both showing metformin blunting muscle outcome →
    agreement (severity 2). This is the load-bearing case where
    multiple sources REINFORCE each other rather than conflicting."""
    masters = _summary("masters", outcome="muscle_function", direction="negative")
    masters_repl = _summary(
        "masters-replication", outcome="muscle_function", direction="negative",
    )
    matrix = build_tension_matrix([masters, masters_repl])
    assert len(matrix.pairs) == 1
    pair = matrix.pairs[0]
    assert pair.kind == "agreement"
    assert pair.receipt_a_id == "masters"  # canonical ordering
    assert pair.receipt_b_id == "masters-replication"


def test_tension_disagreement_when_signs_oppose_on_same_outcome() -> None:
    """Hypothetical: one trial shows metformin improves muscle,
    another shows it blunts. Same outcome, opposite signs → disagreement
    (severity 5, the strongest)."""
    pos = _summary("positive-trial", outcome="muscle_function", direction="positive")
    neg = _summary("negative-trial", outcome="muscle_function", direction="negative")
    matrix = build_tension_matrix([pos, neg])
    assert len(matrix.pairs) == 1
    pair = matrix.pairs[0]
    assert pair.kind == "disagreement"
    assert pair.severity == 5


def test_tension_null_vs_positive_when_one_null_one_signed() -> None:
    """MET-PREVENT (null walk speed) and a hypothetical positive-frailty
    trial → null_vs_positive (severity 4)."""
    null_t = _summary("null-trial", outcome="frailty", direction="null")
    pos_t = _summary("positive-frailty", outcome="frailty", direction="positive")
    matrix = build_tension_matrix([null_t, pos_t])
    assert len(matrix.pairs) == 1
    assert matrix.pairs[0].kind == "null_vs_positive"
    assert matrix.pairs[0].severity == 4


def test_tension_indirectness_gap_when_direct_meets_mechanistic() -> None:
    """MASTERS (direct A1, muscle, negative) and a synthetic mechanism-
    of-muscle receipt (mechanistic, unclear) → indirectness_gap. This
    is the case where synthesis MUST keep direct trial findings
    separate from mechanistic claims about the same biology."""
    direct_t = _summary(
        "masters", outcome="muscle_function",
        direction="negative", directness="direct",
    )
    mech_t = _summary(
        "muscle-mechanism", outcome="muscle_function",
        direction="unclear", directness="mechanistic",
    )
    matrix = build_tension_matrix([direct_t, mech_t])
    assert len(matrix.pairs) == 1
    pair = matrix.pairs[0]
    assert pair.kind == "indirectness_gap"
    assert pair.severity == 3


def test_tension_orthogonal_when_both_unclear() -> None:
    """Two mechanism-only receipts, both unclear direction → orthogonal
    (no useful tension to surface in synthesis prose)."""
    a = _summary("mech-a", outcome="mechanism", direction="unclear", directness="mechanistic")
    b = _summary("mech-b", outcome="mechanism", direction="unclear", directness="mechanistic")
    matrix = build_tension_matrix([a, b])
    assert matrix.pairs[0].kind == "orthogonal"


# ============================================================
# Canonical pair ordering
# ============================================================


def test_pairs_are_canonically_ordered_regardless_of_input_order() -> None:
    """Whether you pass [b, a] or [a, b], the resulting pair is
    (a, b) with a < b — so the matrix doesn't double-count and
    downstream invariants pass."""
    a = _summary("alpha")
    b = _summary("beta")
    matrix1 = build_tension_matrix([b, a])  # reversed
    matrix2 = build_tension_matrix([a, b])
    assert matrix1.pairs == matrix2.pairs
    assert matrix1.pairs[0].receipt_a_id == "alpha"
    assert matrix1.pairs[0].receipt_b_id == "beta"


def test_empty_corpus_returns_empty_pairs() -> None:
    matrix = build_tension_matrix([])
    assert matrix.pairs == ()
    assert matrix.receipts == ()


def test_single_receipt_returns_no_pairs() -> None:
    matrix = build_tension_matrix([_summary("solo")])
    assert matrix.pairs == ()
    assert len(matrix.receipts) == 1


def test_n_choose_2_pairs_for_corpus_of_n() -> None:
    """7 receipts → 21 pairs. The synthesis layer must handle the
    full pairwise matrix without quadratic blowup at N=7."""
    receipts = [_summary(f"r-{i:02d}") for i in range(7)]
    matrix = build_tension_matrix(receipts)
    assert len(matrix.pairs) == 21  # C(7,2)


# ============================================================
# Metformin reference-corpus integration test (the load-bearing case)
# ============================================================


def test_metformin_reference_corpus_tension_signals() -> None:
    """The discriminating integration test: build the 5 reference-paper
    receipts as ReceiptSummary objects and verify the tension matrix
    produces the right kinds of conflicts/agreements/orthogonal pairs.

    Five receipts (subset of the 7-paper corpus that have signed
    direction):
      - MASTERS (Walton 2019)        — muscle, direct A1, negative
      - Konopka 2019                  — cardiometabolic, direct A1, negative
      - MET-PREVENT (Witham 2025)     — frailty, direct A1, null
      - MILES (Kulkarni 2018)         — mechanism, mechanistic, unclear
      - Mohammed 2021 (review)        — mechanism, indirect, unclear
    """
    masters = _summary(
        "masters", outcome="muscle_function",
        direction="negative", directness="direct",
    )
    konopka = _summary(
        "konopka", outcome="cardiometabolic",
        direction="negative", directness="direct",
    )
    met_prevent = _summary(
        "met-prevent", outcome="frailty",
        direction="null", directness="direct",
    )
    miles = _summary(
        "miles", outcome="mechanism",
        direction="unclear", directness="mechanistic",
    )
    mohammed = _summary(
        "mohammed", outcome="mechanism",
        direction="unclear", directness="indirect",
    )
    matrix = build_tension_matrix([masters, konopka, met_prevent, miles, mohammed])

    pairs = {(p.receipt_a_id, p.receipt_b_id): p for p in matrix.pairs}
    assert len(pairs) == 10  # C(5, 2)

    # Cross-outcome pairs are orthogonal — different outcome classes.
    # MASTERS (muscle) vs Konopka (cardiometabolic) is one of them.
    assert pairs[("konopka", "masters")].kind == "orthogonal"
    assert pairs[("masters", "met-prevent")].kind == "orthogonal"
    assert pairs[("masters", "miles")].kind == "orthogonal"
    assert pairs[("masters", "mohammed")].kind == "orthogonal"
    assert pairs[("konopka", "met-prevent")].kind == "orthogonal"

    # The two mechanism receipts share outcome class → orthogonal
    # (both unclear direction, no useful tension to surface).
    assert pairs[("miles", "mohammed")].kind == "orthogonal"


def test_metformin_corpus_with_intra_outcome_replication_yields_agreement() -> None:
    """Add a second muscle-function direct receipt (hypothetical
    MASTERS-replication) — the matrix must surface the agreement
    between MASTERS and the replication, while keeping cross-outcome
    pairs orthogonal."""
    masters = _summary(
        "masters", outcome="muscle_function",
        direction="negative", directness="direct",
    )
    masters_repl = _summary(
        "masters-replication", outcome="muscle_function",
        direction="negative", directness="direct",
    )
    konopka = _summary(
        "konopka", outcome="cardiometabolic",
        direction="negative", directness="direct",
    )
    matrix = build_tension_matrix([masters, masters_repl, konopka])

    pairs = {(p.receipt_a_id, p.receipt_b_id): p for p in matrix.pairs}
    # Both muscle papers agree
    assert pairs[("masters", "masters-replication")].kind == "agreement"
    # Cross-outcome pairs are orthogonal
    assert pairs[("konopka", "masters")].kind == "orthogonal"
    assert pairs[("konopka", "masters-replication")].kind == "orthogonal"

    # non_orthogonal() helper surfaces only the meaningful tensions
    non_orth = matrix.non_orthogonal()
    assert len(non_orth) == 1
    assert non_orth[0].kind == "agreement"


# ============================================================
# build_receipt_summary — claim-graph + spar_review parsing
# ============================================================


def test_build_receipt_summary_extracts_thesis_and_outcome_class() -> None:
    """Given a parsed claim_graph.json + spar_review.json shape, the
    summary captures the thesis text, derives outcome_class from the
    claim text, and pulls the SPAR verdict."""
    claim_graph = {
        "claims": [
            {
                "claim_id": "C001",
                "text": "Metformin blunts muscle hypertrophy in older adults",
                "claim_type": "efficacy",
                "supporting_refs": [1],
                "directness": "direct",
                "evidence_tier": "A1",
                "confidence": "high",
            },
        ],
        "thesis_claim_id": "C001",
        "edges": [],
    }
    spar_review = {"verdict": "accept_clean"}
    items = {
        1: {
            "source": {"ref": 1, "nct": "NCT02308228", "title": "MASTERS"},
            "abstract": "Older adults aged 65-85 in a PRT trial...",
        },
    }
    summary = build_receipt_summary(
        receipt_id="r-test",
        receipt_path="runs/r-test",
        topic="metformin",
        claim_graph=claim_graph,
        items_by_ref=items,
        spar_review=spar_review,
    )
    assert summary.thesis_text.startswith("Metformin blunts")
    assert summary.outcome_class == "muscle_function"
    assert summary.effect_direction == "negative"  # blunts → negative
    assert summary.evidence_tier == "A1"
    assert summary.directness == "direct"
    assert summary.spar_verdict == "accept_clean"
    assert summary.canonical_trial_id == "NCT02308228"
    assert summary.n_claims == 1


# ============================================================
# Day 10.7: unique_evidence_key + dedupe_receipts
# ============================================================


def test_unique_evidence_key_collapses_same_trial_same_thesis() -> None:
    """Two receipts with the same canonical_trial_id and same thesis
    text are duplicates regardless of receipt_id / submission timestamp."""
    a = _summary("run-1")
    b = _summary("run-2")  # different receipt_id, but same trial + thesis
    # Both default to canonical_trial_id="NCT-test", thesis_text="thesis text for {rid}"
    # The thesis_text differs by rid... let me pin them to be identical.
    a = ReceiptSummary(
        receipt_id="run-1", receipt_path="runs/run-1",
        topic="metformin", thesis_text="metformin blunts hypertrophy",
        spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
        canonical_trial_id="NCT02308228", evidence_tier="A1",
        directness="direct", outcome_class="muscle_function",
        effect_direction="negative", p_values=(),
        population_summary="older adults",
    )
    b = ReceiptSummary(
        receipt_id="run-2", receipt_path="runs/run-2",
        topic="metformin", thesis_text="metformin blunts hypertrophy",
        spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
        canonical_trial_id="NCT02308228", evidence_tier="A1",
        directness="direct", outcome_class="muscle_function",
        effect_direction="negative", p_values=(),
        population_summary="older adults",
    )
    assert unique_evidence_key(a) == unique_evidence_key(b)


def test_unique_evidence_key_distinct_for_different_trials() -> None:
    """Different canonical_trial_id → different keys, even with same thesis."""
    a = ReceiptSummary(
        receipt_id="run-1", receipt_path="x", topic="metformin",
        thesis_text="same thesis", spar_verdict="accept_clean",
        n_claims=4, n_failed_traces=0, canonical_trial_id="NCT02308228",
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=(), population_summary="",
    )
    b = ReceiptSummary(
        receipt_id="run-2", receipt_path="x", topic="metformin",
        thesis_text="same thesis", spar_verdict="accept_clean",
        n_claims=4, n_failed_traces=0, canonical_trial_id="NCT04264897",
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=(), population_summary="",
    )
    assert unique_evidence_key(a) != unique_evidence_key(b)


def test_dedupe_receipts_collapses_12_runs_of_one_trial_to_one() -> None:
    """Day 10.7 reviewer P1: 12 metformin receipts all anchored on
    MASTERS NCT02308228 with the same thesis text must dedupe to 1.
    This was the false-positive scenario the reviewer flagged."""
    receipts = [
        ReceiptSummary(
            receipt_id=f"run-{i:02d}", receipt_path=f"runs/run-{i:02d}",
            topic="metformin", thesis_text="metformin blunts hypertrophy",
            spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
            canonical_trial_id="NCT02308228",
            evidence_tier="A1", directness="direct",
            outcome_class="muscle_function", effect_direction="negative",
            p_values=(), population_summary="",
        )
        for i in range(12)
    ]
    deduped = dedupe_receipts(receipts)
    assert len(deduped) == 1
    assert deduped[0].receipt_id == "run-00"  # first-seen wins


def test_dedupe_receipts_keeps_distinct_trials() -> None:
    """3 different canonical trials → 3 unique keys → 3 surviving receipts."""
    receipts = [
        ReceiptSummary(
            receipt_id=f"run-{trial_id}", receipt_path="x", topic="metformin",
            thesis_text=f"thesis for {trial_id}",
            spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
            canonical_trial_id=trial_id, evidence_tier="A1",
            directness="direct", outcome_class="muscle_function",
            effect_direction="negative", p_values=(), population_summary="",
        )
        for trial_id in ("NCT02308228", "NCT04264897", "NCT01765946")
    ]
    deduped = dedupe_receipts(receipts)
    assert len(deduped) == 3


def test_min_unique_trials_for_synthesis_is_three() -> None:
    """The threshold below which synthesis isn't honest. Pinned for
    visibility — changing it requires a DECISIONS.md entry."""
    assert MIN_UNIQUE_TRIALS_FOR_SYNTHESIS == 3


def test_build_receipt_summary_pulls_p_values_from_thesis() -> None:
    """p-values should be canonicalized from the thesis text into the
    `p_values` tuple — the synthesis writer uses these for borderline-p
    hedging compliance (Q1 in the audit checklist)."""
    claim_graph = {
        "claims": [
            {
                "claim_id": "C001",
                "text": "VO2max attenuated p=0.08 with metformin",
                "claim_type": "efficacy",
                "supporting_refs": [1],
                "directness": "direct",
                "evidence_tier": "A1",
                "confidence": "high",
            },
        ],
        "thesis_claim_id": "C001",
        "edges": [],
    }
    summary = build_receipt_summary(
        receipt_id="r-konopka",
        receipt_path="runs/r-konopka",
        topic="metformin",
        claim_graph=claim_graph,
        items_by_ref={1: {"source": {"ref": 1}, "abstract": ""}},
        spar_review={"verdict": "accept_caveated"},
    )
    assert "p=0.08" in summary.p_values
    # p≥0.05 with no signed verb → null
    # ("attenuated" IS a negative verb, so this comes back as negative,
    # which is correct for Konopka's framing)
    assert summary.effect_direction == "negative"
