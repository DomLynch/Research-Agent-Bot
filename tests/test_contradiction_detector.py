from __future__ import annotations

from agent.contradiction_detector import detect_cross_topic_contradictions
from agent.cross_topic_aggregator import FieldManifest, TopicRunSummary


def test_detects_opposite_effect_directions_for_same_outcome() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("glp1", "full_aaa_primary", "cardiometabolic", "positive"),
            _topic("aspirin", "full_aaa_primary", "cardiometabolic", "negative"),
        ),
        unique_citation_count=2,
        duplicate_citation_keys=(),
    )

    contradictions = detect_cross_topic_contradictions(manifest)

    assert len(contradictions) == 1
    assert contradictions[0].outcome_domain == "cardiometabolic"
    assert contradictions[0].positive_topics == ("glp1",)
    assert contradictions[0].negative_topics == ("aspirin",)


def test_scoped_and_excluded_topics_do_not_drive_primary_contradictions() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("taurine", "scoped_support", "muscle_function", "positive"),
            _topic("senolytics", "excluded", "muscle_function", "negative"),
            _topic("creatine", "full_aaa_primary", "muscle_function", "positive"),
        ),
        unique_citation_count=3,
        duplicate_citation_keys=(),
    )

    assert detect_cross_topic_contradictions(manifest) == ()


def test_include_scoped_can_surface_scoped_contradiction() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("taurine", "scoped_support", "muscle_function", "positive"),
            _topic("creatine", "full_aaa_primary", "muscle_function", "negative"),
        ),
        unique_citation_count=2,
        duplicate_citation_keys=(),
    )

    contradictions = detect_cross_topic_contradictions(manifest, include_scoped=True)

    assert contradictions[0].positive_topics == ("taurine",)
    assert contradictions[0].negative_topics == ("creatine",)


def _topic(
    topic: str,
    eligibility: str,
    outcome: str,
    effect: str,
) -> TopicRunSummary:
    return TopicRunSummary(
        topic=topic,
        run_id=f"synthesis-{topic}-v06-TEST",
        run_path=f"runs/synthesis-{topic}-v06-TEST",
        eligibility=eligibility,  # type: ignore[arg-type]
        verdict="AAA",
        maturity_level=5,
        maturity_label="L5",
        certification_track="AAA-CLIN",
        journal_ready=True,
        n_receipts=10,
        n_high_confidence_claims=20,
        n_tensions=5,
        directness_mix={"direct": 10},
        evidence_tier_mix={"A1": 10},
        effect_direction_mix={effect: 10},
        outcome_effects={outcome: {effect: 10}},
        outcome_domains=(outcome,),
        citation_keys=(topic,),
    )
