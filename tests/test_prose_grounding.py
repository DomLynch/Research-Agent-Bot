import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent import prose_grounding as grounding
from agent.revision_evidence import create_revision_evidence_snapshot
from publishing import submission

CLAIM = "Resveratrol reduced fasting glycaemia in older adults, while the comparator was placebo [Smith 2020]."


@pytest.fixture
def run(tmp_path):
    quant, parsed, run = (tmp_path / name for name in ("quant", "parsed", "run"))
    for path in (quant, parsed, run):
        path.mkdir()
    (parsed / "trial.paper_sections.json").write_text(json.dumps({"paper_id": "trial", "title": "Resveratrol trial",
        "sections": {"abstract": "Resveratrol reduced fasting glucose in older adults compared with placebo.",
                     "results": "Resveratrol reduced fasting glucose by 12% compared with placebo."}}))
    (quant / "trial.quant_claims.json").write_text(json.dumps({"paper_id": "trial", "claims": []}))
    contracts = [{"receipt_id": "trial", "topic": "resveratrol", "n_claims": 1,
                  "source_doi": "10.1234/trial", "evidence_tier": "A1", "directness": "direct"}]
    registry = run / "citation_registry.json"
    registry.write_text(json.dumps({"trial": {"receipt_id": "trial", "body_citation": "Smith 2020", "source_doi": "10.1234/trial"}}))
    assert create_revision_evidence_snapshot(run, quant_dir=quant, parsed_dir=parsed, citation_registry=registry,
        receipt_ids=["trial"], receipt_contracts=contracts, topic="resveratrol")["passed"]
    (run / "manifest.json").write_text(json.dumps({"topic": "resveratrol", "receipts": contracts, "n_receipts": 1}))
    (run / "full_paper.md").write_text(f"# Resveratrol findings\n\n## Abstract\n\n{CLAIM}\n\n## Conclusion\n\n{CLAIM}\n")
    return run


def install_judge(monkeypatch, *, supported=True):
    calls = []
    async def judge(**kwargs):
        calls.append(kwargs)
        statements = json.loads(kwargs["messages"][1]["content"])["statements"]
        return SimpleNamespace(model="configured-reviewer", parsed={"assessments": [
            {"row": i, "supported": supported, "reason": "Source comparison checked."} for i in range(len(statements))]})
    monkeypatch.setattr(grounding, "chat_json", judge)
    monkeypatch.setattr(grounding, "build_judge_chain", lambda _: ["configured-reviewer"])
    return calls


def test_reviewed_paraphrase_survives_cleanup_payload_and_context_reset(run, monkeypatch):
    calls = install_judge(monkeypatch)
    bundle = grounding._verified_bundle(run)
    assert not submission._cited_claim_aligns(CLAIM, bundle, {0})
    asyncio.run(grounding.review_manuscript(run))
    assert calls[0]["chain"] == ["configured-reviewer"]
    with grounding.grounding_context(run):
        assert submission._cited_claim_aligns(CLAIM, bundle, {0})
        assert CLAIM in submission._attach_aligned_claim_references("## Conclusion\n\n" + CLAIM, bundle)
    assert not grounding.approved(CLAIM, bundle, {0})
    submission.prepare_submission_manuscript(run, enrich_sources=False)
    payload = submission.build_payload(run, enrich_sources=False)
    assert "reduced fasting glycaemia" in payload["body_markdown"]
    assert payload["core_claims_resolved"] is True
    assert "prose_grounding" not in json.dumps(payload)
    assert not grounding.approved(CLAIM, bundle, {0})


@pytest.mark.parametrize("change", ["number", "direction", "citation", "source", "body", "new_topic"])
def test_text_citation_source_or_topic_changes_cannot_borrow_review(run, monkeypatch, tmp_path, change):
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    claim = CLAIM
    if change == "number":
        claim = claim.replace("reduced", "reduced by 12%")
    elif change == "direction":
        claim = claim.replace("reduced", "increased")
    elif change == "citation":
        claim = claim.replace("Smith 2020", "Jones 2021")
    elif change == "source":
        bundle[0]["excerpt"] += " Correction: the result was null."
    elif change == "body":
        claim = claim.replace("older adults", "children")
    with grounding.grounding_context(tmp_path if change == "new_topic" else run):
        assert not grounding.approved(claim, bundle, {0})


def test_negative_review_and_corrupted_snapshot_fail_closed(run, monkeypatch):
    calls = install_judge(monkeypatch, supported=False)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert not grounding.approved(CLAIM, bundle, {0})
    assert len(calls) == 1
    (run / "revision_evidence_snapshot/parsed/trial.paper_sections.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot_unverified"):
        with grounding.grounding_context(run):
            pass


def test_changed_review_policy_invalidates_cached_support(run, monkeypatch):
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    monkeypatch.setattr(grounding, "_PROMPT", grounding._PROMPT + " New review requirement.")
    with grounding.grounding_context(run):
        assert not grounding.approved(CLAIM, bundle, {0})


@pytest.mark.parametrize("assessments", [[], [{"row": 0, "supported": "true", "reason": "yes"}],
    [{"row": 1, "supported": True, "reason": "yes"}], [{"row": 0, "supported": True, "reason": ""}],
    [{"row": 0, "supported": True, "reason": "yes"}] * 2])
def test_malformed_review_cannot_certify_prose(monkeypatch, assessments):
    async def judge(**kwargs):
        return SimpleNamespace(model="reviewer", parsed={"assessments": deepcopy(assessments)})
    monkeypatch.setattr(grounding, "chat_json", judge)
    with pytest.raises(ValueError, match="prose_semantic_review_invalid"):
        asyncio.run(grounding.review_statements([{"text": CLAIM}], []))


def test_curated_map_keeps_full_length_policy():
    from agent.review_type import COMPACT_REVIEW_TYPES, formal_appraisal_required, parse_review_type
    from agent.publishing.policy import publication_surface
    assert parse_review_type("curated_evidence_map") == "curated_evidence_map"
    assert "curated_evidence_map" not in COMPACT_REVIEW_TYPES
    assert not formal_appraisal_required("curated_evidence_map")
    assert publication_surface("curated_evidence_map") == publication_surface("prisma_scr_scoping_synthesis")
