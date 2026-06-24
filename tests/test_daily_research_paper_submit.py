from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from types import SimpleNamespace
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


def _words(token: str, count: int) -> str:
    return " ".join([token] * count)


def test_seen_field_reads_valid_string_fields_only(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    _write_json(ledger, [
        {"topic": "alpha", "run": "run-a"},
        {"topic": "", "run": "run-b"},
        {"topic": 123, "run": None},
        ["not", "a", "record"],
        {"other": "ignored"},
    ])

    assert daily._seen_field(ledger, "topic") == {"alpha"}
    assert daily._seen_field(ledger, "run") == {"run-a", "run-b"}
    assert daily._seen_field(tmp_path / "missing.json", "topic") == set()


def _run(root: Path, name: str = "synthesis-topic-v06-test", *, tensions: int = 5) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        f"## Abstract\n\n{_words('abstract', 90)}.\n\n"
        f"## Introduction\n\n{_words('introduction', 350)}.\n\n"
        f"## Methods\n\n{_words('methods', 300)}.\n\n"
        f"## Results\n\n{_words('results', 850)}.\n\n"
        f"## Discussion\n\n{_words('discussion', 500)}.\n\n"
        f"## Limitations\n\n{_words('limitations', 200)}.\n\n"
        f"## Conclusion\n\n{_words('conclusion', 120)}.\n\n"
        "## References\n\nR01.",
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
        "n_non_orthogonal_tensions": tensions,
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
    assert payload["domain_slug"] == "longevity"
    assert payload["category"] == "longevity"
    assert payload["author_agent_id"] == "agent-v3-full-paper"
    assert payload["artifact_type"] == "research_paper"
    assert payload["metadata"]["artifact_type"] == "research_paper"
    assert payload["metadata"]["article_type"] == "rapid_evidence_synthesis"
    assert payload["metadata"]["domain_slug"] == "longevity"
    assert payload["metadata"]["category"] == "longevity"
    assert payload["metadata"]["topic"] == "topic"
    assert payload["metadata"]["source_citation_hash"].startswith("sha256:")
    assert payload["metadata"]["submission_identity_key"].startswith("sha256:")
    assert payload["metadata"]["submission_payload_hash"].startswith("sha256:")
    assert payload["body_markdown"].startswith("# Research Synthesis")
    assert "\n## Abstract" in payload["body_markdown"]
    assert "Full Manuscript" not in payload["sections"]
    assert "Abstract" not in payload["sections"]
    assert "Methods" not in payload["sections"]
    assert payload["sections"]["Research Question"]
    assert payload["sections"]["Evidence Landscape"]
    assert payload["author_signature"].startswith("sha256:")
    assert payload["source_bundle"][0]["doi"] == "10.1/x"
    assert payload["source_bundle"][0]["evidence_type"] == "primary"
    assert "published" not in payload


def test_researka_preflight_blocks_thin_full_paper_before_submit(tmp_path: Path) -> None:
    run = _run(tmp_path)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\n" + _words("abstract", 90) + ".\n\n"
        "## Introduction\n\nThin introduction.\n\n"
        "## Methods\n\nThin methods.\n\n"
        "## Results\n\nThin results.\n\n"
        "## Discussion\n\nThin discussion.\n\n"
        "## Limitations\n\nThin limitations.\n\n"
        "## Conclusion\n\nThin conclusion.\n\n",
        encoding="utf-8",
    )

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-07",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("thin paper must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["reason"].startswith("researka_preflight_body_words:")
    assert ledger["submitted"] == 0


def test_researka_preflight_uses_exact_research_synthesis_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_ARTICLE_TYPE_V3", "research_synthesis")
    payload = daily.build_payload(_run(tmp_path))

    assert daily._researka_preflight_status(payload) == "eligible"

    payload["sections"].pop("Methods")
    assert daily._researka_preflight_status(payload) == "researka_preflight_missing_sections:Methods"


def test_evidence_map_auto_selected_for_high_tension_corpus(tmp_path: Path) -> None:
    # Tension density 20/12 = 1.67 >= 1.0 floor: a non-convergent landscape.
    payload = daily.build_payload(_run(tmp_path, tensions=20))

    assert payload["article_type"] == "evidence_map"
    assert payload["metadata"]["article_type"] == "evidence_map"
    for name in ("Scope", "Search Summary", "Evidence Landscape", "Findings Map", "Tensions and Gaps", "Limitations"):
        assert payload["sections"][name].strip(), name
    # Thesis-lane sections must not leak into a landscape payload.
    assert "Research Question" not in payload["sections"]
    assert "Key Findings" not in payload["sections"]
    assert daily._researka_preflight_status(payload) == "eligible"


def test_low_tension_corpus_stays_default_thesis_lane(tmp_path: Path) -> None:
    # Tension density 5/12 = 0.42 < 1.0: coherent enough for a single thesis.
    payload = daily.build_payload(_run(tmp_path, tensions=5))

    assert payload["article_type"] == "rapid_evidence_synthesis"


def test_explicit_article_type_overrides_landscape_auto_select(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_ARTICLE_TYPE_V3", "rapid_evidence_synthesis")
    # High tension would auto-select evidence_map, but the explicit override wins.
    payload = daily.build_payload(_run(tmp_path, tensions=40))

    assert payload["article_type"] == "rapid_evidence_synthesis"


def test_evidence_map_tension_floor_is_env_tunable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_EVIDENCE_MAP_TENSION_FLOOR", "5.0")
    # Density 20/12 = 1.67 now falls below the raised 5.0 floor.
    payload = daily.build_payload(_run(tmp_path, tensions=20))

    assert payload["article_type"] == "rapid_evidence_synthesis"


def test_evidence_map_scope_meets_live_question_word_floor(tmp_path: Path) -> None:
    payload = daily.build_payload(_run(tmp_path, tensions=20))

    # Scope is evidence_map's research-question section; the live core floor is 30.
    assert daily._word_count(payload["sections"]["Scope"]) >= 30
    assert payload["sections"]["Scope"].startswith("This evidence map surveys")


def test_evidence_map_tension_density_boundary_is_inclusive(tmp_path: Path) -> None:
    # 12 receipts: density == 1.0 (exactly the floor) routes to the landscape
    # lane; one fewer tension (density 11/12 < 1.0) stays on the thesis lane.
    at_floor = daily.build_payload(_run(tmp_path, name="synthesis-at-v06", tensions=12))
    below_floor = daily.build_payload(_run(tmp_path, name="synthesis-below-v06", tensions=11))

    assert at_floor["article_type"] == "evidence_map"
    assert below_floor["article_type"] == "rapid_evidence_synthesis"


def test_researka_preflight_requires_twelve_sources(tmp_path: Path) -> None:
    payload = daily.build_payload(_run(tmp_path))
    payload["source_bundle"] = payload["source_bundle"][:11]

    assert daily._researka_preflight_status(payload) == "researka_preflight_insufficient_sources:11 < 12"


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
    assert payload["source_bundle"][0]["cited_as"] == "Smith 2026"


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


def test_source_bundle_grounds_author_year_citation_via_cited_as(tmp_path: Path, monkeypatch) -> None:
    """Reviewer grounding (2026-06-12 semaglutide revise): prose cites sources
    author-year (e.g. 'Zufry 2025') but bundle entries carried only
    doi/pmid/title/year, so the reviewer could not map the citation to a source
    and returned a revise. The entry now emits the registry's body_citation as
    the first-class `cited_as` field the Researka reviewer matches on
    (workflow.py: cited_as / title / year). Universal across domains."""
    run = _run(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["receipts"] = [{
        "receipt_id": "r1", "outcome_class": "cardiometabolic", "n_claims": 5,
        "effect_direction": "unclear", "directness": "review",
    }]
    _write_json(run / "manifest.json", manifest)
    _write_json(run / "citation_registry.json", {
        "r1": {"receipt_id": "r1", "body_citation": "Zufry 2025", "reference_id": "R01", "source_year": 2025, "source_pmid": "123"}
    })
    monkeypatch.setattr(daily, "_pubmed_abstracts", lambda pmids: {"123": "Abstract body text."})

    entry = daily.build_payload(run)["source_bundle"][0]
    assert entry["cited_as"] == "Zufry 2025"
    # Grounding rides the dedicated cited_as field; excerpt is left clean.
    assert entry["excerpt"] == "Abstract body text."


def test_source_bundle_structured_fallback_is_audit_specific(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daily, "_pubmed_abstracts", lambda pmids: {})
    run = _run(tmp_path)

    payload = daily.build_payload(run)

    excerpt = payload["source_bundle"][0]["excerpt"]
    assert "Source-bundle audit" in excerpt
    assert "effect_direction=" in excerpt
    assert "registered as" not in excerpt


def test_high_null_no_direct_abstract_bundle_blocks_without_generation_reconciliation(tmp_path: Path, monkeypatch) -> None:
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
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("unreconciled paper must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "null_coding_requires_reconciliation:15/16_null_no_direct"


def test_generation_reconciled_null_coding_submits_signed_body_unchanged(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path)
    note = (
        "Evidence-honesty note: 15/16 retained sources are coded as null or no extracted directional signal; "
        "this corpus is non-supportive for clinical efficacy claims and hypothesis-generating only. "
        "Source-bundle reconciliation note: Directional coding is conservative claim-level coding from extracted claim records, "
        "not a statement that the source texts contain no directional findings.\n\n"
    )
    paper = (
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\n" + note + _words("abstract", 90) + ".\n\n"
        "## Introduction\n\n" + _words("introduction", 350) + ".\n\n"
        "## Methods\n\n" + _words("methods", 300) + ".\n\n"
        "## Results\n\n" + _words("results", 850) + ".\n\n"
        "## Discussion\n\n" + _words("discussion", 500) + ".\n\n"
        "## Limitations\n\n" + _words("limitations", 200) + ".\n\n"
        "## Conclusion\n\n" + note + _words("conclusion", 120) + ".\n\n"
    )
    (run / "full_paper.md").write_text(paper, encoding="utf-8")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["n_receipts"] = 16
    manifest["receipts"] = [
        {"receipt_id": f"topic_r{i}", "paper_id": f"topic_r{i}", "source_pmid": str(1000 + i), "effect_direction": "null", "directness": "indirect"}
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
    submitted: list[dict[str, Any]] = []

    def submitter(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(payload)
        return {"ok": True, "status": 201, "response": {}}

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-04",
        submit=True,
        submitter=submitter,
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert daily._null_coding_audit_status(submitted[0], manifest) == "eligible"
    assert submitted[0]["body_markdown"] == (run / "full_paper.md").read_text(encoding="utf-8").strip()
    assert submitted[0]["author_signature"] == daily._sha256(run / "full_paper.md")
    assert submitted[0]["metadata"]["content_hash"] == daily._sha256(run / "full_paper.md")
    assert "pre_submit_repairs" not in submitted[0]["metadata"]


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
    assert records[0]["submission_id"] == "obj-1"
    assert records[0]["submission_identity_key"].startswith("sha256:")
    assert records[0]["submission_payload_hash"].startswith("sha256:")


def test_successful_post_records_nested_submission_target_id(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-24",
        submit=True,
        submitter=lambda _payload: {
            "ok": True,
            "status": 201,
            "response": {
                "submission": {"title": "Nested"},
                "job": {"target_object_id": "sub-nested-1"},
            },
        },
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    records = json.loads((tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json").read_text(encoding="utf-8"))
    assert records[0]["submission_id"] == "sub-nested-1"


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
    assert ledger["considered"][0]["status"] == "source_topic_precision_low:1/4<0.50"


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


def test_source_topic_precision_entity_rescue_compound_topic(tmp_path: Path, monkeypatch) -> None:
    """Compound-topic blocker fix: the per-source gate requires EVERY
    specificity token, so a corpus whose titles name the entity but rarely a
    secondary axis term (resveratrol present, "metabolism" sparse) scores below
    the 0.50 floor even though every source is about the named entity. The
    entity rescue counts the dominant-entity (non-drift) sources. Pins the fix
    so future matcher tightening cannot silently re-block compound topics."""
    run = _run(tmp_path / "runs", name="synthesis-resveratrol_metabolism_effects-v06-test")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "resveratrol_metabolism_effects"
    manifest["receipts"] = [
        {"receipt_id": "r1", "source_title": "Resveratrol supplementation improves glucose tolerance in adults"},
        {"receipt_id": "r2", "source_title": "Trans-resveratrol and treadmill exercise on lipid profile"},
        {"receipt_id": "r3", "source_title": "Efficacy of resveratrol on glucose and lipid metabolism"},
        {"receipt_id": "r4", "source_title": "Resveratrol-coated metal oxide electrode for a supercapacitor"},
    ]
    _write_json(run / "manifest.json", manifest)
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ok, status = daily._source_topic_precision(run)

    # Strict precision is 1/4 (only r3 carries both "resveratrol" + "metabolism").
    # The rescue admits r1/r2/r3 (entity in a biomedical, non-drift title) and
    # excludes r4 (non-biomed drift: metal/oxide/electrode/supercapacitor).
    assert ok
    assert status == "source_topic_precision_ok:3/4:entity=resveratrol"


def test_source_topic_precision_entity_rescue_skips_drifted_corpus(tmp_path: Path, monkeypatch) -> None:
    """The rescue does not paper over a genuinely off-entity corpus: when the
    dominant entity is named in too few titles, the run stays blocked."""
    run = _run(tmp_path / "runs", name="synthesis-epigenome_editing_longevity-v06-test")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["topic"] = "epigenome_editing_longevity"
    manifest["receipts"] = [
        {"receipt_id": "r1", "source_title": "Supercapacitor electrode material performance"},
        {"receipt_id": "r2", "source_title": "Plant genetics of flowering time"},
        {"receipt_id": "r3", "source_title": "Glucose transporter expression in muscle"},
        {"receipt_id": "r4", "source_title": "Locus-specific epigenome editing for longevity"},
    ]
    _write_json(run / "manifest.json", manifest)
    monkeypatch.setattr(daily, "_refresh_stale_audit_sidecar", lambda _run: False)

    ok, status = daily._source_topic_precision(run)

    assert not ok
    assert status == "source_topic_precision_low:1/4<0.50"


def test_recency_ratio_blocks_old_source_bundle() -> None:
    # 2/5 of dated entries are 2020+ -> below the 0.50 floor (Researka would
    # reject at intake). Computed over the published bundle, so the padded
    # older reference stubs count against it.
    old_bundle = {"source_bundle": [
        {"year": 2021}, {"year": 2020},
        {"year": 2015}, {"year": 2013}, {"year": 2009},
        {"year": None}, {"title": "no year"},  # undated rows ignored
    ]}
    assert daily._recency_ratio_status(old_bundle) == "recency_ratio_low:2/5<0.50"


def test_recency_ratio_passes_recent_bundle_and_fails_open_when_undated() -> None:
    recent = {"source_bundle": [{"year": 2024}, {"year": 2022}, {"year": 2021}, {"year": 2014}]}
    assert daily._recency_ratio_status(recent) == "eligible"  # 3/4 = 75%
    assert daily._recency_ratio_status({"source_bundle": [{"title": "x"}]}) == "eligible"  # no years -> fail-open
    assert daily._recency_ratio_status({}) == "eligible"


def test_preflight_and_submitter_block_low_recency_before_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = daily.build_payload(_run(tmp_path))
    for row in payload["source_bundle"]:
        row["year"] = 2001

    def fail_urlopen(_req: Request, timeout: int) -> object:
        raise AssertionError("low-recency payload must not reach HTTP")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    assert daily._researka_preflight_status(payload) == "recency_ratio_low:0/12<0.50"
    result = daily._submitter("https://api.example/submissions", "secret", "agent-v3")(payload)

    assert result == {
        "ok": False,
        "status": 0,
        "response": "recency_ratio_low:0/12<0.50",
        "preflight": True,
    }


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


def test_already_submitted_pending_topic_is_not_resubmitted(tmp_path: Path) -> None:
    """A re-synthesized run of a topic already submitted to Researka (still
    pending — not published, not revise-requested) must be skipped: its fresh
    content fingerprint dodges the content-level dedup, but Researka dedups on
    the pending submission and returns duplicate_submission, so re-sending just
    burns the window. Topic-level skip prevents it."""
    _run(tmp_path)  # topic "topic"
    _write_json(
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        [{"topic": "topic", "fingerprint": "sha256:earlier-different-content"}],
    )

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-15",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("pending topic must not be resubmitted")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "topic_already_submitted_pending"


def test_duplicate_submission_response_seeds_pending_topic_skip(tmp_path: Path) -> None:
    """Researka's duplicate_submission means the journal already has this topic
    pending. Record it in the submitted ledger too; otherwise a regenerated run
    with a fresh content fingerprint can keep hitting the same duplicate."""
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-21",
        submit=True,
        submitter=lambda _payload: {
            "ok": False,
            "status": 409,
            "response": {"detail": {"error": "duplicate_submission", "submission_id": "sub-1"}},
        },
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submission_rejected_by_researka"
    submitted = json.loads((tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json").read_text(encoding="utf-8"))
    assert submitted[0]["topic"] == "topic"
    assert submitted[0]["duplicate_submission_id"] == "sub-1"

    regenerated = _run(tmp_path, name="synthesis-topic-v06-regenerated")
    with (regenerated / "full_paper.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\nAdditional regenerated sentence.")
    retry = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-22",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("duplicate topic must not submit again")),
        remote_loader=lambda: (set(), None),
    )

    assert retry["status"] == "no_eligible_research_paper"
    assert retry["considered"][0]["status"] == "topic_already_submitted_pending"


def test_already_submitted_topic_still_allows_revision(tmp_path: Path) -> None:
    """The pending-topic skip must NOT block a genuine revision: a run carrying
    a researka_revision_request is still submitted even though its topic is in
    the submitted ledger."""
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json",
                {"artifactId": "a", "submissionId": "s", "feedback": "tighten"})
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    _write_json(
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        [{"topic": "topic", "fingerprint": "sha256:earlier-different-content"}],
    )

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-15",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"


def test_revision_without_coverage_gate_is_not_submitted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {"artifactId": "a", "submissionId": "s", "feedback": "tighten"})

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-21",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("unverified revision must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "revision_coverage_unverified"


def test_failed_revision_coverage_gate_is_not_submitted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {"artifactId": "a", "submissionId": "s", "feedback": "tighten"})
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": False, "unmet_asks": ["Hedge claims"]})

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-21",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("failed revision must not submit")),
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "revision_coverage_unmet"


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


def test_selection_skips_exact_run_already_submitted_even_if_revision(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {"feedback": "tighten"})
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    ledger_dir = tmp_path / daily.LEDGER_DIR
    _write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "run": run.name,
        "fingerprint": "sha256:old-preflight-payload",
        "topic": "topic",
    }])

    selected, considered = daily.select_candidate(
        tmp_path,
        ledger_dir / "_submitted_fingerprints.json",
        remote_seen=set(),
    )

    assert selected is None
    assert considered[0]["status"] == "duplicate_submission_run"


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


def test_remote_publication_dedupe_allows_explicit_revision_of_existing_title(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "feedback": "Differentiate the revised version.",
    })
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    marker = daily._title_marker(daily.build_payload(run)["title"])

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({marker}, None),
        candidate_run=run,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["considered"][0]["status"] == "submitted_to_researka"


def test_remote_publication_dedupe_blocks_stale_revision_in_generic_sweep(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "feedback": "Already handled.",
    })
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    marker = daily._title_marker(daily.build_payload(run)["title"])

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-22",
        submit=True,
        submitter=lambda _payload: (_ for _ in ()).throw(AssertionError("stale public revision must not submit")),
        remote_loader=lambda: ({marker}, None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"


def test_explicit_revision_candidate_bypasses_recency_floor_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "feedback": "Revise this already-reviewed artifact.",
    })
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    registry = json.loads((run / "citation_registry.json").read_text(encoding="utf-8"))
    for row in registry.values():
        row["source_year"] = 2001
    _write_json(run / "citation_registry.json", registry)
    monkeypatch.setenv("RESEARKA_API_KEY_V3", "secret")

    class Response:
        status = 201

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"id":"revision-submission"}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda _req, timeout: Response())

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-06-22",
        submit=True,
        remote_loader=lambda: (set(), None),
        candidate_run=run,
    )

    assert daily._researka_preflight_status(daily.build_payload(run)) == "recency_ratio_low:0/12<0.50"
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["considered"][0]["status"] == "submitted_to_researka"


def test_remote_publication_dedupe_blocks_exact_content_even_as_revision(tmp_path: Path) -> None:
    # Fasting-bug regression (2026-06-13): an already-published paper
    # re-submitted while carrying a stale revision_request is an exact-content
    # duplicate -> must block. The revision exemption is title-only; identity/
    # content markers in published_seen block regardless of revision.
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "a", "submissionId": "s", "feedback": "stale",
    })
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": True})
    content_markers = daily._metadata_markers(daily.build_payload(run)["metadata"])
    assert content_markers  # identity/content hashes, not the title marker

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (content_markers, None),
    )

    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"
    assert ledger["submitted"] == 0


def test_missing_revision_coverage_gate_is_refreshed_before_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import revision_coverage  # type: ignore[import-not-found]

    run = _run(tmp_path)
    paper = run / "full_paper.md"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace(
            "## Methods\n\n",
            "## Methods\n\n"
            "### Classification Criteria\n\n"
            "- **Outcome class** is assigned from endpoint and claim text.\n"
            "- **Directness** is coded from source design and endpoint match.\n"
            "- **Evidence tier** follows the deterministic taxonomy.\n\n",
        ),
        encoding="utf-8",
    )
    ask = "Define the classification criteria used to assign studies to outcome classes and to code directness."
    _write_json(run / "researka_revision_request.json", {"feedback": ask})
    monkeypatch.setattr(revision_coverage, "unmet_asks", lambda _paper, _asks: [ask])

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=set(),
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"
    gate = json.loads((run / daily.REVISION_COVERAGE_GATE).read_text(encoding="utf-8"))
    assert gate["passed"] is True
    assert gate["refreshed_by"] == "daily_submit"


def test_stale_unmet_revision_gate_refreshes_only_prior_unmet_asks(tmp_path: Path) -> None:
    run = _run(tmp_path)
    ask = (
        "Reclassify or re-label the 'immune and inflammation positive signal' as a "
        "combination-product signal, not a spermidine-monotherapy signal; add a single "
        "sentence in the Findings Map table and Results Summary flagging that the 2/3 "
        "positive sources include one combination-product RCT and one preclinical GWI "
        "mouse model."
    )
    paper = run / "full_paper.md"
    paper.write_text(
        paper.read_text(encoding="utf-8")
        + "\n\n## Results Summary\n\n"
        "The Felix 2024 RCT used a combination product containing spermidine and "
        "hesperidin, so its positive immune/inflammation findings cannot be attributed "
        "to spermidine monotherapy. Trivedi 2026 is a Gulf War Illness mouse model and "
        "is therefore not a human clinical confirmation.\n",
        encoding="utf-8",
    )
    _write_json(run / "researka_revision_request.json", {
        "feedback": f"{ask}; Verify and align author-year prose citations against bundle entries.",
    })
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": False, "unmet_asks": [ask]})

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=set(),
        purpose="revision",
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"
    gate = json.loads((run / daily.REVISION_COVERAGE_GATE).read_text(encoding="utf-8"))
    assert gate["passed"] is True
    assert gate["unmet_asks"] == []
    assert gate["ask_count"] == 1


def test_unmet_refreshed_revision_coverage_still_blocks_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "feedback": "Define the classification criteria used to assign studies to outcome classes and to code directness.",
    })

    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "finalize_run", lambda _path: SimpleNamespace(paper_changed=False))

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=set(),
    )

    assert selected is None
    assert considered[0]["status"] == "revision_coverage_unmet"
    gate = json.loads((run / daily.REVISION_COVERAGE_GATE).read_text(encoding="utf-8"))
    assert gate["passed"] is False


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


def test_selection_repairs_recent_surface_sidecar_before_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path)
    _write_json(run / "full_paper.journal_surface.json", {
        "passed": False,
        "issues": [{"code": "topic_slug_artifact"}],
    })

    def fake_finalize(path: Path) -> object:
        _write_json(path / "full_paper.journal_surface.json", {"passed": True, "issues": []})
        return SimpleNamespace(paper_changed=True)

    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "finalize_run", fake_finalize)

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=set(),
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"


def test_selection_repairs_recent_revision_coverage_sidecar_before_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path)
    ask = (
        "Resolve the disconnect between the '47/48 null-coded' framing and the clearly "
        "directional findings visible in the source bundle excerpts."
    )
    _write_json(run / "researka_revision_request.json", {"feedback": ask})
    _write_json(run / daily.REVISION_COVERAGE_GATE, {"passed": False, "unmet_asks": [ask]})

    def fake_finalize(path: Path) -> object:
        paper = path / "full_paper.md"
        paper.write_text(
            paper.read_text(encoding="utf-8").replace(
                "## Results\n\n",
                "## Results\n\n"
                "Directional coding note: Null or no extracted directional signal means no coded "
                "positive, negative, or mixed effect was extracted for that specific outcome class. "
                "Positive and mixed signals in other outcome classes are separately reported.\n\n",
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(paper_changed=True)

    import agent.journal_finalizer as finalizer
    monkeypatch.setattr(finalizer, "finalize_run", fake_finalize)

    selected, considered = daily.select_candidate(
        tmp_path,
        tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=set(),
    )

    assert selected == run
    assert considered[0]["status"] == "eligible"
    gate = json.loads((run / daily.REVISION_COVERAGE_GATE).read_text(encoding="utf-8"))
    assert gate["passed"] is True


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


def test_publications_url_defaults_to_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARKA_PUBLICATIONS_URL", raising=False)
    monkeypatch.setenv("RESEARKA_URL", "https://api.researka.org")

    assert daily._publications_url() == "https://researka.org/api/publications"


def test_remote_published_fingerprints_ignores_title_only_publication_row(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "publications": [{
            "title": "Research Synthesis: Oral Microbiome Periodontal Aging — full paper",
            "metadata": {"content_hash": "sha256:abc"},
            "body_markdown": "published-looking body",
            "decision": None,
            "publicVisible": None,
            "publishedAt": None,
            "submissionId": None,
        }],
    }

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda _req, timeout: Response())

    markers, error = daily._remote_published_fingerprints("https://api.example/publications")

    assert error is None
    assert markers == set()


def test_remote_published_fingerprints_keeps_accepted_publication_row(monkeypatch: pytest.MonkeyPatch) -> None:
    title = "Research Synthesis: Vitamin D Supplementation Effects — full paper"
    payload = {
        "publications": [{
            "title": title,
            "submission_id": "sub-accepted",
            "topic": "vitamin_d_supplementation",
            "metadata": {"content_hash": "sha256:abc", "submission_identity_key": "sha256:identity"},
            "decision": "accept",
        }],
    }

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda _req, timeout: Response())

    markers, error = daily._remote_published_fingerprints("https://api.example/publications")

    assert error is None
    assert markers == {
        "sha256:abc",
        "sha256:identity",
        daily._submission_marker("sub-accepted"),
        daily._title_marker(title),
        daily._topic_marker("vitamin_d_supplementation"),
    }


def test_http_submitter_sends_runtime_key_headers_and_idempotency(tmp_path: Path, monkeypatch) -> None:
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

    payload = daily.build_payload(_run(tmp_path))
    result = daily._submitter("https://api.example/submissions", "secret", "agent-v3")(payload)

    assert result["ok"] is True
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["headers"]["X-api-key"] == "secret"
    assert seen["headers"]["X-agent-slug"] == "agent-v3"
    assert seen["headers"]["Idempotency-key"] == payload["metadata"]["submission_identity_key"]


def test_select_article_type_routes_zero_tension_to_evidence_map() -> None:
    # Zero-tension corpus = landscape survey -> evidence_map (reviewed for
    # fidelity, not convergence), not the thesis lane that requires >=1 tension.
    assert daily._select_article_type(
        {"n_receipts": 12, "n_non_orthogonal_tensions": 0}
    ) == "evidence_map"
    # Mid-tension corpus keeps the default thesis lane; empty corpus too.
    assert daily._select_article_type(
        {"n_receipts": 12, "n_non_orthogonal_tensions": 3}
    ) == daily.DEFAULT_ARTICLE_TYPE
    assert daily._select_article_type(
        {"n_receipts": 0, "n_non_orthogonal_tensions": 0}
    ) == daily.DEFAULT_ARTICLE_TYPE


def test_run_cycle_capped_passthrough_at_cap_one(tmp_path: Path, monkeypatch) -> None:
    """max_submissions<=1 is an exact passthrough to run_cycle — same ledger
    object, one call, no aggregate fields — so the fresh lane and existing
    single-candidate callers are unaffected."""
    sentinel = {"status": "submitted_to_researka", "submitted": 1, "published": 0,
                "candidate": {"run": "r1"}}
    calls: list[dict] = []

    def _fake(**kw: Any) -> dict:
        calls.append(kw)
        return sentinel

    monkeypatch.setattr(daily, "run_cycle", _fake)
    out = daily.run_cycle_capped(runs_root=tmp_path, date="2026-06-14", submit=True, max_submissions=1)
    assert out is sentinel
    assert len(calls) == 1
    assert "submissions" not in out


def test_run_cycle_capped_submits_up_to_cap(tmp_path: Path, monkeypatch) -> None:
    """Up to max_submissions distinct candidates submit in one cycle; the
    aggregate ledger reports the total and preserves the first candidate."""
    seq = iter([
        {"status": "submitted_to_researka", "submitted": 1, "published": 0, "candidate": {"run": "r1", "topic": "a"}},
        {"status": "submitted_to_researka", "submitted": 1, "published": 0, "candidate": {"run": "r2", "topic": "b"}},
        {"status": "submitted_to_researka", "submitted": 1, "published": 0, "candidate": {"run": "r3", "topic": "c"}},
    ])
    monkeypatch.setattr(daily, "run_cycle", lambda **kw: next(seq))
    out = daily.run_cycle_capped(runs_root=tmp_path, date="2026-06-14", submit=True, max_submissions=3)
    assert out["submitted"] == 3
    assert out["status"] == "submitted_to_researka"
    assert len(out["submissions"]) == 3
    assert out["candidate"]["run"] == "r1"
    assert (tmp_path / daily.LEDGER_DIR / "2026-06-14.json").exists()


def test_run_cycle_capped_stops_on_no_eligible(tmp_path: Path, monkeypatch) -> None:
    """When the ready backlog drains, the cycle stops at the first non-submit
    terminal status and does not burn the remaining cap."""
    seq = iter([
        {"status": "submitted_to_researka", "submitted": 1, "published": 0, "candidate": {"run": "r1"}},
        {"status": "no_eligible_research_paper", "submitted": 0, "published": 0},
    ])
    calls: list[dict] = []

    def _fake(**kw: Any) -> dict:
        calls.append(kw)
        return next(seq)

    monkeypatch.setattr(daily, "run_cycle", _fake)
    out = daily.run_cycle_capped(runs_root=tmp_path, date="2026-06-14", submit=True, max_submissions=3)
    assert out["submitted"] == 1
    assert out["status"] == "submitted_to_researka"
    assert out["candidate"]["run"] == "r1"
    assert len(calls) == 2


def test_run_cycle_capped_continues_past_rejection(tmp_path: Path, monkeypatch) -> None:
    """A duplicate/rejection consumes a candidate but must NOT stall the cycle:
    the loop proceeds to the next ready candidate within the cap and still
    lands the publish. (Before: any non-submit status broke the loop, so a
    single duplicate rejection blocked every other ready paper that window.)"""
    seq = iter([
        {"status": "submission_rejected_by_researka", "submitted": 0, "published": 0, "candidate": {"run": "dup"}},
        {"status": "submitted_to_researka", "submitted": 1, "published": 0, "candidate": {"run": "new", "topic": "b"}},
    ])
    calls: list[dict] = []

    def _fake(**kw: Any) -> dict:
        calls.append(kw)
        return next(seq)

    monkeypatch.setattr(daily, "run_cycle", _fake)
    out = daily.run_cycle_capped(runs_root=tmp_path, date="2026-06-15", submit=True, max_submissions=2)
    assert len(calls) == 2  # the rejection did not stop the loop
    assert out["submitted"] == 1
    assert out["status"] == "submitted_to_researka"
    assert out["candidate"]["run"] == "new"
