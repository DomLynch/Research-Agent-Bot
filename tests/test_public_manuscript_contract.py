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


def test_count_consistency_flags_receipt_mismatch() -> None:
    """Rapa-style: '21 accepted receipts' when canonical is 40."""
    md = "## Methods\n\nThe analysis pooled 21 accepted receipts.\n"
    r = validate(md, _baseline_manifest())
    assert r.status == "FAIL"
    assert any("receipt" in f.detail for f in r.failures)


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


# ---- rule 6: wrong-topic residue ----------------------------------------


def _topic_pack_root(tmp_path: Path, topics: list[str]) -> Path:
    """Make a fake repo root with topic_packs/<topic>.toml stubs."""
    pack_dir = tmp_path / "topic_packs"
    pack_dir.mkdir()
    for t in topics:
        (pack_dir / f"{t}.toml").write_text(f"# stub topic pack for {t}\n")
    return tmp_path


def test_wrong_topic_residue_flags_sibling_claim_assertion(
    tmp_path: Path,
) -> None:
    """metformin paper claiming 'rapamycin evidence should be interpreted'
    is a sibling-topic leak — the universal regression case from the
    2026-05-10 metf run."""
    root = _topic_pack_root(tmp_path, ["metformin", "rapamycin", "statins"])
    md = (
        "## Discussion\n\nrapamycin evidence should be interpreted along "
        "a gradient from proximal to distal outcomes.\n"
    )
    manifest = _baseline_manifest(topic="metformin")
    r = validate(md, manifest, repo_root=root)
    assert any(
        f.rule == "wrong_topic_residue" and "rapamycin" in f.detail
        for f in r.failures
    )


def test_wrong_topic_residue_allows_passing_mention(
    tmp_path: Path,
) -> None:
    """Mentioning a sibling topic in non-claim-asserting context (a list,
    a comparison without an asserting verb) must NOT flag."""
    root = _topic_pack_root(tmp_path, ["metformin", "rapamycin"])
    md = (
        "## Background\n\nThis paper sits alongside related work on "
        "rapamycin and other geroprotectors.\n"
    )
    manifest = _baseline_manifest(topic="metformin")
    r = validate(md, manifest, repo_root=root)
    assert not any(f.rule == "wrong_topic_residue" for f in r.failures)


def test_wrong_topic_residue_skips_when_no_topic_packs(
    tmp_path: Path,
) -> None:
    """No topic_packs/ dir → rule silently skips (universal contract:
    rules degrade gracefully when their inputs are absent)."""
    md = "## Methods\n\nrapamycin evidence should be interpreted ...\n"
    manifest = _baseline_manifest(topic="metformin")
    r = validate(md, manifest, repo_root=tmp_path)  # no topic_packs/ dir
    assert not any(f.rule == "wrong_topic_residue" for f in r.failures)


def test_wrong_topic_residue_skips_when_no_topic_in_manifest() -> None:
    md = "## Methods\n\nrapamycin evidence should be interpreted ...\n"
    manifest = _baseline_manifest()  # no topic field
    r = validate(md, manifest)
    assert not any(f.rule == "wrong_topic_residue" for f in r.failures)


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
