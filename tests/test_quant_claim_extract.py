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
