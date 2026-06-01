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


def test_build_topic_name_does_not_duplicate_plural_claim_axis() -> None:
    row = {"topic": "metabolism", "sub_topic": "threshold", "claim_type": "threshold"}

    assert materializer.build_topic_name(row) == "metabolism threshold"


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


def test_materialize_rows_uses_existing_peer_records_for_specificity(tmp_path: Path) -> None:
    for slug in [
        "longevity_lifespan_effects",
        "longevity_lifespan_thresholds",
        "longevity_mortality_effects",
        "longevity_biomarker_effects",
        "mortality_rates",
        "frailty_rates",
        "inflammation_rates",
        "metabolism_rates",
    ]:
        existing = tmp_path / slug
        existing.mkdir()
        topic = slug.replace("_", " ")
        (existing / "latest.json").write_text(
            '{"candidate_count": 80, "pack_data": {"topic": "%s", '
            '"aliases": ["%s", "longevity"], '
            '"retrieval": {"topic_terms": ["%s", "longevity"]}}}' % (topic, topic, topic),
            encoding="utf-8",
        )
    rows = [{
        "topic": "longevity",
        "sub_topic": "general",
        "claim_type": "rate",
        "facts": 39,
        "exact_facts": 39,
        "papers": 28,
    }]

    result = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)

    assert result["created"] == []
    assert result["skipped"] == [{
        "topic": "longevity rates",
        "slug": "longevity_rates",
        "reason": "low_information_topic",
    }]


def test_fact_field_cross_strategy_uses_fact_json_fields() -> None:
    assert "jsonb_each_text(ft.fact_json::jsonb)" in materializer.FACT_FIELD_CROSS_SQL
    assert "kv.key IN ('sub_topic', 'population', 'intervention'" in materializer.FACT_FIELD_CROSS_SQL
    assert "lower(trim(kv.value)) != lower" in materializer.FACT_FIELD_CROSS_SQL
    assert "'design'" not in materializer.FACT_FIELD_CROSS_SQL
    assert "'comparator'" not in materializer.FACT_FIELD_CROSS_SQL
    assert "claim_kind" not in materializer.FACT_FIELD_CROSS_SQL
    assert "extraction_confidence" not in materializer.FACT_FIELD_CROSS_SQL
    assert "'other'" in materializer.FACT_FIELD_CROSS_SQL


def test_fact_pair_cross_strategy_requires_intervention_population_and_repeated_papers() -> None:
    sql = materializer.FACT_PAIR_CROSS_SQL

    assert "ft.fact_json->>'intervention'" in sql
    assert "ft.fact_json->>'population'" in sql
    assert "count(DISTINCT ft.paper_id) AS papers" in sql
    assert "papers >= %(min_papers)s" in sql
    assert "exact_facts >= %(min_exact_facts)s" in sql
    assert "lower(split_part(sub_topic, ' in ', 1)) != lower(topic)" in sql


def test_materialize_rows_keeps_repeated_intervention_population_pack(tmp_path: Path) -> None:
    rows = [{
        "topic": "fasting",
        "sub_topic": "30% caloric restriction in male c57bl/6j mice",
        "claim_type": "effect_size",
        "facts": 5,
        "exact_facts": 5,
        "papers": 2,
    }]

    result = materializer.materialize_rows(rows, db_dir=tmp_path, persist=True)

    assert result["created"][0]["slug"] == "fasting_30_caloric_restriction_in_male_c57bl_6j_mice_effects"
    assert result["skipped"] == []


def test_fact_intervention_cross_strategy_promotes_repeated_interventions() -> None:
    sql = materializer.FACT_INTERVENTION_CROSS_SQL

    assert "trim(ft.fact_json->>'intervention') AS topic" in sql
    assert "COALESCE(NULLIF(ft.fact_json->>'topic', ''), 'general') AS sub_topic" in sql
    assert "papers >= %(min_papers)s" in sql
    assert "exact_facts >= %(min_exact_facts)s" in sql
    assert "lower(topic) != lower(sub_topic)" in sql
    assert "lower(topic) NOT LIKE 'none%'" in sql
    assert "'placebo'" in sql
