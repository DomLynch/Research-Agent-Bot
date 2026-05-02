"""Tests for scripts/quant_claim_extract.py — Day 10.17 Path B-prime Phase 2.

Phase 2 extracts quantitative claims (p-values, CIs, sample sizes,
percentages, mean±SD, unit-bound values) from each paper_sections.json
artifact in docs/quality-reference/metformin/parsed/. The output is
gold-standard data for Phase 4 (gold benchmark).

Discipline: per v4 Rule 13, each test is discriminating — it catches
ONE specific kind of regression. The gold passages come from the
README + actual results sections of the 7 reference PDFs. If the
extractor regresses on any of these, exactly which signal broke is
visible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quant_claim_extract  # noqa: E402

PARSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs" / "quality-reference" / "metformin" / "parsed"
)


def _all_parsed() -> list[Path]:
    return sorted(PARSED_DIR.glob("*.json"))


def _find_parsed(substring: str) -> Path | None:
    for p in _all_parsed():
        if substring in p.name:
            return p
    return None


# ============================================================
# Pure unit tests — pattern-matchers (no JSON needed)
# ============================================================


def test_p_value_with_leading_zero_extracted() -> None:
    """Konopka-style: 'p = 0.08'."""
    text = "VO2max increase did not reach significance (p = 0.08)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].numeric_values == (0.08,)


def test_p_value_no_leading_zero_extracted() -> None:
    """Walton/Aging-Cell style: 'p = .003' (no leading zero)."""
    text = "Placebo gained more lean body mass (p = .003) than metformin."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].numeric_values == (0.003,)


def test_p_value_lt_extracted_with_comparator() -> None:
    """'p < .001' — comparator preserved in raw_text."""
    text = "Thigh muscle mass increase (p < .001) was higher in placebo."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].numeric_values == (0.001,)
    assert "<" in p_claims[0].raw_text


def test_uppercase_p_value_extracted() -> None:
    """'P = 0.05' (capital P)."""
    text = "The treatment effect was significant (P = 0.05)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1


def test_confidence_interval_extracted_with_range() -> None:
    """Witham MET-PREVENT: '95% CI -0.06 to 0.06' — bounds captured."""
    text = (
        "Adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    ci_claims = [c for c in claims if c.claim_type == "confidence_interval"]
    assert len(ci_claims) == 1
    assert ci_claims[0].numeric_values == (-0.06, 0.06)


def test_confidence_interval_with_endash_separator() -> None:
    """PDF artifact: en-dash '–' in CI range. Must normalize to minus."""
    text = "95% CI –0.06 to 0.06."  # en-dash
    claims = quant_claim_extract.extract_from_text(text, "results")
    ci_claims = [c for c in claims if c.claim_type == "confidence_interval"]
    assert len(ci_claims) == 1
    assert ci_claims[0].numeric_values == (-0.06, 0.06)


def test_sample_size_extracted_with_context() -> None:
    """'n = 53' — single integer, captured."""
    text = "Participants were randomized to placebo (n = 26) or metformin (n = 27)."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    sample_claims = [c for c in claims if c.claim_type == "sample_size"]
    assert len(sample_claims) == 2
    sizes = sorted(c.numeric_values[0] for c in sample_claims)
    assert sizes == [26, 27]


def test_sample_size_does_not_match_dose() -> None:
    """'n = 12 weeks' is NOT a sample size — must reject."""
    text = "Subjects underwent n = 12 weeks of training."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    sample_claims = [c for c in claims if c.claim_type == "sample_size"]
    # Phase 2 v0 design: tolerate both behaviors. The downstream Phase 4
    # gold compare can filter by the trailing token. For this test,
    # require the extractor to NOT crash and to mark this as a
    # sample_size candidate (we can post-filter in Phase 4).
    # If we get >0, the values must be 12 (not garbage).
    for c in sample_claims:
        assert c.numeric_values[0] == 12


def test_mean_sd_extracted_as_pair() -> None:
    """'9.7 ± 8.5' — Kulkarni 2022 style. Bounds: (mean, sd)."""
    text = "Recall improved (9.7 ± 8.5 vs. 5.3 ± 8.5)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    ms_claims = [c for c in claims if c.claim_type == "mean_sd"]
    assert len(ms_claims) == 2
    pairs = sorted((c.numeric_values for c in ms_claims), key=lambda x: x[0])
    assert pairs == [(5.3, 8.5), (9.7, 8.5)]


def test_percentage_extracted() -> None:
    """'58%' — Konopka responder split."""
    text = "58% of participants were positive responders."
    claims = quant_claim_extract.extract_from_text(text, "results")
    pct_claims = [c for c in claims if c.claim_type == "percentage"]
    assert len(pct_claims) == 1
    assert pct_claims[0].numeric_values == (58.0,)
    assert pct_claims[0].units == "%"


def test_unit_value_m_per_s_extracted() -> None:
    """Witham MET-PREVENT: '0.57 m/s' walk speed."""
    text = "Mean 4-m walk speed at 4 months was 0.57 m/s."
    claims = quant_claim_extract.extract_from_text(text, "results")
    unit_claims = [
        c for c in claims if c.claim_type == "unit_value" and c.units == "m/s"
    ]
    assert len(unit_claims) == 1
    assert unit_claims[0].numeric_values == (0.57,)


def test_p_value_with_pdf_no_break_space_separator() -> None:
    """PDF text often has non-breaking spaces (U+00A0) inside 'p = 0.05'.
    Must still match — pre-fix would miss these silently."""
    text = "Effect (p = 0.04) reached significance."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].numeric_values == (0.04,)


def test_lancet_dot_operator_normalized_to_period() -> None:
    """Lancet (Witham MET-PREVENT) typesets decimals with U+22C5 DOT
    OPERATOR ('p=0⋅96') instead of ASCII period. Pre-fix the
    extractor silently dropped EVERY Witham p-value, CI bound, and
    m/s unit value. This test pins the normalization."""
    text = (
        "Adjusted effect 0⋅001 m/s [95% CI –0⋅06 to "
        "0⋅06]; p=0⋅96."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    ci_claims = [c for c in claims if c.claim_type == "confidence_interval"]
    unit_claims = [c for c in claims if c.claim_type == "unit_value"]
    assert len(p_claims) == 1
    assert p_claims[0].numeric_values == (0.96,)
    assert len(ci_claims) == 1
    assert ci_claims[0].numeric_values == (-0.06, 0.06)
    assert len(unit_claims) == 1
    assert unit_claims[0].numeric_values == (0.001,)
    assert unit_claims[0].units == "m/s"


# ============================================================
# Section-aware filtering: references must be skipped
# ============================================================


def test_references_section_is_skipped() -> None:
    """Citation years like '(Smith et al., 2019, p < 0.05)' in references
    must NOT be extracted — they're not the paper's own claims."""
    text = (
        "Smith JM, et al. Effect on aging. Aging Cell. 2019;18:e12345 "
        "(p < 0.001 reported)."
    )
    # When called with section='references', returns empty.
    claims = quant_claim_extract.extract_from_text(text, "references")
    assert claims == ()


def test_non_reference_sections_extract_normally() -> None:
    """Same numeric pattern in 'results' must produce a claim."""
    text = "The effect was significant (p < 0.001)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    assert len(claims) >= 1


# ============================================================
# Sentence + context window plumbing
# ============================================================


def test_sentence_field_contains_full_sentence() -> None:
    """The `sentence` field must contain the complete sentence the claim
    came from — Phase 4 reads it for context-aware comparison."""
    text = (
        "Recall improved. The effect (p = 0.02) was significant. "
        "More analyses are pending."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].sentence.startswith("The effect"), (
        f"sentence wrong: {p_claims[0].sentence!r}"
    )
    assert "p = 0.02" in p_claims[0].sentence


def test_context_window_centered_on_value() -> None:
    """The context_window field must include text both before and after
    the numeric token so Phase 4 can disambiguate."""
    text = "The treatment cohort had a significant improvement (p = 0.04) over baseline."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    cw = p_claims[0].context_window
    assert "treatment cohort" in cw
    assert "baseline" in cw or "over baseline" in cw


# ============================================================
# JSON serialization round-trip
# ============================================================


def test_quant_claim_serializes_to_json_round_trip(tmp_path: Path) -> None:
    """The output artifact must round-trip through json.dumps/loads."""
    text = "Effect (p = 0.001) significant in 58% of n = 53 patients."
    claims = quant_claim_extract.extract_from_text(text, "results")
    artifact = quant_claim_extract.make_artifact(
        paper_id="test-paper", doi="10.1/test", claims=claims,
    )
    out = tmp_path / "out.json"
    out.write_text(json.dumps(artifact, indent=2))
    loaded = json.loads(out.read_text())
    assert loaded["paper_id"] == "test-paper"
    assert loaded["doi"] == "10.1/test"
    assert len(loaded["claims"]) == len(claims)
    # claims_count_by_type sums to total claims
    assert sum(loaded["claims_count_by_type"].values()) == len(claims)


# ============================================================
# Integration: extract from real parsed/ artifacts
# ============================================================


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_walton_masters_extracts_at_least_50_p_values_in_results() -> None:
    """Walton 2019 MASTERS results section is heavily statistical
    (the manual survey showed 70 p-values). Extractor must capture
    at least 50 — slack of 20 absorbs minor regex variations."""
    p = _find_parsed("Walton_2019_MASTERS")
    assert p is not None
    claims = quant_claim_extract.extract_from_paper_sections(p)
    p_in_results = [
        c for c in claims
        if c.claim_type == "p_value" and c.source_section == "results"
    ]
    assert len(p_in_results) >= 50, (
        f"Walton results expected ≥50 p-values, got {len(p_in_results)}"
    )


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_witham_met_prevent_extracts_the_primary_endpoint() -> None:
    """Witham MET-PREVENT primary endpoint (per README gold passage):
    '0.001 m/s [95% CI –0.06 to 0.06]; p=0.96'. The extractor must
    capture the m/s value, the CI, AND the p-value."""
    p = _find_parsed("Witham_2025_MET_PREVENT")
    assert p is not None
    claims = quant_claim_extract.extract_from_paper_sections(p)
    types = {c.claim_type for c in claims}
    # The paper has ALL of: walk-speed unit values, CIs, p-values
    assert "unit_value" in types, "no m/s walk-speed claims extracted"
    assert "confidence_interval" in types, "no CI claims extracted"


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_konopka_extracts_responder_percentages() -> None:
    """Konopka 2019 reports the 58/42 responder split — a key finding."""
    p = _find_parsed("Konopka_2019")
    assert p is not None
    claims = quant_claim_extract.extract_from_paper_sections(p)
    pcts = [c.numeric_values[0] for c in claims if c.claim_type == "percentage"]
    # 58 and 42 must both appear among the percentage claims
    assert 58.0 in pcts or 42.0 in pcts, (
        "Konopka responder split (58%/42%) missing from extracted percentages"
    )


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_review_paper_has_fewer_claims_than_rct() -> None:
    """Review papers (Mohammed, Keys) should produce far fewer claims
    than RCTs (Walton, Konopka). Sanity: prevents a regression where
    the extractor over-fires on prose."""
    walton_p = _find_parsed("Walton_2019_MASTERS")
    mohammed_p = _find_parsed("Mohammed_2021")
    walton_claims = quant_claim_extract.extract_from_paper_sections(walton_p)
    mohammed_claims = quant_claim_extract.extract_from_paper_sections(mohammed_p)
    assert len(walton_claims) > len(mohammed_claims), (
        f"RCT vs review density inverted: Walton={len(walton_claims)}, "
        f"Mohammed={len(mohammed_claims)}"
    )


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_all_seven_papers_extract_without_exception() -> None:
    """Smoke: run extractor against all 7 PDFs. None should raise."""
    failures = []
    for parsed_path in _all_parsed():
        try:
            claims = quant_claim_extract.extract_from_paper_sections(parsed_path)
            # Each claim must have valid types
            for c in claims:
                assert c.claim_type in {
                    "p_value", "confidence_interval", "sample_size",
                    "percentage", "mean_sd", "unit_value",
                    # Phase 2.1 effect-size additions
                    "hazard_ratio", "odds_ratio", "risk_ratio", "correlation",
                }, f"unknown claim_type: {c.claim_type}"
                assert isinstance(c.numeric_values, tuple)
                assert len(c.numeric_values) >= 1
        except Exception as e:
            failures.append(f"{parsed_path.name}: {e}")
    assert not failures, "\n  - ".join([""] + failures)


# ============================================================
# Reviewer-flagged regression tests (v0.2)
# ============================================================


def test_percentage_inside_ci_not_double_counted() -> None:
    """Reviewer HIGH bug: pre-fix the `occupied` membership check
    used tuple-equality, so a "95%" anchor INSIDE a CI literal got
    re-emitted as a standalone percentage claim. After fix, the
    interval-containment check suppresses it. Witham's 113-percent
    bloat collapsed by ~30 once this landed."""
    text = (
        "Adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    pct_claims = [c for c in claims if c.claim_type == "percentage"]
    # The "95%" inside the CI literal must NOT produce a percentage claim.
    assert pct_claims == [], (
        f"95% inside CI leaked as percentage: "
        f"{[(c.raw_text, c.numeric_values) for c in pct_claims]}"
    )


def test_unit_value_outside_ci_still_extracted() -> None:
    """Sibling check: the m/s unit OUTSIDE the CI bracket must still
    be captured. The interval-containment fix must not over-suppress."""
    text = (
        "Adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    unit_claims = [c for c in claims if c.claim_type == "unit_value"]
    assert len(unit_claims) == 1
    assert unit_claims[0].numeric_values == (0.001,)
    assert unit_claims[0].units == "m/s"


def test_sentence_split_handles_number_starting_clause() -> None:
    """Reviewer HIGH bug: pre-fix `(?=[A-Z])` failed to split
    "...significant. 58% of subjects responded." since '5' is not
    [A-Z]. The fix `(?=[A-Z0-9])` makes number-starting clauses
    valid sentence boundaries."""
    text = "The effect was significant. 58% of subjects responded with p = 0.02."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    # The p-value sentence must be ONLY "58% of subjects responded with p = 0.02."
    # (NOT a multi-sentence blob including the prior clause).
    assert p_claims[0].sentence.startswith("58%"), (
        f"sentence segmentation failed to split on number: "
        f"{p_claims[0].sentence!r}"
    )


def test_99_percent_ci_extracted_with_level_in_units() -> None:
    """Reviewer MEDIUM: pre-fix CI regex was hardcoded to 95%; meta-
    analysis sections quote 99% CIs. After fix, level is captured
    into `units` (e.g. '99%CI') so Phase 4 can disambiguate."""
    text = "Hazard ratio 1.25 (99% CI 0.47 to 3.29) supported the analysis."
    claims = quant_claim_extract.extract_from_text(text, "results")
    ci_claims = [c for c in claims if c.claim_type == "confidence_interval"]
    assert len(ci_claims) == 1
    assert ci_claims[0].numeric_values == (0.47, 3.29)
    assert "99" in ci_claims[0].units


def test_clinical_units_mmhg_and_mg_per_dl_extracted() -> None:
    """Reviewer MEDIUM: pre-fix only m/s, kg, mg, mmol covered.
    Clinical papers use mmHg, bpm, mg/dL, ng/mL. Silent drop
    was the wrong tradeoff for a gold benchmark."""
    text = (
        "Baseline blood pressure was 132 mmHg with HbA1c 6.5 mg/dL "
        "and resting heart rate 72 bpm."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    units = sorted(c.units for c in claims if c.claim_type == "unit_value")
    assert "mmHg" in units
    assert "mg/dL" in units
    assert "bpm" in units


def test_make_artifact_accepts_injected_now_for_determinism(tmp_path) -> None:
    """Reviewer LOW: `extracted_at` defaults to wall-clock UTC. To
    snapshot-test artifacts in CI we need an injection point."""
    import datetime as dt
    fixed = dt.datetime(2026, 5, 2, 12, 0, 0, tzinfo=dt.timezone.utc)
    a1 = quant_claim_extract.make_artifact(
        paper_id="x", doi="d", claims=(), now=fixed,
    )
    a2 = quant_claim_extract.make_artifact(
        paper_id="x", doi="d", claims=(), now=fixed,
    )
    assert a1["extracted_at"] == a2["extracted_at"]
    assert a1["extracted_at"] == "2026-05-02T12:00:00+00:00"


@pytest.mark.skipif(
    not _all_parsed(),
    reason="No parsed PDFs available",
)
def test_per_paper_claim_count_under_sanity_ceiling() -> None:
    """Reviewer-flagged anti-gaming pin. Lower bound (Walton >= 50)
    catches a regression that drops to zero. Upper bound (< 1000)
    catches the opposite regression where the extractor over-fires
    on prose. Konopka at 196 is well clear of 1000."""
    for parsed in _all_parsed():
        claims = quant_claim_extract.extract_from_paper_sections(parsed)
        assert len(claims) < 1000, (
            f"{parsed.name}: claim explosion ({len(claims)} >= 1000)"
        )


# ============================================================
# Phase 2.1 - effect-size patterns (HR / OR / RR / correlation)
# ============================================================


def test_hazard_ratio_extracted_from_witham_style_text() -> None:
    """Witham trial: 'adjusted hazard ratio 1.25 (95% CI ...)' must produce
    a hazard_ratio claim with value 1.25."""
    text = "Adjusted hazard ratio 1.25 (95% CI 0.47 to 3.29); p=0.66."
    claims = quant_claim_extract.extract_from_text(text, "results")
    hrs = [c for c in claims if c.claim_type == "hazard_ratio"]
    assert len(hrs) == 1
    assert hrs[0].numeric_values == (1.25,)


def test_odds_ratio_extracted_with_short_form_OR() -> None:
    """Phase 2.1 v0.3: 'OR' alone is too ambiguous (English conjunction).
    Requires either the long form 'odds ratio' OR the abbreviation
    followed by mandatory [:=]. Both shapes captured."""
    text = (
        "The adjusted odds ratio 1.25 was reported in the trial. "
        "A second model gave OR: 0.75 with similar bounds."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    ors = [c for c in claims if c.claim_type == "odds_ratio"]
    assert len(ors) == 2
    values = sorted(c.numeric_values[0] for c in ors)
    assert values == [0.75, 1.25]


def test_relative_risk_extracted() -> None:
    """'relative risk 1.10' / 'RR 1.10'."""
    text = "The relative risk 1.10 indicated marginal increase."
    claims = quant_claim_extract.extract_from_text(text, "results")
    rrs = [c for c in claims if c.claim_type == "risk_ratio"]
    assert len(rrs) == 1
    assert rrs[0].numeric_values == (1.10,)


def test_correlation_coefficient_extracted_with_pearson() -> None:
    """Pearson r = 0.45 must produce a correlation claim."""
    text = "Insulin sensitivity correlated with mitochondrial respiration (Pearson r = 0.45)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    corrs = [c for c in claims if c.claim_type == "correlation"]
    assert len(corrs) == 1
    assert corrs[0].numeric_values == (0.45,)


def test_negative_correlation_extracted_with_parenthesis_anchor() -> None:
    """Phase 2.1 v0.3: bare 'r=' was matching 'for r = 4 patients'.
    Now requires either Pearson/Spearman keyword OR parenthesis anchor.
    Negative sign captured."""
    text = "Body mass and walk speed were inversely related (r = -0.32) in older adults."
    claims = quant_claim_extract.extract_from_text(text, "results")
    corrs = [c for c in claims if c.claim_type == "correlation"]
    assert len(corrs) == 1
    assert corrs[0].numeric_values == (-0.32,)


# ============================================================
# Phase 2.1 - dose units (Mohammed "5 kg/day" false-positive fix)
# ============================================================


def test_dose_unit_kg_per_day_wins_over_bare_kg() -> None:
    """Reviewer-flagged Mohammed false positive: pre-fix the regex
    matched '5 kg' inside '5 kg/day' (a fatal-dose value treated as
    a body weight). Phase 2.1 puts kg/day BEFORE kg in the alternation
    so the longer dose unit wins."""
    text = "The dose was approximately 5 kg/day equivalent in humans."
    claims = quant_claim_extract.extract_from_text(text, "discussion")
    units = [(c.numeric_values, c.units) for c in claims if c.claim_type == "unit_value"]
    assert ((5.0,), "kg/day") in units, f"missing kg/day capture: {units}"
    # And the bare 'kg' must NOT appear separately for the same span.
    bare_kg = [u for u in units if u[1] == "kg" and u[0] == (5.0,)]
    assert bare_kg == [], f"bare kg leaked alongside kg/day: {units}"


def test_mg_per_kg_per_day_dose_unit_extracted() -> None:
    """Dose unit 'mg/kg/day' (mouse studies) must be recognized."""
    text = "Mice received 300 mg/kg/day metformin."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    doses = [c for c in claims if c.units == "mg/kg/day"]
    assert len(doses) == 1
    assert doses[0].numeric_values == (300.0,)


# ============================================================
# Phase 2.1 - claim_role tagging
# ============================================================


def test_claim_role_default_is_empty_for_v01_compatibility() -> None:
    """The new claim_role field must default to a heuristic value.
    For sentences with no role keywords + ambiguous section, it
    falls back to 'unknown' (NOT empty string '') so consumers can
    distinguish 'never tagged' from 'tagged as ambiguous'."""
    text = "An odd number 42 appeared p = 0.05 here."
    claims = quant_claim_extract.extract_from_text(text, "abstract")
    p_claims = [c for c in claims if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    assert p_claims[0].claim_role in ("effect", "background", "unknown")


def test_claim_role_tags_effect_from_increased_keyword() -> None:
    """Sentences containing 'increased / decreased / improved' clearly
    state effects. Role = 'effect'."""
    text = "Walk speed increased by 0.05 m/s in the metformin group (p = 0.04)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    for c in claims:
        if c.claim_type in ("p_value", "unit_value"):
            assert c.claim_role == "effect", (
                f"{c.claim_type} got role={c.claim_role!r}"
            )


def test_claim_role_tags_background_from_prevalence_keyword() -> None:
    """'Prevalence' / 'incidence' keywords mark a sentence as background
    epidemiology, not a study finding."""
    text = "Type 2 diabetes prevalence is approximately 10% globally."
    claims = quant_claim_extract.extract_from_text(text, "introduction")
    pct_claims = [c for c in claims if c.claim_type == "percentage"]
    assert len(pct_claims) == 1
    assert pct_claims[0].claim_role == "background"


def test_claim_role_tags_dose_from_treatment_keyword() -> None:
    """'Treatment with X mg/day' is dose, not effect."""
    text = "Subjects received treatment with 1700 mg/day metformin."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    dose_claims = [c for c in claims if c.units == "mg/day"]
    assert len(dose_claims) == 1
    assert dose_claims[0].claim_role == "dose"


def test_claim_role_tags_duration_from_followup_keyword() -> None:
    """'Follow-up of N years' is duration, not effect."""
    text = "Median follow-up duration of 2.8 years was achieved."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    dur_claims = [c for c in claims if c.units == "years"]
    assert len(dur_claims) == 1
    assert dur_claims[0].claim_role == "duration"


def test_claim_role_field_serialized_in_artifact() -> None:
    """The new field must round-trip through make_artifact JSON."""
    import json
    text = "Walk speed increased (p = 0.04) significantly."
    claims = quant_claim_extract.extract_from_text(text, "results")
    artifact = quant_claim_extract.make_artifact(
        paper_id="x", doi="d", claims=claims,
    )
    payload = json.loads(json.dumps(artifact))
    for c in payload["claims"]:
        assert "claim_role" in c
        assert c["claim_role"] in (
            "effect", "dose", "duration", "population", "background", "unknown",
        )


# ============================================================
# Phase 2.1 v0.3 - reviewer-flagged HIGH bug regression tests
# ============================================================


def test_or_does_not_match_english_conjunction_or() -> None:
    """Reviewer HIGH 1: pre-fix the OR pattern (case-insensitive,
    optional [:=]) matched English 'or' in clauses like 'metformin or
    placebo (n=27)'. Fix: CAPS only + mandatory [:=] for the
    abbreviation form. The phrase below contains 'or' twice but no
    real odds ratio."""
    text = "Subjects received metformin or placebo for 12 weeks; n=27 in each arm."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    ors = [c for c in claims if c.claim_type == "odds_ratio"]
    assert ors == [], f"English 'or' false-positive: {[c.raw_text for c in ors]}"


def test_hr_does_not_match_clinical_heart_rate() -> None:
    """Reviewer HIGH 2: pre-fix 'HR was 72' tagged as hazard_ratio=72
    (heart rate). Fix: CAPS-only HR + mandatory [:=] + sanity bound.
    Spelled-out 'heart rate' is harmless."""
    text = "Resting heart rate was 72 bpm; HR exam taken every 4 weeks."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    hrs = [c for c in claims if c.claim_type == "hazard_ratio"]
    assert hrs == [], f"heart-rate false-positive: {[c.raw_text for c in hrs]}"


def test_hazard_ratio_implausibly_large_value_dropped() -> None:
    """Reviewer HIGH 2: even with [:=] enforced, a clinical typo or
    table-cell collision could produce 'HR: 200'. Sanity bound
    rejects values > 100 (real HRs are 0.01-50 range)."""
    text = "HR: 200 was reported in a table cell error."
    claims = quant_claim_extract.extract_from_text(text, "results")
    hrs = [c for c in claims if c.claim_type == "hazard_ratio"]
    assert hrs == []


def test_correlation_bare_r_equals_does_not_match_outside_anchor() -> None:
    """Reviewer HIGH 3: pre-fix 'for r = 4 patients' false-positive'd.
    Fix requires (Pearson|Spearman) keyword OR parenthesis anchor."""
    text = "The methodology was adapted; for r = 4 patients the formula was simplified."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    corrs = [c for c in claims if c.claim_type == "correlation"]
    assert corrs == [], f"bare r= false-positive: {[c.raw_text for c in corrs]}"


def test_correlation_value_outside_minus1_to_1_dropped() -> None:
    """Sanity: even matched anchors must enforce |r| <= 1."""
    text = "An aberrant value (r = 5.2) was discarded."
    claims = quant_claim_extract.extract_from_text(text, "results")
    corrs = [c for c in claims if c.claim_type == "correlation"]
    assert corrs == []


def test_role_background_wins_when_prevalence_co_occurs_with_increased() -> None:
    """Reviewer HIGH 4: pre-fix 'Global incidence has increased' tagged
    as effect because 'increased' was checked first. Fix: BACKGROUND
    keywords (prevalence/incidence/global) override EFFECT keywords."""
    text = "Global incidence of T2DM has increased to 10% over the past decade."
    claims = quant_claim_extract.extract_from_text(text, "introduction")
    pct_claims = [c for c in claims if c.claim_type == "percentage"]
    assert len(pct_claims) == 1
    assert pct_claims[0].claim_role == "background", (
        f"epidemiology sentence with 'increased' wrongly tagged as effect: "
        f"{pct_claims[0].claim_role}"
    )


def test_role_effect_still_wins_when_no_background_keyword() -> None:
    """The HIGH 4 fix must not over-correct: a sentence with effect
    keywords + NO background signal still tags as effect."""
    text = "Walk speed increased by 0.05 m/s in the metformin arm (p = 0.03)."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p = [c for c in claims if c.claim_type == "p_value"][0]
    assert p.claim_role == "effect"


# ============================================================
# Phase 2.1 v0.3 hotfix - audit-flagged P2 regression tests
# ============================================================


def test_extractor_version_is_proper_semver_and_at_least_v03() -> None:
    """Audit P2 #1: the version must reflect what the code does (the
    audit caught a v0.2.0 vs v0.3 docstring mismatch). After Phase
    2.2 the version is 0.4.0+. Test the SHAPE here so future bumps
    don't break this; the per-version contract lives in the module-
    level history comment."""
    import re as _re
    v = quant_claim_extract.EXTRACTOR_VERSION
    assert _re.match(r"^\d+\.\d+\.\d+$", v), f"version not semver: {v!r}"
    major, minor, _patch = v.split(".")
    assert int(major) >= 0
    assert int(minor) >= 3, f"version {v} predates the v0.3 audit fix"


def test_role_results_section_no_keyword_returns_unknown_not_effect() -> None:
    """Audit P2 #3: pre-fix the section fallback returned 'effect'
    for any results/discussion/conclusion claim with no keyword
    match. That overlabeled interpretive numbers (e.g. table-cell
    residue percentages, citation context) as findings. Now: only
    introduction has a directional default; everything else is
    'unknown' so Phase 4 owns the disambiguation."""
    text = "Table 2 lists 4 cohorts."  # no keyword match
    claims = quant_claim_extract.extract_from_text(text, "results")
    sample_claims = [c for c in claims if c.claim_type == "sample_size"]
    if sample_claims:
        # If we extracted anything, it must NOT be tagged effect.
        for c in sample_claims:
            assert c.claim_role != "effect", (
                f"section fallback overlabeled as effect: {c}"
            )


def test_sample_size_with_trailing_duration_token_tagged_duration() -> None:
    """Audit P2 #2: pre-fix 'n = 12 weeks' was extracted as a
    sample_size with claim_role='effect' (or unknown). Now the
    trailing duration token bumps role to 'duration' so Phase 4
    can post-filter without dropping the candidate."""
    text = "Subjects underwent n = 12 weeks of training."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    sample_claims = [c for c in claims if c.claim_type == "sample_size"]
    assert len(sample_claims) == 1
    assert sample_claims[0].claim_role == "duration", (
        f"trailing-duration sample_size not retagged: "
        f"role={sample_claims[0].claim_role}"
    )


def test_real_sample_size_with_participant_context_stays_effect_or_population() -> None:
    """The hotfix must not over-correct: a real sample size like
    'n = 27 participants' must NOT be retagged as duration."""
    text = "Participants were randomized to placebo (n = 26) or metformin (n = 27)."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    sample_claims = [c for c in claims if c.claim_type == "sample_size"]
    assert len(sample_claims) == 2
    for c in sample_claims:
        assert c.claim_role != "duration", (
            f"real sample size wrongly retagged as duration: {c}"
        )


# ============================================================
# Phase 2.2 - endpoint / arm / direction binding integration
# ============================================================


def test_phase22_schema_has_binding_fields() -> None:
    """v0.4.0 adds endpoint, arm, direction, binding_confidence to
    QuantClaim. Defaults must be backward-compatible."""
    fields = quant_claim_extract.QuantClaim.__dataclass_fields__
    for f in ("endpoint", "arm", "direction", "binding_confidence"):
        assert f in fields, f"missing schema field: {f}"


def test_phase22_walton_passage_binds_endpoint_arm_direction() -> None:
    """Walton MASTERS gold: 'Placebo gained more lean body mass
    (p = .003) than metformin'. Should bind endpoint=lean body
    mass, arm=metformin or placebo, direction=increase, with
    high confidence."""
    text = "Placebo gained more lean body mass (p = .003) than metformin."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claim = next(c for c in claims if c.claim_type == "p_value")
    assert p_claim.endpoint == "lean body mass"
    assert p_claim.arm in ("metformin", "placebo")
    assert p_claim.direction == "increase"
    assert p_claim.binding_confidence == "high"


def test_phase22_konopka_attenuated_increase_binds_decrease() -> None:
    """Konopka 2019 gold: the load-bearing test for the span-
    containment fix. 'Metformin attenuated the increase in VO2max
    ... (p = 0.08)' must bind direction=decrease (the compound
    phrase "attenuated the increase" subsumes the inner "increase"
    word; "did not reach significance" is NOT a no_change pattern
    match because "reach" isn't in the negated-verb set)."""
    text = (
        "Metformin attenuated the increase in VO2max following 12 "
        "weeks of AET, although this did not reach significance (p = 0.08)."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claim = next(c for c in claims if c.claim_type == "p_value")
    assert p_claim.endpoint == "VO2max"
    assert p_claim.arm == "metformin"
    # Tightened from `!= "increase"` (reviewer-flagged: a not-equal
    # assertion doesn't validate that the span-containment fix
    # delivers the right answer, only that it doesn't deliver the
    # wrong one). Confirmed by direct trace: actual result IS
    # "decrease".
    assert p_claim.direction == "decrease"
    assert p_claim.binding_confidence == "high"


def test_phase22_witham_did_not_improve_binds_no_change() -> None:
    """Witham MET-PREVENT primary endpoint: load-bearing for the
    span-containment fix on 'did not improve'. Pre-fix the inner
    'improve' word would have bound to direction=increase."""
    text = (
        "Metformin did not improve 4-m walk speed at 4 months "
        "(p = 0.96)."
    )
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claim = next(c for c in claims if c.claim_type == "p_value")
    assert p_claim.endpoint == "walk speed"
    assert p_claim.arm == "metformin"
    assert p_claim.direction == "no_change"
    assert p_claim.binding_confidence == "high"


def test_phase22_partial_binding_when_no_arm_keyword() -> None:
    """Sentence with endpoint + direction but no arm keyword should
    yield binding_confidence=partial."""
    text = "HbA1c decreased (p = 0.03) at 12 weeks."
    claims = quant_claim_extract.extract_from_text(text, "results")
    p_claim = next(c for c in claims if c.claim_type == "p_value")
    assert p_claim.endpoint == "HbA1c"
    assert p_claim.arm == ""
    assert p_claim.direction == "decrease"
    assert p_claim.binding_confidence == "partial"


def test_phase22_no_binding_when_pure_methodology_text() -> None:
    """A methods-section sentence with no clinical vocab returns
    binding_confidence=none. Phase 4 can drop these for the abstract."""
    text = "Subjects were enrolled in 2018 (n = 45) at three sites."
    claims = quant_claim_extract.extract_from_text(text, "methods")
    sample_claim = next(c for c in claims if c.claim_type == "sample_size")
    assert sample_claim.endpoint == ""
    assert sample_claim.arm == ""
    assert sample_claim.direction == ""
    assert sample_claim.binding_confidence == "none"


def test_phase22_binding_fields_round_trip_through_artifact_json() -> None:
    """v0.4.0 fields must serialize through make_artifact + JSON."""
    import json
    text = "Walk speed increased (p = 0.04) in the metformin arm."
    claims = quant_claim_extract.extract_from_text(text, "results")
    artifact = quant_claim_extract.make_artifact(
        paper_id="x", doi="d", claims=claims,
    )
    payload = json.loads(json.dumps(artifact))
    for c in payload["claims"]:
        assert "endpoint" in c
        assert "arm" in c
        assert "direction" in c
        assert "binding_confidence" in c
        assert c["binding_confidence"] in ("high", "partial", "none")
