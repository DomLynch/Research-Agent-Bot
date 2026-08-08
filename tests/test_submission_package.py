"""Tests for agent.submission_package — multi-file submission finalizer.

Stdlib-only. Universal — package shape is fixed by the target-journal
contract, not the corpus's domain.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

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
        "topic": "test_topic", "n_receipts": 1,
        "receipts": [{"receipt_id": "R1", "n_claims": 0}],
        "retrieval": {"sources": [{"name": "PubMed", "status": "ok"}]},
    }))
    (tmp_path / "full_paper.md").write_text(
        "# Title\n\n## Abstract\n\nClean.\n\n## Methods\n\nUsed corpus. "
        "Accountability is established through reproducible artifacts.\n\n"
        "## References\n\nSmith 2020\n",
    )
    (tmp_path / "structured_evidence_tables.md").write_text(
        "## Table 1\n\n| Citation | Tier |\n| --- | --- |\n| Smith 2020 | A1 |\n",
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "R1": {"receipt_id": "R1", "body_citation": "Smith 2020"},
    }))
    (tmp_path / "benchmark_runtime.json").write_text(json.dumps({"return_code": 0}))
    (tmp_path / "full_paper.audit.json").write_text(json.dumps({
        "p1_pass": True, "n_pass": 1, "n_total": 1,
    }))
    (tmp_path / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": True, "issues": [],
    }))
    (tmp_path / "pre_submit_gate.json").write_text(json.dumps({
        "result": {"passed": True, "failures": []},
    }))
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
    (tmp_path / "full_paper.review_patches.json").write_text(json.dumps({
        "review_available": True, "patches": [],
    }))
    from agent.artifact_consistency import verify_run_artifacts, write_consistency_sidecar
    write_consistency_sidecar(tmp_path, verify_run_artifacts(tmp_path))
    from agent.final_status import compute_and_write
    assert compute_and_write(tmp_path).journal_submission_ready is True
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
        "review_patches.json",
        "manifest.json",
    }
    actual = {p.name for p in pkg.iterdir() if p.is_file()}
    assert actual == must_have
    # Manifest reflects the written files
    assert set(m.files) | {"manifest.json"} == actual
    from agent.artifact_consistency import paper_content_hash
    assert m.paper_sha256 == paper_content_hash(
        (pkg / "final_manuscript.md").read_text(),
    )


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


def test_compose_rejects_stale_trust_sidecars_after_manuscript_mutation(
    tmp_path: Path,
) -> None:
    _seed_l5_run(tmp_path)
    compose(tmp_path)
    (tmp_path / "full_paper.md").write_text("Material mutation after certification.")
    with pytest.raises(SubmissionPackageError, match="artifact_consistency.*stale"):
        compose(tmp_path)
    assert not (tmp_path / PACKAGE_DIRNAME).exists()


def test_compose_rejects_fabricated_consistency_check(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    receipt = json.loads((tmp_path / "artifact_consistency.json").read_text())
    receipt["checks"] = [{"name": "invented", "passed": True}]
    (tmp_path / "artifact_consistency.json").write_text(json.dumps(receipt))

    with pytest.raises(SubmissionPackageError, match="journal_submission_ready|stale"):
        compose(tmp_path)


def test_compose_rejects_fabricated_canonical_consistency_rows(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    receipt = json.loads((tmp_path / "artifact_consistency.json").read_text())
    for check in receipt["checks"]:
        check["detail"] = "forged canonical pass"
    (tmp_path / "artifact_consistency.json").write_text(json.dumps(receipt))

    with pytest.raises(SubmissionPackageError, match="stale"):
        compose(tmp_path)


def test_artifact_consistency_requires_patch_decision_log(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    (tmp_path / "full_paper.review_patches.json").write_text(json.dumps({
        "review_available": True,
        "patches": [{"id": "P1"}],
    }))
    from agent.artifact_consistency import verify_run_artifacts

    report = verify_run_artifacts(tmp_path)

    assert report.passed is False
    assert next(check for check in report.checks if check.name == "reviewer_evidence").passed is False


def test_package_availability_uses_only_verified_manifest_metadata(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest.update({"git_sha": "abc1234", "bundle_path": "bundles/test-run/"})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    from agent.artifact_consistency import verify_run_artifacts, write_consistency_sidecar
    from agent.final_status import compute_and_write
    write_consistency_sidecar(tmp_path, verify_run_artifacts(tmp_path))
    assert compute_and_write(tmp_path).journal_submission_ready is True

    compose(tmp_path)
    availability = (tmp_path / PACKAGE_DIRNAME / "data_code_availability.md").read_text()

    assert "git checkout abc1234" in availability
    assert "`bundles/test-run/`" in availability
    assert "Grok" not in availability
    assert "The bundle contains" not in availability


def test_recompose_removes_stale_optional_files(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    compose(tmp_path)
    supplement = tmp_path / "structured_evidence_tables.md"
    supplement.unlink()

    manifest = compose(tmp_path)

    assert not (tmp_path / PACKAGE_DIRNAME / supplement.name).exists()
    assert supplement.name not in manifest.files


def test_compose_enforces_prisma_and_supplement_contract(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    pack = json.loads((tmp_path / "target_journal_pack.json").read_text())
    pack.update({"requires_prisma": True, "allows_supplement": False})
    (tmp_path / "target_journal_pack.json").write_text(json.dumps(pack))
    from agent.artifact_consistency import paper_content_hash, trust_inputs_hash
    consistency = json.loads((tmp_path / "artifact_consistency.json").read_text())
    consistency.update({
        "paper_sha256": paper_content_hash((tmp_path / "full_paper.md").read_text()),
        "inputs_sha256": trust_inputs_hash(tmp_path),
    })
    (tmp_path / "artifact_consistency.json").write_text(json.dumps(consistency))

    with pytest.raises(SubmissionPackageError, match="journal_submission_ready|PRISMA|prisma"):
        compose(tmp_path)

    (tmp_path / "prisma_flow_diagram.md").write_text(" \n")
    from agent.final_status import compute_and_write
    compute_and_write(tmp_path)
    with pytest.raises(SubmissionPackageError, match="journal_submission_ready|PRISMA|prisma"):
        compose(tmp_path)

    (tmp_path / "prisma_flow_diagram.md").write_text("# PRISMA flow\n")
    consistency["inputs_sha256"] = trust_inputs_hash(tmp_path)
    (tmp_path / "artifact_consistency.json").write_text(json.dumps(consistency))
    compute_and_write(tmp_path)
    manifest = compose(tmp_path)

    assert "prisma_flow_diagram.md" in manifest.files
    assert "structured_evidence_tables.md" not in manifest.files


def test_compose_packages_nonempty_prisma_variant(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    pack = json.loads((tmp_path / "target_journal_pack.json").read_text())
    pack["requires_prisma"] = True
    (tmp_path / "target_journal_pack.json").write_text(json.dumps(pack))
    (tmp_path / "prisma_flow_diagram.md").write_text(" \n")
    (tmp_path / "prisma_flow_diagram.pdf").write_bytes(b"valid-pdf")
    from agent.artifact_consistency import trust_inputs_hash
    consistency = json.loads((tmp_path / "artifact_consistency.json").read_text())
    consistency["inputs_sha256"] = trust_inputs_hash(tmp_path)
    (tmp_path / "artifact_consistency.json").write_text(json.dumps(consistency))
    from agent.final_status import compute_and_write
    compute_and_write(tmp_path)

    manifest = compose(tmp_path)

    assert "prisma_flow_diagram.pdf" in manifest.files
    assert "prisma_flow_diagram.md" not in manifest.files


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
    compose(tmp_path)
    pack = json.loads((tmp_path / "target_journal_pack.json").read_text())
    pack["main_word_limit"] = "not-an-integer"
    (tmp_path / "target_journal_pack.json").write_text(json.dumps(pack))
    with pytest.raises(SubmissionPackageError, match="pack.*invalid"):
        compose(tmp_path)
    assert not (tmp_path / PACKAGE_DIRNAME).exists()


def test_compose_propagates_disclosure_builder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)
    compose(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("disclosure failed")

    monkeypatch.setattr(
        "agent.manuscript_appendix.build_search_provenance_appendix", fail,
    )
    with pytest.raises(RuntimeError, match="disclosure failed"):
        compose(tmp_path)
    assert not (tmp_path / PACKAGE_DIRNAME).exists()
    assert not list(tmp_path.glob(f".{PACKAGE_DIRNAME}-*"))


def test_compose_aborts_when_source_receipts_change_mid_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)

    def mutate_status(*_args, **_kwargs) -> str:
        status = json.loads((tmp_path / "final_status.json").read_text())
        status["maturity_label"] = "concurrently changed"
        (tmp_path / "final_status.json").write_text(json.dumps(status))
        return "search provenance"

    monkeypatch.setattr(
        "agent.manuscript_appendix.build_search_provenance_appendix", mutate_status,
    )
    with pytest.raises(SubmissionPackageError, match="sources changed"):
        compose(tmp_path)
    assert not (tmp_path / PACKAGE_DIRNAME).exists()
    assert not list(tmp_path.glob(f".{PACKAGE_DIRNAME}-*"))


def test_compose_uses_one_manifest_snapshot_during_aba_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    certified = manifest_path.read_bytes()
    seen_topics: list[str] = []

    def aba_provenance(manifest: dict[str, Any], *, topic: str) -> str:
        transient = json.loads(certified)
        transient["topic"] = "uncertified_b"
        manifest_path.write_text(json.dumps(transient))
        try:
            seen_topics.append(str(manifest.get("topic")))
            return f"snapshot topic: {topic}"
        finally:
            manifest_path.write_bytes(certified)

    monkeypatch.setattr(
        "agent.manuscript_appendix.build_search_provenance_appendix",
        aba_provenance,
    )

    compose(tmp_path)

    assert seen_topics == ["test_topic"]
    assert (tmp_path / PACKAGE_DIRNAME / "search_provenance.md").read_text() == (
        "snapshot topic: test_topic"
    )


def test_compose_validates_the_same_snapshot_it_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    certified = manifest_path.read_bytes()
    from agent import artifact_consistency
    validate = artifact_consistency.consistency_receipt_matches
    validated_paths: list[Path] = []

    def aba_validate(run_dir: Path, stored: object) -> bool:
        transient = json.loads(certified)
        transient["topic"] = "uncertified_b"
        manifest_path.write_text(json.dumps(transient))
        try:
            validated_paths.append(run_dir)
            return validate(run_dir, stored)
        finally:
            manifest_path.write_bytes(certified)

    monkeypatch.setattr(artifact_consistency, "consistency_receipt_matches", aba_validate)
    compose(tmp_path)

    assert validated_paths and validated_paths[0] != tmp_path
    packaged = json.loads((tmp_path / PACKAGE_DIRNAME / "manifest.json").read_text())
    assert packaged["run_dir"] == str(tmp_path)


def _seed_revision_source_proof(tmp_path: Path) -> Path:
    excerpt = "The randomized trial reported a durable clinical improvement during follow-up."
    source_path = tmp_path / "revision_evidence_snapshot" / "parsed" / "R1.paper_sections.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps({"sections": {"results": excerpt}}))
    raw = source_path.read_bytes()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    row = manifest["receipts"][0]
    row.update({
        "n_claims": 1, "directness": "direct", "evidence_tier": "A1",
        "source_doi": "10.1000/proof", "evidence_origin": "pubmed",
        "source_record_locator": "revision-snapshot:test-run:test_topic:R1",
        "source_record_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "source_record_verified": True, "excerpt": excerpt,
        "source_content_hash": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
    })
    from agent.publication_evidence import source_identity_hash
    row["source_identity_hash"] = source_identity_hash(row, origin="pubmed")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    from agent.artifact_consistency import verify_run_artifacts, write_consistency_sidecar
    write_consistency_sidecar(tmp_path, verify_run_artifacts(tmp_path))
    from agent.final_status import compute_and_write
    assert compute_and_write(tmp_path).journal_submission_ready is True
    return source_path


def test_compose_snapshot_includes_revision_source_proof(tmp_path: Path) -> None:
    _seed_l5_run(tmp_path)
    _seed_revision_source_proof(tmp_path)

    compose(tmp_path)

    assert (tmp_path / PACKAGE_DIRNAME / "final_manuscript.md").is_file()


def test_compose_aborts_when_revision_source_proof_changes_mid_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_l5_run(tmp_path)
    source_path = _seed_revision_source_proof(tmp_path)

    def mutate_source(*_args: Any, **_kwargs: Any) -> str:
        source_path.write_text('{"sections":{"results":"concurrently changed"}}')
        return "search provenance"

    monkeypatch.setattr(
        "agent.manuscript_appendix.build_search_provenance_appendix", mutate_source,
    )
    with pytest.raises(SubmissionPackageError, match="sources changed"):
        compose(tmp_path)
