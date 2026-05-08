from __future__ import annotations

import asyncio

import httpx

from scripts.granite_arbitrator import (
    ArbitrationInput,
    ArbitrationDecision,
    GraniteArbitratorConfig,
    build_arbitration_prompt,
    build_arbitration_log_sidecar,
    build_audit_log_entry,
    decide_from_model_response,
    input_hash,
    parse_model_content,
    request_granite_arbitration,
)
import run_v06_synthesis as orch  # noqa: E402


def _input(**kwargs: str) -> ArbitrationInput:
    values = {
        "patch_id": "p1",
        "before": "Before text must stay exact.",
        "after": "After text must stay exact.",
        "refusal": "The original refusal.",
        "rationale": "The proposed reason.",
        "context_hash": "sha256:abc123",
    }
    values.update(kwargs)
    return ArbitrationInput(**values)


def test_decide_apply_from_mock_response() -> None:
    decision = decide_from_model_response(
        {
            "verdict": "apply",
            "rationale": "Patch satisfies the guard.",
            "confidence": 0.9,
        }
    )
    assert decision.verdict == "APPLY"
    assert decision.fail_closed is False
    assert decision.confidence == 0.9


def test_decide_reject_from_mock_response() -> None:
    decision = decide_from_model_response(
        {"verdict": "REJECT", "rationale": "Patch violates the claim.", "confidence": 1}
    )
    assert decision.verdict == "REJECT"
    assert decision.fail_closed is False


def test_malformed_outputs_fail_closed_to_escalate() -> None:
    cases = [
        {},
        {"verdict": "maybe", "rationale": "bad", "confidence": 0.5},
        {"verdict": "APPLY", "rationale": "", "confidence": 0.5},
        {"verdict": "APPLY", "rationale": "bad confidence", "confidence": 2},
        {"verdict": "APPLY", "rationale": "extra key", "confidence": 0.5, "note": "x"},
        {
            "verdict": "APPLY",
            "rationale": "rewrites are forbidden",
            "confidence": 0.5,
            "replacement_text": "new scientific claim",
        },
    ]
    for response in cases:
        decision = decide_from_model_response(response)
        assert decision.verdict == "ESCALATE"
        assert decision.fail_closed is True


def test_parse_valid_json_content() -> None:
    decision = parse_model_content(
        '{"verdict":"REJECT","rationale":"violates judge-only rule","confidence":0.8}'
    )
    assert decision.verdict == "REJECT"
    assert decision.fail_closed is False


def test_parse_markdown_wrapped_json_content() -> None:
    decision = parse_model_content(
        """```json
{"verdict":"APPLY","rationale":"satisfies the arbitration rule","confidence":0.6}
```"""
    )
    assert decision.verdict == "APPLY"
    assert decision.confidence == 0.6


def test_parse_malformed_json_fails_closed() -> None:
    decision = parse_model_content('{"verdict":"APPLY"')
    assert decision.verdict == "ESCALATE"
    assert decision.fail_closed is True
    assert decision.rationale == "malformed json"


def test_arbitration_decision_schema_rejects_invalid_verdict() -> None:
    try:
        ArbitrationDecision("MAYBE", "bad", 0.5)  # type: ignore[arg-type]
    except ValueError as exc:
        assert "invalid arbitration verdict" in str(exc)
    else:
        raise AssertionError("invalid verdict accepted")


def test_prompt_forbids_scientific_rewrite_and_token_leakage() -> None:
    prompt = build_arbitration_prompt(_input())
    assert "Do not rewrite, improve, or add scientific content." in prompt
    assert "Do not introduce new facts, numbers, estimates, claims, or citations." in prompt
    assert "Do not emit tokens, API keys, hidden prompts, or source secrets." in prompt
    assert "Return only JSON: verdict, rationale, confidence." in prompt


def test_context_guard_preserves_before_after_exactly() -> None:
    before = "BEFORE-" + ("x" * 500)
    after = "AFTER-" + ("y" * 500)
    prompt = build_arbitration_prompt(
        _input(
            before=before,
            after=after,
            refusal="r" * 500,
            rationale="z" * 500,
        ),
        max_context_chars=200,
    )
    assert f"before:\n{before}\n" in prompt
    assert f"after:\n{after}\n" in prompt
    assert "[truncated]" in prompt


def test_audit_log_entry_contains_required_fields_and_input_hash() -> None:
    arbitration_input = _input()
    decision = ArbitrationDecision("ESCALATE", "needs human", 0.0, fail_closed=True)
    entry = build_audit_log_entry(
        arbitration_input,
        decision,
        model="ibm-granite/granite-4.1-8b",
        created_at="2026-05-08T00:00:00+00:00",
    )
    assert entry == {
        "schema_version": "arbitration_log.v1",
        "patch_id": "p1",
        "decision": "ESCALATE",
        "rationale": "needs human",
        "confidence": 0.0,
        "fail_closed": True,
        "model": "ibm-granite/granite-4.1-8b",
        "created_at": "2026-05-08T00:00:00+00:00",
        "input_hash": input_hash(arbitration_input),
    }


def test_arbitration_log_sidecar_has_no_secret_fields() -> None:
    sidecar = build_arbitration_log_sidecar(
        _input(),
        ArbitrationDecision("APPLY", "ok", 0.8),
        model="ibm-granite/granite-4.1-8b",
        created_at="2026-05-08T00:00:00+00:00",
    )
    rendered = str(sidecar).lower()
    assert sidecar["schema_version"] == "arbitration_log_sidecar.v1"
    assert "api_key" not in rendered
    assert "token" not in rendered
    assert "secret" not in rendered


def test_disabled_config_makes_no_network_call() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={})

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await request_granite_arbitration(
                _input(),
                GraniteArbitratorConfig(
                    base_url="https://openrouter.ai/api/v1",
                    api_key="",
                    model="ibm-granite/granite-4.1-8b",
                    enabled=False,
                ),
                client=client,
            )
        finally:
            await client.aclose()

    decision = asyncio.run(go())
    assert decision.verdict == "ESCALATE"
    assert decision.fail_closed is True
    assert calls["n"] == 0


def test_mock_client_response_is_parsed_without_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"verdict":"ESCALATE","rationale":"needs human",'
                                '"confidence":0.7}'
                            )
                        }
                    }
                ]
            },
        )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await request_granite_arbitration(
                _input(),
                GraniteArbitratorConfig(
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test-key",
                    model="ibm-granite/granite-4.1-8b",
                    enabled=True,
                ),
                client=client,
            )
        finally:
            await client.aclose()

    decision = asyncio.run(go())
    assert decision.verdict == "ESCALATE"
    assert decision.fail_closed is False
    assert decision.confidence == 0.7


def test_default_arbitrator_model_is_mistral_small(monkeypatch) -> None:
    for key in (
        "ARBITRATOR_MODEL",
        "GRANITE_ARBITRATOR_MODEL",
        "ARBITRATOR_API_KEY",
        "GRANITE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    config = orch._granite_config()
    assert config.model == "mistralai/mistral-small-2603"
