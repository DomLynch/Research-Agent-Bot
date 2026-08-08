from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.topic_pack import load_topic_pack
from agent.topic_pack_generator import (
    RetrievalCounts,
    classify_topic,
    classify_topic_tier,
    generate_candidate_topic_pack,
    precursor_terms,
    run_adaptive_expansion,
    suggest_adaptive_expansion,
    validate_candidate_pack,
)


def test_generates_mainstream_biomedical_candidate() -> None:
    pack = generate_candidate_topic_pack(
        "metformin",
        seed_terms=("biguanide", "type 2 diabetes"),
    )
    data = pack.to_topic_pack_dict()

    assert pack.status == "proceed"
    assert pack.domain == "biomedical"
    assert pack.tier == "mainstream"
    assert pack.validation_errors == ()
    assert data["topic"] == "metformin"
    assert data["class_"] == "generated_biomedical"
    assert "metformin" in pack.topic_terms
    assert "biguanide" in pack.aliases
    retrieval = data["retrieval"]
    assert isinstance(retrieval, dict) and retrieval["species"] == []


def test_generated_queries_anchor_every_context_term_to_the_fact_entity() -> None:
    pack = generate_candidate_topic_pack(
        "metformin metabolism effects",
        seed_terms=("metformin", "metabolism"),
        query_anchor="metformin",
    )

    assert all("metformin" in query.lower() for query in pack.corpus_search_queries)
    assert "metabolism randomized controlled trial" not in pack.corpus_search_queries


def test_short_anchor_does_not_match_inside_longer_context_term() -> None:
    pack = generate_candidate_topic_pack(
        "RA rapamycin effects", seed_terms=("RA", "rapamycin"), query_anchor="RA",
    )

    assert "rapamycin" not in pack.corpus_search_queries
    assert all("RA" in query.split() for query in pack.corpus_search_queries)


def test_precursor_expansion_for_urolithin_a() -> None:
    pack = generate_candidate_topic_pack("urolithin A")

    assert pack.tier == "emerging"
    assert "ellagitannin" in pack.topic_terms
    assert "ellagic acid" in pack.topic_terms
    assert "punicalagin" in pack.topic_terms
    assert precursor_terms("urolithin A")[:3] == (
        "ellagitannin",
        "ellagic acid",
        "punicalagin",
    )
    assert len(pack.corpus_search_queries) <= 10


def test_pseudo_topic_stops_and_cannot_be_forced_to_proceed() -> None:
    pack = generate_candidate_topic_pack("homeopathy longevity detox")

    assert pack.domain == "biomedical"
    assert pack.tier == "pseudo"
    assert pack.status == "stop"
    assert pack.candidate_cap == 0
    unsafe = replace(pack, status="proceed")

    assert "pseudo tier cannot proceed" in validate_candidate_pack(unsafe)


def test_out_of_scope_topic_stops_before_retrieval() -> None:
    pack = generate_candidate_topic_pack("best javascript UI library 2026")
    classification = classify_topic("best javascript UI library 2026")
    unsafe = replace(pack, status="proceed")

    assert pack.domain == "out_of_scope"
    assert pack.tier == "out_of_scope"
    assert pack.status == "stop"
    assert classification.accept_decision == "stop"
    assert "out_of_scope tier cannot proceed" in validate_candidate_pack(unsafe)
    assert "out_of_scope domain cannot proceed" in validate_candidate_pack(unsafe)


def test_contested_topic_proceeds_with_low_candidate_cap() -> None:
    pack = generate_candidate_topic_pack("young blood plasma exchange aging")
    plan = suggest_adaptive_expansion(pack, RetrievalCounts(unique_candidates=150))

    assert pack.tier == "contested"
    assert pack.status == "proceed"
    assert pack.candidate_cap == 150
    assert plan.status == "stop"
    assert plan.reason == "candidate cap reached"


def test_adaptive_expansion_uses_counts_without_network() -> None:
    pack = generate_candidate_topic_pack("taurine aging")
    thin = suggest_adaptive_expansion(pack, RetrievalCounts(unique_candidates=12))
    enough = suggest_adaptive_expansion(pack, RetrievalCounts(unique_candidates=80))

    assert thin.status == "expand"
    assert "randomized controlled trial" in thin.additional_terms
    assert "safety" in thin.additional_terms
    assert enough.status == "enough"
    assert enough.additional_terms == ()


def test_adaptive_expansion_loop_updates_pack_once_without_network() -> None:
    pack = generate_candidate_topic_pack("magnesium sleep")
    result = run_adaptive_expansion(
        pack,
        (
            RetrievalCounts(unique_candidates=12),
            RetrievalCounts(unique_candidates=12),
        ),
    )

    assert result.rounds_applied == 1
    assert result.status == "stop"
    assert result.reason == "no new expansion terms"
    assert "randomized controlled trial" in result.pack.topic_terms
    assert result.pack.validation_errors == ()
    assert result.pack is not pack


def test_generated_pack_is_compatible_with_biomedical_default() -> None:
    default = load_topic_pack(
        Path("topic_packs") / "_biomedical_default.toml"
    )
    pack = generate_candidate_topic_pack("vitamin D frailty")
    data = pack.to_topic_pack_dict()
    slots = data["expected_evidence_slots"]
    retrieval = data["retrieval"]

    assert isinstance(slots, list)
    assert set(default.expected_evidence_slots).issubset(
        set(slots)
    )
    assert default.retrieval is not None and isinstance(retrieval, dict)
    background = retrieval["background"]
    assert isinstance(background, dict) and isinstance(background["allow"], list)
    assert set(default.retrieval.background_allow).issubset(
        set(background["allow"])
    )
    assert data["known_role_overrides"] == {}
    assert data["canonical_trials"] == []


def test_species_hard_filter_is_validation_error() -> None:
    pack = generate_candidate_topic_pack("spermidine")
    hard_filtered = replace(pack, species=("humans",))

    assert "generated biomedical packs must not hard-filter species" in (
        validate_candidate_pack(hard_filtered)
    )


def test_empty_topic_rejected() -> None:
    with pytest.raises(ValueError, match="topic_name is required"):
        generate_candidate_topic_pack("   ")


def test_tier_labels_are_deterministic() -> None:
    assert classify_topic_tier("omega-3 cardiovascular aging") == "mainstream"
    assert classify_topic_tier("urolithin A mitophagy") == "emerging"
    assert classify_topic_tier("young blood protocol") == "contested"
    assert classify_topic_tier("crystal healing longevity") == "pseudo"
    assert classify_topic_tier("crypto trading bot") == "out_of_scope"
