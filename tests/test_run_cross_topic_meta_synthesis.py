from __future__ import annotations

import json
from pathlib import Path

from scripts.run_cross_topic_meta_synthesis import select_best_runs


def test_select_best_runs_prefers_complete_certified_run_over_larger_legacy(
    tmp_path: Path,
) -> None:
    legacy = _write_run(
        tmp_path,
        "synthesis-metformin-v06-ACTIVE-2026-05-05T00-00-00Z",
        receipts=45,
        track=None,
        audit_total=13,
    )
    certified = _write_run(
        tmp_path,
        "synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08T00-00-00Z",
        receipts=43,
        track="AAA-CLIN",
        audit_total=14,
    )

    assert legacy not in select_best_runs(tmp_path)
    assert certified in select_best_runs(tmp_path)


def test_select_best_runs_excludes_incomplete_audit_even_with_cert_track(
    tmp_path: Path,
) -> None:
    _write_run(
        tmp_path,
        "synthesis-rapamycin-v06-PARTA-2026-05-07T00-00-00Z",
        track="AAA-CLIN",
        audit_total=13,
    )

    assert select_best_runs(tmp_path) == ()


def test_select_best_runs_keeps_scop_only_with_scop_track(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "synthesis-taurine-v06-LANE-2026-05-08T00-00-00Z",
        track="AAA-SCOP",
        audit_total=14,
    )

    selected = select_best_runs(tmp_path)

    assert len(selected) == 1
    assert selected[0].name.startswith("synthesis-taurine-v06-")


def test_select_best_runs_uses_timestamp_not_lexical_suffix(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z",
        track="AAA-CLIN",
        audit_total=14,
    )
    later = _write_run(
        tmp_path,
        "synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z",
        track="AAA-CLIN",
        audit_total=14,
    )

    assert select_best_runs(tmp_path) == (later,)


def test_select_best_runs_excludes_benchmark_variants(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z",
        track="AAA-CLIN",
        audit_total=14,
    )
    brief = _write_run(
        tmp_path,
        "synthesis-rapamycin_clinical_brief-v06-BENCHMARK-2026-05-09T00-00-00Z",
        track="AAA-CLIN",
        audit_total=14,
        receipts=40,
    )

    selected = select_best_runs(tmp_path)

    assert brief not in selected
    assert len(selected) == 1
    assert selected[0].name.startswith("synthesis-rapamycin-v06-")


def _write_run(
    root: Path,
    name: str,
    *,
    receipts: int = 10,
    track: str | None,
    audit_total: int,
) -> Path:
    run = root / name
    run.mkdir()
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 5,
        "maturity_label": "L5 - JOURNAL-READY",
        "journal_ready": True,
        "certification_track": track,
    })
    _write_json(run / "full_paper.audit.json", {
        "n_pass": audit_total,
        "n_total": audit_total,
        "p1_pass": True,
        "score_out_of_10": 10.0,
    })
    _write_json(run / "manifest.json", {
        "n_receipts": receipts,
        "n_high_confidence_claims_total": receipts * 2,
        "n_non_orthogonal_tensions": 1,
        "receipts": [
            {
                "directness": "direct",
                "evidence_tier": "A1",
                "effect_direction": "positive",
                "outcome_class": "cardiometabolic",
            }
        ],
    })
    _write_json(run / "citation_registry.json", {
        "r1": {"source_doi": "10.1/example", "source_pmid": None},
    })
    return run


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
