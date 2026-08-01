"""Tests for agent.submission_package — multi-file submission finalizer.

Stdlib-only. Universal — package shape is fixed by the target-journal
contract, not the corpus's domain.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.human_signoff import HumanSignoff, write as write_human_signoff

from agent.submission_package import (  # type: ignore[import-not-found]
    PACKAGE_DIRNAME,
    SubmissionPackageError,
    compose,
)


# ---- fixtures -------------------------------------------------------------


def _seed_l5_run(tmp_path: Path) -> Path:
    """Build a minimal run_dir that satisfies submission readiness."""
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "test_topic", "n_receipts": 30,
        "retrieval": {"sources": [{"name": "PubMed", "status": "ok"}]},
    }))
    (tmp_path / "full_paper.md").write_text(
        "# Title\n\n## Abstract\n\nClean.\n\n## Methods\n\nUsed corpus.\n",
    )
    (tmp_path / "structured_evidence_tables.md").write_text(
        "## Table 1\n\n| Citation | Tier |\n| --- | --- |\n| Smith 2020 | A1 |\n",
    )
    (tmp_path / "final_status.json").write_text(json.dumps({
        "submission_ready": True,
        "journal_submission_ready": True,
        "maturity_level": 5,
        "maturity_label": "L5 — SUBMISSION READY",
        "dimensions": {
            "runtime_pass": True, "audit_pass": True,
            "journal_surface_pass": True, "pre_submit_pass": True,
            "target_journal_pass": True, "human_signoff_pass": True,
        },
        "blocking_reasons": [],
        "sidecars_read": [],
    }))
    (tmp_path / "target_journal_pack.json").write_text(json.dumps({
        "journal": "Aging Cell", "article_type": "Review",
        "abstract_max_words": 250, "main_word_limit": 6000,
        "reference_style": "Vancouver",
        "requires_prisma": False, "requires_ai_disclosure": True,
        "allows_supplement": True, "notes": "",
        "declared_in_topic_pack": True,
    }))
    write_human_signoff(tmp_path, HumanSignoff(
        author="Dom Lynch", reviewed=True, evidence_claims_reviewed=True,
        conflicts_declared=True, ready_to_submit=True, signature="Dom Lynch",
    ))
    return tmp_path


# ---- gate enforcement -----------------------------------------------------


def test_compose_refuses_when_final_status_missing(tmp_path: Path) -> None:
    with pytest.raises(SubmissionPackageError, match="final_status.json missing"):
        compose(tmp_path)


def test_compose_refuses_below_l5_by_default(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    # Downgrade to L2 → must refuse
    fs = json.loads((tmp_path / "final_status.json").read_text())
    fs["maturity_level"] = 2
    (tmp_path / "final_status.json").write_text(json.dumps(fs))
    with pytest.raises(SubmissionPackageError, match="journal_submission_ready"):
        compose(tmp_path)


def test_compose_allows_below_l4_with_override(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    fs = json.loads((tmp_path / "final_status.json").read_text())
    fs["maturity_level"] = 2
    (tmp_path / "final_status.json").write_text(json.dumps(fs))
    # Should not raise
    m = compose(tmp_path, allow_below_l4=True)
    assert m.maturity_level == 2


def test_compose_refuses_when_pack_missing(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    (tmp_path / "target_journal_pack.json").unlink()
    with pytest.raises(SubmissionPackageError, match="pack.*missing"):
        compose(tmp_path)


def test_compose_refuses_when_signoff_missing(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    (tmp_path / "human_signoff.json").unlink()
    with pytest.raises(SubmissionPackageError, match="signoff.*invalid"):
        compose(tmp_path)


def test_compose_refuses_unbound_signoff(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    signoff = json.loads((tmp_path / "human_signoff.json").read_text())
    signoff["manuscript_sha256"] = "0" * 64
    (tmp_path / "human_signoff.json").write_text(json.dumps(signoff))
    with pytest.raises(SubmissionPackageError, match="manuscript_hash_mismatch"):
        compose(tmp_path)


# ---- package contents -----------------------------------------------------


def test_compose_writes_expected_files(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    m = compose(tmp_path)
    pkg = tmp_path / PACKAGE_DIRNAME
    assert pkg.is_dir()
    must_have = {
        "final_manuscript.md",
        "structured_evidence_tables.md",
        "search_provenance.md",
        "AI_use_disclosure.md",
        "data_code_availability.md",
        "ethics_funding_conflict.md",
        "cover_letter.md",
        "final_status.json",
        "target_journal_pack.json",
        "human_signoff.json",
        "manifest.json",
    }
    actual = {p.name for p in pkg.iterdir() if p.is_file()}
    assert must_have.issubset(actual), (
        f"missing from package: {must_have - actual}"
    )
    # Manifest reflects the written files
    assert set(m.files).issubset(actual)


def test_cover_letter_substitutes_journal_and_author(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    compose(tmp_path)
    letter = (tmp_path / PACKAGE_DIRNAME / "cover_letter.md").read_text()
    assert "Aging Cell" in letter
    assert "Dom Lynch" in letter
    assert "Review" in letter  # article_type
    assert "Vancouver" in letter  # reference_style


def test_final_manuscript_is_copy_of_full_paper(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    compose(tmp_path)
    src = (tmp_path / "full_paper.md").read_text()
    dst = (tmp_path / PACKAGE_DIRNAME / "final_manuscript.md").read_text()
    assert src == dst


def test_manifest_records_maturity_and_journal(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    m = compose(tmp_path)
    assert m.maturity_level == 5
    assert "L5" in m.maturity_label
    assert m.target_journal == "Aging Cell"
    assert m.author == "Dom Lynch"


def test_manifest_is_frozen_immutable(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    m = compose(tmp_path)
    with pytest.raises(AttributeError):
        m.target_journal = "Other"  # type: ignore[misc]


# ---- universal compliance -------------------------------------------------


def test_ethics_stub_is_domain_agnostic(tmp_path: Path) -> None:
    """The ethics-funding-conflict template must NOT contain biomedical-
    specific clauses (clinical trial, IRB, etc.) by default — those are
    journal-specific add-ons the human author fills in."""
    _seed_l5_run(tmp_path)
    compose(tmp_path)
    text = (tmp_path / PACKAGE_DIRNAME / "ethics_funding_conflict.md").read_text()
    # Allowed framing: "primary data", "ethics statement"
    # NOT allowed by default: "IRB", "clinical trial", "HIPAA"
    for biomed_only in ("IRB", "clinical trial", "HIPAA", "Helsinki"):
        assert biomed_only not in text, (
            f"biomedical-only token '{biomed_only}' in ethics stub"
        )


def test_compose_works_with_any_journal_name(tmp_path: Path) -> None:
    """Universal: any non-empty journal name from the pack should
    appear verbatim in the cover letter — no allowlist."""
    _seed_l5_run(tmp_path)
    pack = json.loads((tmp_path / "target_journal_pack.json").read_text())
    pack["journal"] = "Journal of Climate Modelling"
    (tmp_path / "target_journal_pack.json").write_text(json.dumps(pack))
    compose(tmp_path)
    letter = (tmp_path / PACKAGE_DIRNAME / "cover_letter.md").read_text()
    assert "Journal of Climate Modelling" in letter


def test_compose_requires_nonempty_manuscript(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    (tmp_path / "full_paper.md").write_text("  \n")
    with pytest.raises(SubmissionPackageError, match="manuscript is required"):
        compose(tmp_path)


def test_compose_rejects_invalid_journal_pack(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    pack = json.loads((tmp_path / "target_journal_pack.json").read_text())
    pack["main_word_limit"] = "not-an-integer"
    (tmp_path / "target_journal_pack.json").write_text(json.dumps(pack))
    with pytest.raises(SubmissionPackageError, match="pack.*invalid"):
        compose(tmp_path)


def test_compose_propagates_disclosure_builder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("disclosure failed")

    monkeypatch.setattr(
        "agent.manuscript_appendix.build_search_provenance_appendix", fail,
    )
    with pytest.raises(RuntimeError, match="disclosure failed"):
        compose(tmp_path)
    assert not (tmp_path / PACKAGE_DIRNAME).exists()
