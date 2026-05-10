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
