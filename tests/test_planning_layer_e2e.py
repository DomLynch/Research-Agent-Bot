"""End-to-end integration test for the Phase 3-8 planning layer.

Composes framework_section + effect_normalizer + meta_analysis +
forest_plot_svg + quality_methods_bundle + template_gate_adapter +
final_gate_mapper + final_gate on a synthetic 5-receipt corpus. The
tests are the wiring contract for Codex's runner integration.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from agent.effect_normalizer import RawContinuous, normalize_md
from agent.final_gate import GateThresholds, evaluate_final_gate
from agent.final_gate_mapper import build_gate_inputs_from_artifacts
from agent.forest_plot_svg import render_forest_plot_svg
from agent.framework_section import build_framework_section
from agent.meta_analysis import pool_random_effects
from agent.quality_methods_bundle import build_quality_methods_bundle
from agent.risk_of_bias_schema import ROB2_DOMAINS
from agent.template_gate_adapter import evaluate_template_gate


# ---- Fixtures: synthetic 5-receipt rapamycin corpus ----------------------


_RECEIPTS = [
    {"receipt_id": "PMC_M_2018", "outcome_class": "immune",
     "effect_direction": "positive", "evidence_tier": "A1", "directness": "direct"},
    {"receipt_id": "PMC_L_2012", "outcome_class": "cardiometabolic",
     "effect_direction": "null", "evidence_tier": "B1", "directness": "indirect"},
    {"receipt_id": "PMC_K_2014", "outcome_class": "geroscience",
     "effect_direction": "positive", "evidence_tier": "A2", "directness": "direct"},
    {"receipt_id": "PMC_KAE_2017", "outcome_class": "companion_animal",
     "effect_direction": "positive", "evidence_tier": "B2", "directness": "indirect"},
    {"receipt_id": "PMC_LO_2023", "outcome_class": "hallmarks",
     "effect_direction": "supports", "evidence_tier": "A2", "directness": "direct"},
]
_REGISTRY = {
    "PMC_M_2018": {"body_citation": "Mannick 2018"},
    "PMC_L_2012": {"body_citation": "Lamming 2012"},
    "PMC_K_2014": {"body_citation": "Kennedy 2014"},
    "PMC_KAE_2017": {"body_citation": "Kaeberlein 2017"},
    "PMC_LO_2023": {"body_citation": "López-Otín 2023"},
}


def _rob_payload(study_ids=("PMC_M_2018", "PMC_L_2012", "PMC_K_2014")) -> list[dict]:
    return [{
        "study_id": sid, "design": "rct", "tool": "rob2", "overall_rating": "low",
        "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
    } for sid in study_ids]


def _grade_payload() -> list[dict]:
    return [
        {"outcome": "immune", "starting_certainty": "high",
         "downgrades": [{"reason": "rob", "levels": 1}], "upgrades": []},
        {"outcome": "cardiometabolic", "starting_certainty": "high",
         "downgrades": [{"reason": "inconsistency", "levels": 2}], "upgrades": []},
    ]


def _three_continuous_studies():
    return [
        RawContinuous("M_2018", 10.0, 2.0, 50, 8.0, 2.0, 50),
        RawContinuous("Sta_2026", 11.0, 2.5, 40, 8.5, 2.5, 40),
        RawContinuous("Lam_2024", 9.5, 2.0, 45, 8.0, 2.0, 45),
    ]


# ---- Stage 1: framework section -------------------------------------------


def test_stage1_framework_section_renders_known_authors() -> None:
    md = build_framework_section(
        receipts=_RECEIPTS, citation_registry=_REGISTRY
    )
    assert "## Engagement with Established Frameworks" in md
    # Mannick has the only positive immune (primary domain), so support.
    assert "supports the Mannick framework" in md
    # Lopez-Otin has hallmarks (primary domain) plus supports direction.
    assert "supports the Lopez-Otin framework" in md
    # Lamming primary domain is cardiometabolic, direction null, so challenge.
    assert "challenges the Lamming framework" in md


# ---- Stage 2: effect normalizer + meta-analysis --------------------------


def test_stage2_effect_normalizer_to_pool_chain() -> None:
    rows = [normalize_md(r) for r in _three_continuous_studies()]
    assert all(r.metric == "MD" for r in rows)
    assert len(rows) == 3
    pool = pool_random_effects(rows)
    assert pool.method == "random_effects"
    assert pool.n_studies == 3
    assert 0 <= pool.i_squared <= 100
    assert pool.tau_squared >= 0


# ---- Stage 3: forest plot SVG --------------------------------------------


def test_stage3_forest_plot_emits_valid_svg() -> None:
    rows = [normalize_md(r) for r in _three_continuous_studies()]
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool, title="rapamycin: synthetic outcome")
    # Must parse as XML
    ET.fromstring(svg)
    # Must contain study labels + pool diamond + heterogeneity caption
    for sid in ("M_2018", "Sta_2026", "Lam_2024"):
        assert sid in svg
    assert "Pooled" in svg
    assert "I^2=" in svg


# ---- Stage 4: quality methods bundle -------------------------------------


def test_stage4_quality_methods_bundle_on_full_inputs() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=_rob_payload(), grade_payload=_grade_payload(),
        receipt_count=5, outcome_count=2,
    )
    assert "Quality Methods Bundle" in bundle.markdown
    # rob_coverage = 3 unique RoB / 5 receipts = 0.6
    assert bundle.rob_coverage == pytest.approx(0.6)
    # grade_coverage = 2 unique outcomes / 2 outcome_count = 1.0
    assert bundle.grade_coverage == 1.0


def test_stage4_quality_methods_bundle_with_missing_payloads_fails_closed() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=None, grade_payload=None,
        receipt_count=5, outcome_count=2,
    )
    assert bundle.rob_coverage == 0.0
    assert bundle.grade_coverage == 0.0
    assert "_No RoB data provided._" in bundle.markdown


# ---- Stage 5: template-gate adapter ---------------------------------------


def test_stage5_template_gate_clean_paper_passes() -> None:
    paper = (
        "Mannick 2018 reported reduced respiratory tract infection rate "
        "in older adults receiving RTB101.\n"
        "Lamming 2012 demonstrated mTORC2 disruption with chronic dosing.\n"
        "Pending further trials, rapamycin should not be used off-label "
        "for healthspan extension outside clinical-trial settings.\n"
    )
    report = evaluate_template_gate(paper, source="full_paper.md")
    assert not report.template_language_blocking
    assert report.total_hits == 0


def test_stage5_template_gate_dirty_paper_blocks() -> None:
    paper = (
        "It is clear that rapamycin works in older adults.\n"
        "Further research is needed to confirm.\n"
    )
    report = evaluate_template_gate(paper)
    assert report.template_language_blocking
    assert report.p1_count >= 1
    assert report.p2_count >= 1


# ---- Stage 6: full chain to final gate (PASS) ----------------------------


def test_e2e_clean_inputs_yield_passing_final_gate() -> None:
    """All-green synthetic corpus gives final gate PASS, no failures."""
    receipts = _RECEIPTS
    paper_text = (
        "Engagement section: Mannick 2018 supports immune-aging.\n"
        "Pending further trials, rapamycin should not be used off-label.\n"
    )

    template_report = evaluate_template_gate(paper_text)
    quality_bundle = build_quality_methods_bundle(
        rob_payload=[{
            "study_id": rid, "design": "rct", "tool": "rob2",
            "overall_rating": "low",
            "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
        } for rid in [r["receipt_id"] for r in receipts[:5]]],
        grade_payload=[{
            "outcome": oc, "starting_certainty": "high",
            "downgrades": [], "upgrades": [],
        } for oc in {r["outcome_class"] for r in receipts}],
        receipt_count=len(receipts),
        outcome_count=len({r["outcome_class"] for r in receipts}),
    )

    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches={"unresolved_p1_count": 0},
        template_gate=template_report,
        quality_methods=quality_bundle,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=3, n_receipts=len(receipts),
    )
    # Use relaxed thresholds; synthetic 5-receipt corpus is below the
    # default 10-receipt floor. This mimics the AAA-SCOP track.
    custom = GateThresholds(min_receipts=3, warn_below_receipts=10)
    result = evaluate_final_gate(inputs, thresholds=custom)
    assert result.passed, f"unexpected fail: {result.summary}"
    # n_receipts=5 < warn_below=10, so P2 warning (non-blocking).
    assert any("below recommended" in w for w in result.warnings)


def test_e2e_dirty_template_blocks_final_gate() -> None:
    """Template-language gate failure propagates to final gate."""
    paper_dirty = "It is clear that rapamycin works.\nFurther research is needed.\n"
    template_report = evaluate_template_gate(paper_dirty)
    quality_bundle = build_quality_methods_bundle(
        rob_payload=_rob_payload(),
        grade_payload=_grade_payload(),
        receipt_count=3, outcome_count=2,
    )
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches=None,
        template_gate=template_report,
        quality_methods=quality_bundle,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=1, n_receipts=3,
    )
    custom = GateThresholds(min_receipts=3, warn_below_receipts=5)
    result = evaluate_final_gate(inputs, thresholds=custom)
    assert not result.passed
    assert "template_language_gate_blocking" in result.failures


def test_e2e_missing_rob_blocks_on_coverage() -> None:
    """No RoB means rob_coverage=0.0 and blocks the default gate."""
    paper = "Clean paper text.\n"
    template_report = evaluate_template_gate(paper)
    quality_bundle = build_quality_methods_bundle(
        rob_payload=None, grade_payload=_grade_payload(),
        receipt_count=5, outcome_count=2,
    )
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches=None,
        template_gate=template_report,
        quality_methods=quality_bundle,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=1, n_receipts=5,
    )
    result = evaluate_final_gate(inputs)
    assert not result.passed
    assert any("rob_coverage" in f for f in result.failures)


def test_e2e_audit_failure_blocks() -> None:
    """audit_gates_passed=False (Q1-Q14 fail) gives final gate FAIL."""
    paper = "Clean paper text.\n"
    template_report = evaluate_template_gate(paper)
    quality_bundle = build_quality_methods_bundle(
        rob_payload=_rob_payload(), grade_payload=_grade_payload(),
        receipt_count=3, outcome_count=2,
    )
    inputs = build_gate_inputs_from_artifacts(
        audit={"pass_count": 13, "total_count": 14},  # 13/14, not clean.
        journal_surface={"pass": True},
        reviewer_patches=None,
        template_gate=template_report,
        quality_methods=quality_bundle,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=1, n_receipts=3,
    )
    custom = GateThresholds(min_receipts=3, warn_below_receipts=5)
    result = evaluate_final_gate(inputs, thresholds=custom)
    assert not result.passed
    assert "audit_gates_failed" in result.failures


# ---- Determinism check ---------------------------------------------------


def test_e2e_deterministic_outputs() -> None:
    """Same inputs give same outputs across the chain."""
    md1 = build_framework_section(_RECEIPTS,
                                  citation_registry=_REGISTRY)
    md2 = build_framework_section(_RECEIPTS,
                                  citation_registry=_REGISTRY)
    assert md1 == md2

    rows = [normalize_md(r) for r in _three_continuous_studies()]
    pool = pool_random_effects(rows)
    svg1 = render_forest_plot_svg(rows, pool)
    svg2 = render_forest_plot_svg(rows, pool)
    assert svg1 == svg2

    paper = "Clean paper.\n"
    r1 = evaluate_template_gate(paper)
    r2 = evaluate_template_gate(paper)
    assert r1.markdown_report == r2.markdown_report
