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


def test_moa_spar_bridge_preserves_json_provider_contract() -> None:
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[
            {"question": "Self draft", "usage": {"input_tokens": 10, "output_tokens": 5}, "estimated_cost_usd": 0.01},
            {"question": "Synthesized", "conclusion": "Done.", "usage": {"input_tokens": 12, "output_tokens": 7}, "estimated_cost_usd": 0.02},
        ],
    )
    reviewer = StubProvider(
        model="MiniMax-M2.7-highspeed",
        prompt_version="test/minimax",
        responses=[
            {"question": "Reviewer draft", "usage": {"input_tokens": 9, "output_tokens": 4}, "estimated_cost_usd": 0.03},
            {"approved": True, "summary": "Looks complete.", "issues": [], "fix": None, "usage": {"input_tokens": 8, "output_tokens": 3}, "estimated_cost_usd": 0.04},
        ],
    )
    judge = StubProvider(
        model="deepseek-reasoner",
        prompt_version="test/deepseek",
        responses=[
            {"question": "Judge draft", "usage": {"input_tokens": 11, "output_tokens": 6}, "estimated_cost_usd": 0.05},
            {"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None, "usage": {"input_tokens": 7, "output_tokens": 2}, "estimated_cost_usd": 0.06},
        ],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Synthesized"
    assert result["conclusion"] == "Done."
    assert result["model"] == "moa-spar-bridge"
    assert result["usage"] == {"input_tokens": 57, "output_tokens": 27, "total_tokens": 84}
    assert result["estimated_cost_usd"] == 0.21
    assert result["_bridge"]["moa"]["reference_models"] == ["mimo-v2-pro", "MiniMax-M2.7-highspeed", "deepseek-reasoner"]
    assert result["_bridge"]["spar"]["approved"] is True
    assert result["_bridge"]["spar"]["judge"]["approved"] is True
    assert "moa" in raw
    assert "spar" in raw


def test_moa_spar_bridge_repairs_invalid_review_json_once() -> None:
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[
            {"question": "Self"},
            {"question": "Candidate"},
            {"question": "Fixed candidate"},
        ],
    )
    reviewer = StubProvider(
        model="MiniMax-M2.7-highspeed",
        prompt_version="test/minimax",
        responses=[
            {"question": "Reviewer"},
            {"summary": "Missing approved boolean"},
            {"approved": True, "summary": "Fixed.", "issues": [], "fix": None},
        ],
    )
    judge = StubProvider(
        model="deepseek-reasoner",
        prompt_version="test/deepseek",
        responses=[
            {"question": "Judge"},
            {"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None},
        ],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Fixed candidate"
    assert result["_bridge"]["spar"]["approved"] is True
    assert "fix_raw" in raw["spar"]


def test_moa_spar_bridge_degrades_to_builder_when_reference_model_fails() -> None:
    builder = StubProvider(
        model="mimo-v2-pro",
        prompt_version="test/mimo",
        responses=[{"question": "Builder fallback", "findings": "usable"}],
    )
    reviewer = StubProvider(model="MiniMax-M2.7-highspeed", prompt_version="test/minimax", responses=[{"question": "Reviewer"}])
    judge = FailingProvider(model="deepseek-reasoner", prompt_version="test/deepseek", responses=[])

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Builder fallback"
    assert result["_bridge"]["mode"] == "moa_spar_degraded"
    assert result["_bridge"]["spar"]["approved"] is False
    assert raw["degraded"] is True
