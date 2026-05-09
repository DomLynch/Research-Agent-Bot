"""Deterministic cross-topic mechanism convergence detector."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from agent.cross_topic_aggregator import FieldManifest, TopicRunSummary

_TOPIC_MECHANISMS = {
    "rapamycin": ("mTOR", "autophagy"),
    "metformin": ("AMPK", "mTOR", "mitochondrial function"),
    "caloric_restriction": ("mTOR", "autophagy", "insulin signaling"),
    "glp1": ("cardiometabolic signaling", "inflammation"),
    "omega3": ("inflammation", "cardiovascular risk"),
    "statins": ("cardiovascular risk", "inflammation"),
    "urolithin_a": ("mitophagy", "mitochondrial function"),
    "creatine": ("mitochondrial function", "muscle function"),
    "aspirin": ("inflammation", "cardiovascular risk"),
}


@dataclass(frozen=True, slots=True)
class MechanismConvergence:
    mechanism: str
    topics: tuple[str, ...]
    run_ids: tuple[str, ...]
    outcome_domains: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_mechanism_convergences(
    manifest: FieldManifest,
    *,
    min_topics: int = 2,
    include_scoped: bool = False,
) -> tuple[MechanismConvergence, ...]:
    grouped: dict[str, list[TopicRunSummary]] = defaultdict(list)
    for topic in manifest.topics:
        if topic.eligibility == "excluded":
            continue
        if topic.eligibility == "scoped_support" and not include_scoped:
            continue
        for mechanism in _mechanisms_for_topic(topic):
            grouped[mechanism].append(topic)
    convergences = []
    for mechanism, topics in grouped.items():
        unique_topics = _unique_by_topic(topics)
        if len(unique_topics) < min_topics:
            continue
        convergences.append(_to_convergence(mechanism, unique_topics))
    return tuple(sorted(convergences, key=lambda c: (-len(c.topics), c.mechanism)))


def _mechanisms_for_topic(topic: TopicRunSummary) -> tuple[str, ...]:
    explicit = _TOPIC_MECHANISMS.get(topic.topic, ())
    outcome_markers = tuple(
        domain.replace("_", " ") for domain in topic.outcome_domains
        if domain in {"cardiometabolic", "inflammation", "muscle_function"}
    )
    return tuple(dict.fromkeys((*explicit, *outcome_markers)))


def _unique_by_topic(topics: list[TopicRunSummary]) -> tuple[TopicRunSummary, ...]:
    out: dict[str, TopicRunSummary] = {}
    for topic in topics:
        out.setdefault(topic.topic, topic)
    return tuple(out.values())


def _to_convergence(
    mechanism: str,
    topics: tuple[TopicRunSummary, ...],
) -> MechanismConvergence:
    return MechanismConvergence(
        mechanism=mechanism,
        topics=tuple(sorted(t.topic for t in topics)),
        run_ids=tuple(sorted(t.run_id for t in topics)),
        outcome_domains=tuple(sorted({d for t in topics for d in t.outcome_domains})),
    )
