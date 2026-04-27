"""Tests for agent/topic_pack.py — TOML loader + lookups.

Discriminating tests focused on the seams (v4 Rule 57):
- Loader rejects malformed packs with clear errors (not silent misclassification)
- Alias whitelist is case-insensitive and whitespace-stripped — defends planted
  failure case 4 (alias drift, e.g. "Glufomin")
- Role override pins TAME to registered_pending — defends planted failure
  case 1 (protocol-as-results: "TAME demonstrated CV benefit")
- Verb-ban catches the case-1 verbs case-insensitively
- Frozen-ness — no runtime mutation
"""
from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path

import pytest

from agent.topic_pack import (
    OverrideRecord,
    TopicPack,
    TopicPackError,
    load_topic_pack,
)

METFORMIN_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


# --- Loader smoke ---------------------------------------------------------


def test_metformin_pack_loads() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert isinstance(pack, TopicPack)
    assert pack.topic == "metformin"
    assert pack.drug_class == "biguanide"


def test_metformin_pack_is_frozen() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pack.topic = "rapamycin"  # type: ignore[misc]


def test_loader_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TopicPackError, match="not found"):
        load_topic_pack(tmp_path / "nonexistent.toml")


def test_loader_raises_on_missing_top_level_keys(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text('topic = "bad"\nclass_ = "x"\n')
    with pytest.raises(TopicPackError, match="missing top-level keys"):
        load_topic_pack(p)


def test_loader_raises_on_empty_aliases(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text(textwrap.dedent('''
        topic = "x"
        class_ = "x"
        aliases = []
        expected_evidence_slots = []
        special_rules = []
        forbidden_verbs_for_protocol_role = []
        forbidden_verbs_for_results_role_with_protocol_keywords = []
        canonical_trials = []
        known_role_overrides = {}
    '''))
    with pytest.raises(TopicPackError, match="aliases must be non-empty"):
        load_topic_pack(p)


def test_loader_raises_on_invalid_role_override(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text(textwrap.dedent('''
        topic = "x"
        class_ = "x"
        aliases = ["x"]
        expected_evidence_slots = []
        special_rules = []
        forbidden_verbs_for_protocol_role = []
        forbidden_verbs_for_results_role_with_protocol_keywords = []
        canonical_trials = []
        [known_role_overrides.NCT12345]
        role = "totally_made_up_role"
        design = "rct"
        tier = "A1"
    '''))
    with pytest.raises(TopicPackError, match="invalid role"):
        load_topic_pack(p)


# --- Alias whitelist — defends planted-failure case 4 ---------------------


def test_alias_whitelist_accepts_canonical_metformin() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.has_alias("metformin")
    assert pack.has_alias("biguanide")
    assert pack.has_alias("Glucophage")


def test_alias_whitelist_is_case_insensitive() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.has_alias("METFORMIN")
    assert pack.has_alias("MetForMin")


def test_alias_whitelist_strips_whitespace() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.has_alias("  metformin  ")


def test_planted_failure_4_alias_drift_caught() -> None:
    """Planted failure 4: 'Glufomin' (made-up) must be rejected by whitelist."""
    pack = load_topic_pack(METFORMIN_PATH)
    assert not pack.has_alias("Glufomin")
    assert not pack.has_alias("metformine")  # close-but-not-canonical
    assert not pack.has_alias("Glucophase")  # near-typo


# --- Role override — defends planted-failure case 1 -----------------------


def test_planted_failure_1_tame_pinned_to_registered_pending() -> None:
    """Planted failure 1 root cause: TAME (NCT04264897) is a protocol, not results.

    Any prose claiming 'TAME demonstrated cardiovascular benefit' must be
    rejected because the registry override pins role=registered_pending.
    """
    pack = load_topic_pack(METFORMIN_PATH)
    tame = pack.lookup_role_override("NCT04264897")
    assert tame is not None
    assert tame.role == "registered_pending"
    assert tame.design == "rct"
    assert tame.tier == "A1"


def test_canonical_trials_pinned_to_published_results() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    for nct in ("NCT02308228", "ISRCTN29932357", "NCT01765946"):
        rec = pack.lookup_role_override(nct)
        assert rec is not None and rec.role == "published_results", \
            f"{nct} should be pinned to published_results"


def test_unknown_nct_returns_none() -> None:
    """Falls through to deterministic abstract classifier (Day 2)."""
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.lookup_role_override("NCT99999999") is None
    assert pack.lookup_role_override(None) is None
    assert pack.lookup_role_override("") is None


def test_override_lookup_strips_whitespace() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.lookup_role_override("  NCT04264897  ") is not None


# --- Verb-ban — fed to validators.py (Day 2) ------------------------------


def test_planted_failure_1_verb_ban_catches_demonstrated() -> None:
    """The verb 'demonstrated' applied to a protocol-role source must be banned."""
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.is_protocol_verb_forbidden("demonstrated")


def test_protocol_verb_ban_is_case_insensitive() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    for verb in ("found", "FOUND", "Showed", "improved"):
        assert pack.is_protocol_verb_forbidden(verb)


def test_protocol_verb_ban_does_not_block_neutral_verbs() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    for verb in ("investigated", "studied", "measured", "compared"):
        assert not pack.is_protocol_verb_forbidden(verb)


def test_results_role_protocol_keyword_ban() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    assert pack.is_results_protocol_keyword("planned")
    assert pack.is_results_protocol_keyword("PENDING")
    assert not pack.is_results_protocol_keyword("completed")


# --- Canonical trials surface check ---------------------------------------


def test_canonical_trials_present() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    names = {t.name for t in pack.canonical_trials}
    assert names == {"MASTERS", "MET-PREVENT", "TAME", "MILES"}


def test_override_record_is_typed() -> None:
    pack = load_topic_pack(METFORMIN_PATH)
    rec = pack.lookup_role_override("NCT04264897")
    assert isinstance(rec, OverrideRecord)
