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

from dataclasses import replace

from agent.synthesis import (
    MIN_UNIQUE_TRIALS_FOR_SYNTHESIS,
    _detect_population_summary,
    build_receipt_summary,
    build_tension_matrix,
    count_unique_trials,
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
    endpoints: tuple[str, ...] | None = None,
    endpoint_directions: tuple[tuple[str, EffectDirection], ...] | None = None,
) -> ReceiptSummary:
    endpoints = endpoints if endpoints is not None else (outcome.replace("_", " "),)
    endpoint_directions = (
        endpoint_directions
        if endpoint_directions is not None
        else ((endpoints[0], direction),) if endpoints else ()
    )
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
        endpoints=endpoints,
        endpoint_directions=endpoint_directions,
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
# _detect_population_summary — Day 10.17a tier-gated extraction
# ============================================================
# Bug found in 10.16i empirical: the regex set matched any abstract
# mentioning "type 2 diabetes" anywhere, including model-organism
# longevity reviews and untrialed mechanistic studies that mention
# T2D only as background context. The Limitations section then said
# "all studies focused on T2D" which was factually wrong for c04
# (longevity review) and c05 (mechanistic, no trial).
#
# Day 10.17a fix: gate the regex extraction by directness. Only
# direct clinical RCT receipts (where a population was actually
# enrolled and studied) get text-mined for population. Mechanistic /
# indirect receipts return "" so downstream prose can hedge honestly
# instead of inheriting a clinical label they don't deserve.


def test_population_summary_extracts_from_direct_receipt_abstract() -> None:
    """Direct receipt with abstract describing 'older adults' →
    population_summary captures that span. The regex returns the
    FIRST canonical pattern match (one of: 'older adults', 'aged X-Y',
    'postmenopausal', etc.) — not concatenated spans."""
    items = {
        1: {"abstract": "Trial enrolled older adults aged 65 with sarcopenia."},
    }
    out = _detect_population_summary(
        thesis_text="metformin blunts hypertrophy",
        items_by_ref=items,
        directness="direct",
    )
    assert "older adults" in out.lower(), (
        f"expected 'older adults' span; got {out!r}"
    )


def test_population_summary_does_not_inherit_clinical_label_for_mechanistic() -> None:
    """Mechanistic receipt whose abstract mentions T2D as context
    → returns "" (NOT 'type 2'). This is the load-bearing fix for
    the c04/c05 bug from 10.16i."""
    items = {
        1: {"abstract": (
            "Metformin, a first-line drug for type 2 diabetes, has been "
            "explored as a geroprotective intervention. We review the "
            "preclinical longevity literature in C. elegans and mice."
        )},
    }
    out = _detect_population_summary(
        thesis_text=(
            "Metformin shows lifespan extension in model organisms via "
            "mitochondrial mechanisms."
        ),
        items_by_ref=items,
        directness="mechanistic",
    )
    assert out == "", (
        f"mechanistic receipt should not inherit clinical population from "
        f"contextual T2D mention; got {out!r}"
    )


def test_population_summary_returns_empty_for_indirect_receipt() -> None:
    """Indirect (review/meta) receipt that mentions populations in
    cited studies should not inherit them as its own population."""
    items = {
        1: {"abstract": "Review of trials in postmenopausal type 2 diabetes patients."},
    }
    out = _detect_population_summary(
        thesis_text="systematic review of metformin trials",
        items_by_ref=items,
        directness="indirect",
    )
    assert out == "", (
        "indirect-evidence receipt should not adopt populations from cited trials"
    )


def test_population_summary_empty_when_direct_but_no_pattern_match() -> None:
    """Direct receipt with abstract that has no canonical population
    pattern → empty string (existing behavior preserved)."""
    items = {
        1: {"abstract": "Generic prose with no canonical population marker."},
    }
    out = _detect_population_summary(
        thesis_text="metformin study",
        items_by_ref=items,
        directness="direct",
    )
    assert out == ""


def test_population_summary_fails_closed_on_empty_directness() -> None:
    """Defensive: a malformed claim graph with directness="" must not
    re-introduce the bug. The default kwarg is "indirect" so any future
    caller that forgets to pass directness also fails closed."""
    items = {
        1: {"abstract": "Trial enrolled older adults aged 65 with T2D."},
    }
    assert _detect_population_summary(
        thesis_text="metformin study", items_by_ref=items, directness="",
    ) == ""
    # Default-kwarg path: caller forgot directness — must fail closed.
    assert _detect_population_summary(
        thesis_text="metformin study", items_by_ref=items,
    ) == ""


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


def test_tension_null_vs_negative_when_signed_arm_negative() -> None:
    """#5: a null arm vs a NEGATIVE signed arm must label as
    null_vs_negative (not null_vs_positive) so the public label matches the
    signed arm's true direction. Same severity (4) as null_vs_positive."""
    null_t = _summary("null-trial", outcome="frailty", direction="null")
    neg_t = _summary("negative-frailty", outcome="frailty", direction="negative")
    matrix = build_tension_matrix([null_t, neg_t])
    assert len(matrix.pairs) == 1
    assert matrix.pairs[0].kind == "null_vs_negative"
    assert matrix.pairs[0].severity == 4
    assert "negative" in matrix.pairs[0].summary


def test_directional_tension_requires_an_exact_shared_endpoint() -> None:
    null_t = _summary(
        "null-trial", outcome="cardiometabolic", direction="null",
        endpoints=("blood pressure",),
        endpoint_directions=(("blood pressure", "null"),),
    )
    pos_t = _summary(
        "positive-trial", outcome="cardiometabolic", direction="positive",
        endpoints=("ldl cholesterol",),
        endpoint_directions=(("ldl cholesterol", "positive"),),
    )
    empty_t = _summary(
        "empty-trial", outcome="cardiometabolic", direction="positive",
        endpoints=(), endpoint_directions=(),
    )

    assert build_tension_matrix([null_t, pos_t]).pairs[0].kind == "orthogonal"
    assert build_tension_matrix([null_t, empty_t]).pairs[0].kind == "orthogonal"


def test_multi_endpoint_rollups_cannot_manufacture_a_conflict() -> None:
    aggregate_positive = _summary(
        "aggregate-positive", outcome="cardiometabolic", direction="positive",
        endpoints=("ldl cholesterol", "blood pressure"),
        endpoint_directions=(
            ("ldl cholesterol", "positive"),
            ("blood pressure", "positive"),
        ),
    )
    aggregate_negative = _summary(
        "aggregate-negative", outcome="cardiometabolic", direction="negative",
        endpoints=("ldl cholesterol", "heart rate"),
        endpoint_directions=(
            ("ldl cholesterol", "positive"),
            ("heart rate", "negative"),
        ),
    )

    pair = build_tension_matrix([aggregate_positive, aggregate_negative]).pairs[0]
    assert pair.kind == "agreement"
    assert pair.endpoint == "ldl cholesterol"
    assert "ldl cholesterol" in pair.summary


def test_shared_endpoint_direction_drives_the_tension_kind() -> None:
    null_t = _summary(
        "null-trial", outcome="cardiometabolic", direction="mixed",
        endpoints=("ldl cholesterol", "blood pressure"),
        endpoint_directions=(
            ("ldl cholesterol", "null"),
            ("blood pressure", "positive"),
        ),
    )
    pos_t = _summary(
        "positive-trial", outcome="cardiometabolic", direction="mixed",
        endpoints=("ldl cholesterol", "heart rate"),
        endpoint_directions=(
            ("ldl cholesterol", "positive"),
            ("heart rate", "negative"),
        ),
    )

    pair = build_tension_matrix([null_t, pos_t]).pairs[0]
    assert pair.kind == "null_vs_positive"
    assert pair.endpoint == "ldl cholesterol"


def test_tension_orthogonal_for_non_opposable_directions() -> None:
    """A pair only conflicts when its directions are genuinely opposed. Pairs
    where neither side asserts an opposable direction (unclear/mixed, both
    mixed, null/mixed, both unclear) stay orthogonal — they do NOT inflate the
    tension count. Locks the seam a reviewer flagged as manufacturing tensions."""
    combos: tuple[tuple[EffectDirection, EffectDirection], ...] = (
        ("unclear", "mixed"), ("mixed", "mixed"),
        ("null", "mixed"), ("unclear", "unclear"),
    )
    for da, db in combos:
        a = _summary(f"a-{da}-{db}", outcome="muscle_function", direction=da)
        b = _summary(f"b-{da}-{db}", outcome="muscle_function", direction=db)
        matrix = build_tension_matrix([a, b])
        assert matrix.pairs[0].kind == "orthogonal", f"{da} vs {db}"


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


def test_tension_mechanism_vs_clinical_for_direct_vs_review_cross_outcome() -> None:
    """Regression (Fix #1): a direct trial vs a review-tier source on a
    DIFFERENT outcome is a cross-domain mechanism_vs_clinical tension. The
    retired duplicate classifier in run_v06 only recognised
    directness=='mechanistic' here, so it mislabelled direct-vs-review and
    direct-vs-indirect pairs orthogonal and inflated the published
    non-orthogonal count (~2.6x) vs this canonical classifier — now the single
    source feeding the manifest count, review-type routing, and audit replay."""
    direct_t = _summary(
        "trial", outcome="muscle_function", direction="positive", directness="direct",
    )
    review_t = _summary(
        "review", outcome="frailty", direction="mixed", directness="review",
    )
    matrix = build_tension_matrix([direct_t, review_t])
    assert len(matrix.pairs) == 1
    assert matrix.pairs[0].kind == "mechanism_vs_clinical"


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

    # Cross-outcome pairs where BOTH are direct → orthogonal
    # (different clinical outcomes, no cross-domain trust hazard).
    assert pairs[("konopka", "masters")].kind == "orthogonal"
    assert pairs[("masters", "met-prevent")].kind == "orthogonal"
    assert pairs[("konopka", "met-prevent")].kind == "orthogonal"

    # Day 10.17 Phase 2: cross-outcome pairs where ONE is direct/clinical
    # and the OTHER is mechanistic/indirect now surface as
    # mechanism_vs_clinical — the cross-domain trust hazard the metformin
    # paper hinges on (clinical muscle suppression vs mechanistic /
    # preclinical longevity promise).
    assert pairs[("masters", "miles")].kind == "mechanism_vs_clinical"
    assert pairs[("masters", "mohammed")].kind == "mechanism_vs_clinical"
    assert pairs[("konopka", "miles")].kind == "mechanism_vs_clinical"
    assert pairs[("konopka", "mohammed")].kind == "mechanism_vs_clinical"
    assert pairs[("met-prevent", "miles")].kind == "mechanism_vs_clinical"
    assert pairs[("met-prevent", "mohammed")].kind == "mechanism_vs_clinical"

    # The two mechanism receipts share outcome class → orthogonal
    # (both unclear direction, no useful tension to surface).
    assert pairs[("miles", "mohammed")].kind == "orthogonal"


# ============================================================
# Day 10.17 Phase 2 — mechanism_vs_clinical cross-domain detection
# ============================================================
# All three external reviewers of 10.17a flagged that the tension
# matrix said "no non-orthogonal tensions" while the rendered paper
# argued a clear metabolic-vs-muscle tension. Root cause: the old
# classifier returned "orthogonal" whenever outcome classes differed,
# even when the pair was the cross-domain trust hazard the synthesis
# writer must keep separate (direct clinical evidence on outcome A
# fused with mechanistic / preclinical evidence on outcome B).
# Day 10.17 Phase 2 adds the `mechanism_vs_clinical` kind — same
# severity as `indirectness_gap` (3) since both are direct-vs-
# mechanistic trust hazards, just in the cross-class variant.


def test_mechanism_vs_clinical_fires_on_direct_plus_mechanistic_cross_outcome() -> None:
    """The metformin paper's central tension: c01 (muscle, direct) + c04
    (longevity, mechanistic) — different outcomes, one direct clinical,
    one mechanistic preclinical. Must be flagged, not buried as
    'orthogonal' as the old classifier did."""
    c01 = _summary(
        "c01", outcome="muscle_function", direction="negative",
        directness="direct", tier="A1",
    )
    c04 = _summary(
        "c04", outcome="longevity", direction="unclear",
        directness="mechanistic", tier="C",
    )
    matrix = build_tension_matrix([c01, c04])
    pair = matrix.pairs[0]
    assert pair.kind == "mechanism_vs_clinical"
    assert pair.severity == 3  # same as indirectness_gap
    assert "cross-domain" in pair.summary
    assert pair in matrix.non_orthogonal()


def test_mechanism_vs_clinical_also_fires_on_indirect_directness() -> None:
    """`indirect` directness counts the same as `mechanistic` — both are
    non-clinical evidence types that must not be fused with direct
    findings on a different outcome."""
    a = _summary(
        "direct-A", outcome="muscle_function", direction="negative",
        directness="direct",
    )
    b = _summary(
        "indirect-B", outcome="longevity", direction="unclear",
        directness="indirect",
    )
    matrix = build_tension_matrix([a, b])
    assert matrix.pairs[0].kind == "mechanism_vs_clinical"


def test_mechanism_vs_clinical_does_not_fire_when_both_direct_cross_outcome() -> None:
    """Two direct A1 trials on different outcomes are still orthogonal
    — they're both clinical, just on different endpoints. No cross-
    domain trust hazard."""
    a = _summary(
        "a", outcome="muscle_function", direction="negative",
        directness="direct",
    )
    b = _summary(
        "b", outcome="cardiometabolic", direction="negative",
        directness="direct",
    )
    matrix = build_tension_matrix([a, b])
    assert matrix.pairs[0].kind == "orthogonal"


def test_mechanism_vs_clinical_does_not_fire_when_both_mechanistic_cross_outcome() -> None:
    """Two mechanistic preclinical receipts on different outcomes are
    still orthogonal — both are non-clinical, no direct-vs-mechanistic
    trust hazard."""
    a = _summary(
        "a", outcome="longevity", direction="unclear",
        directness="mechanistic",
    )
    b = _summary(
        "b", outcome="cardiometabolic", direction="unclear",
        directness="mechanistic",
    )
    matrix = build_tension_matrix([a, b])
    assert matrix.pairs[0].kind == "orthogonal"


def test_mechanism_vs_clinical_does_not_steal_from_indirectness_gap() -> None:
    """Same outcome class + direct + mechanistic still goes to
    indirectness_gap, not mechanism_vs_clinical. The cross-class
    variant only fires when outcomes differ."""
    a = _summary(
        "a", outcome="muscle_function", direction="negative",
        directness="direct",
    )
    b = _summary(
        "b", outcome="muscle_function", direction="unclear",
        directness="mechanistic",
    )
    matrix = build_tension_matrix([a, b])
    assert matrix.pairs[0].kind == "indirectness_gap"


def test_mechanism_vs_clinical_uses_fail_closed_predicate() -> None:
    """Day 10.17 Phase 2 reviewer fix: the non-direct side uses
    `not direct` rather than an explicit list. A receipt with
    `directness=""` (or any unknown value) paired with a direct
    cross-outcome receipt must still fire as mechanism_vs_clinical
    — the trust hazard exists regardless of how the non-direct side
    is labeled."""
    direct = _summary(
        "direct-A", outcome="muscle_function", direction="negative",
        directness="direct",
    )
    unknown = _summary(
        "unknown-B", outcome="longevity", direction="unclear",
        directness="",  # malformed / unknown — must still flag
    )
    matrix = build_tension_matrix([direct, unknown])
    assert matrix.pairs[0].kind == "mechanism_vs_clinical"


def test_indirectness_gap_now_includes_indirect_directness() -> None:
    """Day 10.17 Phase 2 reviewer fix: same-outcome direct + indirect
    is now indirectness_gap (was orthogonal). Resolves the asymmetry
    the reviewer flagged — cross-outcome direct+indirect was already
    severity 3, but same-outcome direct+indirect was severity 0."""
    direct = _summary(
        "direct-A", outcome="muscle_function", direction="negative",
        directness="direct",
    )
    indirect = _summary(
        "indirect-B", outcome="muscle_function", direction="unclear",
        directness="indirect",
    )
    matrix = build_tension_matrix([direct, indirect])
    assert matrix.pairs[0].kind == "indirectness_gap"


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
                "endpoint": "muscle hypertrophy",
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
    assert summary.endpoints == ("muscle hypertrophy",)
    assert summary.endpoint_directions == (("muscle hypertrophy", "negative"),)


def test_real_receipt_builder_drives_same_endpoint_tension() -> None:
    def built(receipt_id: str, text: str) -> ReceiptSummary:
        return build_receipt_summary(
            receipt_id=receipt_id,
            receipt_path=f"runs/{receipt_id}",
            topic="intervention",
            claim_graph={
                "claims": [{
                    "claim_id": "C001", "text": text,
                    "endpoint": "systolic blood pressure",
                    "supporting_refs": [1], "directness": "direct",
                    "evidence_tier": "A1",
                }],
                "thesis_claim_id": "C001",
            },
            items_by_ref={1: {"source": {"ref": 1}, "abstract": ""}},
            spar_review={"verdict": "accept_clean"},
        )

    null_receipt = built(
        "null-trial", "No significant difference in systolic blood pressure.",
    )
    positive_receipt = built(
        "positive-trial", "The intervention improved systolic blood pressure.",
    )
    pair = build_tension_matrix([null_receipt, positive_receipt]).pairs[0]
    assert pair.kind == "null_vs_positive"
    assert pair.endpoint == "systolic blood pressure"


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


def test_dedupe_receipts_prefers_registered_copy_without_merging_conflicting_doi() -> None:
    title = "Efficacy and Safety of Liraglutide: A Systematic Review"
    bare = replace(_summary("bare", n_claims=11), source_title=title)
    canonical = replace(
        _summary("canonical", n_claims=45), source_title=title,
        source_doi="10.2147/clep.s391819", source_pmid="36510488",
    )
    alias = replace(
        _summary("alias"), source_title="Abbreviated systematic review title",
        source_doi="10.2147/clep.s391819",
    )
    distinct = replace(
        _summary("distinct"), source_title=title,
        source_doi="10.1000/distinct", source_pmid="9999",
    )

    assert [row.receipt_id for row in dedupe_receipts((bare, alias, canonical, distinct))] == [
        "canonical", "distinct",
    ]


def test_min_unique_trials_for_synthesis_is_three() -> None:
    """The threshold below which synthesis isn't honest. Pinned for
    visibility — changing it requires a DECISIONS.md entry."""
    assert MIN_UNIQUE_TRIALS_FOR_SYNTHESIS == 3


# ============================================================
# Day 10.8a: count_unique_trials — strict cross-source gate
# ============================================================


def test_count_unique_trials_collapses_same_trial_multi_endpoint() -> None:
    """Day 10.8a reviewer P1: three different endpoints from one trial
    dedupe to three different evidence units (different theses) but
    they represent ONE source. count_unique_trials must reflect that
    so the cross-source gate doesn't pass same-trial multi-endpoint
    reporting as if it were synthesis."""
    receipts = tuple(
        ReceiptSummary(
            receipt_id=f"r-{endpoint}", receipt_path="x", topic="metformin",
            thesis_text=f"MASTERS thesis on {endpoint}",
            spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
            canonical_trial_id="NCT02308228",  # all same trial
            evidence_tier="A1", directness="direct",
            outcome_class="muscle_function", effect_direction="negative",
            p_values=(), population_summary="",
        )
        for endpoint in ("lean_body_mass", "thigh_muscle_area", "fiber_type")
    )
    # Different theses → 3 unique evidence keys
    assert len({unique_evidence_key(r) for r in receipts}) == 3
    # But ONE trial — count_unique_trials must reflect that
    assert count_unique_trials(receipts) == 1


def test_count_unique_trials_distinct_trials_count_separately() -> None:
    receipts = tuple(
        ReceiptSummary(
            receipt_id=f"r-{trial}", receipt_path="x", topic="metformin",
            thesis_text="thesis", spar_verdict="accept_clean",
            n_claims=4, n_failed_traces=0,
            canonical_trial_id=trial, evidence_tier="A1",
            directness="direct", outcome_class="muscle_function",
            effect_direction="negative", p_values=(), population_summary="",
        )
        for trial in ("NCT02308228", "NCT04264897", "NCT01765946")
    )
    assert count_unique_trials(receipts) == 3


def test_count_unique_trials_untrialed_receipts_use_thesis_signature() -> None:
    """Receipts without canonical_trial_id contribute via thesis text
    so unsignposted single-source-multiple-restatements don't bypass
    the gate."""
    same_thesis = "metformin blunts hypertrophy"
    receipts = tuple(
        ReceiptSummary(
            receipt_id=f"r-{i}", receipt_path="x", topic="metformin",
            thesis_text=same_thesis,
            spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
            canonical_trial_id=None,  # untrialed
            evidence_tier="A1", directness="direct",
            outcome_class="muscle_function", effect_direction="negative",
            p_values=(), population_summary="",
        )
        for i in range(5)
    )
    # 5 receipts, all untrialed, same thesis → 1 effective "trial"
    assert count_unique_trials(receipts) == 1


def test_count_unique_trials_mixed_trialed_and_untrialed() -> None:
    """Mix of trialed and untrialed receipts should count correctly."""
    receipts = (
        ReceiptSummary(
            receipt_id="r-a", receipt_path="x", topic="metformin",
            thesis_text="A", spar_verdict="accept_clean",
            n_claims=4, n_failed_traces=0,
            canonical_trial_id="NCT-A", evidence_tier="A1",
            directness="direct", outcome_class="muscle_function",
            effect_direction="negative", p_values=(), population_summary="",
        ),
        ReceiptSummary(
            receipt_id="r-b", receipt_path="x", topic="metformin",
            thesis_text="B unique untrialed thesis",
            spar_verdict="accept_clean",
            n_claims=4, n_failed_traces=0,
            canonical_trial_id=None, evidence_tier="A1",
            directness="direct", outcome_class="muscle_function",
            effect_direction="negative", p_values=(), population_summary="",
        ),
    )
    assert count_unique_trials(receipts) == 2


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


def test_classify_pair_null_vs_requires_comparable_strata() -> None:
    """Item 4: a null mechanistic (preclinical) finding vs a signed clinical
    one (same outcome, different strata) is NOT a null_vs disagreement — it
    falls to orthogonal, dissolving the spurious all-vs-one severity-4 cluster.
    Comparable strata (both non-mechanistic) still form a real null_vs."""
    from agent.synthesis import _classify_pair  # noqa: PLC0415
    mech_null = _summary("MECH", direction="null", directness="mechanistic")
    clin_neg = _summary("CLIN", direction="negative", directness="indirect")
    assert _classify_pair(mech_null, clin_neg).kind == "orthogonal"
    # both non-mechanistic → genuine null_vs preserved
    a = _summary("A", direction="null", directness="indirect")
    b = _summary("B", direction="negative", directness="indirect")
    assert _classify_pair(a, b).kind == "null_vs_negative"
