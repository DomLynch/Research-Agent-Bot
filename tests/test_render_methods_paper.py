from __future__ import annotations

import json
from pathlib import Path

from scripts.render_methods_paper import collect_metrics, render_methods_paper


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(base: Path, topic: str, *, cost: float = 0.01) -> Path:
    run = base / f"synthesis-{topic}-v06-TEST"
    run.mkdir()
    _write_json(run / "manifest.json", {
        "topic": topic,
        "n_receipts": 3,
        "n_high_confidence_claims_total": 7,
        "n_non_orthogonal_tensions": 2,
        "n_llm_calls": 4,
        "total_cost_usd": cost,
    })
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 4,
        "journal_ready": False,
        "grok_flagged": 1,
        "grok_unresolved_p1": 0,
        "stage2_p1": 0,
    })
    _write_json(run / "full_paper.journal_surface.json", {
        "passed": True,
        "issues": [],
    })
    _write_json(run / "full_paper.audit.json", {
        "n_pass": 14,
        "n_total": 14,
        "checks": [{
            "name": "Q2_numeric_integrity",
            "detail": "7/7 numerics trace to corpus (100%)",
            "passed": True,
        }],
    })
    _write_json(run / "pre_submit_gate.json", {
        "inputs": {
            "numeric_coverage": 1.0,
            "citation_registry_complete": True,
        },
        "result": {"failures": []},
    })
    _write_json(run / "citation_registry.json", {
        "r1": {"source_doi": "10.1/test"},
    })
    return run


def test_collect_metrics_freezes_requested_topics(tmp_path: Path) -> None:
    _run(tmp_path, "alpha")
    metrics = collect_metrics(tmp_path, ("alpha", "beta"))

    assert metrics["topics"] == ["alpha", "beta"]
    assert metrics["totals"]["topics_measured"] == 1
    assert metrics["totals"]["missing_topics"] == ["beta"]
    assert metrics["rows"][0]["citation_registry_complete"] is True
    assert metrics["rows"][0]["numeric_grounding"] == 1.0


def test_methods_paper_claim_is_bounded(tmp_path: Path) -> None:
    _run(tmp_path, "alpha")
    paper = render_methods_paper(collect_metrics(tmp_path, ("alpha",)))

    assert "auditable structured evidence synthesis" in paper
    assert "automated systematic-review equivalence" in paper
    assert "not automated systematic review" in paper
    assert "| Topic | Receipts | Claims | Citation accuracy | Numeric grounding |" in paper
    assert "{'code':" not in paper


def test_numeric_grounding_falls_back_to_audit_q2(tmp_path: Path) -> None:
    run = _run(tmp_path, "alpha")
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    del gate["inputs"]["numeric_coverage"]
    _write_json(run / "pre_submit_gate.json", gate)
    metrics = collect_metrics(tmp_path, ("alpha",))

    assert metrics["rows"][0]["numeric_grounding"] == 1.0


def test_fresh_incomplete_run_does_not_fallback_to_stale_run(tmp_path: Path) -> None:
    _run(tmp_path, "alpha")
    fresh = tmp_path / "synthesis-alpha-v06-METHODS-FRESH"
    fresh.mkdir()
    _write_json(fresh / "benchmark_runtime.json", {
        "fresh_run": True,
        "runtime_seconds": 12,
        "return_code": 1,
    })
    _write_json(fresh / "citation_registry.json", {
        "r1": {},
        "r2": {},
    })
    metrics = collect_metrics(tmp_path, ("alpha",))
    row = metrics["rows"][0]

    assert row["fresh_run"] is True
    assert row["receipts"] == 2
    assert row["run_id"] == "synthesis-alpha-v06-METHODS-FRESH"
    assert row["contract_failures"][0]["code"] == "fresh_run_incomplete"
