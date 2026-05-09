from __future__ import annotations

from agent.convergence_detector import detect_mechanism_convergences
from agent.cross_topic_aggregator import FieldManifest, TopicRunSummary


def test_detects_mtor_convergence_across_primary_topics() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("rapamycin", "full_aaa_primary"),
            _topic("metformin", "full_aaa_primary"),
            _topic("caloric_restriction", "full_aaa_primary"),
        ),
        unique_citation_count=3,
        duplicate_citation_keys=(),
    )

    convergences = detect_mechanism_convergences(manifest)
    by_mechanism = {c.mechanism: c for c in convergences}

    assert by_mechanism["mTOR"].topics == (
        "caloric_restriction",
        "metformin",
        "rapamycin",
    )
    assert "autophagy" in by_mechanism


def test_scoped_topics_are_excluded_by_default() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("urolithin_a", "scoped_support"),
            _topic("creatine", "full_aaa_primary"),
        ),
        unique_citation_count=2,
        duplicate_citation_keys=(),
    )

    assert detect_mechanism_convergences(manifest) == ()
    assert detect_mechanism_convergences(manifest, include_scoped=True)


def test_excluded_topics_never_contribute() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("omega3", "full_aaa_primary"),
            _topic("statins", "excluded"),
            _topic("aspirin", "excluded"),
        ),
        unique_citation_count=3,
        duplicate_citation_keys=(),
    )

    assert detect_mechanism_convergences(manifest) == ()


def _topic(topic: str, eligibility: str) -> TopicRunSummary:
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
        effect_direction_mix={"positive": 10},
        outcome_effects={"cardiometabolic": {"positive": 10}},
        outcome_domains=("cardiometabolic", "muscle_function"),
        citation_keys=(topic,),
    )
