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
    assert repaired.startswith("Taken together,")
    assert log == [{"before": "In conclusion,", "after": "Taken together,"}]


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
