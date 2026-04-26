"""Tests for draft.py — orchestrator wiring with mocked LLM and retrieval.

Covers:
- BOT_ENABLED kill switch returns error early.
- MIMO_API_KEY missing returns error early.
- Happy path: mocked LLM produces a draft that QA approves -> markdown rendered.
- Sad path: first LLM response fails QA -> retry happens -> success.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import draft as draft_mod
from agent.llm import WriterUsage
from agent.settings import Settings
from agent.types import RawHit, Source


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        mimo_api_key="test-key",
        mimo_model="mimo-test",
        mimo_base_url="http://example.test",
        mimo_timeout_sec=5.0,
        openrouter_api_key="",
        openrouter_base_url="http://or.example.test",
        judge_model="google/gemma-4-31b-it",
        fallback_model="mistralai/mistral-small-2603",
        bot_enabled=True,
        daily_cost_cap_usd=10.0,
        dashboard_host="127.0.0.1",
        dashboard_port=8791,
        runs_dir=str(tmp_path / "runs"),
    )
    base.update(overrides)
    return Settings(**base)


def _approved_draft_json() -> dict:
    return {
        "title": "A clean draft",
        "abstract": ["The trial reduced X by 22% [1]."],
        "sections": {
            "introduction": ["Introduction [1]."],
            "methods": ["Methods text."],
            "findings": ["The cited trial reduced mortality 22% [1]."],
            "limitations": ["Some limitations."],
            "conclusion": ["Calibrated takeaway."],
        },
    }


@pytest.fixture
def stub_retrieve_and_llm(monkeypatch):
    """Patch retrieve() and write_draft() into deterministic test doubles."""
    src = Source(ref=1, title="Trial X", year=2024, url="https://example.org/1",
                 source="pubmed", doi="10.1/x", pmid="1")

    async def fake_retrieve(topic, criteria, *, sources, client, limit_per_source=8):
        return ([src], {1: "Trial reduced mortality by 22% (p=0.01)."}, {1: {}})

    monkeypatch.setattr(draft_mod, "retrieve", fake_retrieve)

    state = {"calls": 0, "responses": [_approved_draft_json()]}

    async def fake_write_draft(items, topic, domain, criteria, *, settings, client, correction=None):
        idx = min(state["calls"], len(state["responses"]) - 1)
        state["calls"] += 1
        usage = WriterUsage(input_tokens=100, output_tokens=50,
                            estimated_cost_usd=0.001, model="mimo-test",
                            prompt_version="v1-test")
        return state["responses"][idx], usage

    monkeypatch.setattr(draft_mod, "write_draft", fake_write_draft)
    return state


# --- safety rails ----------------------------------------------------------


def test_run_blocks_when_bot_disabled(tmp_path):
    out = draft_mod.run(
        topic="t", domain="d",
        settings=_settings(tmp_path, bot_enabled=False),
    )
    assert out["error"] == "BOT_ENABLED is false"


def test_run_blocks_without_any_provider_key(tmp_path):
    out = draft_mod.run(
        topic="t", domain="d",
        settings=_settings(tmp_path, mimo_api_key="", openrouter_api_key=""),
    )
    assert "MIMO_API_KEY" in out["error"] or "OPENROUTER" in out["error"]


def test_run_blocks_when_daily_cost_cap_reached(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    today = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime())
    (runs / f"{today}T00-00-00Z-prior.json").write_text(
        json.dumps({"estimated_cost_usd": 99.0})
    )
    out = draft_mod.run(
        topic="t", domain="d",
        settings=_settings(tmp_path, daily_cost_cap_usd=10.0),
    )
    assert "daily cost cap" in out["error"]


# --- happy path ------------------------------------------------------------


def test_run_happy_path_renders_markdown(stub_retrieve_and_llm, tmp_path):
    out = draft_mod.run(
        topic="rapamycin",
        domain="aging older adults",
        criteria="",
        settings=_settings(tmp_path),
    )
    assert out["approved"] is True
    assert out["attempts"] == 1
    assert "# A clean draft" in out["markdown"]
    assert out["estimated_cost_usd"] == pytest.approx(0.001)
    assert Path(out["log_path"]).exists()
    assert Path(out["markdown_file"]).exists()


# --- retry path ------------------------------------------------------------


def test_run_retries_once_when_qa_rejects(stub_retrieve_and_llm, tmp_path):
    bad = {
        "title": "Bad draft",
        "abstract": ["The trial showed mortality fell 47% [1]."],  # 47% not in source
        "sections": {
            "introduction": ["x [1]."],
            "methods": ["x."],
            "findings": ["x [1]."],
            "limitations": ["x."],
            "conclusion": ["x."],
        },
    }
    stub_retrieve_and_llm["responses"] = [bad, _approved_draft_json()]

    out = draft_mod.run(
        topic="rapamycin",
        domain="aging",
        settings=_settings(tmp_path),
    )
    assert out["attempts"] == 2
    assert out["approved"] is True
    assert "# A clean draft" in out["markdown"]


def test_run_returns_unrendered_when_both_attempts_fail(stub_retrieve_and_llm, tmp_path):
    bad = {
        "title": "Bad",
        "abstract": ["Mortality fell 47% [1]."],
        "sections": {
            "introduction": ["[1]."], "methods": ["x."], "findings": ["[1]."],
            "limitations": ["x."], "conclusion": ["x."],
        },
    }
    stub_retrieve_and_llm["responses"] = [bad, bad]

    out = draft_mod.run(
        topic="rapamycin",
        domain="aging",
        settings=_settings(tmp_path),
    )
    assert out["attempts"] == 2
    assert out["approved"] is False
    assert out["markdown"] == ""
    assert out["qa_failures"]
