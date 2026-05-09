from __future__ import annotations

from scripts.synthesize import build_topic_flow, main


FRESH_TOPICS = (
    "vitamin K2 cardiovascular",
    "magnesium glycinate sleep",
    "alpha-lipoic acid neuropathy",
    "lithium orotate mood",
    "glycine sleep",
)


def test_five_fresh_topics_generate_valid_pack_records(tmp_path) -> None:
    for topic in FRESH_TOPICS:
        result = build_topic_flow(
            topic,
            candidate_counts=(20, 80),
            db_dir=tmp_path,
            persist=True,
        )

        assert result["status"] == "pack_ready"
        assert result["topic_pack_version"] == 1
        assert result["validation_errors"] == []
        assert (tmp_path / result["slug"] / "v1.json").exists()


def test_build_topic_flow_generates_pack_without_persisting(tmp_path) -> None:
    result = build_topic_flow(
        "vitamin K2 cardiovascular",
        candidate_counts=(12,),
        db_dir=tmp_path,
    )

    assert result["status"] == "pack_ready"
    assert result["slug"] == "vitamin_k2_cardiovascular"
    assert "randomized controlled trial" in result["topic_terms"]
    assert not list(tmp_path.iterdir())


def test_build_topic_flow_persists_versioned_pack(tmp_path) -> None:
    result = build_topic_flow(
        "glycine sleep",
        candidate_counts=(80,),
        db_dir=tmp_path,
        persist=True,
    )

    assert result["status"] == "pack_ready"
    assert result["topic_pack_version"] == 1
    assert (tmp_path / "glycine_sleep" / "v1.json").exists()


def test_build_topic_flow_rejects_out_of_scope_without_persisting(tmp_path) -> None:
    result = build_topic_flow(
        "crypto trading bot",
        db_dir=tmp_path,
        persist=True,
    )

    assert result["status"] == "rejected"
    assert result["tier"] == "out_of_scope"
    assert not list(tmp_path.iterdir())


def test_cli_prints_json(capsys, tmp_path) -> None:
    code = main([
        "--topic", "alpha lipoic acid neuropathy",
        "--candidate-count", "30",
        "--db-dir", str(tmp_path),
    ])

    assert code == 0
    assert '"slug": "alpha_lipoic_acid_neuropathy"' in capsys.readouterr().out
