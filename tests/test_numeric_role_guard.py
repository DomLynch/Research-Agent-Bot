"""Unit tests for scripts/numeric_role_guard.py — universal class-
level fix for numeric mis-interpretation patterns. Tests synthetic
examples spanning gait speed, BMI, BP, dose, duration to verify
topic-agnostic behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from numeric_role_guard import (  # noqa: E402
    auto_strip_offending_sentences,
    scan_paper,
    _check_arithmetic_violations,
    _check_role_mismatch,
    _check_malformed_subject,
    _has_change_framing,
    _has_change_threshold,
)


# ---------- arithmetic violations -----------------------------------

def test_arithmetic_violation_metformin_pattern():
    """The exact reviewer-flagged pattern: 0.13 m/s claimed to fall
    at or below 0.1 m/s threshold (0.13 > 0.1, so 'below' is false)."""
    s = (
        "The observed change in the MET-PREVENT trial of 0.13 m/s "
        "falls at or below this 0.1 m/s threshold, suggesting "
        "minimal clinical impact."
    )
    issue = _check_arithmetic_violations(s)
    assert issue is not None
    assert issue.issue_type == "arithmetic_violation"
    assert issue.severity == "P1"


def test_arithmetic_violation_above_pattern():
    """Same class, opposite direction: 'X exceeds Y' when X < Y."""
    s = "A pressure of 100 mmHg exceeds the 130 mmHg hypertension threshold."
    issue = _check_arithmetic_violations(s)
    assert issue is not None
    assert issue.issue_type == "arithmetic_violation"


def test_arithmetic_correct_below_passes():
    """Correct claim: 0.5 m/s IS below 0.6 m/s. No issue."""
    s = "Walk speed of 0.5 m/s falls below the 0.6 m/s severe-frailty cutoff."
    assert _check_arithmetic_violations(s) is None


def test_arithmetic_universal_units_bmi():
    """Generalizes to BMI."""
    s = "A BMI of 35 kg/m² falls below the 30 kg/m² obesity threshold."
    # 35 > 30 but sentence says "below" → violation
    issue = _check_arithmetic_violations(s)
    assert issue is not None


# ---------- role mismatch ------------------------------------------

def test_role_mismatch_change_vs_absolute_frailty():
    """'A change of X is below the frailty cutoff' — change_score
    compared to absolute_value threshold via explicit comparison.
    Reviewer-tightened: P1 issue_type='change_score_vs_absolute_threshold',
    auto-strip."""
    s = (
        "The observed change of 0.05 m/s is below the 0.8 m/s "
        "frailty threshold, indicating severe impairment."
    )
    issue = _check_role_mismatch(s)
    assert issue is not None
    assert issue.issue_type == "change_score_vs_absolute_threshold"
    assert issue.severity == "P1"


def test_role_mismatch_allows_change_vs_change_threshold():
    """Change-vs-clinically-meaningful-change is the LEGITIMATE
    framing. Must NOT flag."""
    s = (
        "The observed change of 0.15 m/s exceeds the clinically "
        "meaningful change threshold of 0.1 m/s."
    )
    assert _check_role_mismatch(s) is None


def test_role_mismatch_no_change_framing_passes():
    """Sentences without change framing aren't subject to this rule."""
    s = "Walk speed was 0.5 m/s, below the 0.8 m/s frailty cutoff."
    assert _check_role_mismatch(s) is None


def test_role_mismatch_universal_bp():
    """Generalizes to blood-pressure change vs hypertension cutoff."""
    s = (
        "A change of 5 mmHg is below the 140 mmHg hypertension "
        "threshold."
    )
    issue = _check_role_mismatch(s)
    assert issue is not None
    assert issue.severity == "P1"


def test_role_mismatch_no_explicit_comparison_passes():
    """Discussion of change scores AND thresholds without an
    EXPLICIT below/above/falls-at comparison is allowed —
    recommendation prose, MCID benchmarks, etc. are legitimate."""
    s = (
        "Future trials should target an annual gait-speed decline of "
        "0.05 m/s, given established frailty cutoffs in the 0.8 m/s "
        "range."
    )
    # No 'falls below', 'is above' — just discussion of both numerics
    assert _check_role_mismatch(s) is None


# ---------- malformed subject (duplicate-subject artifact) ---------

def test_malformed_subject_metformin_pattern():
    """The exact reviewer-flagged pattern: 'the placebo group
    experienced ... for the placebo group was 0.13 m/s'."""
    s = (
        "The placebo group experienced change in walk speed for "
        "the placebo group was 0.13 m/s."
    )
    issue = _check_malformed_subject(s)
    assert issue is not None
    assert issue.issue_type == "malformed_subject"
    assert issue.severity == "P2"


def test_malformed_subject_well_formed_passes():
    """Same words, different structure (no duplication) — passes."""
    s = "The placebo group experienced no change in walk speed."
    assert _check_malformed_subject(s) is None


def test_malformed_subject_universal_aspirin():
    """Generalizes to any group name."""
    s = (
        "The aspirin group reported gastrointestinal effects for "
        "the aspirin group were minimal."
    )
    issue = _check_malformed_subject(s)
    assert issue is not None


# ---------- change framing detection -------------------------------

def test_has_change_framing_signals():
    """Various phrasings of 'change' should be detected."""
    assert _has_change_framing("a change of 5%")
    assert _has_change_framing("an increase of 10")
    assert _has_change_framing("decrease from baseline")
    assert _has_change_framing("improvement of 0.2 units")
    assert not _has_change_framing("walk speed was 0.5 m/s")


def test_has_change_threshold_allowlist():
    """The allowlist phrases mark sentences as legitimately
    change-vs-change-threshold."""
    assert _has_change_threshold(
        "exceeds the clinically meaningful change threshold"
    )
    assert _has_change_threshold("MCID is 0.1 m/s")
    assert _has_change_threshold(
        "the minimal clinically important difference is 5 points"
    )
    assert not _has_change_threshold("below the 0.8 m/s threshold")


# ---------- end-to-end scan + strip --------------------------------

def test_scan_paper_finds_metformin_paragraph_issues():
    """The exact metformin failing paragraph should produce an
    arithmetic_violation issue."""
    paper = (
        "The MET-PREVENT trial showed a change of 0.13 m/s. "
        "The observed change in the trial of 0.13 m/s falls at or "
        "below this 0.1 m/s threshold, suggesting minimal clinical "
        "impact."
    )
    issues = scan_paper(paper)
    assert any(i.issue_type == "arithmetic_violation" for i in issues)


def test_scan_clean_paper_returns_empty():
    """A paper with no role-mismatch / arithmetic / malformed
    issues should produce zero flags."""
    paper = (
        "The placebo group's walk speed was 0.5 m/s. This was below "
        "the 0.6 m/s severe-frailty cutoff (Cesari 2009). The "
        "observed change of 0.15 m/s exceeded the clinically "
        "meaningful change threshold."
    )
    issues = scan_paper(paper)
    assert issues == []


def test_auto_strip_removes_p1_only():
    """auto_strip_offending_sentences removes P1 sentences but
    leaves P2 (which need non-strip handling)."""
    paper = (
        "Good sentence. The change of 0.13 falls at or below the 0.1 "
        "m/s threshold, indicating minimal effect."
    )
    issues = scan_paper(paper)
    new_md, n = auto_strip_offending_sentences(paper, issues)
    assert n == 1  # P1 stripped
    assert "0.13 falls at or below" not in new_md
    assert "Good sentence" in new_md


# --- Slice 7 step 1: source-context numeric drift -------------------

def test_source_context_drift_flags_unknown_numeric_for_citation(tmp_path):
    """Prose says 'Mannick 2014 used 50 mg' but the source paper
    actually has 5 mg. Source-context drift → P1."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_mannick.quant_claims.json").write_text(
        '{"paper_id":"PMC_mannick","claims":'
        '[{"raw_text":"5 mg","numeric_values":[5],'
        '"binding_confidence":"high","claim_type":"unit_value"}]}'
    )
    manifest = {
        "receipts": [{
            "paper_id": "PMC_mannick",
            "citation_token": "Mannick 2014",
        }],
    }
    paper = (
        "Mannick 2014 employed a regimen involving 50 mg "
        "administered intermittently."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    assert any(
        i.issue_type == "source_context_drift" for i in issues
    )


def test_source_context_drift_passes_correct_attribution(tmp_path):
    """Prose says 'Mannick 2014 used 5 mg' and the source paper has
    5 mg → no drift flag."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_mannick.quant_claims.json").write_text(
        '{"paper_id":"PMC_mannick","claims":'
        '[{"numeric_values":[5],"binding_confidence":"high",'
        '"claim_type":"unit_value"}]}'
    )
    manifest = {
        "receipts": [{
            "paper_id": "PMC_mannick",
            "citation_token": "Mannick 2014",
        }],
    }
    paper = "Mannick 2014 used 5 mg administered intermittently."
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    assert not any(
        i.issue_type == "source_context_drift" for i in issues
    )


def test_source_context_drift_uses_bg_lit_registry():
    """Background literature registry numerics are also valid
    sources of context (Harrison 2009 lifespan increases are in
    bg_lit, not in receipts)."""
    bg_lit = {
        "harrison_lifespan_male": {
            "citation_token": "Harrison 2009",
            "numeric": "14",
            "context": "median lifespan males",
        },
    }
    paper = "Harrison 2009 reported median lifespan increases of 14% in males."
    issues = scan_paper(
        paper, manifest={}, bg_lit_registry=bg_lit,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_skips_unknown_citations():
    """Fail-soft: a citation token that's not in registry/manifest →
    no flag (we'd rather miss than false-positive on a citation we
    have no source-context data on)."""
    paper = "Smith 2099 reported a totally fictional 99% reduction."
    issues = scan_paper(
        paper, manifest={}, bg_lit_registry={},
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_skips_year_numerics():
    """The year '2014' in 'Mannick 2014' must not be flagged as a
    drift — it's the citation token itself, not a claim."""
    bg_lit = {
        "x": {
            "citation_token": "Mannick 2014",
            "numeric": "5",
            "context": "dose",
        },
    }
    paper = "Mannick 2014 reported 5 mg."
    issues = scan_paper(
        paper, manifest={}, bg_lit_registry=bg_lit,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_handles_numeric_variants():
    """'5' / '5.0' / '05' should all match the source's stored 5."""
    bg_lit = {
        "x": {
            "citation_token": "X 2020",
            "numeric": "5",
            "context": "dose",
        },
    }
    for prose_num in ("5", "5.0", "5.00"):
        paper = f"X 2020 used {prose_num} mg."
        issues = scan_paper(
            paper, manifest={}, bg_lit_registry=bg_lit,
        )
        drift = [
            i for i in issues if i.issue_type == "source_context_drift"
        ]
        assert drift == [], f"failed on {prose_num!r}"


def test_scan_paper_back_compat_no_kwargs_works():
    """Existing callers passing only paper_md (no manifest /
    bg_lit) keep working — drift check is silently disabled."""
    paper = "The paper says 5 mg of compound."
    issues = scan_paper(paper)
    # No drift check ran (registry empty)
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


# --- Slice 7 P1b: ROLE drift (not just value drift) ----------------

def test_role_drift_flags_baseline_when_source_is_change_score(tmp_path):
    """The user's blocker: prose says 'baseline gait speed 0.13 m/s'
    but Witham 2025 has 0.13 only as a CHANGE_SCORE, not a baseline.
    Numeric exists in source → value check passes. Role check must
    fire."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high",'
        '"claim_role":"change_score",'
        '"endpoint":"walk speed",'
        '"context_window":"clinically important improvement of 0.13 m/s"'
        '}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_witham",
        "citation_token": "Witham 2025",
    }]}
    paper = (
        "Baseline gait speed in this cohort was 0.13 m/s "
        "(Witham 2025), suggesting severely impaired mobility."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift, "ROLE drift should fire even when value matches"
    assert "ROLE drift" in drift[0].detail
    assert "baseline" in drift[0].detail.lower()
    assert "change_score" in drift[0].detail.lower()


def test_role_drift_passes_when_prose_role_matches_source(tmp_path):
    """Same Witham 0.13 m/s — prose now correctly frames as change."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high",'
        '"claim_role":"change_score",'
        '"endpoint":"walk speed",'
        '"context_window":"improvement of 0.13 m/s"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_witham",
        "citation_token": "Witham 2025",
    }]}
    paper = (
        "MET-PREVENT reported a clinically important improvement "
        "of 0.13 m/s in walk speed (Witham 2025)."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == [], "Correct prose role should NOT trigger drift"


def test_role_drift_outcome_compatible_with_population_baseline():
    """A bg_lit/canonical numeric is compatible with any prose role
    so the existing Harrison 2009 / 14% lifespan-extension sentence
    still passes (no false positives on the bg_lit pool)."""
    bg_lit = {
        "harrison": {
            "citation_token": "Harrison 2009",
            "numeric": "14%",
            "context": "median lifespan extension",
        },
    }
    paper = (
        "Harrison 2009 reported median lifespan increases of 14% "
        "in males."
    )
    issues = scan_paper(paper, bg_lit_registry=bg_lit)
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_role_drift_fail_soft_when_source_lacks_claim_role(tmp_path):
    """Older quant_claims without claim_role → role check skipped
    (back-compat / fail-soft)."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_old.quant_claims.json").write_text(
        '{"paper_id":"PMC_old","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_old",
        "citation_token": "Older 2018",
    }]}
    paper = "Baseline gait speed 0.13 m/s (Older 2018)."
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    # Without claim_role on source, fail-soft passes
    assert drift == []
