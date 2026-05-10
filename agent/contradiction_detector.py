"""Deterministic cross-topic contradiction detector."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agent.cross_topic_aggregator import FieldManifest, TopicRunSummary

_CONTRADICTORY = {"positive", "negative"}


@dataclass(frozen=True, slots=True)
class TopicContradiction:
    outcome_domain: str
    positive_topics: tuple[str, ...]
    negative_topics: tuple[str, ...]
    run_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_cross_topic_contradictions(
    manifest: FieldManifest,
    *,
    include_scoped: bool = False,
) -> tuple[TopicContradiction, ...]:
    by_outcome: dict[str, dict[str, list[TopicRunSummary]]] = {}
    for topic in manifest.topics:
        if topic.eligibility == "excluded":
            continue
        if topic.eligibility == "scoped_support" and not include_scoped:
            continue
        for outcome, effects in topic.outcome_effects.items():
            dominant = _dominant_effect(effects)
            if dominant in _CONTRADICTORY:
                by_outcome.setdefault(outcome, {}).setdefault(dominant, []).append(topic)

    contradictions = []
    for outcome, grouped in by_outcome.items():
        positive = _unique_topics(grouped.get("positive", ()))
        negative = _unique_topics(grouped.get("negative", ()))
        if positive and negative:
            run_ids = tuple(sorted(t.run_id for t in (*positive, *negative)))
            contradictions.append(TopicContradiction(
                outcome_domain=outcome,
                positive_topics=tuple(sorted(t.topic for t in positive)),
                negative_topics=tuple(sorted(t.topic for t in negative)),
                run_ids=run_ids,
            ))
    return tuple(sorted(contradictions, key=lambda c: c.outcome_domain))


def _dominant_effect(effects: dict[str, int]) -> str:
    positive = effects.get("positive", 0)
    negative = effects.get("negative", 0)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "mixed"


def _unique_topics(topics: object) -> tuple[TopicRunSummary, ...]:
    if not isinstance(topics, (list, tuple)):
        return tuple()
    out: dict[str, TopicRunSummary] = {}
    for topic in topics:  # type: ignore[attr-defined]
        out.setdefault(topic.topic, topic)
    return tuple(out.values())
