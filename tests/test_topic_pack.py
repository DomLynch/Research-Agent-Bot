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


# --- Immutability of the override map (P1 reviewer fix) -------------------


def test_known_role_overrides_is_runtime_immutable() -> None:
    """The frozen dataclass alone does NOT lock the dict. We wrap with
    MappingProxyType so the registry-pinned roles cannot be overwritten at
    runtime by any downstream caller. This is the defensive layer that
    keeps the table sacred even if a misbehaving caller tries to mutate it.
    """
    pack = load_topic_pack(METFORMIN_PATH)
    # All three mutation paths must raise.
    with pytest.raises(TypeError):
        pack.known_role_overrides["NCT99999999"] = OverrideRecord(
            role="published_results", design="rct", tier="A1"
        )  # type: ignore[index]
    with pytest.raises(TypeError):
        del pack.known_role_overrides["NCT04264897"]  # type: ignore[attr-defined]
    # Attempting to overwrite an existing override is also a write.
    with pytest.raises(TypeError):
        pack.known_role_overrides["NCT04264897"] = OverrideRecord(
            role="published_results", design="rct", tier="A1"
        )  # type: ignore[index]


def test_known_role_overrides_still_iterable_and_readable() -> None:
    """Immutability must not break read access — that's the whole point."""
    pack = load_topic_pack(METFORMIN_PATH)
    # Iteration works
    assert "NCT04264897" in pack.known_role_overrides
    # Subscript read works
    rec = pack.known_role_overrides["NCT04264897"]
    assert rec.role == "registered_pending"
    # Length, keys, items all work
    assert len(pack.known_role_overrides) == 4
    assert set(pack.known_role_overrides.keys()) == {
        "NCT02308228", "ISRCTN29932357", "NCT04264897", "NCT01765946",
    }


# --- Slice 6 step 2: [retrieval] schema -----------------------------

RAPAMYCIN_PATH = (
    Path(__file__).parent.parent / "topic_packs" / "rapamycin.toml"
)


def test_retrieval_block_loads_when_present() -> None:
    """Rapamycin pack has a [retrieval] block (added 2026-05-05)."""
    pack = load_topic_pack(RAPAMYCIN_PATH)
    r = pack.retrieval
    assert r is not None
    assert "rapamycin" in r.topic_terms
    assert "sirolimus" in r.topic_terms
    assert "aging" in r.scope_terms
    assert "clinical trial" in r.evidence_types
    assert "transplant rejection" in r.exclude_terms
    assert r.date_from == 2010
    assert r.languages == ("English",)
    assert r.species == ("humans",)


def test_retrieval_background_allow_loads_from_subblock() -> None:
    """[retrieval.background] sub-block populates background_allow."""
    pack = load_topic_pack(RAPAMYCIN_PATH)
    r = pack.retrieval
    assert r is not None
    assert "mTOR mechanism" in r.background_allow
    assert "preclinical lifespan landmark" in r.background_allow


def test_retrieval_is_none_when_block_absent() -> None:
    """Packs without [retrieval] block fall back to legacy
    corpus_search_queries (back-compat)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "legacy.toml"
        p.write_text(textwrap.dedent("""
            topic = "legacy"
            class_ = "test"
            aliases = ["legacy"]
            expected_evidence_slots = []
            special_rules = []
            forbidden_verbs_for_protocol_role = []
            forbidden_verbs_for_results_role_with_protocol_keywords = []
            active_arm_synonyms = ["legacy"]
            corpus_search_queries = ["legacy AND aging"]
            canonical_trials = []
            known_role_overrides = {}
        """))
        pack = load_topic_pack(p)
    assert pack.retrieval is None
    assert pack.corpus_search_queries  # non-empty


def test_retrieval_spec_is_frozen() -> None:
    """RetrievalSpec is frozen — caller can't mutate after load."""
    from agent.topic_pack import RetrievalSpec
    pack = load_topic_pack(RAPAMYCIN_PATH)
    r = pack.retrieval
    assert isinstance(r, RetrievalSpec)
    with pytest.raises((dataclasses.FrozenInstanceError,
                        AttributeError)):
        r.date_from = 1990  # type: ignore[misc]


def test_retrieval_spec_default_empty():
    """A bare RetrievalSpec() with no fields → empty tuples + None
    dates. Defensive: the dataclass should NOT require any fields."""
    from agent.topic_pack import RetrievalSpec
    r = RetrievalSpec()
    assert r.topic_terms == ()
    assert r.scope_terms == ()
    assert r.date_from is None
    assert r.background_allow == ()


def test_inference_spec_loads_from_topic_pack() -> None:
    pack = load_topic_pack(RAPAMYCIN_PATH)
    assert pack.inference.allow is True
    assert "C1_preclinical" in pack.inference.accepted_mechanism_tiers
    assert "Harrison 2009" in pack.inference.canon_references
    assert pack.inference.max_inferences_per_paper == 5


def test_inference_defaults_on_for_standard_topic_packs() -> None:
    for path in sorted(METFORMIN_PATH.parent.glob("*.toml")):
        if path.stem.endswith("_clinical_brief"):
            continue
        assert load_topic_pack(path).inference.allow is True, path.name


def test_clinical_brief_topic_packs_disable_inference() -> None:
    for path in sorted(METFORMIN_PATH.parent.glob("*_clinical_brief.toml")):
        assert load_topic_pack(path).inference.allow is False, path.name
