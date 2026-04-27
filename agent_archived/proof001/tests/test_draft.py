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
from agent.types import Source


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

    async def fake_retrieve(topic, criteria, *, sources, client, limit_per_source=8, domain=""):
        return ([src], {1: "Trial reduced mortality by 22% (p=0.01)."}, {1: {}})

    monkeypatch.setattr(draft_mod, "retrieve", fake_retrieve)

    state = {"calls": 0, "responses": [_approved_draft_json()]}

    async def fake_write_draft(items, topic, domain, criteria, *, settings, client, correction=None, previous_draft=None):
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


# --- judge re-judge after revision (P0 reviewer flagged) ------------------


@pytest.fixture
def stub_with_judge(monkeypatch, stub_retrieve_and_llm):
    """Layer a configurable judge stub on top of stub_retrieve_and_llm.

    `state["judge_responses"]` is a list of (approved, score, summary,
    blocking_issues, revision_notes) tuples consumed in order. Default
    is empty -> judge returns None (skipped path)."""
    state = stub_retrieve_and_llm
    state.setdefault("judge_responses", [])
    state.setdefault("judge_calls", 0)

    async def fake_judge(candidate, items, topic, domain, *, settings, client):
        if not state["judge_responses"]:
            return None
        idx = min(state["judge_calls"], len(state["judge_responses"]) - 1)
        state["judge_calls"] += 1
        approved, score, summary, blocking, notes = state["judge_responses"][idx]
        from agent.judge import JudgeVerdict
        return JudgeVerdict(
            approved=approved, score=score, summary=summary,
            blocking_issues=tuple(blocking), revision_notes=notes,
            model="judge-test", input_tokens=10, output_tokens=10,
            estimated_cost_usd=0.0001,
        )

    monkeypatch.setattr(draft_mod, "judge_draft", fake_judge)
    return state


def test_judge_rejects_then_revision_passes_re_judge(stub_with_judge, tmp_path):
    """Judge rejects -> writer revises -> judge re-runs on the REVISED draft
    and approves -> ship with the new approved verdict (not the stale
    rejection). This is the P0 reviewer flag."""
    revised = {
        "title": "Revised draft",
        "abstract": ["Revised abstract [1]."],
        "sections": {
            "introduction": ["intro [1]."],
            "methods": ["methods."],
            "findings": ["The cited trial reduced mortality 22% [1]."],
            "limitations": ["limits."],
            "conclusion": ["calibrated."],
        },
    }
    stub_with_judge["responses"] = [_approved_draft_json(), revised]
    stub_with_judge["judge_responses"] = [
        # Call 1: reject the first draft, request revision
        (False, 4, "stale issue", ["[1] mis-attributed"], "fix the attribution"),
        # Call 2: approve the revised draft
        (True, 9, "revised draft is clean", [], ""),
    ]
    out = draft_mod.run(
        topic="rapamycin", domain="aging older adults",
        settings=_settings(tmp_path),
    )
    assert out["approved"] is True
    assert out["judge"]["approved"] is True, "judge verdict should reflect REVISED draft, not stale rejection"
    assert out["judge"]["score"] == 9
    assert stub_with_judge["judge_calls"] == 2, "judge must run a second time on revised draft"


def test_judge_rejects_revision_too_dual_rejection_path(stub_with_judge, tmp_path):
    """Judge rejects, writer revises, judge re-runs and STILL rejects:
    ship UNVERIFIED markdown so the user sees what the judge caught."""
    revised = {
        "title": "Still bad",
        "abstract": ["Same problem [1]."],
        "sections": {
            "introduction": ["[1]."], "methods": ["x."], "findings": ["[1]."],
            "limitations": ["x."], "conclusion": ["x."],
        },
    }
    stub_with_judge["responses"] = [_approved_draft_json(), revised]
    stub_with_judge["judge_responses"] = [
        (False, 4, "first reject", ["[1] still wrong"], "fix the attribution"),
        (False, 5, "second reject still bad", ["[1] still wrong post-revision"], ""),
    ]
    out = draft_mod.run(
        topic="rapamycin", domain="aging older adults",
        settings=_settings(tmp_path),
    )
    assert out["approved"] is False, "dual-judge rejection -> approved=False"
    assert out["markdown"], "markdown still ships (UNVERIFIED) so user sees what was flagged"
    assert "UNVERIFIED" in out["markdown"]
    assert "judge_rejected_post_revision" in out["markdown"]
    assert stub_with_judge["judge_calls"] == 2


# --- pre-existing dual-rejection (QA both attempts fail) -------------------


def test_run_ships_unverified_markdown_when_both_attempts_fail(
    stub_retrieve_and_llm, tmp_path,
):
    """Dual-rejection path: rather than shipping nothing, the system writes
    out the failed draft with an UNVERIFIED banner + ## QA Failures block
    so the human reviewer can see what went wrong."""
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
    assert out["qa_failures"]
    # Dual-rejection: markdown IS rendered, with UNVERIFIED banner + QA block
    assert out["markdown"]
    assert "UNVERIFIED" in out["markdown"]
    assert "## QA Failures" in out["markdown"]
