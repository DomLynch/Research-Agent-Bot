from __future__ import annotations

from agent.topic_pack_generator import generate_candidate_topic_pack
from agent.topic_pack_store import (
    load_topic_pack_record,
    persist_generated_pack,
)


def test_persist_generated_pack_creates_versioned_record(tmp_path) -> None:
    pack = generate_candidate_topic_pack("vitamin K2 cardiovascular")

    record = persist_generated_pack(pack, tmp_path, candidate_count=72)
    loaded = load_topic_pack_record(tmp_path / pack.slug / "v1.json")

    assert record.version == 1
    assert record.topic_pack_id == loaded.topic_pack_id
    assert record.pack_hash == loaded.pack_hash
    assert record.candidate_count == 72
    assert record.pack_data["topic"] == "vitamin_k2_cardiovascular"
    assert (tmp_path / pack.slug / "latest.json").exists()


def test_persist_generated_pack_preserves_parent_lineage(tmp_path) -> None:
    pack = generate_candidate_topic_pack("magnesium glycinate sleep")
    first = persist_generated_pack(pack, tmp_path, candidate_count=40)

    second = persist_generated_pack(
        pack,
        tmp_path,
        candidate_count=75,
        parent_id=first.topic_pack_id,
    )

    assert second.version == 2
    assert second.parent_id == first.topic_pack_id
    assert second.topic_pack_id != first.topic_pack_id


def test_persist_generated_pack_rejects_invalid_pack(tmp_path) -> None:
    pack = generate_candidate_topic_pack("best javascript UI library 2026")

    try:
        persist_generated_pack(pack, tmp_path, candidate_count=0)
    except ValueError as exc:
        assert "out_of_scope" in str(exc)
    else:  # pragma: no cover - keeps assertion explicit without pytest import
        raise AssertionError("invalid generated pack persisted")
