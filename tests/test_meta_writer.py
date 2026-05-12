from __future__ import annotations

from agent.contradiction_detector import TopicContradiction
from agent.convergence_detector import MechanismConvergence
from agent.cross_topic_aggregator import FieldManifest, TopicRunSummary
from agent.meta_writer import render_cross_topic_meta_synthesis


def test_meta_writer_renders_source_run_boundaries() -> None:
    manifest = FieldManifest(
        topics=(
            _topic("rapamycin", "full_aaa_primary"),
            _topic("taurine", "scoped_support", track="AAA-SCOP"),
        ),
        unique_citation_count=2,
        duplicate_citation_keys=(),
    )
    md = render_cross_topic_meta_synthesis(
        manifest,
        (
            MechanismConvergence(
                mechanism="mTOR",
                topics=("rapamycin",),
                run_ids=("synthesis-rapamycin-v06-TEST",),
                outcome_domains=("cardiometabolic",),
            ),
        ),
        (
            TopicContradiction(
                outcome_domain="muscle_function",
                positive_topics=("taurine",),
                negative_topics=("rapamycin",),
                run_ids=("synthesis-rapamycin-v06-TEST", "synthesis-taurine-v06-TEST"),
            ),
        ),
    )

    assert "`synthesis-rapamycin-v06-TEST`" in md
    assert "`synthesis-taurine-v06-TEST` remains scoped support only" in md
    assert "not assert human journal review" in md
    assert "pipeline-qualified" in md
    assert "Maturity" not in md
    assert "Excluded and SCOP topics do not drive primary conclusions" in md


def _topic(topic: str, eligibility: str, *, track: str = "AAA-CLIN") -> TopicRunSummary:
    return TopicRunSummary(
        topic=topic,
        run_id=f"synthesis-{topic}-v06-TEST",
        run_path=f"runs/synthesis-{topic}-v06-TEST",
        eligibility=eligibility,  # type: ignore[arg-type]
        verdict="AAA",
        maturity_level=5,
        maturity_label="L5",
        certification_track=track,
        journal_ready=True,
        n_receipts=10,
        n_high_confidence_claims=20,
        n_tensions=5,
        directness_mix={"direct": 10},
        evidence_tier_mix={"A1": 10},
        effect_direction_mix={"positive": 10},
        outcome_effects={"cardiometabolic": {"positive": 10}},
        outcome_domains=("cardiometabolic",),
        citation_keys=(topic,),
    )
