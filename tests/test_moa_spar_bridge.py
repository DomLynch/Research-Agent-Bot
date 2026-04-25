from __future__ import annotations

import json
from typing import Any

import httpx

from agent.moa_spar_bridge import OpenAICompatJsonClient
from agent.moa_spar_bridge import MoaSparBridgeClient


class StubProvider:
    def __init__(self, *, model: str, prompt_version: str, responses: list[dict[str, Any]]) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self._responses = list(responses)

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = self._responses.pop(0)
        return payload, {"choices": [{"message": {"content": "raw"}}], "usage": {}}

    @property
    def remaining(self) -> int:
        return len(self._responses)


class FailingProvider(StubProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        raise RuntimeError("provider unavailable")


class PromptCapturingProvider(StubProvider):
    def __init__(self, *, model: str, prompt_version: str, responses: list[dict[str, Any]]) -> None:
        super().__init__(model=model, prompt_version=prompt_version, responses=responses)
        self.prompts: list[str] = []

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.prompts.append(user_prompt)
        return super().complete_json(system_prompt=system_prompt, user_prompt=user_prompt)


def test_moa_spar_bridge_preserves_json_provider_contract() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[
            {"question": "Self draft", "usage": {"input_tokens": 10, "output_tokens": 5}, "estimated_cost_usd": 0.01},
            {"question": "Synthesized", "conclusion": "Done.", "usage": {"input_tokens": 12, "output_tokens": 7}, "estimated_cost_usd": 0.02},
        ],
    )
    reviewer = StubProvider(
        model="stepfun/step-3.5-flash",
        prompt_version="test/stepfun",
        responses=[
            {"question": "Reviewer draft", "usage": {"input_tokens": 9, "output_tokens": 4}, "estimated_cost_usd": 0.03},
            {"approved": True, "summary": "Looks complete.", "issues": [], "fix": None, "usage": {"input_tokens": 8, "output_tokens": 3}, "estimated_cost_usd": 0.04},
        ],
    )
    judge = StubProvider(
        model="google/gemma-4-31b-it",
        prompt_version="test/gemma4-31b",
        responses=[
            {"question": "Judge draft", "usage": {"input_tokens": 11, "output_tokens": 6}, "estimated_cost_usd": 0.05},
            {"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None, "usage": {"input_tokens": 7, "output_tokens": 2}, "estimated_cost_usd": 0.06},
        ],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge, reference_drafts=True).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Synthesized"
    assert result["conclusion"] == "Done."
    assert result["model"] == "moa-spar-bridge"
    assert result["usage"] == {"input_tokens": 57, "output_tokens": 27, "total_tokens": 84}
    assert result["estimated_cost_usd"] == 0.21
    assert result["_bridge"]["moa"]["reference_models"] == [
        "mimo-v2.5-pro",
        "stepfun/step-3.5-flash",
        "google/gemma-4-31b-it",
    ]
    assert result["_bridge"]["spar"]["approved"] is True
    assert result["_bridge"]["spar"]["judge"]["approved"] is True
    assert result["_bridge"]["spar"]["review_models"] == [
        "stepfun/step-3.5-flash",
        "google/gemma-4-31b-it",
    ]
    assert "moa" in raw
    assert "spar" in raw


def test_moa_spar_bridge_defaults_to_fast_review_only_path() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[{"question": "Builder draft", "usage": {"input_tokens": 10, "output_tokens": 5}, "estimated_cost_usd": 0.01}],
    )
    reviewer = StubProvider(
        model="stepfun/step-3.5-flash",
        prompt_version="test/stepfun",
        responses=[{"approved": True, "summary": "Looks complete.", "issues": [], "fix": None, "usage": {"input_tokens": 8, "output_tokens": 3}, "estimated_cost_usd": 0.04}],
    )
    judge = StubProvider(
        model="google/gemma-4-31b-it",
        prompt_version="test/gemma4-31b",
        responses=[{"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None, "usage": {"input_tokens": 7, "output_tokens": 2}, "estimated_cost_usd": 0.06}],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Builder draft"
    assert result["_bridge"]["moa"]["reference_models"] == ["mimo-v2.5-pro"]
    assert result["_bridge"]["spar"]["approved"] is True
    assert raw["moa"]["raw"]["synth"] == {"skipped": "reference_drafts_disabled"}
    assert reviewer.remaining == 0
    assert judge.remaining == 0
    assert "timings_sec" in raw


def test_moa_spar_bridge_reviews_raw_draft_schema_not_final_artifact_schema() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[{"question": "Draft question", "findings": "Draft findings", "conclusion": "Draft conclusion"}],
    )
    reviewer = PromptCapturingProvider(
        model="stepfun/step-3.5-flash",
        prompt_version="test/stepfun",
        responses=[{"approved": True, "summary": "Raw draft schema is complete.", "issues": [], "fix": None}],
    )
    judge = StubProvider(
        model="google/gemma-4-31b-it",
        prompt_version="test/gemma4-31b",
        responses=[{"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None}],
    )

    result, _ = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge).complete_json(
        system_prompt="Return exactly these JSON keys: question, findings, conclusion.",
        user_prompt="Topic: rapamycin",
    )

    assert result["question"] == "Draft question"
    assert "task_system_excerpt" in reviewer.prompts[0]
    assert "question" in reviewer.prompts[0]
    assert "source_bundle" not in reviewer.prompts[0]


def test_moa_spar_bridge_repairs_invalid_review_json_once() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[
            {"question": "Self"},
            {"question": "Candidate"},
            {"question": "Fixed candidate"},
        ],
    )
    reviewer = StubProvider(
        model="stepfun/step-3.5-flash",
        prompt_version="test/stepfun",
        responses=[
            {"question": "Reviewer"},
            {"summary": "Missing approved boolean"},
            {"approved": True, "summary": "Fixed.", "issues": [], "fix": None},
        ],
    )
    judge = StubProvider(
        model="google/gemma-4-31b-it",
        prompt_version="test/gemma4-31b",
        responses=[
            {"question": "Judge"},
            {"approved": True, "summary": "Judge agrees.", "issues": [], "fix": None},
        ],
    )

    result, raw = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge, reference_drafts=True).complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Fixed candidate"
    assert result["_bridge"]["spar"]["approved"] is True
    assert "fix_raw" in raw["spar"]


def test_moa_spar_bridge_accepts_null_review_issues() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[{"question": "Self"}, {"question": "Candidate"}],
    )
    reviewer = StubProvider(
        model="stepfun/step-3.5-flash",
        prompt_version="test/stepfun",
        responses=[{"question": "Reviewer"}, {"approved": True, "summary": "No material issues.", "issues": None, "fix": None}],
    )
    judge = StubProvider(
        model="google/gemma-4-31b-it",
        prompt_version="test/gemma4-31b",
        responses=[{"question": "Judge"}, {"approved": True, "summary": "Judge agrees.", "issues": None, "fix": None}],
    )

    result, _ = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge, reference_drafts=True).complete_json(system_prompt="system", user_prompt="user")

    assert result["_bridge"]["spar"]["issues"] == []
    assert result["_bridge"]["spar"]["judge"]["issues"] == []


def test_moa_spar_bridge_degrades_to_builder_when_reference_model_fails() -> None:
    builder = StubProvider(
        model="mimo-v2.5-pro",
        prompt_version="test/mimo",
        responses=[
            {"question": "Builder fallback", "findings": "usable"},
            {"question": "Fast degraded fallback", "findings": "usable"},
        ],
    )
    reviewer = StubProvider(model="stepfun/step-3.5-flash", prompt_version="test/stepfun", responses=[{"question": "Reviewer"}])
    judge = FailingProvider(model="google/gemma-4-31b-it", prompt_version="test/gemma4-31b", responses=[])
    client = MoaSparBridgeClient(builder=builder, reviewer=reviewer, judge=judge)

    result, raw = client.complete_json(system_prompt="system", user_prompt="user")
    second, second_raw = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "Builder fallback"
    assert result["_bridge"]["mode"] == "moa_spar_degraded"
    assert result["_bridge"]["spar"]["approved"] is False
    assert raw["degraded"] is True
    assert second["question"] == "Fast degraded fallback"
    assert second_raw["degraded"] is True
    assert reviewer.remaining == 0


def test_moa_spar_bridge_from_env_defaults_to_openrouter_models(monkeypatch) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "test-mimo")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    monkeypatch.delenv("REVIEWER_MODEL", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("REVIEWER_BASE_URL", raising=False)
    monkeypatch.delenv("JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("REVIEWER_API_KEY_ENV", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY_ENV", raising=False)

    client = MoaSparBridgeClient.from_env()

    assert client.builder.model == "mimo-v2.5-pro"
    assert client.reviewer.model == "stepfun/step-3.5-flash"
    assert client.judge.model == "google/gemma-4-31b-it"
    assert client.reviewer.base_url == "https://openrouter.ai/api/v1"
    assert client.judge.base_url == "https://openrouter.ai/api/v1"
    assert client.reviewer.api_key_env == "OPENROUTER_API_KEY"
    assert client.judge.api_key_env == "OPENROUTER_API_KEY"
    assert client.reference_drafts is False
    assert client.reviewer.timeout_sec == 65
    assert client.judge.timeout_sec == 65
    assert client.reviewer.retries == 1
    assert client.judge.retries == 1


def test_moa_spar_bridge_from_env_honors_openrouter_timeout_and_retries(monkeypatch) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "test-mimo")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SEC", "12")
    monkeypatch.setenv("OPENROUTER_RETRIES", "2")

    client = MoaSparBridgeClient.from_env()

    assert client.reviewer.timeout_sec == 12
    assert client.judge.timeout_sec == 12
    assert client.reviewer.retries == 2
    assert client.judge.retries == 2


def test_openrouter_client_records_reported_cost(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "cost": 0},
            },
        )

    client = OpenAICompatJsonClient(
        model="google/gemma-4-31b-it",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        prompt_version="test/openrouter",
        transport=httpx.MockTransport(handler),
    )

    result, _ = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["ok"] is True
    assert result["estimated_cost_usd"] == 0.0
    assert json.loads(requests[0].content)["max_tokens"] == 900


def test_openrouter_client_allows_reported_cost_for_paid_models(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "cost": 0.01},
            },
        )

    client = OpenAICompatJsonClient(
        model="stepfun/step-3.5-flash",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        prompt_version="test/openrouter",
        transport=httpx.MockTransport(handler),
    )

    result, _ = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["ok"] is True
    assert result["estimated_cost_usd"] == 0.01


def test_openrouter_client_retries_retryable_transport_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary connect failure")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "cost": 0.01},
            },
        )

    client = OpenAICompatJsonClient(
        model="google/gemma-4-31b-it",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        prompt_version="test/openrouter",
        retries=1,
        retry_backoff_sec=0,
        transport=httpx.MockTransport(handler),
    )

    result, _ = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["ok"] is True
    assert calls == 2
