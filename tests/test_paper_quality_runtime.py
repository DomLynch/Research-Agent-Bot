from __future__ import annotations

import json
from pathlib import Path

from scripts import paper_quality_runtime as pqr


def _receipts() -> list[dict]:
    return [
        {
            "paper_id": "S1",
            "receipt_id": "S1",
            "citation_token": "Study 1",
            "evidence_tier": "A1",
            "directness": "direct",
            "outcome_class": "immune",
            "effect_direction": "positive",
            "n_claims": 3,
        },
        {
            "paper_id": "S2",
            "receipt_id": "S2",
            "citation_token": "Study 2",
            "evidence_tier": "B2",
            "directness": "mechanistic",
            "outcome_class": "immune",
            "effect_direction": "null",
            "n_claims": 2,
        },
        {
            "paper_id": "S3",
            "receipt_id": "S3",
            "citation_token": "Study 3",
            "evidence_tier": "A2",
            "directness": "direct",
            "outcome_class": "cardiometabolic",
            "effect_direction": "mixed",
            "n_claims": 4,
        },
    ]


def test_quality_methods_payloads_cover_receipts_and_outcomes(tmp_path: Path) -> None:
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    (parsed / "S1.paper_sections.json").write_text(json.dumps({
        "sections": {"abstract": "randomized double-blind placebo trial"}
    }))
    artifact = pqr.write_quality_methods(tmp_path, _receipts(), parsed)

    assert artifact["bundle"].rob_coverage == 1.0
    assert artifact["bundle"].grade_coverage == 1.0
    rob = json.loads((tmp_path / "risk_of_bias.json").read_text())
    assert {row["study_id"] for row in rob} == {"Study 1", "Study 2", "Study 3"}
    assert (tmp_path / "quality_methods.md").exists()
    paper_md = pqr.render_quality_section_for_paper(artifact["bundle"])
    assert "rob(-1)" not in paper_md
    assert "Final certainty" in paper_md


def _claim(text: str) -> dict:
    return {
        "claim_type": "confidence_interval",
        "raw_text": text,
        "sentence": text,
    }


def test_meta_analysis_pools_when_three_compatible_rows(tmp_path: Path) -> None:
    qdir = tmp_path / "quant"
    qdir.mkdir()
    for idx, effect in enumerate((1.0, 2.0, 3.0), start=1):
        (qdir / f"S{idx}.quant_claims.json").write_text(json.dumps({
            "paper_id": f"S{idx}",
            "claims": [_claim(f"mean difference = {effect} (95% CI = 0.1 to 4.0)")],
        }))

    receipts = _receipts()
    for receipt in receipts:
        receipt["outcome_class"] = "immune"
    result = pqr.write_meta_analysis(tmp_path, receipts, qdir)

    assert len(result["pools"]) == 1
    assert result["pools"][0]["group"] == "immune:MD"
    assert (tmp_path / result["pools"][0]["plot"]).exists()
    assert "Random-effects pooled effect" in (tmp_path / "meta_analysis_results.md").read_text()


def test_meta_analysis_fails_closed_without_three_studies(tmp_path: Path) -> None:
    qdir = tmp_path / "quant"
    qdir.mkdir()
    (qdir / "S1.quant_claims.json").write_text(json.dumps({
        "paper_id": "S1",
        "claims": [_claim("OR = 0.5, 95% CI = 0.2 to 0.9")],
    }))

    result = pqr.write_meta_analysis(tmp_path, _receipts(), qdir)

    assert result["pools"] == []
    assert "No quantitative pool was run" in (tmp_path / "meta_analysis_results.md").read_text()


def test_template_repairs_remove_blocking_phrase() -> None:
    repaired, log = pqr.apply_template_repairs("In conclusion, the evidence is mixed.")
    assert repaired.startswith("The evidence profile indicates that")
    assert log == [
        {
            "before": "In conclusion,",
            "after": "The evidence profile indicates that",
        },
    ]


def test_tension_directness_normalizes_review_records(tmp_path: Path) -> None:
    class Receipt:
        def __init__(self, rid: str, directness: str) -> None:
            self.receipt_id = rid
            self.evidence_tier = "B1"
            self.directness = directness
            self.p_values = ()

    class Tension:
        receipt_a_id = "A"
        receipt_b_id = "B"
        kind = "disagreement"
        outcome_class = "immune"
        severity = 4

    class Matrix:
        receipts = (Receipt("A", "review"), Receipt("B", "direct"))

        def non_orthogonal(self):
            return (Tension(),)

    payload = pqr.write_tension_plans(tmp_path, Matrix())
    assert payload["plans"][0]["paper_a"] == "A"


def test_final_quality_gates_emit_accepting_artifacts(tmp_path: Path) -> None:
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    artifact = pqr.write_quality_methods(tmp_path, _receipts(), parsed)
    (tmp_path / "field_engagement.json").write_text(json.dumps([
        {"framework_name": "Mannick", "status": "support"},
    ]))
    paper = (
        "## Limitations\n\n"
        "Pending further trials, rapamycin should not be used off-label "
        "for healthspan extension outside clinical-trial settings.\n"
    )
    manifest = {
        "n_receipts": 40,
        "n_non_orthogonal_tensions": 5,
        "thesis": "Receipt-bound thesis.",
        "receipts": _receipts(),
    }
    audit = {"p1_pass": True, "n_pass": 14, "n_total": 14, "checks": [
        {"name": "Q2_numeric_integrity", "detail": "10/10 numerics trace"}
    ]}

    result = pqr.write_final_quality_gates(
        out_dir=tmp_path,
        paper_text=paper,
        manifest=manifest,
        audit=audit,
        journal_surface={"passed": True},
        reviewer_patches={"unresolved_p1_count": 0},
        quality_bundle=artifact["bundle"],
        citation_registry_complete=True,
    )

    assert result["gate"].passed
    assert result["score"].verdict == "accept"
    assert (tmp_path / "pre_submit_gate.json").exists()
    assert (tmp_path / "publication_score.json").exists()
    gate_payload = json.loads((tmp_path / "pre_submit_gate.json").read_text())
    contract = gate_payload["journal_readiness_contract"]
    assert len(contract) == 15
    assert [row["id"] for row in contract] == list(range(1, 16))
    assert all(row["next_action"] for row in contract)
    assert all(
        row["blocks_submission"] is (row["status"] != "pass" and not row.get("advisory", False))
        for row in contract
    )
    by_name = {row["name"]: row for row in contract}
    assert by_name["product_tiers"]["status"] == "pass"
    assert by_name["claim_atoms"]["status"] == "pass"
    assert by_name["target_journal_finalizer"]["status"] == "not_ready"
    # Slice 18: item 13 is accountability-model-aware. The default for
    # this fixture (no manifest.accountability_model) is researka_agent_
    # certified, which surfaces an `accountability` row instead of the
    # legacy `human_signoff` row.
    assert by_name["accountability"]["status"] == "not_ready"
    assert by_name["universal_benchmark_target"]["status"] == "not_ready"
    assert by_name["target_journal_finalizer"]["advisory"]
    assert not by_name["target_journal_finalizer"]["blocks_submission"]
    assert "Select target journal" in by_name["target_journal_finalizer"]["next_action"]
    for name in (
        "domain_pack",
        "journal_grade_retrieval",
        "deterministic_abstract_conclusion",
        "section_repair_loop",
    ):
        assert by_name[name]["advisory"]
        assert not by_name[name]["blocks_submission"]
    assert by_name["accountability"]["blocks_submission"]
    assert "artifact-consistency" in by_name["accountability"]["next_action"]
    assert by_name["universal_benchmark_target"]["advisory"]
    assert not by_name["universal_benchmark_target"]["blocks_submission"]
    assert "frozen benchmark" in by_name["universal_benchmark_target"]["next_action"]
    gate_md = (tmp_path / "pre_submit_gate.md").read_text()
    assert "## Journal Readiness Contract" in gate_md
    assert "| 12 | target_journal_finalizer | not_ready |" in gate_md
    assert "| 13 | accountability | not_ready |" in gate_md
    assert "| 14 | universal_benchmark_target | not_ready |" in gate_md


def test_final_quality_gates_allow_advisory_audit_miss(tmp_path: Path) -> None:
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    artifact = pqr.write_quality_methods(tmp_path, _receipts(), parsed)
    audit = {"p1_pass": True, "n_pass": 13, "n_total": 14, "checks": [
        {"name": "Q2_numeric_integrity", "detail": "10/10 numerics trace"},
        {"name": "Q9_numeric_density", "passed": False, "detail": "density below advisory target"},
    ]}
    result = pqr.write_final_quality_gates(
        out_dir=tmp_path,
        paper_text="## Limitations\n\nPending further trials, rapamycin should not be used off-label for healthspan extension outside clinical-trial settings.",
        manifest={"n_receipts": 40, "n_non_orthogonal_tensions": 5, "thesis": "Receipt-bound thesis.", "receipts": _receipts()},
        audit=audit,
        journal_surface={"passed": True},
        reviewer_patches={"unresolved_p1_count": 0},
        quality_bundle=artifact["bundle"],
        citation_registry_complete=True,
    )
    gate_payload = json.loads((tmp_path / "pre_submit_gate.json").read_text())
    assert result["gate"].passed
    assert gate_payload["inputs"]["audit_gates_passed"] is True


def test_final_quality_gates_block_failed_fresh_runtime(tmp_path: Path) -> None:
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    artifact = pqr.write_quality_methods(tmp_path, _receipts(), parsed)
    (tmp_path / "benchmark_runtime.json").write_text(json.dumps({
        "fresh_run": True,
        "return_code": 1,
        "timed_out": False,
    }))
    result = pqr.write_final_quality_gates(
        out_dir=tmp_path,
        paper_text="## Limitations\n\nPending further trials.",
        manifest={
            "n_receipts": 40,
            "n_non_orthogonal_tensions": 5,
            "thesis": "Receipt-bound thesis.",
            "receipts": _receipts(),
        },
        audit={"p1_pass": True, "score": 10, "max_score": 10},
        journal_surface={"passed": True},
        reviewer_patches={"unresolved_p1_count": 0},
        quality_bundle=artifact["bundle"],
        citation_registry_complete=True,
    )
    payload = json.loads((tmp_path / "pre_submit_gate.json").read_text())

    assert not result["gate"].passed
    assert payload["runtime_integrity_failure"] == "benchmark_runtime_return_code=1"
    assert payload["runtime_integrity"] == {
        "failure_stage": "fresh_run",
        "failure_type": "nonzero_return_code",
        "detail": "benchmark_runtime_return_code=1",
        "recoverable": True,
        "artifact_validity": "partial",
        "blocks_submission": True,
    }
    assert "benchmark_runtime_return_code=1" in payload["result"]["failures"]
    by_name = {row["name"]: row for row in payload["journal_readiness_contract"]}
    assert by_name["product_tiers"]["status"] == "not_ready"
