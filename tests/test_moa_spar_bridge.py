from __future__ import annotations

from typing import Any

from agent.moa_spar_bridge import MoaSparBridgeClient


class StubProvider:
    def __init__(self, *, model: str, prompt_version: str, responses: list[dict[str, Any]]) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self._responses = list(responses)

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = self._responses.pop(0)
        return payload, {"choices": [{"message": {"content": "raw"}}], "usage": {}}


class FailingProvider(StubProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        raise RuntimeError("provider unavailable")


def test_moa_spar_bridge_happy_path_preserves_provider_contract():
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[
            {
                "question": "Self draft question",
                "findings": "Self draft findings.",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "estimated_cost_usd": 0.01,
            },
            {
                "question": "Synthesized question",
                "findings": "Synthesized findings.",
                "conclusion": "Synthesized conclusion.",
                "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
                "estimated_cost_usd": 0.02,
            },
        ],
    )
    reviewer = StubProvider(
        model="MiniMax-M2.7-highspeed",
        prompt_version="test/minimax",
        responses=[
            {
                "question": "Reviewer draft question",
                "findings": "Reviewer draft findings.",
                "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                "estimated_cost_usd": 0.03,
            },
            {
                "approved": True,
                "summary": "Looks complete.",
                "issues": [],
                "fix": None,
                "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
                "estimated_cost_usd": 0.04,
            },
        ],
    )
    judge = StubProvider(
        model="deepseek-reasoner",
        prompt_version="test/deepseek",
        responses=[
            {
                "question": "Judge draft question",
                "findings": "Judge draft findings.",
                "usage": {"input_tokens": 11, "output_tokens": 6, "total_tokens": 17},
                "estimated_cost_usd": 0.05,
            },
            {
                "approved": True,
                "summary": "Judge agrees.",
                "issues": [],
                "fix": None,
                "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
                "estimated_cost_usd": 0.06,
            },
        ],
    )

    client = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge)
    result, raw = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Synthesized question"
    assert result["findings"] == "Synthesized findings."
    assert result["conclusion"] == "Synthesized conclusion."
    assert result["model"] == "moa-spar-bridge"
    assert result["prompt_version"] == "research-agent-bot/moa-spar-bridge-v1"
    assert result["usage"] == {"input_tokens": 57, "output_tokens": 27, "total_tokens": 84}
    assert result["estimated_cost_usd"] == 0.21
    assert result["_bridge"]["mode"] == "moa_spar"
    assert result["_bridge"]["moa"]["reference_models"] == [
        "mimo-v2-pro",
        "MiniMax-M2.7-highspeed",
        "deepseek-reasoner",
    ]
    assert result["_bridge"]["spar"]["approved"] is True
    assert result["_bridge"]["spar"]["judge"]["approved"] is True
    assert "moa" in raw
    assert "spar" in raw


def test_moa_spar_bridge_invalid_review_json_triggers_single_fix():
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[
            {"findings": "self"},
            {"findings": "synth"},
            {"findings": "fixed", "conclusion": "fixed conclusion"},
        ],
    )
    reviewer = StubProvider(
        model="MiniMax-M2.7-highspeed",
        prompt_version="test/minimax",
        responses=[
            {"findings": "reviewer"},
            {"summary": "missing approved boolean"},
            {"approved": True, "summary": "fixed", "issues": [], "fix": None},
        ],
    )
    judge = StubProvider(
        model="deepseek-reasoner",
        prompt_version="test/deepseek",
        responses=[
            {"findings": "judge"},
            {"approved": True, "summary": "judge ok", "issues": [], "fix": None},
        ],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(
        system_prompt="system",
        user_prompt="user",
    )

    assert result["findings"] == "fixed"
    assert result["_bridge"]["spar"]["approved"] is True
    assert raw["spar"]["fix_raw"]


def test_moa_spar_bridge_degrades_to_builder_when_reference_model_fails():
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[{"findings": "builder result", "usage": {"input_tokens": 1, "output_tokens": 1}}],
    )
    reviewer = StubProvider(model="MiniMax-M2.7-highspeed", prompt_version="test/minimax", responses=[{"findings": "reviewer"}])
    judge = FailingProvider(model="deepseek-reasoner", prompt_version="test/deepseek", responses=[])

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(
        system_prompt="system",
        user_prompt="user",
    )

    assert result["findings"] == "builder result"
    assert result["_bridge"]["mode"] == "moa_spar_degraded"
    assert result["_bridge"]["spar"]["approved"] is False
    assert raw["degraded"] is True
