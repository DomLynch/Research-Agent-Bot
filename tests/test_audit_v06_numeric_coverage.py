"""P1 reviewer fix regression: numeric audit must cover percentages
+ p-values + ratios + sample sizes + doses + speeds — not just
percentages. A discriminating test per category."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # type: ignore[import-not-found]  # noqa: E402


def test_p_value_untraceable_flagged() -> None:
    """A p-value that doesn't trace to corpus must lower the integrity
    score. Pre-fix this passed because only percentages were checked."""
    paper = "Treatment improved outcomes (p < 0.0007)."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.05"})
    # 0.0007 is not in corpus → should be flagged
    assert "0.0007" in msg or "p_value" in msg, msg


def test_hazard_ratio_untraceable_flagged() -> None:
    """An HR not in corpus must trip the gate."""
    paper = "Mortality reduced (HR = 0.123)."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.85"})
    assert "0.123" in msg or "ratio" in msg, msg


def test_sample_size_untraceable_flagged() -> None:
    """A sample-size n=N not in corpus must trip the gate."""
    paper = "The trial enrolled n=99999 participants."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"100"})
    assert "99999" in msg or "sample_size" in msg, msg


def test_results_summary_corpus_slice_n_is_not_sample_size() -> None:
    paper = (
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Other | n=46; claims=1335 | null signal in 36/46 sources |\n"
    )
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set())
    assert ok, msg


def test_thin_corpus_audit_does_not_require_full_manuscript_sections() -> None:
    paper = (
        "## Abstract\n\n" + "a " * 250 + "\n\n"
        "## Methods\n\n" + "m " * 300 + "\n\n"
        "## Results\n\n" + "r " * 300 + "\n\n"
        "## Limitations\n\n" + "l " * 250 + "\n\n"
        "## Conclusion\n\n" + "c " * 250 + "\n"
    )
    report = audit.audit(paper, review_type="evidence_brief")
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "Q1_word_count" not in failed
    assert "Q7_section_coverage" not in failed
    assert "Q9_numeric_density" not in failed
    assert "Q10_hedge_density" not in failed
    assert "Q11_discussion_depth" not in failed
    assert "Q12_cross_domain_depth" not in failed
    assert "Q13_analytical_ratio" not in failed


def test_dose_untraceable_flagged() -> None:
    """A dose value not in corpus must trip the gate."""
    paper = "Patients received 7777 mg of metformin daily."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"850"})
    assert "7777" in msg or "dose" in msg, msg


def test_all_traceable_passes() -> None:
    """When every numeric traces, gate passes regardless of category mix."""
    paper = (
        "Treatment improved outcomes 32% (p < 0.05). "
        "Hazard ratio HR=0.85 with n=120 patients on 850 mg/day."
    )
    corpus = {"32", "32.0", "0.05", "0.85", "120", "850"}
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=corpus)
    assert ok, msg


def test_grouped_and_brief_numerics_are_detected_and_trace() -> None:
    paper = (
        "The cohort included 26 916 participants and 26,916 matched controls. "
        "The synthesis retained 1046 tensions (p < 0.001; HR = 1.19)."
    )
    corpus = {"26916", "1046", "0.001", "1.19"}
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=corpus)
    assert ok, msg
    assert "grouped_number=" in msg
    assert "brief_count=" in msg


def test_manifest_counts_are_allowed_in_evidence_brief() -> None:
    paper = (
        "This evidence brief includes 65 source papers, "
        "1977 claims, and 1046 cross-study disagreements."
    )
    manifest = {
        "n_receipts": 65,
        "n_high_confidence_claims_total": 1977,
        "n_non_orthogonal_tensions": 1046,
    }
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest=manifest,
    )
    assert ok, msg


def test_manifest_receipt_p_values_are_traceable_structural_numerics() -> None:
    paper = "Representative statistic: P < 0.001. Secondary statistic: P = 0.044."
    manifest = {"receipts": [{"p_values": ["P < 0.001", "P = 0.044"]}]}
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set(), manifest=manifest)
    assert ok, msg


def test_source_context_map_counts_are_traceable_structural_numerics() -> None:
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
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest={"receipts": receipts},
    )
    assert ok, msg


def test_evidence_snapshot_representative_p_values_are_appendix_metadata() -> None:
    paper = (
        "## Results\n\nNo reportable p-value here.\n\n"
        "## Evidence Snapshot\n\n"
        "### Load-Bearing Included Studies\n\n"
        "- Smith 2024; representative statistic=P < 0.001.\n"
    )
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set())
    assert ok, msg


def test_percentage_still_filtered_for_trivial_values() -> None:
    """Percentages ≤1.0 (rounding artifacts) and ≥1000 (typos) are
    still skipped to keep the existing prose-noise filter."""
    paper = "Improvement was 0.5% modest with prevalence at 1500%."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set())
    # Both 0.5 and 1500 should be filtered; gate passes by vacuity.
    assert ok, msg


# ----- Fix #8 reviewer-P1: STRICT zero-tolerance gate ------------------


def test_strict_gate_one_untraceable_value_fails_q2() -> None:
    """Fix #8: zero-tolerance. Pre-fix the 90% threshold let 1 of 19
    untraceable values pass (the literal `59` in the latest E2E paper).
    Now any single untraceable numeric trips Q2."""
    paper = (
        "Mortality 32% (p < 0.05). HR=0.85, n=120, 850 mg. "
        "Plus an untraceable 59% finding."
    )
    # 59 is NOT in the corpus
    corpus = {"32", "0.05", "0.85", "120", "850"}
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=corpus)
    assert ok is False, (
        f"Strict Q2 should fail with even one untraceable: {msg}"
    )
    assert "59" in msg


def test_strict_gate_pre_fix_90_percent_threshold_no_longer_passes() -> None:
    """A paper with 18/20 traceable (90% pass rate) used to PASS at
    the old `pct_clean >= 0.9` threshold. Now it FAILS because two
    values are untraceable."""
    paper = (
        "Findings: 32%, p < 0.05, HR=0.85, n=120, 850 mg, "
        "extras 11%, 12%, 13%, 14%, 15%, 16%, 17%, 18%, 19%, 20%, "
        "21%, 22%, 23%, 24%, 25%, 99%, 88%."
    )
    corpus = {
        "32", "0.05", "0.85", "120", "850",
        "11", "12", "13", "14", "15", "16", "17", "18",
        "19", "20", "21", "22", "23", "24", "25",
        # 99 and 88 are intentionally MISSING → 2 untraceable
    }
    ok, _msg = audit._check_numeric_integrity(paper, corpus_nums=corpus)
    assert ok is False, (
        "90%-pass rate should not pass under strict gate"
    )


def test_strict_gate_all_traceable_still_passes() -> None:
    """Sanity: when every numeric traces, gate passes."""
    paper = "Treatment improved outcomes 32% (p < 0.05). HR=0.85."
    ok, _ = audit._check_numeric_integrity(
        paper, corpus_nums={"32", "0.05", "0.85"},
    )
    assert ok is True


def test_strict_gate_empty_paper_passes_vacuously() -> None:
    """Paper with zero reportable numerics → gate passes vacuously."""
    paper = "## Discussion\n\nQualitative discussion only.\n"
    ok, _ = audit._check_numeric_integrity(paper, corpus_nums=set())
    assert ok is True


# ----- Fix #12: Q9 numeric density extended pattern set ----------------


def test_q9_density_counts_hr_or_rr_ratios() -> None:
    """Pre-fix Q9 only counted percentages + p-values + speed/dose units.
    Now ratios like HR=0.85, OR 1.2, RR 0.7 also count toward density."""
    # 100-word paragraph with 2 ratios → density = 2/100*1000 = 20
    paper = " ".join(
        ["The"] * 96 + ["HR=0.85", "and", "OR=1.2", "."]
    )
    ok, msg = audit._check_numeric_density(paper, threshold=8.0)
    assert ok is True, msg
    assert "20.0" in msg or "density 20" in msg


def test_q9_density_counts_sample_size_n_eq() -> None:
    """`n=120` counts toward numeric density."""
    paper = " ".join(
        ["The"] * 99 + ["n=120"]
    )
    ok, msg = audit._check_numeric_density(paper, threshold=8.0)
    assert ok is True, msg


def test_q9_density_counts_table_cell_numerics() -> None:
    """Numerics inside markdown tables MUST count — explicit metric
    contract change. Per the reviewer's 'tables-not-paragraphs' guide."""
    table_paper = (
        "## Results\n\n"
        "| Study | Tier | N | p |\n"
        "| --- | --- | --- | --- |\n"
        "| Walton 2019 | A1 | n=120 | p < 0.001 |\n"
        "| Konopka 2019 | A1 | n=53 | p = 0.02 |\n"
        "| Witham 2025 | A1 | n=160 | p = 0.96 |\n"
    )
    # Word count of table (each row is mostly 1-word cells) = ~30 words.
    # Numerics: 3 n= + 3 p< → 6/30 *1000 = 200/1k → way over threshold.
    ok, msg = audit._check_numeric_density(table_paper, threshold=8.0)
    assert ok is True, f"Table cells should count: {msg}"


def test_q9_density_threshold_default_is_8() -> None:
    """Sanity: default threshold remains 8.0/1k."""
    # 1000-word paper with exactly 7 numerics → density 7.0 < 8.0
    paper = " ".join(["The"] * 993 + ["7%", "n=12", "HR=1.5",
                                       "p < 0.05", "8 mg",
                                       "12 weeks", "0.5 m/s"])
    ok, msg = audit._check_numeric_density(paper)
    assert ok is False
    assert "7.0" in msg


# ----- Reviewer-fix v2 on Fix #12 (P1 + P2 hardening) ------------------


def test_q9_or_does_not_match_english_word_or() -> None:
    """P1 reviewer: pre-fix `OR\\s*[=:]?\\s*\\d` matched 'OR 10' in
    prose like '5 or 10 mg' (English 'or' + space + digit). Now the
    separator `=` or `:` is mandatory."""
    # 100-word paper with prose 'or 10' that should NOT count as a ratio.
    paper = " ".join(["The"] * 98 + ["5", "or", "10", "mg"])
    ok, msg = audit._check_numeric_density(paper, threshold=20.0)
    # Should count "10 mg" once via dose pattern, not double via ratio.
    # 1 numeric in 102 words → density ≈ 9.8/1k → fails threshold 20
    assert ok is False, f"prose 'or' must not inflate count: {msg}"


def test_q9_range_pattern_does_not_match_year_ranges() -> None:
    """P1 reviewer: pre-fix `\\d+\\s*-\\s*\\d+` matched '2024-2026'
    and 'section 1-3'. Now ranges only match inside CI/range context."""
    paper = " ".join(["The"] * 95 + [
        "trials", "spanned", "2019-2025", "across", "section", "1-3",
    ])
    # No CI/range keyword → no range matches → 0 numerics
    ok, msg = audit._check_numeric_density(paper, threshold=8.0)
    assert ok is False, msg
    # Density should be 0.0 (no numerics caught)
    assert "0.0" in msg


def test_q9_range_pattern_still_matches_real_ci() -> None:
    """Real CIs in clinical context should still count."""
    paper = " ".join(["The"] * 90 + [
        "HR=0.85", "(95% CI", "0.72", "to", "0.99)", "p", "<", "0.05",
    ])
    # Counted: HR=0.85, range 0.72-0.99, p<0.05 → 3 numerics in 98 words
    # Density ≈ 30/1k → easily passes
    ok, msg = audit._check_numeric_density(paper, threshold=20.0)
    assert ok is True, msg


def test_q9_density_compares_at_reported_precision() -> None:
    paper = " ".join(["word"] * 249 + ["n=1", "n=2"])

    ok, msg = audit._check_numeric_density(paper)

    assert ok is True
    assert "density 8.0" in msg


def test_q9_contract_version_in_message() -> None:
    """Reviewer P2: metric output must surface the contract version
    so a future replay-on-old-paper can't misattribute score changes
    to paper changes."""
    paper = "## Discussion\n\nQualitative text."
    _ok, msg = audit._check_numeric_density(paper)
    assert "contract=" in msg
    assert "2026-07-10-v3" in msg


def test_q2_or_does_not_match_english_word_or() -> None:
    """Symmetric P1 fix on Q2: 'or 850 mg' must not extract 850 as
    an unverified ratio. Pre-fix it could → strict-Q2 false-fail."""
    paper = "Patients received 500 or 850 mg of metformin daily."
    # 850 should be caught as a dose (corpus has 850), NOT a ratio.
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums={"500", "850"},
    )
    assert ok is True, f"Strict Q2 should pass when 850 traces: {msg}"
    # Confirm only dose category fires (no ratio category)
    assert "ratio=" not in msg or "ratio=0/0" in msg


def test_q2_aor_irr_smr_ratios_extracted() -> None:
    """Symmetric P1 fix: aOR / IRR / SHR / SMR are real epidemiology
    ratios; Q2 should extract them and check trace."""
    paper = "Adjusted aOR=0.7, IRR=1.2, SMR=0.8 across the cohort."
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums={"0.7", "1.2", "0.8"},
    )
    assert ok is True, msg


def test_q2_allows_manifest_outcome_counts_and_tension_anchors() -> None:
    paper = (
        "The synthesis includes 171 sources and 4684 tensions. "
        "contextual other (n=83) anchors the largest class. "
        "Numeric anchors include p = 0.003 and p = 0.013."
    )
    manifest = {
        "n_receipts": 171,
        "n_non_orthogonal_tensions": 4684,
        "receipts": [{"outcome_class": "contextual_other"} for _ in range(83)],
        "_tension_plans": [{"numeric_anchors": ["p = 0.003", "p = 0.013"]}],
    }
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest=manifest,
    )
    assert ok is True, msg


def test_q2_allows_manifest_receipt_counts_tiers_directness_and_title_dose() -> None:
    paper = (
        "The evidence-tier distribution is: B2 (n=2), A1 (n=1). "
        "By directness, the breakdown is: review (n=2), direct (n=1). "
        "Smith 2024: finding=18 extracted claim(s). "
        "Uddin 2024: Real-world evidence on gliclazide MR 60 mg during fasting."
    )
    manifest = {
        "receipts": [
            {
                "evidence_tier": "B2",
                "directness": "review",
                "effect_direction": "null",
                "outcome_class": "cardiometabolic",
                "n_claims": 18,
                "source_title": "Review without dose",
            },
            {
                "evidence_tier": "B2",
                "directness": "review",
                "effect_direction": "null",
                "outcome_class": "cardiometabolic",
                "n_claims": 3,
                "source_title": "Real-world evidence on gliclazide MR 60 mg during fasting",
            },
            {
                "evidence_tier": "A1",
                "directness": "direct",
                "effect_direction": "mixed",
                "outcome_class": "safety",
                "n_claims": 4,
                "source_title": "Trial without dose",
            },
        ],
    }

    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set(), manifest=manifest)

    assert ok is True, msg


def test_q2_still_blocks_unmanifested_exact_tension_count() -> None:
    paper = "The direct sources generate 22 paired directness-gap tensions."
    manifest = {"n_non_orthogonal_tensions": 207, "receipts": []}

    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set(), manifest=manifest)

    assert ok is False
    assert "22" in msg or "brief_count" in msg


def test_q13_excludes_deterministic_evidence_landscape_bulk() -> None:
    paper = (
        "## Evidence Landscape\n\n" + ("maprow " * 4000) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + ("cross " * 850) + "\n\n"
        "## Discussion\n\n" + ("discussion " * 850) + "\n\n"
        "## Results\n\n" + ("result " * 800) + "\n"
    )

    ok, msg = audit._check_analytical_ratio(paper)

    assert ok is True, msg


def test_reference_title_grouped_number_not_audited() -> None:
    """A cited paper's title sample size lives in References and is
    bibliographic, not a synthesis claim — it must not fail Q2 tracing.
    Regression for the live blocker where '435,046'/'88,000' in reference
    titles dragged numeric coverage below 1.000."""
    paper = (
        "## Abstract\n\nThe effect was positive (p < 0.05).\n\n"
        "## References\n\n"
        "- Liu 2023. Telomere length and dementia risk: an observational "
        "and mendelian randomization study of 435,046 UK Biobank "
        "participants. Aging Cell, 2023.\n"
    )
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.05"})
    assert ok is True, msg
    assert "435,046" not in msg


def test_major_claim_trace_source_span_numerics_are_not_authored_claims() -> None:
    claim = "The bounded result was source-linked (p < 0.05) [bundle:1]."
    span = "Participants were 69.8% female and 79.2% white."
    row = {
        "citation_token": "Smith 2024",
        "directness": "direct",
        "evidence_tier": "A1",
        "source_doi": "10.1/x",
        "thesis_text": span,
    }
    paper = (
        f"## Results\n\n{claim}\n\n"
        "## Major Claim Trace\n\n"
        f"- **Manuscript claim 1.** {claim} "
        "**Supporting source:** Smith 2024 [bundle:1] https://doi.org/10.1/x "
        f"**Evidence span:** {span}\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums={"0.05"}, manifest={"receipts": [row]},
    )

    assert ok is True, msg
    assert "69.8" not in msg
    assert "79.2" not in msg


def test_forged_major_claim_trace_numeric_still_fails_q2() -> None:
    paper = (
        "## Results\n\nA bounded result was reported (p < 0.05) [bundle:1].\n\n"
        "## Major Claim Trace\n\n"
        "- **Manuscript claim 1.** Fabricated result [bundle:999]. "
        "**Supporting source:** Unknown 2024 [bundle:999] "
        "**Evidence span:** Fabricated response was 99.9%.\n"
    )
    manifest = {"receipts": [{
        "citation_token": "Smith 2024",
        "thesis_text": "Validated source span.",
    }]}

    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums={"0.05"}, manifest=manifest,
    )

    assert ok is False
    assert "99.9" in msg


def test_extra_numeric_appended_to_valid_trace_support_fails_q2() -> None:
    claim = "A bounded result was reported (p < 0.05) [bundle:1]."
    span = "Validated source span."
    paper = (
        f"## Results\n\n{claim}\n\n"
        "## Major Claim Trace\n\n"
        f"- **Manuscript claim 1.** {claim} "
        "**Supporting source:** Smith 2024 [bundle:1] "
        "https://doi.org/10.1/x fabricated=99.9% "
        f"**Evidence span:** {span}\n"
    )
    manifest = {"receipts": [{
        "citation_token": "Smith 2024",
        "receipt_id": "smith",
        "source_doi": "10.1/x",
        "thesis_text": span,
    }]}

    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums={"0.05"}, manifest=manifest,
    )

    assert ok is False
    assert "99.9" in msg


def test_body_grouped_number_still_audited() -> None:
    """An untraceable grouped number in the body (not References) still
    trips the gate — the References exclusion must not weaken body tracing."""
    paper = (
        "## Results\n\nThe pooled analysis covered 435,046 participants.\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.05"})
    assert ok is False
    assert "435,046" in msg or "grouped_number" in msg, msg
