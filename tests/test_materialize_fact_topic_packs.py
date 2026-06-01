from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import materialize_fact_topic_packs as materializer  # type: ignore[import-not-found]  # noqa: E402


def test_build_topic_name_uses_fact_topic_subtopic_and_claim_type() -> None:
    row = {"topic": "senescence", "sub_topic": "biomarker", "claim_type": "effect_size"}

    assert materializer.build_topic_name(row) == "senescence biomarker effects"


def test_build_topic_name_uses_topic_and_claim_for_generic_subtopic() -> None:
    row = {"topic": "resveratrol", "sub_topic": "other", "claim_type": "regimen"}

    assert materializer.build_topic_name(row) == "resveratrol regimens"


def test_materialize_rows_is_idempotent_for_unchanged_pack(tmp_path: Path) -> None:
    rows = [{
        "topic": "senescence",
        "sub_topic": "biomarker",
        "claim_type": "effect_size",
        "facts": 12,
        "exact_facts": 12,
        "papers": 4,
    }]

    first = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)
    second = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)

    assert first["created"][0]["slug"] == "senescence_biomarker_effects"
    assert (tmp_path / "senescence_biomarker_effects" / "latest.json").exists()
    assert second["created"] == []
    assert second["skipped"][0]["reason"] == "unchanged"


def test_materialize_rows_skips_low_information_fact_groups(tmp_path: Path) -> None:
    rows = [{
        "topic": "biomarker",
        "sub_topic": "general",
        "claim_type": "effect_size",
        "facts": 12,
        "exact_facts": 12,
        "papers": 4,
    }]

    result = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)

    assert result["created"] == []
    assert result["skipped"][0]["slug"] == "biomarker_effects"
    assert result["skipped"][0]["reason"] == "low_information_topic"


def test_materialize_rows_keeps_specific_generic_subtopic_pack_publishable(tmp_path: Path) -> None:
    rows = [{
        "topic": "metformin",
        "sub_topic": "other",
        "claim_type": "effect_size",
        "facts": 65,
        "exact_facts": 65,
        "papers": 12,
    }]

    result = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)

    assert result["created"][0]["slug"] == "metformin_effects"
    latest = tmp_path / "metformin_effects" / "latest.json"
    assert latest.exists()
    assert result["skipped"] == []
