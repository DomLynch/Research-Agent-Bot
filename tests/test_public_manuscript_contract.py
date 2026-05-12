"""Tests for agent.public_manuscript_contract — final-render gate.

Stdlib-only, no LLM. Two of the assertions use the actual fresh
synthesis runs as golden-fail fixtures so the contract is anchored to
real regressions, not synthetic toy strings.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.public_manuscript_contract import (  # type: ignore[import-not-found]
    CanonicalCounts,
    ContractFailure,
    FORBIDDEN_PHRASES,
    validate,
    validate_run_dir,
    write_sidecar,
)


# ---- canonical counts ---------------------------------------------------


def test_canonical_counts_from_manifest() -> None:
    m = {
        "n_receipts": 40,
        "n_high_confidence_claims_total": 173,
        "n_non_orthogonal_tensions": 153,
    }
    c = CanonicalCounts.from_manifest(m)
    assert c.source_papers == 40
    assert c.high_confidence_claims == 173
    assert c.tensions == 153
    assert c.accepted_papers == 40
    assert c.accepted_publications == 40


def test_canonical_counts_from_manifest_with_spar_rejects() -> None:
    m = {
        "n_receipts": 3,
        "n_accepted_receipts": 2,
        "n_quarantined_receipts": 1,
        "receipts": [
            {"receipt_id": "r1", "citation_token": "Walton 2019"},
            {"receipt_id": "r2", "citation_token": "Walton 2019"},
            {"receipt_id": "r3", "citation_token": "Rejected 2020"},
        ],
    }
    c = CanonicalCounts.from_manifest(m, {"r3": "reject_direction_mismatch"})
    assert c.source_papers == 3
    assert c.accepted_papers == 2
    assert c.rejected_papers == 1
    assert c.accepted_publications == 1


def test_canonical_counts_missing_keys_default_zero() -> None:
    c = CanonicalCounts.from_manifest({})
    assert c.source_papers == c.high_confidence_claims == c.tensions == 0


# ---- rule 1: count consistency ------------------------------------------


def _baseline_manifest(**over) -> dict:
    base = {
        "n_receipts": 40,
        "n_high_confidence_claims_total": 173,
        "n_non_orthogonal_tensions": 153,
        "receipts": [],
    }
    base.update(over)
    return base


def test_count_consistency_passes_when_all_match() -> None:
    md = "## Methods\n\nWe analysed 40 source papers and 173 claims.\n"
    r = validate(md, _baseline_manifest())
    assert r.status == "PASS"


def test_count_consistency_accepts_dual_count_total_or_accepted() -> None:
    """Wave 24: paper/receipt counts may match EITHER n_receipts (total
    screened) OR n_accepted_receipts (post-SPAR accepted). Both are
    honest — they refer to different surfaces. Universal."""
    manifest = _baseline_manifest(
        n_receipts=43, n_accepted_receipts=28,
    )
    # Saying "28 accepted receipts" should pass.
    md_accepted = "## Methods\n\nWe analysed 28 accepted receipts.\n"
    r1 = validate(md_accepted, manifest)
    rules1 = {f.rule for f in r1.failures}
    assert "count_consistency" not in rules1, f"unexpected: {r1.failures}"
    # Saying "43 source papers" should also pass (total screened).
    md_total = "## Methods\n\nWe analysed 43 source papers.\n"
    r2 = validate(md_total, manifest)
    rules2 = {f.rule for f in r2.failures}
    assert "count_consistency" not in rules2, f"unexpected: {r2.failures}"
    # Saying "30" (neither) should fail.
    md_bad = "## Methods\n\nWe analysed 30 source papers.\n"
    r3 = validate(md_bad, manifest)
    assert any(f.rule == "count_consistency" for f in r3.failures)


def test_count_consistency_rejects_accepted_label_with_source_count() -> None:
    manifest = _baseline_manifest(
        n_receipts=43, n_accepted_receipts=26, n_quarantined_receipts=17,
    )
    md = (
        "## Appendix\n\n"
        "The appendix contains 43 accepted high-confidence receipt papers.\n"
    )
    r = validate(md, manifest)
    assert any(f.rule == "count_consistency" for f in r.failures)


def test_count_consistency_ignores_severity_scored_tensions() -> None:
    md = (
        "## Results\n\nThe matrix identified 30 non-orthogonal tensions. "
        "A severity-5 tension remained clinically important.\n"
    )
    r = validate(md, _baseline_manifest(n_non_orthogonal_tensions=30))
    assert not any(f.rule == "count_consistency" for f in r.failures)


def test_count_consistency_enforces_rejected_count() -> None:
    manifest = _baseline_manifest(
        n_receipts=43, n_accepted_receipts=26, n_quarantined_receipts=17,
    )
    md_good = "## Methods\n\nThe run quarantined 17 rejected receipts.\n"
    assert validate(md_good, manifest).status == "PASS"
    md_bad = "## Methods\n\nThe run quarantined 11 rejected receipts.\n"
    assert any(
        f.rule == "count_consistency"
        for f in validate(md_bad, manifest).failures
    )


def test_count_consistency_flags_paper_count_mismatch() -> None:
    md = "## Abstract\n\nWe analysed 20 studies of the topic.\n"
    r = validate(md, _baseline_manifest())
    assert r.status == "FAIL"
    rules = {f.rule for f in r.failures}
    assert "count_consistency" in rules


def test_count_consistency_filters_year_tokens() -> None:
    """4-digit years 1900–2100 must not be flagged as paper counts.

    'Yang 2023 study may not be comparable' must not be read as a claim
    that there are 2023 papers in the corpus."""
    md = (
        "## Methods\n\nThe Yang 2023 study analysed 40 source papers.\n"
        "Smith 1999 study reviewed prior work.\n"
    )
    r = validate(md, _baseline_manifest())
    # 2023 and 1999 are years; only 40 is a real paper claim, matches canon.
    assert r.status == "PASS", f"unexpected fails: {r.failures}"


def test_count_consistency_filters_small_per_section_noise() -> None:
    """Per-section figures < 5 are noise (e.g. 'in 3 RCTs the direction
    was negative'); the contract only enforces top-line summary totals."""
    md = (
        "## Results\n\nIn 3 RCTs the effect was negative; in 2 papers it was "
        "positive.\nThe full corpus comprises 40 source papers.\n"
    )
    r = validate(md, _baseline_manifest())
    assert r.status == "PASS"


def test_count_consistency_ignores_subgroup_k_counts() -> None:
    md = (
        "## Results\n\n"
        "The cardiometabolic subgroup comprises k=6 studies, while the "
        "full corpus comprises 40 source papers.\n"
    )
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "count_consistency" for f in r.failures)


def test_count_consistency_flags_receipt_mismatch() -> None:
    """Rapa-style: '21 accepted receipts' when canonical is 40."""
    md = "## Methods\n\nThe analysis pooled 21 accepted receipts.\n"
    r = validate(md, _baseline_manifest())
    assert r.status == "FAIL"
    assert any(f.rule == "count_consistency" for f in r.failures)


def test_results_subsection_completeness_blocks_empty_or_missing_outcomes() -> None:
    md = (
        "# Research Synthesis: Topic — full paper\n\n"
        "## Abstract\n\nSummary.\n\n## Introduction\n\nIntro.\n\n"
        "## Background\n\nBg.\n\n## Methods\n\nMethods.\n\n"
        "## Results\n\n### Cardiometabolic Outcomes\n\n"
        + " ".join(f"word{i}" for i in range(190))
        + " Smith 2020. Jones 2021.\n\n"
        "### Longevity and Lifespan Outcomes\n\n\n"
        "## Cross-Domain Synthesis\n\nSynthesis.\n\n"
        "## Metabolic-Functional Tradeoff Framework\n\n"
        "| Layer | Evidence example | Supports | Cannot support |\n"
        "|---|---|---|---|\n| A | B | C | D |\n\n"
        "## Discussion\n\nDiscuss.\n\n## Limitations\n\nLimit.\n\n"
        "## Conclusion\n\nClose.\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Smith 2020", "outcome_class": "cardiometabolic"},
        {"receipt_id": "r2", "citation_token": "Jones 2021", "outcome_class": "cardiometabolic"},
        {"receipt_id": "r3", "citation_token": "Walton 2019", "outcome_class": "muscle_function", "directness": "direct", "tier": "A1"},
        {"receipt_id": "r4", "citation_token": "Anisimov 2010", "outcome_class": "longevity"},
        {"receipt_id": "r5", "citation_token": "Cabreiro 2013", "outcome_class": "longevity"},
    ])
    r = validate(md, manifest)
    details = "\n".join(f.detail for f in r.failures)
    assert any(f.rule == "section_outcome_integrity" for f in r.failures)
    assert "Longevity and Lifespan Outcomes" in details
    assert "muscle_function" in details


def test_framework_integrity_requires_real_heading_not_abstract_sentence() -> None:
    md = (
        "# Research Synthesis: Topic — full paper\n\n"
        "## Abstract\n\nWe propose a Metabolic-Functional Tradeoff Framework "
        "showing the evidence is bounded.\n\n"
        "## Introduction\n\nIntro.\n\n## Background\n\nBg.\n\n"
        "## Methods\n\nMethods.\n\n## Results\n\nResult.\n\n"
        "## Discussion\n\nDiscuss.\n\n## Limitations\n\nLimit.\n\n"
        "## Conclusion\n\nClose.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "framework_integrity"
        and "framework section missing" in f.detail
        for f in r.failures
    )


# ---- rule 2: duplicate rows ---------------------------------------------


_DUP_TABLE_HEAD = (
    "## Included Studies\n\n"
    "| Citation | Design | Tier | N | Population |\n"
    "| --- | --- | --- | --- | --- |\n"
)


def test_duplicate_row_flags_byte_identical_rows() -> None:
    md = (
        _DUP_TABLE_HEAD
        + "| Walton 2019 | RCT | A1 | 49 | older adults |\n"
        + "| Walton 2019 | RCT | A1 | 49 | older adults |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Walton 2019"},
        {"receipt_id": "r2", "citation_token": "Walton 2019"},
    ])
    r = validate(md, manifest)
    assert r.status == "FAIL"
    assert any("byte-identical" in f.detail for f in r.failures)


def test_duplicate_row_allows_legitimate_split() -> None:
    """Manifest has 2 receipts under one citation, MD renders 2
    differing rows → legitimate split, no failure."""
    md = (
        _DUP_TABLE_HEAD
        + "| Walton 2019 | RCT | A1 | 49 | older adults |\n"
        + "| Walton 2019 | RCT | A1 | 49 | adults [secondary endpoint] |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Walton 2019"},
        {"receipt_id": "r2", "citation_token": "Walton 2019"},
    ])
    r = validate(md, manifest)
    # No duplicate_row failure — the split is legitimate AND rows differ.
    rules = {f.rule for f in r.failures}
    assert "duplicate_row" not in rules, f"unexpected: {r.failures}"


def test_duplicate_row_flags_conflicting_tiers() -> None:
    """Same citation, two tiers (A1 + B2) → render bug."""
    md = (
        _DUP_TABLE_HEAD
        + "| Konopka 2019 | Observational | B2 | 53 | older adults |\n"
        + "| Konopka 2019 | RCT | A1 | 53 | older adults |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Konopka 2019"},
        {"receipt_id": "r2", "citation_token": "Konopka 2019"},
    ])
    r = validate(md, manifest)
    assert r.status == "FAIL"
    assert any(
        "conflicting evidence tiers" in f.detail for f in r.failures
    )


def test_table_count_consistency_matches_unique_accepted_citations(
    tmp_path: Path,
) -> None:
    md = (
        _DUP_TABLE_HEAD
        + "| Walton 2019 | RCT | A1 | 49 | older adults |\n"
        + "| Konopka 2019 | RCT | A1 | 53 | older adults |\n"
    )
    manifest = _baseline_manifest(
        n_receipts=3,
        n_accepted_receipts=3,
        receipts=[
            {"receipt_id": "r1", "citation_token": "Walton 2019"},
            {"receipt_id": "r2", "citation_token": "Walton 2019"},
            {"receipt_id": "r3", "citation_token": "Konopka 2019"},
        ],
    )
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "verdicts": {
            "r1": {"verdict": "accept_clean"},
            "r2": {"verdict": "accept_clean"},
            "r3": {"verdict": "accept_clean"},
        }
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(f.rule == "table_count_consistency" for f in r.failures)


def test_table_count_consistency_accepts_alphanumeric_citation_tokens(
    tmp_path: Path,
) -> None:
    md = (
        _DUP_TABLE_HEAD
        + "| T2DM 2023 | RCT | A1 | 90 | adults |\n"
        + "| miaek 2023 | RCT | A1 | 90 | adults |\n"
    )
    manifest = _baseline_manifest(
        n_receipts=2,
        n_accepted_receipts=2,
        receipts=[
            {"receipt_id": "r1", "citation_token": "T2DM 2023"},
            {"receipt_id": "r2", "citation_token": "miaek 2023"},
        ],
    )
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "verdicts": {
            "r1": {"verdict": "accept_clean"},
            "r2": {"verdict": "accept_clean"},
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(f.rule == "table_count_consistency" for f in r.failures)


def test_table_count_consistency_flags_missing_accepted_citation(
    tmp_path: Path,
) -> None:
    md = (
        _DUP_TABLE_HEAD
        + "| Walton 2019 | RCT | A1 | 49 | older adults |\n"
    )
    manifest = _baseline_manifest(
        n_receipts=2,
        n_accepted_receipts=2,
        receipts=[
            {"receipt_id": "r1", "citation_token": "Walton 2019"},
            {"receipt_id": "r2", "citation_token": "Konopka 2019"},
        ],
    )
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "verdicts": {
            "r1": {"verdict": "accept_clean"},
            "r2": {"verdict": "accept_clean"},
        }
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(f.rule == "table_count_consistency" for f in r.failures)


def test_evidence_role_count_consistency_flags_stale_role_counts() -> None:
    manifest = _baseline_manifest(
        receipts=[
            {
                "receipt_id": "r1",
                "citation_token": "Direct 2020",
                "directness": "direct",
                "spar_verdict": "accept_clean",
            },
            {
                "receipt_id": "r2",
                "citation_token": "Mechanistic 2021",
                "directness": "mechanistic",
                "spar_verdict": "accept_clean",
            },
            {
                "receipt_id": "r3",
                "citation_token": "Rejected 2022",
                "directness": "indirect",
                "spar_verdict": "reject_direction_mismatch",
            },
        ],
    )
    md = (
        "## Limitations\n\nThe corpus contains 2 direct clinical receipt(s), "
        "14 indirect clinical receipt(s), and 14 mechanistic or model-system "
        "receipt(s).\n"
    )
    r = validate(md, manifest)
    assert any(
        f.rule == "evidence_role_count_consistency"
        for f in r.failures
    )


def test_appendix_distribution_counts_must_match_accepted_receipts() -> None:
    manifest = _baseline_manifest(n_accepted_receipts=2)
    md = (
        "## Publication Appendix\n\n"
        "**Evidence tier distribution:**\n\n"
        "| Tier | Description | Count |\n"
        "|---|---|---|\n"
        "| A1 | RCT | 2 |\n"
        "| B1 | Review | 10 |\n"
        "\n"
        "**Directness distribution:**\n\n"
        "| Directness | Count |\n"
        "|---|---|\n"
        "| direct | 2 |\n"
        "| review | 10 |\n"
    )
    r = validate(md, manifest)
    assert any(
        f.rule == "evidence_role_count_consistency"
        and "distribution totals 12" in f.detail
        for f in r.failures
    )


def test_section_outcome_integrity_flags_wrong_outcome_subsection() -> None:
    manifest = _baseline_manifest(
        receipts=[
            {
                "receipt_id": "r1",
                "citation_token": "Walton 2019",
                "outcome_class": "muscle_function",
                "spar_verdict": "accept_clean",
            },
        ],
    )
    md = (
        "## Results\n\n"
        "### Longevity and Mortality Outcomes\n\n"
        "Walton 2019 reported lean-mass findings in older adults.\n"
    )
    r = validate(md, manifest)
    assert any(f.rule == "section_outcome_integrity" for f in r.failures)


def test_table_set_consistency_flags_table2_citation_missing_from_table1() -> None:
    md = (
        "## Table 1: Included Studies\n\n"
        "| Citation | Design | Tier | N | Population | Endpoint | Direction | Directness |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Kim 2020 | Review | B1 | — | — | cardiometabolic | negative | review |\n\n"
        "## Table 2: Per-Study Endpoint Evidence\n\n"
        "| Endpoint | Study | p/CI | Direction | Directness | Tier | Interpretation |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| muscle function | Walton 2019 | P = 0.003 | mixed | direct | A1 | reported |\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "table_set_consistency" for f in r.failures)


def test_cross_table_metadata_conflict_flags_tier_directness_drift() -> None:
    md = (
        "## Table 1: Included Studies\n\n"
        "| Citation | Design | Tier | N | Population | Endpoint | Direction | Directness |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Konopka 2019 | RCT | A1 | — | adults | cardiometabolic | mixed | direct |\n\n"
        "## Table 2: Per-Study Endpoint Evidence\n\n"
        "| Endpoint | Study | p/CI | Direction | Directness | Tier | Interpretation |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| cardiometabolic | Konopka 2019 | P = 0.08 | mixed | indirect | B2 | reported |\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "cross_table_metadata_conflict" for f in r.failures)


def test_tension_table_integrity_flags_self_pairs_and_duplicates() -> None:
    md = (
        "## Table 3: Cross-Domain Tensions\n\n"
        "| Tension kind | Severity | Receipt A | Receipt B | Outcome class | Summary | Practical implication |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| agreement | 1 | Walton 2019 | Walton 2019 | muscle function | self | minor |\n"
        "| disagreement | 4 | A 2020 | B 2021 | longevity | one | load-bearing |\n"
        "| disagreement | 4 | B 2021 | A 2020 | longevity | duplicate | load-bearing |\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "tension_table_integrity" for f in r.failures)


def test_conclusion_hygiene_flags_table_boilerplate() -> None:
    md = (
        "## Conclusion\n\n"
        "Prior narrative reviews did not compare this pair. Table 4 "
        "summarizes the weighting layer.\n\n"
        "### Boundary-Condition Matrix\n\nRows.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "conclusion_hygiene" for f in r.failures)


def test_duplicate_row_flags_excess_rows_for_unsplit_citation() -> None:
    """Manifest has 1 receipt for the citation; MD renders 3 rows → fail."""
    md = (
        _DUP_TABLE_HEAD
        + "| Smith 2020 | RCT | A1 | 100 | adults [arm 1] |\n"
        + "| Smith 2020 | RCT | A1 | 100 | adults [arm 2] |\n"
        + "| Smith 2020 | RCT | A1 | 100 | adults [arm 3] |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Smith 2020"},
    ])
    r = validate(md, manifest)
    assert r.status == "FAIL"
    assert any(
        "rendered 3 rows" in f.detail and "Smith 2020" in f.detail
        for f in r.failures
    )


# ---- rule 3: section boundary -------------------------------------------


def test_section_boundary_flags_oversized_abstract() -> None:
    md = "## Abstract\n\n" + " ".join(["word"] * 600) + "\n## Introduction\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "section_boundary" and "abstract is" in f.detail
        for f in r.failures
    )


def test_section_boundary_flags_h3_residue() -> None:
    md = "## Results\n\nH3: This is internal section-tagging language.\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "section_boundary" and "H3:" in f.detail
        for f in r.failures
    )


def test_section_boundary_flags_duplicate_top_level() -> None:
    md = (
        "## Methods\n\nFirst section.\n## Methods\n\nSecond duplicate.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "section_boundary"
        and "duplicate top-level section" in f.detail
        for f in r.failures
    )


def test_section_boundary_passes_normal_paper() -> None:
    md = (
        "## Abstract\n\n" + " ".join(["word"] * 250) + "\n"
        "## Introduction\n\nClean prose.\n"
        "## Methods\n\nClean methods.\n"
    )
    r = validate(md, _baseline_manifest())
    rules = {f.rule for f in r.failures}
    assert "section_boundary" not in rules


def test_public_shape_flags_pre_abstract_fused_heading_and_ordinal_gap() -> None:
    md = (
        "Orphan public sentence before abstract.\n\n"
        "## Abstract\n\n"
        "Metformin is being studied. elegans model, metformin improved lifespan. "
        "It was dosed at 850 mg for diabetes.\n\n"
        "## Cross-Domain Synthesis\n\n"
        "A second tension is visible. A fourth tension remains unresolved. "
        "summary.## Metabolic-Functional Tradeoff Framework\n\n"
        "| Layer | Evidence example | Supports | Cannot support |\n"
        "|---|---|---|---|\n| A | B | C | D |\n"
    )
    r = validate(md, _baseline_manifest())
    details = "\n".join(f.detail for f in r.failures)
    assert "before the Abstract" in details
    assert "lowercase sentence fragment" in details
    assert "dose-as-definition" in details
    assert "heading fused" in details
    assert "ordinal gap" in details


def test_reference_integrity_flags_orphan_and_merged_pmids() -> None:
    md = (
        "## References\n\n"
        "- **Walton 2019.** _Title._ PMID: 31557380. PMID: 30548390.\n"
        "PMID: 12345678.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "reference_integrity" for f in r.failures)


# ---- rule 4: residue phrase ---------------------------------------------


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_residue_phrase_flags_each_forbidden(phrase: str) -> None:
    md = f"## Methods\n\nSomething about {phrase} which leaked in.\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "residue_phrase" and phrase in f.detail
        for f in r.failures
    )


def test_residue_phrase_passes_clean_md() -> None:
    md = "## Methods\n\nWe used a deterministic pipeline. End.\n"
    r = validate(md, _baseline_manifest())
    rules = {f.rule for f in r.failures}
    assert "residue_phrase" not in rules


# ---- orchestrator + sidecar ---------------------------------------------


def test_validate_pass_returns_clean_result() -> None:
    md = (
        "## Abstract\n\nThe corpus comprises 40 source papers and yielded "
        "173 high-confidence claims with 153 tensions.\n"
        "## Methods\n\nClean methods.\n"
    )
    r = validate(md, _baseline_manifest())
    assert r.status == "PASS"
    assert r.failures == ()


def test_validate_fail_when_manifest_unreadable() -> None:
    """Manifest with non-int values fails-closed."""
    bad = {"n_receipts": "not-a-number"}
    r = validate("## Abstract\n", bad)
    assert r.status == "FAIL"
    assert any(f.rule == "canonical_link" for f in r.failures)


def test_write_sidecar_emits_json(tmp_path: Path) -> None:
    md = "## Abstract\n\nClean.\n"
    manifest = _baseline_manifest()
    (tmp_path / "full_paper.md").write_text(md)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    r = validate_run_dir(tmp_path)
    out = write_sidecar(tmp_path, r)
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["status"] == "PASS"
    assert payload["canonical_counts"]["source_papers"] == 40


def test_validate_run_dir_fails_closed_on_bad_manifest(tmp_path: Path) -> None:
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nClean.\n")
    (tmp_path / "manifest.json").write_text("[]")
    r = validate_run_dir(tmp_path)
    assert r.status == "FAIL"
    assert any(f.rule == "canonical_link" for f in r.failures)


# ---- rule 7: broken prose -----------------------------------------------


def test_broken_prose_flags_truncated_but_was() -> None:
    md = (
        "## Results\n\nThe drug was not associated with mortality in the "
        "first three months but was mortality, underscoring timing.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "but was" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_year_as_effect_estimate() -> None:
    md = "## Results\n\nThe trial reported an effect estimate of 2023.\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "year-as-effect-estimate" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_dose_as_effect_estimate() -> None:
    md = (
        "## Results\n\nAnisimov 2010 reported an effect estimate of "
        "100 mg/kg in mice.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "dose-as-effect-estimate" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_duration_as_effect_estimate() -> None:
    md = "## Results\n\nThe study reported an effect estimate of 5 years.\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "duration-as-effect-estimate" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_truncated_effect_estimate() -> None:
    md = (
        "## Results\n\nWitham 2025 reported an effect estimate. Yet the "
        "direction remains unclear.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "no value" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_floor_backfill_fragment() -> None:
    md = (
        "## Discussion\n\nThe public interpretation remains tied to "
        "the source record rather than to any single . When a cannot "
        "support its own specificity, the paper does not infer a "
        "replacement result.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "single . When a cannot" in f.detail
        for f in r.failures
    )


def test_broken_prose_flags_standalone_numeric_fragment() -> None:
    md = (
        "## Cross-Domain Synthesis\n\n"
        "A tension remains unresolved. 02. The supported sentence follows.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "broken_prose" and "standalone numeric" in f.detail
        for f in r.failures
    )


def test_malformed_table_row_flags_orphan_fragment() -> None:
    md = (
        "## Table 2: Per-Study Endpoint Evidence\n\n"
        "| Endpoint | Study | p/CI | Direction |\n"
        "| --- | --- | --- | --- |\n"
        "| healthspan | Smith 2020 | P = 0.023 | mixed |\n"
        "023 | mixed | direct | A1 |\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "malformed_table_row" for f in r.failures)


def test_broken_prose_passes_clean_prose() -> None:
    md = (
        "## Results\n\nThe trial reported an effect estimate of 0.78 "
        "(95% CI 0.62-0.94) on mortality.\n"
    )
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "broken_prose" for f in r.failures)


# ---- rule 8: repeated boilerplate ---------------------------------------


def test_repeated_boilerplate_flags_repeated_sentences() -> None:
    sent = (
        "Translational relevance to humans remains uncertain in this "
        "particular framing."
    )
    md = f"## A\n\n{sent}\n## B\n\n{sent}\n## C\n\n{sent}\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "repeated_boilerplate" and "Translational" in f.detail
        for f in r.failures
    )


def test_repeated_boilerplate_passes_short_repeats() -> None:
    """Short fragments (< min_words) should NOT trigger — sub-clause
    repetition is normal English."""
    md = "## A\n\nIt was good.\n## B\n\nIt was good.\n## C\n\nIt was good.\n"
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "repeated_boilerplate" for f in r.failures)


def test_repeated_boilerplate_flags_duplicate_paragraphs() -> None:
    para = (
        "Against this, the most damaging direct evidence comes from an "
        "exercise-adaptation trial where functional interpretation remains "
        "conditional and clinically relevant for trial design, outcome "
        "selection, and future geroscience translation."
    )
    md = f"## A\n\n{para}\n\n## B\n\n{para}\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "repeated_boilerplate" and "paragraph repeated" in f.detail
        for f in r.failures
    )


def test_residue_flags_public_outline_artifacts() -> None:
    md = (
        "## Abstract\n\n**Thesis:** The accepted receipt corpus is bounded.\n\n"
        "## Background\n\nThe context is constrained. Third, the evidence remains conditional.\n\n"
        "## Discussion\n\nThe tension matrix should stay internal.\n"
    )
    r = validate(md, _baseline_manifest())
    assert sum(f.rule == "residue_phrase" for f in r.failures) >= 4


def test_framework_integrity_requires_public_table() -> None:
    md = "## Endpoint-Sensitivity Framework\n\nFramework prose only.\n"
    r = validate(md, _baseline_manifest())
    assert any(f.rule == "framework_integrity" for f in r.failures)


def test_framework_integrity_passes_with_evidence_layer_table() -> None:
    md = (
        "## Metabolic-Functional Tradeoff Framework\n\n"
        "| Layer | Evidence example | Supports | Cannot support |\n"
        "| --- | --- | --- | --- |\n"
        "| Biomarker | HbA1c | metabolic signal | geroprotection |\n"
    )
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "framework_integrity" for f in r.failures)


# ---- rule 9: SPAR reject leakage ----------------------------------------


def test_spar_reject_leakage_flags_reject_in_discussion(
    tmp_path: Path,
) -> None:
    """A receipt with reject_* verdict must not be cited in Discussion /
    Conclusion / Results / Synthesis / Tensions prose. Universal: applies
    to any topic."""
    md = (
        "## Discussion\n\nThe disagreement between Cameron 2016 and "
        "Hanem 2018 highlights heterogeneity.\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Cameron 2016"},
    ])
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "gemma-4-31b",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "test",
                "judge_model": "gemma-4-31b",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(
        f.rule == "spar_reject_leakage" and "Cameron 2016" in f.detail
        for f in r.failures
    )


def test_spar_reject_leakage_flags_main_evidence_table(
    tmp_path: Path,
) -> None:
    """Wave 22 trust-spine: rejected receipts must NOT appear in main
    evidence tables either. The only legitimate surface is the
    'Rejected / Contested Evidence' quarantine appendix."""
    md = (
        "## Included Studies\n\n"
        "| Citation | Tier |\n| --- | --- |\n"
        "| Cameron 2016 | B2 |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Cameron 2016"},
    ])
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "gemma-4-31b",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(
        f.rule == "spar_reject_leakage" and "Cameron 2016" in f.detail
        for f in r.failures
    )


def test_spar_reject_leakage_excises_quarantine_appendix(
    tmp_path: Path,
) -> None:
    """Rejected citations inside the dedicated 'Rejected / Contested
    Evidence' section are legitimate — that's the one allowed surface.
    The rule must excise this section before scanning."""
    md = (
        "## Methods\n\nClean methods.\n"
        "## Rejected / Contested Evidence\n\n"
        "| Citation | Verdict |\n| --- | --- |\n"
        "| Cameron 2016 | reject_internal_contradiction |\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Cameron 2016"},
    ])
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "gemma-4-31b",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(f.rule == "spar_reject_leakage" for f in r.failures)


# ---- rule 10: rejected appendix required --------------------------------


def test_rejected_appendix_required_flags_missing_section(
    tmp_path: Path,
) -> None:
    """Rejects exist in spar_cache but no quarantine heading in MD →
    fail. Universal: applies to every topic."""
    md = "## Methods\n\nClean methods.\n## Discussion\n\nClean prose.\n"
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Cameron 2016"},
    ])
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "g",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(
        f.rule == "rejected_appendix_required" for f in r.failures
    )


def test_rejected_appendix_required_passes_when_section_present(
    tmp_path: Path,
) -> None:
    md = (
        "## Methods\n\nClean methods.\n"
        "## Rejected / Contested Evidence\n\n_listed below._\n"
    )
    manifest = _baseline_manifest()
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "g",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(
        f.rule == "rejected_appendix_required" for f in r.failures
    )


def test_rejected_appendix_required_passes_when_section_in_supplement(
    tmp_path: Path,
) -> None:
    md = "## Methods\n\nClean methods.\n"
    manifest = _baseline_manifest()
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "g",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    (tmp_path / "supplement.md").write_text(
        "## Rejected / Contested Evidence\n\n_listed below._\n",
    )
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(
        f.rule == "rejected_appendix_required" for f in r.failures
    )


def test_table_contract_reads_structured_evidence_sidecar(
    tmp_path: Path,
) -> None:
    """Journal main can omit full evidence tables, but the contract still
    audits the deterministic table sidecar."""
    md = "## Abstract\n\nShort.\n## Methods\n\nClean methods.\n"
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Walton 2019"},
    ])
    (tmp_path / "structured_evidence_tables.md").write_text(
        "## Structured Evidence Tables\n\n"
        "### Table 1: Included Studies\n\n"
        "| Citation | Tier |\n|---|---|\n"
        "| Walton 2019 | A1 |\n"
        "| Walton 2019 | A1 |\n",
    )
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(f.rule == "duplicate_row" for f in r.failures)


def test_qei_contract_reads_quantitative_evidence_sidecar(
    tmp_path: Path,
) -> None:
    """Journal main can omit QEI, but the contract still audits it."""
    md = "## Abstract\n\nShort.\n## Methods\n\nClean methods.\n"
    manifest = _baseline_manifest()
    (tmp_path / "quantitative_evidence_index.md").write_text(
        "## Quantitative Evidence Index — topic\n\n"
        "_Top 40 high-confidence numeric claims._\n\n"
        "| Study | Endpoint |\n| --- | --- |\n"
        "| Smith 2020 | A |\n"
        "| Jones 2021 | B |\n"
    )
    r = validate(md, manifest, run_dir=tmp_path)
    assert any(f.rule == "qei_title_row_mismatch" for f in r.failures)


def test_residue_flags_cited_marker_in_public_main() -> None:
    md = "## Results\n\n_Cited: `Walton 2019`_\n"
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "residue_phrase" and "_Cited:" in f.detail
        for f in r.failures
    )


def test_rejected_appendix_required_skips_when_no_rejects(
    tmp_path: Path,
) -> None:
    """No rejects → rule is silently inapplicable (universal: degrades
    gracefully when input absent)."""
    md = "## Methods\n\nClean methods.\n"
    manifest = _baseline_manifest()
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(
        f.rule == "rejected_appendix_required" for f in r.failures
    )


def test_spar_reject_leakage_skips_when_no_cache(tmp_path: Path) -> None:
    """No spar_cache.json → rule silently skips (universal: degrades
    gracefully when its input is absent)."""
    md = "## Discussion\n\nThe disagreement between Cameron 2016 ... \n"
    manifest = _baseline_manifest()
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(f.rule == "spar_reject_leakage" for f in r.failures)


# ---- rule 11: QEI title row mismatch ------------------------------------


def test_qei_title_row_mismatch_flags_when_title_lies() -> None:
    md = (
        "## Quantitative Evidence Index — topic\n\n"
        "_Top 40 high-confidence numeric claims._\n\n"
        "| Study | Endpoint |\n| --- | --- |\n"
        "| Smith 2020 | A |\n"
        "| Jones 2021 | B |\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "qei_title_row_mismatch" and "Top 40" in f.detail
        for f in r.failures
    )


def test_qei_title_passes_when_count_matches() -> None:
    md = (
        "## Quantitative Evidence Index — topic\n\n"
        "Top 2 claims.\n\n"
        "| Study | Endpoint |\n| --- | --- |\n"
        "| Smith 2020 | A |\n"
        "| Jones 2021 | B |\n"
    )
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "qei_title_row_mismatch" for f in r.failures)


# ---- rule 12: References section duplicates -----------------------------


def test_reference_duplicates_flags_dup_entries() -> None:
    md = (
        "## References\n\n"
        "- **Walton 2019.** _A._ Aging Cell, 2019.\n"
        "- **Walton 2019.** _A._ Aging Cell, 2019.\n"
        "- **Smith 2020.** _B._ JAMA, 2020.\n"
    )
    r = validate(md, _baseline_manifest())
    assert any(
        f.rule == "reference_duplicates" and "Walton 2019" in f.detail
        for f in r.failures
    )


def test_reference_duplicates_passes_when_unique() -> None:
    md = (
        "## References\n\n"
        "- **Walton 2019.** _A._ Aging Cell, 2019.\n"
        "- **Smith 2020.** _B._ JAMA, 2020.\n"
    )
    r = validate(md, _baseline_manifest())
    assert not any(f.rule == "reference_duplicates" for f in r.failures)


# ---- References excised from spar_reject_leakage scan -------------------


def test_spar_leak_excises_references_section(tmp_path: Path) -> None:
    """Wave 25: References is the audit trail (every receipt listed
    with verdict tag). A rejected citation appearing in References is
    legitimate transparency, not a leak. The leak rule must skip the
    References section."""
    md = (
        "## Methods\n\nNothing controversial here.\n"
        "## References\n\n"
        "- **Cameron 2016.** _Quarantined paper._ J, 2016.\n"
    )
    manifest = _baseline_manifest(receipts=[
        {"receipt_id": "r1", "citation_token": "Cameron 2016"},
    ])
    (tmp_path / "spar_cache.json").write_text(json.dumps({
        "judge_model": "g",
        "verdicts": {
            "r1": {
                "receipt_id": "r1",
                "verdict": "reject_internal_contradiction",
                "rationale": "x", "judge_model": "g",
                "fail_soft_default": False,
            },
        },
    }))
    r = validate(md, manifest, run_dir=tmp_path)
    assert not any(f.rule == "spar_reject_leakage" for f in r.failures)


# ---- regression-anchor fixtures (live runs) -----------------------------


_REPO = Path(__file__).resolve().parent.parent
_RAPA_RUN = _REPO / "runs" / (
    "synthesis-rapamycin-v06-GEMMA-SPAR-2026-05-10T10-41-37Z"
)
_METF_RUN = _REPO / "runs" / (
    "synthesis-metformin-v06-GEMMA-SPAR-2026-05-10T10-41-37Z"
)


@pytest.mark.skipif(
    not _RAPA_RUN.exists(), reason="rapa fixture run not present",
)
def test_regression_rapamycin_fails_count_and_residue() -> None:
    """Live fixture: 2026-05-10 rapa run had 20 vs 40 paper count
    contradiction + Tournament-selector residue. Pin those failures."""
    r = validate_run_dir(_RAPA_RUN)
    assert r.status == "FAIL"
    rules = {f.rule for f in r.failures}
    assert "count_consistency" in rules
    assert "residue_phrase" in rules


@pytest.mark.skipif(
    not _METF_RUN.exists(), reason="metf fixture run not present",
)
def test_regression_metformin_fails_dup_and_section() -> None:
    """Live fixture: 2026-05-10 metf run had Walton-2019 byte-identical
    rows, Konopka-2019 conflicting tiers, and a 1560-word abstract."""
    r = validate_run_dir(_METF_RUN)
    assert r.status == "FAIL"
    rules = {f.rule for f in r.failures}
    assert "duplicate_row" in rules
    assert "section_boundary" in rules


# ---- shape guards -------------------------------------------------------


def test_failure_dataclass_is_immutable() -> None:
    f = ContractFailure(rule="count_consistency", detail="x")
    with pytest.raises(AttributeError):
        f.rule = "residue_phrase"  # type: ignore[misc]
