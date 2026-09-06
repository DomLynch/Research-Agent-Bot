"""Unit tests for scripts/numeric_role_guard.py — universal class-
level fix for numeric mis-interpretation patterns. Tests synthetic
examples spanning gait speed, BMI, BP, dose, duration to verify
topic-agnostic behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from numeric_role_guard import (  # type: ignore[import-not-found]  # noqa: E402
    auto_strip_offending_sentences,
    repair_source_context_drift_sentences,
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
    assert _check_arithmetic_violations(
        "A 0.13 m/s change at week 24 is below 0.1 m/s."
    ) is not None
    assert _check_arithmetic_violations(
        "The assay is below the limit, but 0.13 m/s is below 0.1 m/s."
    ) is not None
    assert _check_arithmetic_violations("Allocation was 1:2 and 20 mg is below 10 mg.") is not None
    assert _check_arithmetic_violations("A level of 20 mg/L is below 10 mg/L.") is not None


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


def test_arithmetic_does_not_bind_duration_to_p_value():
    for p_value in ("P <= 0.03", "*P* <= 0.03", "**P** <= 0.03", "_P_ <= 0.03", "p-value <= 1e-3"):
        assert _check_arithmetic_violations(f"Mean at 24 hours ({p_value}).") is None
    assert _check_arithmetic_violations("A score of 13 at week 24 is below 10.") is None
    assert _check_arithmetic_violations("A duration of 24 months is below 18 months.") is None
    assert _check_arithmetic_violations("At 24 months, the value is below 18 months.") is None
    assert _check_arithmetic_violations("A change of -0.13 m/s is below 0.1 m/s.") is None
    assert _check_arithmetic_violations("A level of 20 mg/L is below 10 mg/dL.") is None
    assert _check_arithmetic_violations(
        "A 0.05 m/s change at week 24 is below 0.1 m/s."
    ) is None
    assert _check_arithmetic_violations("A dose of 1e-3 mg is below 0.01 mg.") is None
    assert _check_arithmetic_violations(
        "A dose of 20 mg (95% CI 10-30 mg) is below 25 mg."
    ) is None
    assert _check_arithmetic_violations("A dose of 1,000 mg is above 500 mg.") is None
    assert _check_arithmetic_violations("A dose of 1 000 mg is above 500 mg.") is None
    assert _check_arithmetic_violations("A dose of 1,000.5 mg is above 500 mg.") is None
    assert _check_arithmetic_violations("A change of −0.13 m/s is below 0.1 m/s.") is None
    assert _check_arithmetic_violations("A dose of 2 mg·L−1 is below 10 mg.") is None
    assert _check_arithmetic_violations("A dose of 20 mg per week is below 10 mg per day.") is None
    for quantity in ("20 ± 2 mg", "1/2 mg", "10–20 mg", "about 20 mg", "approximately 20 mg"):
        assert _check_arithmetic_violations(f"A dose of {quantity} is above 10 mg.") is None
    assert _check_arithmetic_violations("A dose of 20 mg weekly is below 10 mg daily.") is None
    assert _check_arithmetic_violations("A dose of 20 mg per 24 hours is below 10 mg per day.") is None
    assert _check_arithmetic_violations("A dose of 20 mg is not below 10 mg.") is None
    assert _check_arithmetic_violations("A dose of 20 mg is not greater than 30 mg.") is None


def test_arithmetic_supports_unambiguous_scientific_notation():
    issue = _check_arithmetic_violations("A dose of 1e-2 mg is below 1e-3 mg.")
    assert issue is not None
    assert issue.issue_type == "arithmetic_violation"


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


def test_source_context_drift_skips_compiler_source_rows(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "study.quant_claims.json").write_text(
        '{"paper_id":"study","claims":[{'
        '"numeric_values":[4],"binding_confidence":"high",'
        '"claim_type":"unit_value","claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "study",
        "receipt_id": "study",
        "citation_token": "Smith 2024a",
        "outcome_class": "clinical",
        "endpoints": ["endpoint"],
        "effect_direction": "positive",
        "directness": "direct",
        "evidence_tier": "A1",
        "spar_verdict": "accept_clean",
        "n_failed_traces": 0,
        "n_claims": 1,
        "source_doi": "10.1000/example",
        "thesis_text": "source excerpts: The treatment reduced the endpoint by 5%.",
    }]}
    paper = (
        "Clinical remains a separate Results slice. Source-level findings are:\n"
        "- Smith 2024 (representative statistic 50 mg; source-level statistic reported).\n\n"
        "Smith 2024a [bundle:1] reports: The treatment reduced the endpoint by 5% "
        "[exact source: https://doi.org/10.1000/example].\n\n"
        "Smith 2024a [bundle:1] reports: The treatment reduced the endpoint by 50% "
        "[exact source: https://doi.org/10.1000/example].\n\n"
        "Reviewer-classification audit uses the map below.\n\n"
        "### Source Classification Map\n\n"
        "- Smith 2024: outcome=clinical; direction=positive; directness=direct; tier=A1.\n\n"
        "### Findings Map\n\nAll 53 rows remain visible.\n\n"
        "## Limitations\n\nThe narrative remains source-bounded."
    )

    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )

    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert len(drift) == 1 and "50%" in drift[0].sentence


def test_source_context_drift_ignores_citation_identifiers(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "study.quant_claims.json").write_text(
        '{"paper_id":"study","claims":[{'
        '"numeric_values":[5],"binding_confidence":"high",'
        '"claim_role":"effect"},{"numeric_values":[10],'
        '"binding_confidence":"high","claim_role":"threshold"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "study", "citation_token": "Smith 2024",
    }]}
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "Smith 2024 reported a 5% change [bundle:16] that is below "
        "10% [exact source: https://doi.org/10.1000/20mg]."
    )
    issues = scan_paper(paper, manifest=manifest, quant_claims_dir=qc_dir)
    fixed, n = auto_strip_offending_sentences(paper, issues)
    assert not issues and n == 0
    assert "## Cross-Domain Synthesis" in fixed


def test_source_context_drift_ignores_biomedical_identifiers_not_quantities():
    from numeric_role_guard import _check_source_context_drift

    sources = {"Smith 2025": {"0.05": {"effect"}}}
    for label in ("FGF-21", "FGF-23", "type 2 diabetes", "type 1 diabetes"):
        text = f"Smith 2025 studied {label} (P < 0.05)."
        assert _check_source_context_drift(text, sources) is None
        assert _check_source_context_drift(text + " A reduction of 99% was reported by Smith 2025.", sources)
    assert _check_source_context_drift("Smith 2025 measured FGF 80 pg/mL.", sources)


def test_source_context_drift_validates_exact_manifest_bullets():
    from journal_finalizer import _manifest_source_finding_line
    from numeric_role_guard import _strip_compiler_source_finding_lines

    rows = [{
        "citation_token": "Smith 2025", "source_title": "Serum FGF-21 responses",
        "n_claims": 8, "outcome_class": "cardiometabolic",
        "effect_direction": "unclear", "directness": "direct", "evidence_tier": "A1",
    }]
    trusted = "- " + _manifest_source_finding_line(rows[0]) + "."
    rendered = trusted.replace("Smith 2025", "Smith 2025 [bundle:1]")
    forged = rendered.replace("8 extracted", "80 extracted")
    prose = "Smith 2025 reported a reduction of 99%."
    checked = _strip_compiler_source_finding_lines("\n\n".join((rendered, forged, prose)), {"receipts": rows})
    assert rendered not in checked
    assert forged in checked and prose in checked


def test_source_context_drift_skips_compiler_manifest_synthesis_blocks(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "study.quant_claims.json").write_text(
        '{"paper_id":"study","claims":[{'
        '"numeric_values":[5],"binding_confidence":"high",'
        '"claim_type":"unit_value","claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "study",
        "citation_token": "Smith 2024",
    }]}
    paper = (
        "## Evidence Landscape\n\n"
        "Substantive evidence synthesis: The manifest includes 53 retained sources. "
        "Smith 2024 anchors the generated map.\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis:\n\n"
        "Outcome-class key findings:\n\n"
        "- Smith 2024: generated claims=53.\n\n"
        "Synthesis interpretation: The 53 manifest rows bound the conclusion.\n\n"
        "## Limitations\n\nNo hard endpoint was available.\n\n"
        "## Conclusion\n\n"
        "Substantive conclusion for the topic: 53 sources were retained.\n\n"
        "The conclusion remains bounded."
    )

    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )

    assert not [i for i in issues if i.severity == "P1"]


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


def test_source_context_drift_skips_closest_unknown_citation(tmp_path):
    """If a numeric is closest to an unregistered guideline/canon cite,
    do not assign it to a farther registered receipt citation."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_majeed.quant_claims.json").write_text(
        '{"paper_id":"PMC_majeed","claims":[{'
        '"numeric_values":[6.52,0.19,0.001],'
        '"binding_confidence":"high","claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_majeed",
        "citation_token": "Majeed 2021",
    }]}
    paper = (
        "Majeed 2021 reported HbA1c reductions, consistent with the "
        "ADA 2024 target of 7% for most adults with diabetes."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_skips_post_numeric_unknown_citation(tmp_path):
    """A numeric followed by its own unknown/canon citation should not
    be charged to an earlier registered citation in the same sentence."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_anisimov.quant_claims.json").write_text(
        '{"paper_id":"PMC_anisimov","claims":[{'
        '"numeric_values":[14],"binding_confidence":"high",'
        '"claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_anisimov",
        "citation_token": "Anisimov 2011",
    }]}
    paper = (
        "Anisimov 2011 reported a 14% increase, consistent with the "
        "canonical 5% benchmark (Anisimov 2008)."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_ignores_cited_footer_lines(tmp_path):
    """Rendered `_Cited:` footers are metadata, not prose sentences."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_yang.quant_claims.json").write_text(
        '{"paper_id":"PMC_yang","claims":[{'
        '"numeric_values":[6],"binding_confidence":"high",'
        '"claim_role":"background"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_yang",
        "citation_token": "Yang 2023",
    }]}
    paper = (
        "The matrix contains 283 tensions.\n\n"
        " _Cited: `Yang 2023`_\n\n"
        "## Methods\n\n"
        "This was produced by v0.6."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
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


def test_numeric_contract_allows_hedge_with_inline_canonical_value():
    bg_lit = {
        "smith_response": {
            "citation_token": "Smith 2020",
            "numeric": "52%",
            "context": "response proportion",
        },
    }
    paper = (
        "Smith 2020 reported around 50% (52%) of participants "
        "meeting the response threshold."
    )
    issues = scan_paper(paper, manifest={}, bg_lit_registry=bg_lit)
    assert not [
        i for i in issues
        if i.issue_type in {
            "source_context_drift", "numeric_claim_contract",
        }
    ]


def test_numeric_contract_blocks_unanchored_hedged_unregistered_value(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_weight.quant_claims.json").write_text(
        '{"paper_id":"PMC_weight","claims":[{'
        '"numeric_values":[93,90.8,0.001],'
        '"binding_confidence":"high","claim_role":"effect"},{'
        '"numeric_values":[91],'
        '"binding_confidence":"high","claim_role":"unknown"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_weight",
        "citation_token": "Weight 2024",
    }]}
    paper = (
        "Short-term caloric restriction lowered body weight from "
        "approximately 93 to 91 kg (P < 0.001)."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    found = [i for i in issues if i.issue_type == "numeric_claim_contract"]
    assert found and "91" in found[0].detail


def test_numeric_contract_blocks_editorial_fraction_without_exact_value():
    bg_lit = {
        "smith_response": {
            "citation_token": "Smith 2020",
            "numeric": "31%",
            "context": "response proportion",
        },
    }
    paper = (
        "Smith 2020 reported approximately one-third of participants "
        "meeting the response threshold."
    )
    issues = scan_paper(paper, manifest={}, bg_lit_registry=bg_lit)
    found = [i for i in issues if i.issue_type == "numeric_claim_contract"]
    assert found and found[0].severity == "P1"


def test_numeric_contract_allows_editorial_fraction_with_exact_value():
    bg_lit = {
        "smith_response": {
            "citation_token": "Smith 2020",
            "numeric": "31%",
            "context": "response proportion",
        },
    }
    paper = (
        "Smith 2020 reported approximately one-third (31%) of "
        "participants meeting the response threshold."
    )
    issues = scan_paper(paper, manifest={}, bg_lit_registry=bg_lit)
    assert not [i for i in issues if i.severity == "P1"]


def test_numeric_range_contract_allows_supported_citation_set():
    bg_lit = {
        "smith": {
            "citation_token": "Smith 2020",
            "numeric": "8.2%",
            "context": "mortality change",
        },
        "jones": {
            "citation_token": "Jones 2021",
            "numeric": "11%",
            "context": "mortality change",
        },
        "lee": {
            "citation_token": "Lee 2022",
            "numeric": "14.8%",
            "context": "mortality change",
        },
    }
    paper = (
        "Smith 2020, Jones 2021, and Lee 2022 reported effects "
        "within an 8-15% range."
    )
    issues = scan_paper(paper, manifest={}, bg_lit_registry=bg_lit)
    assert not [i for i in issues if i.issue_type == "source_context_drift"]


def test_numeric_range_contract_blocks_unsupported_range():
    bg_lit = {
        "smith": {
            "citation_token": "Smith 2020",
            "numeric": "8.2%",
            "context": "mortality change",
        },
        "jones": {
            "citation_token": "Jones 2021",
            "numeric": "11%",
            "context": "mortality change",
        },
        "lee": {
            "citation_token": "Lee 2022",
            "numeric": "14.8%",
            "context": "mortality change",
        },
    }
    paper = (
        "Smith 2020, Jones 2021, and Lee 2022 reported effects "
        "within an 8-10% range."
    )
    issues = scan_paper(paper, manifest={}, bg_lit_registry=bg_lit)
    assert [i for i in issues if i.issue_type == "source_context_drift"]


def test_source_context_drift_handles_leading_decimal_p_values(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "walton.quant_claims.json").write_text(
        '{"paper_id":"walton","claims":[{'
        '"numeric_values":[0.003],"binding_confidence":"high",'
        '"claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "walton",
        "citation_token": "Walton 2019",
    }]}
    paper = "Walton 2019 reported lean-mass differences (p = .003)."
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_source_context_drift_skips_deterministic_tables(tmp_path):
    """QEI / structured evidence tables are numeric matrices, not
    prose. The role guard must skip them to avoid false drift checks
    and large-corpus quadratic scans."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high","claim_role":"change_score"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_witham",
        "citation_token": "Witham 2025",
    }]}
    paper = (
        "## Quantitative Evidence Index — metformin\n\n"
        "| Study | Endpoint | Value |\n"
        "|---|---|---|\n"
        "| Witham 2025 | baseline gait speed | 0.13 m/s |\n\n"
        "## Results\n\n"
        "Witham 2025 reported no clear functional improvement."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_untraceable_numeric_guard_skips_inline_markdown_tables(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    manifest = {"receipts": []}
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice |\n"
        "|---|---|\n"
        "| Other | n=46; claims=1335 |\n\n"
        "The synthesis remains bounded."
    )
    issues = scan_paper(paper, manifest=manifest, quant_claims_dir=qc_dir)
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_untraceable_numeric_guard_skips_what_this_adds_evidence_lists(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    manifest = {"receipts": []}
    paper = (
        "## What This Synthesis Adds\n\n"
        "### Load-Bearing Included Studies\n\n"
        "- Meattini 2025; RCT; representative statistic=P < 0.001.\n"
        "- Mostaza 2022; Observational; representative statistic=P = 0.044.\n\n"
        "## Discussion\n\n"
        "The synthesis remains bounded."
    )
    issues = scan_paper(paper, manifest=manifest, quant_claims_dir=qc_dir)
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_untraceable_numeric_guard_skips_evidence_snapshot_lists(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    paper = (
        "## Evidence Snapshot\n\n"
        "### Load-Bearing Included Studies\n\n"
        "- Meattini 2025; RCT; representative statistic=P < 0.001.\n"
        "- Mostaza 2022; Observational; representative statistic=P = 0.044.\n\n"
        "## Discussion\n\n"
        "The synthesis remains bounded."
    )
    issues = scan_paper(paper, manifest={"receipts": []}, quant_claims_dir=qc_dir)
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_untraceable_numeric_guard_blocks_citationless_prose_value(tmp_path):
    """Q2-blocking numerics must be stripped even when the sentence
    names an author without an exact Author-Year citation token."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_keech.quant_claims.json").write_text(
        '{"paper_id":"PMC_keech","claims":[{'
        '"claim_type":"unit_value","numeric_values":[12.3,24,0.001],'
        '"binding_confidence":"high","claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_keech",
        "citation_token": "Keech 2003",
    }]}
    paper = (
        "Keech et al. showed pravastatin reduced major coronary "
        "heart disease events from 15.9% to 12.3% "
        "(relative risk reduction 24%, P < 0.001)."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    found = [i for i in issues if i.issue_type == "untraceable_numeric"]
    assert found
    assert "15.9" in found[0].detail
    fixed, n = auto_strip_offending_sentences(paper, issues)
    assert n == 1
    assert "15.9%" not in fixed


def test_untraceable_numeric_guard_blocks_grouped_number(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    paper = "The cohort included 26 916 participants without source trace."
    manifest = {"n_receipts": 65, "receipts": []}
    issues = scan_paper(paper, manifest=manifest, quant_claims_dir=qc_dir)
    found = [i for i in issues if i.issue_type == "untraceable_numeric"]
    assert found
    assert "26 916" in found[0].detail


def test_untraceable_numeric_guard_allows_manifest_brief_counts(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    manifest = {
        "n_receipts": 65,
        "n_high_confidence_claims_total": 1977,
        "n_non_orthogonal_tensions": 1046,
        "receipts": [],
    }
    paper = (
        "This evidence brief includes 65 source papers, "
        "1977 claims, and 1046 cross-study disagreements."
    )
    issues = scan_paper(paper, manifest=manifest, quant_claims_dir=qc_dir)
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_untraceable_numeric_guard_allows_source_context_counts(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    paper = (
        "Oncology and cancer context: 17 sources; significant source "
        "statistic in 8/17 sources; receipt-level direction coded null."
    )
    receipts = [
        {
            "source_title": f"Everolimus oncology cancer study {i}",
            "effect_direction": "null",
            "p_values": ["p < 0.05"] if i < 8 else [],
        }
        for i in range(17)
    ]
    issues = scan_paper(
        paper, manifest={"receipts": receipts}, quant_claims_dir=qc_dir,
    )
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_untraceable_numeric_guard_allows_compiler_owned_summary_counts(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    receipts = [
        {
            "outcome_class": "clinical",
            "effect_direction": "positive" if i < 2 else "null",
            "directness": "direct" if i < 2 else "indirect",
            "n_claims": i + 4,
        }
        for i in range(3)
    ]
    paper = (
        "Clinical: n=3; claims=15; benefit signal in 2/3 sources; "
        "directness: 2 direct; 1 indirect."
    )
    issues = scan_paper(
        paper, manifest={"receipts": receipts}, quant_claims_dir=qc_dir,
    )
    assert [i for i in issues if i.issue_type == "untraceable_numeric"] == []


def test_scan_paper_back_compat_no_kwargs_works():
    """Existing callers passing only paper_md (no manifest /
    bg_lit) keep working — drift check is silently disabled."""
    paper = "The paper says 5 mg of compound."
    issues = scan_paper(paper)
    # No drift check ran (registry empty)
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


def test_no_change_with_nonzero_parenthetical_unit_is_p1():
    paper = (
        "The trial found no change in walk speed (0.13 m/s) over "
        "follow-up."
    )
    issues = scan_paper(paper)
    found = [
        i for i in issues
        if i.issue_type == "no_change_nonzero_parenthetical"
    ]
    assert found and found[0].severity == "P1"


def test_no_change_with_p_value_parenthetical_is_allowed():
    paper = "The trial found no significant change in walk speed (p = 0.13)."
    issues = scan_paper(paper)
    found = [
        i for i in issues
        if i.issue_type == "no_change_nonzero_parenthetical"
    ]
    assert found == []


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


def test_role_drift_flags_leading_citation_baseline_drift(tmp_path):
    """Sentence-opening citations govern later numerics too."""
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high","claim_role":"effect"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_witham",
        "citation_token": "Witham 2025",
    }]}
    paper = (
        "Witham 2025 reported placebo groups showed no change in "
        "frailty status and no change in walk speed, with a baseline "
        "walk speed of 0.13 m/s in the placebo arm."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift, "leading-citation role drift should fire"
    assert "baseline" in drift[0].detail.lower()
    assert "effect" in drift[0].detail.lower()


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


def test_role_drift_repair_rewrites_to_source_role(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high","claim_role":"change_score"}]}'
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
    fixed, n = repair_source_context_drift_sentences(
        paper, issues, manifest=manifest, quant_claims_dir=qc_dir,
    )
    assert n == 1
    assert "change of 0.13 m/s" in fixed
    assert not scan_paper(
        fixed, manifest=manifest, quant_claims_dir=qc_dir,
    )


def test_role_drift_repair_skips_unitless_dose_artifact(tmp_path):
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_dose.quant_claims.json").write_text(
        '{"paper_id":"PMC_dose","claims":[{'
        '"claim_type":"unit_value","numeric_values":[4],'
        '"binding_confidence":"high","claim_role":"dose"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_dose",
        "citation_token": "Kell 2026",
    }]}
    paper = "Kell 2026 reported an effect of 4 (Kell 2026)."
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    fixed, n = repair_source_context_drift_sentences(
        paper, issues, manifest=manifest, quant_claims_dir=qc_dir,
    )
    assert n == 0
    assert fixed == paper


def test_role_drift_passes_when_prose_uses_source_dose(tmp_path):
    """Dose numerics near a valid citation are not role drift.

    This keeps the guard from falsely blocking sentences like
    "liraglutide 1.8 mg reduced HbA1c" when the cited source tags
    1.8 mg as a dose.
    """
    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_glp1.quant_claims.json").write_text(
        '{"paper_id":"PMC_glp1","claims":[{'
        '"claim_type":"unit_value","numeric_values":[1.8],'
        '"binding_confidence":"high","claim_role":"dose"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_glp1",
        "citation_token": "Russell-Jones 2009",
    }]}
    paper = (
        "Russell-Jones 2009 found that liraglutide 1.8 mg "
        "reduced HbA1c versus placebo."
    )
    issues = scan_paper(
        paper, manifest=manifest, quant_claims_dir=qc_dir,
    )
    drift = [i for i in issues if i.issue_type == "source_context_drift"]
    assert drift == []


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


def test_duration_numeric_not_classified_as_population():
    """Item 6b: a numeric followed by a time unit is a study DURATION, never a
    participant count — 'enrolled ... over 12 months' must not render as a
    population descriptor. Ages ('aged 65 years') stay population."""
    from numeric_role_guard import _classify_prose_numeric_role as role  # noqa: PLC0415

    def r(sent, num):
        return role(sent, sent.index(num), num)

    # durations must NOT be population
    assert r("Monda 2026 enrolled 400 adults over 12 months", "12") != "population"
    assert r("a 12-month randomized trial enrolled patients", "12") != "population"
    assert r("Recruited 150 subjects for 6 weeks", "6") != "population"
    # genuine counts + ages stay population
    assert r("Monda 2026 enrolled 400 adults over 12 months", "400") == "population"
    assert r("older adults aged 65 years received it", "65") == "population"
    assert r("a cohort of 65-year-old participants", "65") == "population"
    # plural "years old" with a population cue must stay population (is_age
    # broadening) — not be skipped as a duration
    assert r("participants 65 years old at entry", "65") == "population"
