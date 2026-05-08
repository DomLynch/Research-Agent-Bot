"""BRIEFS-V1 Phase 2 topic matcher tests."""
from __future__ import annotations

from pathlib import Path

from agent.briefs import match_topics, parse_question

REPO = Path(__file__).resolve().parent.parent
TOPIC_PACKS = REPO / "topic_packs"


def _topics(question: str) -> tuple[str, ...]:
    return tuple(p.topic for p in match_topics(parse_question(question), TOPIC_PACKS))


def test_match_metformin_from_question() -> None:
    assert _topics("metformin for mortality over 65") == ("metformin",)


def test_match_glp1_plural_alias() -> None:
    assert _topics("GLP-1 receptor agonists for weight loss") == ("glp1",)


def test_match_omega3_aliases() -> None:
    assert _topics("fish oil for cognition in older adults") == ("omega3",)


def test_match_multiple_interventions() -> None:
    topics = _topics("metformin and creatine for frailty")
    assert "metformin" in topics
    assert "creatine" in topics


def test_no_intervention_returns_no_topics() -> None:
    assert _topics("what evidence exists for mortality in older adults") == ()
