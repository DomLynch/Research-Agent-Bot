"""Tests for agent.judge — verdict parsing, non-material filter, fallback."""
from __future__ import annotations

import pytest

from agent.judge import _filter_material, _parse, judge_draft
from agent.settings import Settings
from agent.types import EvidenceItem, Source


def _settings(**overrides) -> Settings:
    base = dict(
        mimo_api_key="m", mimo_model="mimo", mimo_base_url="http://m",
        mimo_timeout_sec=5.0,
        openrouter_api_key="o", openrouter_base_url="http://or",
        judge_model="google/gemma-4-31b-it",
        fallback_model="mistral-small-2603",
        bot_enabled=True, daily_cost_cap_usd=10.0,
        dashboard_host="x", dashboard_port=1, runs_dir=".",
    )
    base.update(overrides)
    return Settings(**base)


def _bundle() -> list[EvidenceItem]:
    s = Source(ref=1, title="Trial X", year=2024, url="", source="pubmed")
    return [EvidenceItem(source=s, abstract="abstract.", design="rct",
                         role="published_results", tier="A2", direct=True, strict=True)]


# --- non-material filter ---------------------------------------------------


def test_filter_drops_cosmetic_critique():
    issues = [
        "Phrasing of conclusion is awkward",
        "Could improve readability",
        "Over-claims efficacy from a Tier C source",  # material
    ]
    out = _filter_material(issues)
    assert out == ["Over-claims efficacy from a Tier C source"]


def test_filter_keeps_material_critique():
    issues = ["Hallucinated 47% reduction not in source", "Missed [3] in findings"]
    assert _filter_material(issues) == issues


# --- _parse ----------------------------------------------------------------


def test_parse_approved_strips_revision_notes():
    payload = {"approved": True, "score": 9, "summary": "good", "blocking_issues": [], "revision_notes": "x"}
    v = _parse(payload, "gemma-4", {"input_tokens": 100, "output_tokens": 50})
    assert v.approved is True
    assert v.score == 9
    assert v.revision_notes == ""
    assert v.estimated_cost_usd > 0


def test_parse_filters_out_only_cosmetic_rejection():
    """Judge said reject but every blocking issue was cosmetic -> approved."""
    payload = {
        "approved": False,
        "score": 7,
        "summary": "wording rough",
        "blocking_issues": ["Naming could be cleaner", "Phrasing nitpick"],
        "revision_notes": "Improve readability",
    }
    v = _parse(payload, "gemma-4", {"input_tokens": 100, "output_tokens": 50})
    assert v.approved is True
    assert v.blocking_issues == ()
    assert v.revision_notes == ""


def test_parse_keeps_material_rejection():
    payload = {
        "approved": False,
        "score": 4,
        "summary": "over-claims",
        "blocking_issues": ["Hallucinated 47% effect not in source"],
        "revision_notes": "Replace fabricated numbers with qualitative description",
    }
    v = _parse(payload, "gemma-4", {"input_tokens": 100, "output_tokens": 50})
    assert v.approved is False
    assert "47%" in v.blocking_issues[0]
    assert v.revision_notes


# --- judge_draft graceful skip --------------------------------------------


def test_judge_skipped_when_openrouter_key_missing():
    """If OPENROUTER_API_KEY is empty, judge_draft returns None (graceful)."""
    import asyncio

    s = _settings(openrouter_api_key="")
    result = asyncio.run(judge_draft(
        candidate={"title": "x"},
        items=_bundle(),
        topic="t",
        domain="d",
        settings=s,
    ))
    assert result is None
