from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_submit as daily  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_live_pubmed_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARKA_SOURCE_ABSTRACT_LIMIT", "0")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(root: Path, name: str = "synthesis-topic-v06-test") -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n## Abstract\n\nFull abstract.\n\n## References\n\nR01.",
        encoding="utf-8",
    )
    receipts = [
        {
            "receipt_id": f"topic_effect_{i}",
            "outcome_class": "longevity",
            "n_claims": 9,
            "effect_direction": "mixed",
            "directness": "direct",
        }
        for i in range(12)
    ]
    _write_json(run / "manifest.json", {
        "topic": "topic",
        "n_receipts": 12,
        "n_high_confidence_claims_total": 34,
        "n_non_orthogonal_tensions": 5,
        "receipts": receipts,
    })
    _write_json(run / "citation_registry.json", {
        row["receipt_id"]: {
            "receipt_id": row["receipt_id"],
            "body_citation": f"Smith {idx} 2026",
            "reference_id": f"R{idx:02d}",
            "source_year": 2026,
            "source_doi": "10.1/x" if idx == 1 else f"10.1/{idx}",
            "source_pmid": str(123 + idx),
        }
        for idx, row in enumerate(receipts, start=1)
    })
    _write_json(run / "full_paper.audit.json", {"p1_pass": True, "n_pass": 14, "n_total": 14})
    _write_json(run / "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write_json(run / "full_paper.final_verdict.json", {"verdict": "AAA"})
    _write_json(run / "pre_submit_gate.json", {"result": {"passed": True}})
    return run


def test_dry_run_selects_eligible_research_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(runs_root=tmp_path, date="2026-05-23")

    assert ledger["status"] == "dry_run_selected"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert (tmp_path / daily.LEDGER_DIR / "2026-05-23.json").exists()


def test_pre_submit_corpus_floor_returns_specific_blocker(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "pre_submit_gate.json", {
        "result": {
            "passed": False,
            "failures": [
                "n_receipts=3 < threshold 12",
                "n_tensions=0 < threshold 1",
            ],
        }
    })

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
    )

    assert selected is None
    assert considered[0]["status"] == (
        "preflight_insufficient_corpus:"
        "n_receipts=3 < threshold 12; n_tensions=0 < threshold 1"
    )


def test_source_floor_blocks_stale_passing_gate_below_researka_minimum(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["n_receipts"] = 11
    manifest["receipts"] = [
        {"receipt_id": f"r{i}", "outcome_class": "longevity", "n_claims": 1}
        for i in range(11)
    ]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        f"r{i}": {"receipt_id": f"r{i}", "body_citation": f"Smith {i}", "reference_id": f"R{i:02d}"}
        for i in range(11)
    })
    _write_json(run / "pre_submit_gate.json", {"result": {"passed": True}})

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
    )

    assert selected is None
    assert considered[0]["status"] == (
        "preflight_insufficient_corpus:n_receipts=11 < threshold 12"
    )


def test_source_floor_uses_actual_citation_bundle_not_manifest_only(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "citation_registry.json", {
        f"r{i}": {"receipt_id": f"r{i}", "body_citation": f"Smith {i}", "reference_id": f"R{i:02d}"}
        for i in range(11)
    })
    _write_json(run / "pre_submit_gate.json", {"result": {"passed": True}})

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
    )

    assert selected is None
    assert considered[0]["status"] == (
        "preflight_insufficient_corpus:n_receipts=11 < threshold 12"
    )


def test_pre_submit_passing_gate_still_selects_candidate(tmp_path: Path) -> None:
    run = _run(tmp_path)

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"


def test_payload_uses_researka_v2_submission_contract(tmp_path: Path) -> None:
    run = _run(tmp_path)

    payload = daily.build_payload(run)

    assert payload["article_type"] == "rapid_evidence_synthesis"
    assert payload["author_agent_id"] == "agent-v3-full-paper"
    assert payload["artifact_type"] == "research_paper"
    assert payload["metadata"]["artifact_type"] == "research_paper"
    assert payload["body_markdown"].startswith("# Research Synthesis")
    assert "\n## Abstract" in payload["body_markdown"]
    assert "Full Manuscript" not in payload["sections"]
    assert payload["sections"]["Research Question"]
    assert payload["author_signature"].startswith("sha256:")
    assert payload["source_bundle"][0]["doi"] == "10.1/x"
    assert payload["source_bundle"][0]["evidence_type"] == "primary"
    assert "published" not in payload


def test_source_bundle_uses_claim_excerpt_and_directness_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daily, "ROOT", tmp_path)
    run = _run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "topic"
    manifest["receipts"] = [{
        "receipt_id": "r1",
        "outcome_class": "longevity",
        "n_claims": 9,
        "effect_direction": "mixed",
        "directness": "indirect",
    }]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        "r1": {"receipt_id": "r1", "body_citation": "Smith 2026", "reference_id": "R01", "source_year": 2026, "source_doi": "10.1/x", "source_pmid": "123"}
    })
    claims_dir = tmp_path / "docs" / "quality-reference" / "topic" / "quant_claims"
    claims_dir.mkdir(parents=True)
    _write_json(claims_dir / "r1.quant_claims.json", {
        "claims": [
            {"sentence": "Generic extraction noise.", "binding_confidence": "none"},
            {"sentence": "GDF11 changed a measured endpoint in the retained source.", "binding_confidence": "partial"},
        ],
    })

    payload = daily.build_payload(run)

    assert payload["source_bundle"][0]["evidence_type"] == "primary"
    assert payload["source_bundle"][0]["excerpt"] == "GDF11 changed a measured endpoint in the retained source."


def test_source_bundle_prefers_pubmed_abstract_over_registry_summary(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["receipts"] = [{
        "receipt_id": "r1",
        "source_title": "Real source title",
        "outcome_class": "longevity",
        "n_claims": 9,
        "effect_direction": "mixed",
        "directness": "direct",
    }]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        "r1": {"receipt_id": "r1", "body_citation": "Smith 2026", "reference_id": "R01", "source_year": 2026, "source_pmid": "123"}
    })
    monkeypatch.setattr(daily, "_pubmed_abstracts", lambda pmids: {"123": "PubMed abstract with methods, outcomes, and directional findings."})

    payload = daily.build_payload(run)

    assert payload["source_bundle"][0]["title"] == "Real source title"
    assert payload["source_bundle"][0]["excerpt"] == "PubMed abstract with methods, outcomes, and directional findings."
    assert "registered as" not in payload["source_bundle"][0]["excerpt"]


def test_source_bundle_structured_fallback_is_audit_specific(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daily, "_pubmed_abstracts", lambda pmids: {})
    run = _run(tmp_path)

    payload = daily.build_payload(run)

    excerpt = payload["source_bundle"][0]["excerpt"]
    assert "Source-bundle audit" in excerpt
    assert "effect_direction=" in excerpt
    assert "registered as" not in excerpt


def test_high_null_no_direct_abstract_bundle_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nEvidence-honesty note: 15/16 retained sources are coded as null or no extracted directional signal. "
        "The retained evidence has no direct interventional hard-endpoint evidence.\n\n",
        encoding="utf-8",
    )
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["n_receipts"] = 16
    manifest["receipts"] = [
        {
            "receipt_id": f"topic_r{i}",
            "paper_id": f"topic_r{i}",
            "source_pmid": str(1000 + i),
            "source_title": f"Topic source {i}",
            "effect_direction": "null",
            "directness": "indirect",
            "outcome_class": "context",
            "n_claims": 3,
        }
        for i in range(16)
    ]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        f"topic_r{i}": {"receipt_id": f"topic_r{i}", "source_pmid": str(1000 + i), "reference_id": f"R{i:02d}"}
        for i in range(16)
    })
    monkeypatch.setattr(
        daily,
        "_pubmed_abstracts",
        lambda pmids: {pmid: f"BACKGROUND: Source {pmid} reports extractable outcome direction." for pmid in pmids},
    )

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-04",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("mismatched null coding must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "null_coding_requires_reconciliation:15/16_null_no_direct"


def test_lower_null_ratio_abstract_bundle_still_eligible(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nEvidence-honesty note: 15/27 retained sources are coded as null or no extracted directional signal.\n\n",
        encoding="utf-8",
    )
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["n_receipts"] = 27
    manifest["receipts"] = [
        {"receipt_id": f"topic_r{i}", "paper_id": f"topic_r{i}", "source_pmid": str(1000 + i), "effect_direction": "null", "directness": "indirect"}
        for i in range(27)
    ]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        f"topic_r{i}": {"receipt_id": f"topic_r{i}", "source_pmid": str(1000 + i), "reference_id": f"R{i:02d}"}
        for i in range(27)
    })
    monkeypatch.setattr(
        daily,
        "_pubmed_abstracts",
        lambda pmids: {pmid: f"BACKGROUND: Source {pmid} reports extractable outcome direction." for pmid in pmids},
    )

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"


def test_source_bundle_keeps_review_type_for_review_receipts(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["receipts"][0]["directness"] = "review"
    _write_json(run / "manifest.json", manifest)

    payload = daily.build_payload(run)

    assert payload["source_bundle"][0]["evidence_type"] == "review"


def test_payload_key_findings_distill_not_duplicate_evidence_landscape(tmp_path: Path) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nAbstract overview.\n\n"
        "## Results\n\n| Outcome | Signal |\n|---|---|\n| immune | mixed |\n\nResults repeat table detail.\n\n"
        "## Limitations\n\nThe evidence base is dominated by preclinical and review evidence.\n\n"
        "## Conclusion\n\nThe core finding is that human application remains bounded by few direct clinical trials. "
        "Future work should test patient-relevant outcomes.\n\n"
        "## References\n\nR01.",
        encoding="utf-8",
    )

    payload = daily.build_payload(run)

    assert payload["sections"]["Evidence Landscape"] != payload["sections"]["Key Findings"]
    assert "|" not in payload["sections"]["Key Findings"]
    assert "few direct clinical trials" in payload["sections"]["Key Findings"]


def test_payload_gaps_identified_is_actionable_not_limitations_duplicate(tmp_path: Path) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nAbstract overview.\n\n"
        "## Results\n\nOutcome evidence is mixed.\n\n"
        "## Discussion\n\nThe evidence base is sparse and mixed.\n\n"
        "## Limitations\n\nThe evidence base is sparse and mixed.\n\n"
        "## Conclusion\n\nConservative conclusion.\n\n",
        encoding="utf-8",
    )

    payload = daily.build_payload(run)
    gaps = payload["sections"]["Gaps Identified"]

    assert gaps != payload["sections"]["Limitations"]
    assert "Run adequately powered human studies" in gaps
    assert "Standardize exposure, comparator, follow-up duration, and endpoint definitions" in gaps
    assert "direct evidence is" in gaps


def test_payload_gaps_identified_preserves_distinct_paper_section(tmp_path: Path) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nAbstract overview.\n\n"
        "## Gaps Identified\n\nRecruit older adult cohorts with prespecified endpoints and 12-month follow-up.\n\n"
        "## Limitations\n\nThe evidence base is sparse and mixed.\n\n",
        encoding="utf-8",
    )

    payload = daily.build_payload(run)

    assert payload["sections"]["Gaps Identified"] == (
        "Recruit older adult cohorts with prespecified endpoints and 12-month follow-up."
    )


def test_payload_text_fields_do_not_truncate_mid_sentence(tmp_path: Path) -> None:
    run = _run(tmp_path)
    long_abstract = " ".join(f"Sentence {i} supports a bounded evidence interpretation." for i in range(80))
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        f"## Abstract\n\n{long_abstract}\n\n"
        "## Results\n\nResult sentence.\n\n"
        "## Conclusion\n\nConclusion sentence.\n\n",
        encoding="utf-8",
    )

    payload = daily.build_payload(run)

    assert payload["abstract"][-1] == "."
    assert payload["sections"]["Research Question"][-1] == "."
    assert len(payload["sections"]["Research Question"]) < 900


def test_payload_empty_agent_env_still_uses_v3_slug(tmp_path: Path, monkeypatch: Any) -> None:
    run = _run(tmp_path)
    monkeypatch.setenv("AGENT_ID", "")
    monkeypatch.setenv("RESEARKA_AGENT_SLUG_V3", "")

    payload = daily.build_payload(run)

    assert payload["author_agent_id"] == "agent-v3-full-paper"


def test_payload_carries_revision_metadata_when_present(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "source_run": "old-run",
        "title": "Research Synthesis: Topic",
        "feedback": "Add clearer caveats and resubmit.",
    })

    payload = daily.build_payload(run)

    assert payload["metadata"]["revision_of"] == {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "source_run": "old-run",
        "title": "Research Synthesis: Topic",
    }
    assert payload["metadata"]["revision_feedback"] == "Add clearer caveats and resubmit."


def test_successful_post_records_submitted_not_published(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda payload: {"ok": True, "status": 201, "response": {"id": "obj-1", "title": payload["title"]}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["published"] == 0
    records = json.loads((tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json").read_text(encoding="utf-8"))
    assert records[0]["topic"] == "topic"


def test_submit_uses_final_status_ready_over_all_green_verdict(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    _write_json(run / "full_paper.audit.json", {"p1_pass": True, "n_pass": 13, "n_total": 14})
    _write_json(run / "full_paper.final_verdict.json", {"verdict": "Trust-Spine Pass"})
    _write_json(run / "final_status.json", {"submission_ready": True})
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda payload: {"ok": True, "status": 201, "response": {"id": "obj-1", "title": payload["title"]}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"


def test_low_source_topic_precision_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path, name="synthesis-epigenome_editing_longevity-v06-test")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "epigenome_editing_longevity"
    manifest["receipts"] = [
        {"receipt_id": "supercapacitor_electrode_material", "paper_id": "supercapacitor_electrode_material"},
        {"receipt_id": "plant_genetics_flowering", "paper_id": "plant_genetics_flowering"},
        {"receipt_id": "glucose_transporter_fgt1", "paper_id": "glucose_transporter_fgt1"},
        {"receipt_id": "epigenome_editing_locus_specific", "paper_id": "epigenome_editing_locus_specific"},
    ]
    _write_json(run / "manifest.json", manifest)
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-01",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("off-topic corpus must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "source_topic_precision_low:1/4<0.35"


def test_source_topic_precision_uses_topic_aliases(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path / "runs", name="synthesis-hydrogen_water-v06-test")
    (tmp_path / "topic_packs").mkdir()
    (tmp_path / "topic_packs" / "hydrogen_water.toml").write_text(
        'aliases = ["molecular hydrogen", "hydrogen-rich water"]\n',
        encoding="utf-8",
    )
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "hydrogen_water"
    manifest["receipts"] = [
        {"receipt_id": "randomized_molecular_hydrogen_trial", "paper_id": "randomized_molecular_hydrogen_trial"},
        {"receipt_id": "molecular_hydrogen_human_metabolic_trial", "paper_id": "molecular_hydrogen_human_metabolic_trial"},
        {"receipt_id": "molecular_hydrogen_improves_blueberry_plant_traits", "paper_id": "molecular_hydrogen_improves_blueberry_plant_traits"},
    ]
    _write_json(run / "manifest.json", manifest)
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ok, status = daily._source_topic_precision(run)

    assert ok
    assert status == "source_topic_precision_ok:2/3"


def test_source_topic_precision_counts_static_hrt_aliases(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path / "runs", name="synthesis-hormone_optimization_hrt-v06-test")
    (tmp_path / "topic_packs").mkdir()
    (tmp_path / "topic_packs" / "hormone_optimization_hrt.toml").write_text(
        'aliases = ["HRT", "hormone replacement therapy", "menopause hormone therapy"]\n',
        encoding="utf-8",
    )
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "hormone_optimization_hrt"
    manifest["receipts"] = [
        {"receipt_id": "hormone_replacement_therapy_associated_with_cognition", "paper_id": "hormone_replacement_therapy_associated_with_cognition"},
        {"receipt_id": "benefits_and_risks_of_menopause_hormone_therapy", "paper_id": "benefits_and_risks_of_menopause_hormone_therapy"},
        {"receipt_id": "growth_hormone_replacement_in_older_adults", "paper_id": "growth_hormone_replacement_in_older_adults"},
    ]
    _write_json(run / "manifest.json", manifest)
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ok, status = daily._source_topic_precision(run)

    assert ok
    assert status == "source_topic_precision_ok:2/3"


def test_candidate_run_restriction_does_not_submit_other_eligible_runs(tmp_path: Path) -> None:
    older = _run(tmp_path, name="synthesis-topic-v06-eligible-old")
    current = _run(tmp_path, name="synthesis-topic-v06-current")
    _write_json(current / "full_paper.journal_surface.json", {"passed": False, "issues": ["short_conclusion"]})
    os.utime(older, (1, 1))
    os.utime(current, (2, 2))

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-29",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("should not submit older run")),
        remote_loader=lambda: (set(), None),
        candidate_run=current,
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["considered"] == [{
        "run": current.name,
        "fingerprint": daily._sha256(current / "full_paper.md"),
        "status": "journal_surface_not_passed",
    }]


def test_duplicate_fingerprint_is_not_resubmitted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    fp = daily._payload_fingerprint(daily.build_payload(run))
    _write_json(tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json", [{"fingerprint": fp}])

    ledger = daily.run_cycle(runs_root=tmp_path, date="2026-05-23")

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_researka_rejection_records_and_skips_same_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": False, "status": 422, "response": "gate rejected"},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submission_rejected_by_researka"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["status"] == "submission_rejected_by_researka"
    assert ledger["revision_feedback"] == "gate rejected"
    rejected = json.loads((tmp_path / daily.LEDGER_DIR / daily.REJECTED_FINGERPRINTS).read_text(encoding="utf-8"))
    assert rejected[0]["topic"] == "topic"

    retry = daily.run_cycle(runs_root=tmp_path, date="2026-05-24")

    assert retry["status"] == "no_eligible_research_paper"
    assert retry["considered"][0]["status"] == "researka_rejected_fingerprint"


def test_researka_revise_records_feedback_and_skips_same_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {
            "ok": False,
            "status": 422,
            "response": {"decision": "revise", "checklist": ["tighten headline", "resubmit"]},
        },
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submission_revise_requested"
    assert "tighten headline" in ledger["revision_feedback"]
    assert ledger["considered"][0]["status"] == "submission_revise_requested"
    records = json.loads((tmp_path / daily.LEDGER_DIR / daily.REVISION_FINGERPRINTS).read_text(encoding="utf-8"))
    assert records[0]["topic"] == "topic"
    assert "resubmit" in records[0]["feedback"]

    retry = daily.run_cycle(runs_root=tmp_path, date="2026-05-24")

    assert retry["status"] == "no_eligible_research_paper"
    assert retry["considered"][0]["status"] == "researka_revision_fingerprint"


def test_remote_publication_dedupe_blocks_resubmission_without_local_seed(tmp_path: Path) -> None:
    run = _run(tmp_path)
    fp = daily.build_payload(run)["metadata"]["content_hash"]

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({fp}, None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"


def test_remote_publication_dedupe_blocks_same_title_rerun(tmp_path: Path) -> None:
    run = _run(tmp_path)
    marker = daily._title_marker(daily.build_payload(run)["title"])

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({marker}, None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"


def test_remote_publication_dedupe_allows_revision_of_existing_title(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "feedback": "Differentiate the revised version.",
    })
    marker = daily._title_marker(daily.build_payload(run)["title"])

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({marker}, None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["considered"][0]["status"] == "submitted_to_researka"


def test_selection_skips_stale_older_runs_for_same_topic(tmp_path: Path) -> None:
    older = _run(tmp_path, name="synthesis-topic-v06-older")
    newer = _run(tmp_path, name="synthesis-topic-v06-newer")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({daily.build_payload(newer)["metadata"]["content_hash"]}, None),
    )

    statuses = [row["status"] for row in ledger["considered"]]
    assert "duplicate_remote_publication" in statuses
    assert "superseded_topic_run" in statuses
    assert ledger["submitted"] == 0


def test_selection_submits_older_retry_when_newer_retry_fails_gates(tmp_path: Path) -> None:
    older = _run(tmp_path, name="synthesis-topic-v06-R2")
    newer = _run(tmp_path, name="synthesis-topic-v06-R3")
    _write_json(newer / "full_paper.journal_surface.json", {"passed": False, "issues": ["short_conclusion"]})
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-28",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["candidate"]["run"] == older.name
    assert [row["status"] for row in ledger["considered"]] == [
        "journal_surface_not_passed",
        "submitted_to_researka",
    ]


def test_selection_repairs_stale_accountability_sidecar_before_skip(
    tmp_path: Path, monkeypatch,
) -> None:
    run = _run(tmp_path)
    _write_json(run / "target_journal_pack.json", {
        "journal": "GeroScience", "declared_in_topic_pack": True,
    })
    _write_json(run / "benchmark_runtime.json", {"return_code": 0})
    _write_json(run / "pre_submit_gate.json", {
        "result": {"passed": True, "failures": []},
        "journal_readiness_contract": [{
            "id": 13, "name": "accountability", "status": "not_ready",
            "audit": "machine proof package unavailable",
            "blocks_submission": True,
        }],
    })
    def fake_refresh(path: Path) -> list[object]:
        _write_json(path / "artifact_consistency.json", {"passed": True, "checks": []})
        gate = json.loads((path / "pre_submit_gate.json").read_text(encoding="utf-8"))
        gate["journal_readiness_contract"][0].update({
            "status": "pass", "audit": "researka_agent_certified mode",
            "blocks_submission": False,
        })
        _write_json(path / "pre_submit_gate.json", gate)
        return [object()]

    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "_phase_g_refresh_sidecars", fake_refresh)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-28",
        submit=True,
        submitter=lambda payload: {"ok": True, "status": 201, "response": {"title": payload["title"]}},
        remote_loader=lambda: (set(), None),
    )
    gate = json.loads((run / "pre_submit_gate.json").read_text(encoding="utf-8"))
    item_13 = next(row for row in gate["journal_readiness_contract"] if row["id"] == 13)

    assert ledger["status"] == "submitted_to_researka"
    assert (run / "artifact_consistency.json").is_file()
    assert item_13["status"] == "pass"


def _recording_refresh(called: list[Path]):
    def fake_refresh(path: Path) -> list[object]:
        called.append(path)
        return [object()]
    return fake_refresh


def test_stale_audit_refresh_fires_for_recent_failing_run(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    _write_json(run / "full_paper.audit.json", {"p1_pass": False, "n_pass": 13, "n_total": 14})
    called: list[Path] = []
    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "_phase_g_refresh_sidecars", _recording_refresh(called))
    assert daily._refresh_stale_audit_sidecar(run) is True
    assert called == [run]


def test_stale_audit_refresh_skips_old_failing_run(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    _write_json(run / "full_paper.audit.json", {"p1_pass": False, "n_pass": 13, "n_total": 14})
    old = time.time() - (daily.STALE_AUDIT_REFRESH_WINDOW_S + 3600)
    os.utime(run, (old, old))
    called: list[Path] = []
    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "_phase_g_refresh_sidecars", _recording_refresh(called))
    assert daily._refresh_stale_audit_sidecar(run) is False
    assert called == []


def test_stale_audit_refresh_skips_all_green_run(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)  # _run writes an all-green audit (p1_pass True, 14/14)
    called: list[Path] = []
    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "_phase_g_refresh_sidecars", _recording_refresh(called))
    assert daily._refresh_stale_audit_sidecar(run) is False
    assert called == []


def test_submit_holds_when_remote_dedupe_fails(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (set(), "timeout"),
    )

    assert ledger["status"] == "remote_dedupe_failed"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0


def test_submit_without_token_is_held(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path)
    for name in daily.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    calls = 0

    def remote_loader() -> tuple[set[str], str | None]:
        nonlocal calls
        calls += 1
        return set(), None

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        remote_loader=remote_loader,
    )

    assert ledger["status"] == "submit_not_configured"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert calls == 0


def test_http_submitter_sends_runtime_key_headers_and_idempotency(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Response:
        status = 201

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"id":"obj-1"}'

    def fake_urlopen(req: Request, timeout: int) -> Response:
        seen["timeout"] = timeout
        seen["headers"] = dict(req.header_items())
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = daily._submitter("https://api.example/submissions", "secret", "agent-v3")(
        {"title": "paper", "metadata": {"content_hash": "sha256:abc"}},
    )

    assert result["ok"] is True
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["headers"]["X-api-key"] == "secret"
    assert seen["headers"]["X-agent-slug"] == "agent-v3"
    assert seen["headers"]["Idempotency-key"] == "sha256:abc"
