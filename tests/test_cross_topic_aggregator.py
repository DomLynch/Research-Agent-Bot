from __future__ import annotations

import json
from pathlib import Path

from agent.cross_topic_aggregator import build_field_manifest, load_topic_run_summary


def test_load_topic_run_summary_classifies_full_aaa(tmp_path) -> None:
    run = _write_run(tmp_path, "synthesis-metformin-v06-TEST", level=5)

    summary = load_topic_run_summary(run)

    assert summary.topic == "metformin"
    assert summary.eligibility == "full_aaa_primary"
    assert summary.n_receipts == 2
    assert summary.directness_mix == {"direct": 1, "mechanistic": 1}
    assert summary.evidence_tier_mix == {"A1": 1, "C1": 1}
    assert summary.effect_direction_mix == {"positive": 1, "negative": 1}
    assert summary.outcome_effects["cardiometabolic"] == {"positive": 1}
    assert summary.outcome_domains == ("cardiometabolic", "muscle_function")


def test_build_field_manifest_dedupes_citations_across_topics(tmp_path) -> None:
    first = _write_run(tmp_path, "synthesis-rapamycin-v06-TEST", doi="10.1/shared")
    second = _write_run(tmp_path, "synthesis-metformin-v06-TEST", doi="10.1/shared")

    manifest = build_field_manifest((first, second))

    assert len(manifest.topics) == 2
    assert manifest.unique_citation_count == 1
    assert manifest.duplicate_citation_keys == ("10.1/shared",)


def test_missing_required_artifacts_excludes_topic(tmp_path) -> None:
    run = tmp_path / "synthesis-broken-v06-TEST"
    run.mkdir()

    summary = load_topic_run_summary(run)

    assert summary.eligibility == "excluded"
    assert "missing artifacts" in (summary.exclusion_reason or "")


def test_scop_topic_stays_out_of_primary_lane(tmp_path) -> None:
    run = _write_run(
        tmp_path,
        "synthesis-taurine-v06-TEST",
        level=5,
        track="AAA-SCOP",
    )

    summary = load_topic_run_summary(run)

    assert summary.eligibility == "scoped_support"


def _write_run(
    root: Path,
    name: str,
    *,
    level: int = 5,
    track: str = "AAA-CLIN",
    doi: str = "10.1/example",
) -> Path:
    run = root / name
    run.mkdir()
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": level,
        "maturity_label": f"L{level}",
        "journal_ready": level >= 5,
        "certification_track": track,
    })
    _write_json(run / "manifest.json", {
        "n_receipts": 2,
        "n_high_confidence_claims_total": 8,
        "n_non_orthogonal_tensions": 3,
        "receipts": [
            {
                "directness": "direct",
                "evidence_tier": "A1",
                "effect_direction": "positive",
                "outcome_class": "cardiometabolic",
            },
            {
                "directness": "mechanistic",
                "evidence_tier": "C1",
                "effect_direction": "negative",
                "outcome_class": "muscle_function",
            },
        ],
    })
    _write_json(run / "citation_registry.json", {
        "r1": {"source_doi": doi, "source_pmid": None, "source_pmcid": None},
    })
    return run


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
