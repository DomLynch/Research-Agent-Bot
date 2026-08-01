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


def test_frozen_inventory_normalizes_outcomes_and_ignores_receipts() -> None:
    record = frozen_retrieval_record({
        "retrieval": {
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
    quant_dir.mkdir(parents=True)
    (corpus_root / "corpus_manifest.json").write_text(json.dumps({
        "retrieval": {"sources": {"PubMed": "succeeded"}},
    }))
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    (source_run / "manifest.json").write_text(json.dumps({"receipts": []}))
    monkeypatch.setattr(synthesis, "QUANT_DIR", quant_dir)

    assert synthesis._load_frozen_retrieval_record(source_run).sources == ()
    assert synthesis._load_frozen_retrieval_record(None).sources == (
        ("PubMed", "succeeded"),
    )


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
