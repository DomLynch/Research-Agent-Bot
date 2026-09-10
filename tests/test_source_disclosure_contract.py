from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.manuscript_prisma import frozen_retrieval_record
from agent.methods_pack import build_methods_pack, render_methods_md


def _build_pack(*, source_inventory: tuple[tuple[str, str], ...] = ()):
    return build_methods_pack(
        review_type="evidence_brief",
        topic="example_topic",
        corpus_search_queries=("example query",) if source_inventory else (),
        n_retrieved=2,
        n_screened=2,
        n_included=1,
        n_rejected=1,
        outcome_classes=("clinical",),
        source_inventory=source_inventory,
    )


def test_search_yields_survive_freezing_without_becoming_full_text_exclusions(tmp_path: Path) -> None:
    from dataclasses import replace
    record = frozen_retrieval_record({
        "per_wave_stats": [{"wave": "precision", "raw_total": 12, "wave_unique": 10,
            "new_to_corpus": 10, "cumulative": 10, "stats": {
                "status_pubmed": "ok", "raw_pubmed": 8,
                "status_openalex": "timeout", "raw_openalex": 4,
            }}],
        "funnel": {"retrieved": 10, "classified_keep": 6, "classified_drop": 4},
        "entries": [{"keep_for_extraction": False, "reason": "Off topic"},
                    {"keep_for_extraction": True, "reason": "Retained"}],
    })
    frozen = frozen_retrieval_record({"retrieval": record.to_manifest()})
    assert frozen.audit == record.audit
    assert frozen.audit['exclusion_reasons'] == {"Off topic": 1}
    pack = replace(_build_pack(), retrieval_audit=frozen.audit,
                   screening_flow={"n_included": 2})
    text = render_methods_md(pack, submission_id="run-test")
    assert "| precision | 12 | 10 | 10 | 10 |" in text
    assert "| precision | openalex | 4 | timeout |" in text
    assert "| classified drop | 4 |" in text
    assert "4 were excluded at full-text" not in text
    assert "No blinded dual human screening" in text
    assert "retrieval_audit" not in replace(_build_pack(), retrieval_audit={}).required_fields_missing()
    (tmp_path / "methods_pack.json").write_text(json.dumps(pack.to_json()))
    finalizer = importlib.import_module("scripts.journal_finalizer")
    settled, _ = finalizer._phase_a_methods_replace("## Methods\nOld.\n## Results\nFindings.\n", tmp_path)
    assert "| precision | openalex | 4 | timeout |" in settled
    guard = importlib.import_module("scripts.numeric_role_guard")
    counts = guard._manifest_count_values({"retrieval": frozen.to_manifest()})
    assert {"12", "10", "8", "4", "6", "1"} <= counts


def test_missing_search_yield_remains_unknown_and_zero_is_preserved() -> None:
    from agent.manuscript_prisma import render_retrieval_audit
    text = render_retrieval_audit({"waves": [{"wave": "recall", "stats": {
        "status_pubmed": "ok", "raw_pubmed": 0, "status_openalex": "timeout",
    }}]})
    assert "| recall | pubmed | 0 | ok |" in text
    assert "| recall | openalex | Not recorded | timeout |" in text
    assert "| recall | Not recorded | Not recorded | Not recorded | Not recorded |" in text
    assert frozen_retrieval_record({"receipts": [{"source": "PubMed"}]}).audit == {}


def test_frozen_inventory_normalizes_outcomes_and_ignores_receipts() -> None:
    record = frozen_retrieval_record({
        "retrieval": {
            "retrieved_at": "2026-08-13T19:00:00+00:00",
            "sources": [
                {"name": "PubMed", "status": "ok"},
                {"name": "OpenAlex", "status": "rate_limited"},
                {"name": "Crossref", "enabled": True},
                {"name": "Unknown", "status": "mystery"},
            ],
        },
        "receipts": [{"source": "Semantic Scholar"}],
    })

    assert record.sources == (
        ("Crossref", "enabled"),
        ("OpenAlex", "failed"),
        ("PubMed", "succeeded"),
    )
    assert "Semantic Scholar" not in dict(record.sources)
    assert "Unknown" not in dict(record.sources)
    assert record.retrieved_at == "2026-08-13T19:00:00+00:00"
    assert record.to_manifest()["retrieved_at"] == record.retrieved_at


def test_methods_pack_uses_only_frozen_source_inventory() -> None:
    record = frozen_retrieval_record({
        "retrieval": {
            "sources": {
                "PubMed": "succeeded",
                "OpenAlex": "failed",
                "Crossref": "enabled",
            },
        },
    })
    pack = _build_pack(source_inventory=record.sources)
    rendered = render_methods_md(pack, submission_id="run-test")

    assert "3 enabled; 1 succeeded; 1 failed; 1 enabled" in rendered
    assert "PubMed (succeeded)" in rendered
    assert "OpenAlex (failed)" in rendered
    assert "Europe PMC" not in rendered
    assert pack.source_inventory == record.sources
    assert pack.databases_searched == ("PubMed",)


def test_methods_pack_without_inventory_makes_no_database_claim() -> None:
    rendered = render_methods_md(_build_pack(), submission_id="run-test")
    assert "No database inventory was frozen" in rendered
    assert "no query-execution claim is made" in rendered
    assert "No retrieval date was frozen" in rendered
    assert "protocol governed source retrieval" not in rendered


def test_methods_pack_rejects_noncanonical_source_status() -> None:
    with pytest.raises(ValueError, match="enabled/succeeded/failed"):
        _build_pack(source_inventory=(("PubMed", "unknown"),))


def test_revision_run_does_not_fall_back_to_mutable_corpus_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    synthesis = importlib.import_module("scripts.run_v06_synthesis")

    corpus_root = tmp_path / "corpus"
    quant_dir = corpus_root / "quant_claims"
    parsed_dir = corpus_root / "parsed"
    quant_dir.mkdir(parents=True)
    parsed_dir.mkdir()
    (quant_dir / "paper.quant_claims.json").write_text("{}")
    (quant_dir / "stale.quant_claims.json").write_text("{}")
    (parsed_dir / "paper.paper_sections.json").write_text("{}")
    (parsed_dir / "stale.paper_sections.json").write_text("{}")
    (corpus_root / "_extract_report.json").write_text(json.dumps({
        "active_paper_ids": ["paper"],
        "topic": "urolithin", "n_selected_for_fetch": 7, "n_abstract_fallback": 3,
    }))
    (corpus_root / "corpus_manifest.json").write_text(json.dumps({
        "topic": "urolithin",
        "retrieved_at": "2026-08-13T19:00:00+00:00",
        "retrieval": {"queries": []},
        "per_wave_stats": [
            {"stats": {
                "status_pubmed": "ok",
                "query_pubmed": "urolithin[tiab] AND muscle[tiab]",
            }},
            {"stats": {
                "status_pubmed": "server_error",
                "status_openalex": "provider_error",
                "query_pubmed": "urolithin[tiab]",
            }},
        ],
        "expected_evidence_slots": ["muscle function"],
    }))
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    (source_run / "manifest.json").write_text(json.dumps({"receipts": []}))
    monkeypatch.setattr(synthesis, "QUANT_DIR", quant_dir)
    monkeypatch.setattr(synthesis, "PARSED_DIR", parsed_dir)
    monkeypatch.setattr(synthesis, "_TOPIC_PACK", SimpleNamespace(
        corpus_search_queries=("stale query that was not executed",),
    ))

    assert synthesis._load_frozen_retrieval_record(source_run).sources == ()
    record = synthesis._load_frozen_retrieval_record(None)
    assert record.sources == (
        ("openalex", "failed"),
        ("pubmed", "succeeded"),
    )
    assert record.n_parsed == 1
    assert record.n_extracted == 1
    assert record.queries == (
        "urolithin[tiab] AND muscle[tiab]",
        "urolithin[tiab]",
    )
    assert record.retrieved_at == "2026-08-13T19:00:00+00:00"
    assert record.expected_evidence_slots == ("muscle function",)
    assert record.audit["extraction_counts"] == {"selected_for_fetch": 7, "abstract_fallback": 3}


def test_v06_contract_freezes_only_executed_methods_operations() -> None:
    synthesis = importlib.import_module("scripts.run_v06_synthesis")
    contract = synthesis._build_run_mode_contract(
        settings=SimpleNamespace(
            minimax_model="writer",
            judge_model="judge",
            final_layer_reviewer_model="reviewer",
            fallback_model="fallback",
        ),
        topic="example_topic",
        submission_id="run-test",
        n_papers=2,
        n_claims=3,
        source_inventory=(("PubMed", "succeeded"),),
    )
    rendered = synthesis._run_mode.render_methods(contract)

    assert "constructed one evidence receipt per contributing paper" in rendered
    assert "built the citation registry before manuscript drafting" in rendered
    assert "screened for quantitative outcome statements" not in rendered
    assert contract.source_inventory == (("PubMed", "succeeded"),)
