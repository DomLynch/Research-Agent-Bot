from __future__ import annotations

from pathlib import Path

from agent.topic_pack import load_topic_pack


def _write_pack(path: Path, osf_block: str = "") -> Path:
    path.write_text(
        f"""
topic = "testtopic"
class_ = "test class"
aliases = ["TestTopic"]
expected_evidence_slots = ["published_results"]
special_rules = []
forbidden_verbs_for_protocol_role = ["improves"]
forbidden_verbs_for_results_role_with_protocol_keywords = ["will"]
{osf_block}

[[canonical_trials]]
id = "NCT00000001"
name = "TEST"
expected_role = "published_results"
design = "rct"

[known_role_overrides.NCT00000001]
role = "published_results"
design = "rct"
tier = "A1"
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_optional_osf_block_parses(tmp_path: Path) -> None:
    pack = load_topic_pack(_write_pack(
        tmp_path / "pack.toml",
        """
[osf]
node_id = "abc123"
doi = "10.17605/OSF.IO/ABC123"
first_registered_at = "2026-05-01T00:00:00Z"
latest_version_at = "2026-05-08T00:00:00Z"
""".strip(),
    ))
    assert dict(pack.osf or {}) == {
        "node_id": "abc123",
        "doi": "10.17605/OSF.IO/ABC123",
        "first_registered_at": "2026-05-01T00:00:00Z",
        "latest_version_at": "2026-05-08T00:00:00Z",
    }


def test_absent_osf_block_is_safe(tmp_path: Path) -> None:
    pack = load_topic_pack(_write_pack(tmp_path / "pack.toml"))
    assert pack.osf is None
