"""Edge-case stress tests across the Phase 3/4/5/7/8 planning primitives.

Covers: unicode in identifiers, very large weights, NaN propagation,
near-zero SE numerical stability, boundary sample sizes, and surface-
escape interactions in the markdown renderers.

These are NOT replacements for the per-module test files — they are
adversarial probes targeting numerical and encoding edge cases the
per-module tests don't have to cover individually.
"""
from __future__ import annotations

import math

import pytest

from agent.effect_normalizer import RawBinary, RawContinuous, normalize_md
from agent.field_engagement import evaluate_engagement
from agent.final_gate import GateInputs, evaluate_final_gate
from agent.grade_schema import (
    DowngradeAdjustment,
    GradeAssessment,
)
from agent.meta_analysis import (
    EffectRow,
    pool_fixed_effect,
    pool_random_effects,
)
from agent.risk_of_bias_schema import (
    ROB2_DOMAINS,
    DomainAssessment,
    StudyAssessment,
)
from agent.template_language import detect_template_language
from agent.tension_elaboration import TensionRecord, build_plan
from scripts.render_quality_tables import render_grade_table, render_rob_table


# ---- Unicode in identifiers -----------------------------------------------


def test_unicode_study_id_in_meta_analysis() -> None:
    rows = [
        EffectRow("López-Otín 2023", 0.1, 0.05, 100, "MD"),
        EffectRow("Mañé 2024", 0.2, 0.05, 100, "MD"),
        EffectRow("北京 2025", 0.15, 0.05, 100, "MD"),
    ]
    r = pool_fixed_effect(rows)
    assert r.n_studies == 3
    assert r.metric == "MD"


def test_unicode_in_field_engagement_anchors() -> None:
    receipts = [
        {"receipt_id": "X", "citation_token": "López-Otín 2023",
         "outcome_class": "hallmarks", "effect_direction": "supports"},
    ]
    results = evaluate_engagement(receipts=receipts)
    by_name = {e.framework_name: e for e in results}
    assert by_name["Lopez-Otin"].status == "support"


def test_unicode_in_tension_paper_ids() -> None:
    r = TensionRecord(
        tension_id="T-é", paper_a="Mañé 2024", paper_b="北京 2025",
        conflict_type="disagreement", outcome_class="cardiometabolic",
        severity=4,
    )
    plan = build_plan(r)
    assert plan.paper_a == "Mañé 2024"
    assert plan.paper_b == "北京 2025"


def test_unicode_in_outcome_class_grade() -> None:
    g = GradeAssessment("免疫功能", "high",
        downgrades=(DowngradeAdjustment("rob", 1),))
    md = render_grade_table([g])
    assert "免疫功能" in md
    assert g.final_certainty == "moderate"


def test_unicode_in_rob_study_id() -> None:
    s = StudyAssessment(
        "Mannick 2018 — PIE",  # em-dash
        "rct", "rob2",
        tuple(DomainAssessment(d, "low") for d in ROB2_DOMAINS),
        "low",
    )
    md = render_rob_table([s])
    assert "Mannick 2018 — PIE" in md


# ---- Numerical stability: near-zero SE -------------------------------------


def test_meta_analysis_handles_near_zero_se_without_overflow() -> None:
    """SE of 1e-10 → weight 1e20. Pool weight sum stays finite."""
    rows = [
        EffectRow("a", 0.5, 1e-10, 100, "MD"),
        EffectRow("b", 0.50001, 1e-10, 100, "MD"),
        EffectRow("c", 0.50002, 1e-10, 100, "MD"),
    ]
    r = pool_fixed_effect(rows)
    assert math.isfinite(r.pooled_effect)
    assert math.isfinite(r.pooled_se)
    assert r.pooled_effect == pytest.approx(0.50001, abs=1e-3)


def test_effect_normalizer_rejects_zero_se_at_construction() -> None:
    """Truly zero SE must fail closed (not silently divide-by-zero)."""
    with pytest.raises(ValueError):
        EffectRow("a", 0.5, 0.0, 100, "MD")


def test_effect_normalizer_rejects_subnormal_negative_se() -> None:
    with pytest.raises(ValueError):
        EffectRow("a", 0.5, -1e-300, 100, "MD")


# ---- Numerical stability: very large weights / values ---------------------


def test_meta_analysis_handles_large_effects() -> None:
    """Effects up to 1e6 with proportional SE — pool stays finite."""
    rows = [
        EffectRow("a", 1e6, 1e3, 100, "MD"),
        EffectRow("b", 1.0001e6, 1e3, 100, "MD"),
        EffectRow("c", 0.9999e6, 1e3, 100, "MD"),
    ]
    r = pool_random_effects(rows)
    assert math.isfinite(r.pooled_effect)
    assert math.isfinite(r.tau_squared)


def test_tension_handles_large_weights() -> None:
    r = TensionRecord(
        tension_id="t", paper_a="A", paper_b="B",
        conflict_type="disagreement", outcome_class="x", severity=3,
        weight_a=1e9, weight_b=1.0,
    )
    plan = build_plan(r)
    assert plan.corpus_weight_winner == "A"


# ---- NaN propagation -------------------------------------------------------


def test_effect_row_rejects_nan_at_construction() -> None:
    with pytest.raises(ValueError):
        EffectRow("a", float("nan"), 0.1, 100, "MD")


def test_raw_continuous_rejects_inf_sd() -> None:
    with pytest.raises(ValueError):
        RawContinuous("S", 5.0, float("inf"), 30, 3.0, 1.0, 30)


def test_meta_analysis_zero_heterogeneity_yields_zero_tau_zero_q() -> None:
    """Homogeneous pool: Q=0, I²=0, τ²=0, RE=FE."""
    rows = [EffectRow(f"s{i}", 0.5, 0.1, 100, "MD") for i in range(5)]
    fe = pool_fixed_effect(rows)
    re = pool_random_effects(rows)
    assert fe.q == pytest.approx(0.0)
    assert fe.i_squared == pytest.approx(0.0)
    assert re.tau_squared == pytest.approx(0.0)
    assert fe.pooled_effect == pytest.approx(re.pooled_effect)


# ---- Boundary sample sizes -------------------------------------------------


def test_exactly_min_studies_works() -> None:
    """3 studies (the floor) should pool without error."""
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.2, 0.1, 100, "MD"),
        EffectRow("c", 0.15, 0.1, 100, "MD"),
    ]
    pool_fixed_effect(rows)
    pool_random_effects(rows)


def test_one_below_min_studies_fails() -> None:
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.2, 0.1, 100, "MD"),
    ]
    with pytest.raises(ValueError):
        pool_fixed_effect(rows)


def test_normalize_md_with_n_eq_1() -> None:
    """n=1 per arm: legitimate but extreme; SE explodes but stays finite."""
    r = normalize_md(RawContinuous("S", 5.0, 2.0, 1, 3.0, 2.0, 1))
    assert math.isfinite(r.se)
    assert r.n == 2


def test_log_rr_one_event_each_arm_smallest_meaningful_pool() -> None:
    """The smallest non-degenerate binary case."""
    raw = RawBinary("S", 1, 100, 1, 100)
    from agent.effect_normalizer import normalize_log_rr
    r = normalize_log_rr(raw)
    assert math.isfinite(r.effect)
    assert math.isfinite(r.se)


# ---- Template-language detector against unicode + long content -----------


def test_template_detector_handles_unicode_prose() -> None:
    """Unicode characters must not break the regex scanner or sentence split."""
    text = (
        "The PEARL trial reported null findings — including in older adults.\n"
        "It is clear that further work in 北京 cohorts is needed.\n"
    )
    hits = detect_template_language(text)
    # Should still detect the "It is clear that" P1 hit.
    assert any(h.severity == "P1" for h in hits)


def test_template_detector_handles_long_single_line_paragraphs() -> None:
    long_para = " ".join(["The trial showed effects."] * 200)
    hits = detect_template_language(long_para + " More studies are needed.")
    assert any(h.category == "generic_research_cliche" for h in hits)


def test_template_detector_no_false_positive_in_specific_recommendation() -> None:
    text = "Trials should measure HbA1c at 12 months in 200 adults aged 65+."
    assert detect_template_language(text) == []


# ---- Final gate boundary conditions ---------------------------------------


def test_final_gate_at_threshold_boundaries() -> None:
    """Exactly at threshold passes; one ulp below fails."""
    pass_inputs = GateInputs(
        numeric_coverage=1.0, citation_registry_complete=True,
        rob_coverage=0.8, grade_coverage=1.0,
        n_tensions=1, n_receipts=10, template_language_blocking=False,
    )
    assert evaluate_final_gate(pass_inputs).passed
    fail_inputs = GateInputs(
        numeric_coverage=1.0, citation_registry_complete=True,
        rob_coverage=0.7999999999, grade_coverage=1.0,
        n_tensions=1, n_receipts=10, template_language_blocking=False,
    )
    assert not evaluate_final_gate(fail_inputs).passed


# ---- Pipe-escape in markdown table renderers ------------------------------


def test_grade_table_escapes_pipe_in_outcome_name() -> None:
    g = GradeAssessment("immune | function", "high")
    md = render_grade_table([g])
    assert "immune \\| function" in md


def test_rob_table_escapes_pipe_in_study_id() -> None:
    s = StudyAssessment(
        "study|with|pipe", "rct", "rob2",
        tuple(DomainAssessment(d, "low") for d in ROB2_DOMAINS),
        "low",
    )
    md = render_rob_table([s])
    assert "study\\|with\\|pipe" in md
