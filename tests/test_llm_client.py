"""Tests for agent/llm_client.py — extract_json + CostLedger + chat_json chain.

httpx.MockTransport drives all chat_json tests offline (no network). Tests
are sync def + asyncio.run() rather than introducing a pytest-anyio config
just for this module.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

try:
    import httpx
except ModuleNotFoundError:
    class _FakeHTTPStatusError(Exception):
        def __init__(self, response: "_FakeResponse") -> None:
            super().__init__(f"{response.status_code} response")
            self.response = response

    class _FakeRequest:
        def __init__(
            self,
            url: str,
            content: bytes,
            headers: dict[str, str],
        ) -> None:
            self.url = url
            self.content = content
            self.headers = headers

    class _FakeResponse:
        def __init__(
            self,
            status_code: int,
            *,
            json: dict[str, Any] | None = None,
            text: str = "",
        ) -> None:
            self.status_code = status_code
            self._json = json
            self.text = text

        def json(self) -> dict[str, Any]:
            return self._json or {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise _FakeHTTPStatusError(self)

    class _FakeMockTransport:
        def __init__(self, handler: Any) -> None:
            self.handler = handler

    class _FakeAsyncClient:
        def __init__(self, transport: _FakeMockTransport | None = None) -> None:
            self.transport = transport

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
            timeout: float,
        ) -> _FakeResponse:
            assert self.transport is not None
            request = _FakeRequest(
                url, content=__import__("json").dumps(json).encode(),
                headers=headers,
            )
            return self.transport.handler(request)

        async def aclose(self) -> None:
            return None

    class _FakeHttpx:
        AsyncClient = _FakeAsyncClient
        MockTransport = _FakeMockTransport
        Request = _FakeRequest
        Response = _FakeResponse
        HTTPError = Exception
        HTTPStatusError = _FakeHTTPStatusError
        TimeoutException = TimeoutError
        NetworkError = OSError
        RemoteProtocolError = RuntimeError
        PoolTimeout = TimeoutError

    httpx = _FakeHttpx()  # type: ignore[assignment]

from agent.llm_client import (
    CallSpec,
    CostLedger,
    LLMError,
    LLMResponse,
    build_extract_chain,
    build_judge_chain,
    chat_json,
    extract_json,
)
import agent.llm_client as llm_client
from agent.settings import Settings

llm_client.httpx = httpx


# --- extract_json ---------------------------------------------------------


def test_extract_json_clean_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_think_block() -> None:
    text = '<think>weighing options</think>{"a": 1}'
    assert extract_json(text) == {"a": 1}


def test_extract_json_strips_json_fence() -> None:
    text = '```json\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_json_strips_plain_fence() -> None:
    text = '```\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_json_handles_prose_prefix() -> None:
    text = 'Here is the result: {"a": 1, "b": [2, 3]}. Hope that helps.'
    assert extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_picks_first_valid_object_after_garbage() -> None:
    """Decoder walks `{` positions until one parses cleanly."""
    text = '{"oops": broken {"a": 1} {"b": 2}'
    assert extract_json(text) == {"a": 1}


def test_extract_json_no_object_raises() -> None:
    with pytest.raises(ValueError, match="no JSON object"):
        extract_json("just prose, no JSON")


def test_extract_json_array_only_raises() -> None:
    """A top-level array is valid JSON but not an *object* — fact extraction
    requires an object so this must raise."""
    with pytest.raises(ValueError, match="no JSON object"):
        extract_json("[1, 2, 3]")


# --- CostLedger -----------------------------------------------------------


def _resp(model: str, cost: float) -> LLMResponse:
    return LLMResponse(
        text="", parsed={}, model=model,
        input_tokens=0, output_tokens=0,
        estimated_cost_usd=cost,
    )


def test_cost_ledger_total_sums_calls() -> None:
    led = CostLedger()
    led.add(_resp("a", 0.01))
    led.add(_resp("b", 0.02))
    assert led.total_usd() == pytest.approx(0.03)


def test_cost_ledger_by_model_groups() -> None:
    led = CostLedger()
    led.add(_resp("a", 0.01))
    led.add(_resp("a", 0.02))
    led.add(_resp("b", 0.04))
    grouped = led.by_model()
    assert grouped["a"] == pytest.approx(0.03)
    assert grouped["b"] == pytest.approx(0.04)


def test_cost_ledger_to_dict_is_json_serializable() -> None:
    led = CostLedger()
    led.add(_resp("a", 0.012345678))  # exercise rounding
    d = led.to_dict()
    json.dumps(d)  # raises if not serializable
    assert d["total_usd"] == pytest.approx(0.012346, abs=1e-7)
    assert "a" in d["by_model"]
    assert d["calls"][0]["model"] == "a"


def test_cost_ledger_empty_state_is_clean() -> None:
    led = CostLedger()
    assert led.total_usd() == 0.0
    assert led.by_model() == {}
    assert led.to_dict()["calls"] == []


# --- chat_json: mock transport patterns ----------------------------------


def _spec(
    model: str = "test/model",
    api_key: str = "k",
    base_url: str = "https://api.example.com/v1",
    max_attempts: int = 1,
) -> CallSpec:
    return CallSpec(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_sec=5.0,
        max_attempts=max_attempts,
    )


def _ok_body(content: str = '{"x": 1}', prompt_tok: int = 10, comp_tok: int = 20) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tok, "completion_tokens": comp_tok},
    }


def _anthropic_ok_body(
    content: str = '{"x": 1}', input_tok: int = 10, output_tok: int = 20,
) -> dict:
    return {
        "content": [{"type": "text", "text": content}],
        "usage": {"input_tokens": input_tok, "output_tokens": output_tok},
    }


def _run(coro):
    return asyncio.run(coro)


def test_chat_json_happy_path_returns_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body())

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.parsed == {"x": 1}
    assert resp.input_tokens == 10
    assert resp.output_tokens == 20
    assert resp.model == "test/model"


def test_chat_json_anthropic_compatible_minimax_m3() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_anthropic_ok_body())

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": "hi"},
                ],
                chain=(
                    _spec(
                        model="MiniMax-M3",
                        base_url="https://api.minimax.io/anthropic",
                    ),
                ),
                client=client,
                max_tokens=123,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert captured["url"] == "https://api.minimax.io/anthropic/v1/messages"
    assert captured["payload"] == {
        "model": "MiniMax-M3",
        "temperature": 0.2,
        "max_tokens": 123,
        "messages": [{"role": "user", "content": "hi"}],
        "system": "Return JSON only.",
    }
    assert resp.parsed == {"x": 1}
    assert resp.input_tokens == 10
    assert resp.output_tokens == 20
    assert resp.model == "MiniMax-M3"


def test_chat_json_falls_back_on_5xx() -> None:
    """First spec returns 500; second spec succeeds — fallback path proven."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_ok_body('{"y": 2}'))

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("primary"), _spec("fallback")),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.parsed == {"y": 2}
    assert resp.model == "fallback"
    assert call_count["n"] == 2


def test_chat_json_retries_retryable_status_before_fallback() -> None:
    """Transient 5xx on a provider should retry the same model first."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, text="temporary overload")
        return httpx.Response(200, json=_ok_body('{"recovered": true}'))

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("primary", max_attempts=2), _spec("fallback")),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.parsed == {"recovered": True}
    assert resp.model == "primary"
    assert call_count["n"] == 2
    assert [a["ok"] for a in resp.attempts] == [False, True]


def test_chat_json_skips_specs_without_api_key() -> None:
    """A spec with empty api_key is skipped without an HTTP attempt."""
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        return httpx.Response(200, json=_ok_body('{"z": 3}'))

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("primary", api_key=""), _spec("fallback")),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.model == "fallback"
    assert resp.parsed == {"z": 3}
    assert http_calls["n"] == 1  # primary skipped at api_key gate, no HTTP


def test_chat_json_all_specs_fail_raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("a"), _spec("b")),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(LLMError, match="every spec in chain failed"):
        _run(go())


def test_chat_json_empty_chain_raises() -> None:
    async def go() -> None:
        await chat_json(
            messages=[{"role": "user", "content": "hi"}], chain=(),
        )

    with pytest.raises(LLMError, match="empty chain"):
        _run(go())


def test_chat_json_records_to_ledger_when_provided() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body())

    led = CostLedger()

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
                ledger=led,
            )
        finally:
            await client.aclose()

    _run(go())
    assert len(led.calls) == 1
    assert led.calls[0].model == "test/model"


def test_chat_json_unparseable_response_falls_back() -> None:
    """First model emits prose with no JSON; chat_json must fall through."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(200, json=_ok_body("just prose, no JSON"))
        return httpx.Response(200, json=_ok_body('{"saved": true}'))

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("primary"), _spec("fallback")),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.parsed == {"saved": True}
    assert resp.model == "fallback"


def test_chat_json_retries_unparseable_response_same_model() -> None:
    """A one-off JSON formatting miss should not immediately burn fallback."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(200, json=_ok_body("prose without json"))
        return httpx.Response(200, json=_ok_body('```json\n{"ok": true}\n```'))

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("primary", max_attempts=2), _spec("fallback")),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.parsed == {"ok": True}
    assert resp.model == "primary"
    assert call_count["n"] == 2


def test_chat_json_estimates_cost_for_known_model() -> None:
    """A known-priced model produces a non-zero cost; unknown is 0."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_ok_body(prompt_tok=1000, comp_tok=1000),
        )

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("mimo-v2.5-pro"),),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    # 1k input * $0.00014/1k + 1k output * $0.00028/1k = $0.00042
    assert resp.estimated_cost_usd == pytest.approx(0.00042, abs=1e-7)


def test_chat_json_unknown_model_costs_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_ok_body(prompt_tok=1000, comp_tok=1000),
        )

    async def go() -> LLMResponse:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec("never/heard/of"),),
                client=client,
            )
        finally:
            await client.aclose()

    resp = _run(go())
    assert resp.estimated_cost_usd == 0.0


def test_chat_json_request_includes_response_format_when_enforce_json() -> None:
    """Verify the wire-level payload has response_format=json_object set."""
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
                enforce_json=True,
            )
        finally:
            await client.aclose()

    _run(go())
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_chat_json_request_omits_response_format_when_not_enforce_json() -> None:
    """Some OpenRouter models reject response_format; toggle must remove it."""
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
                enforce_json=False,
            )
        finally:
            await client.aclose()

    _run(go())
    assert "response_format" not in captured["payload"]


def test_chat_json_openrouter_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenRouter requires app metadata headers for reliable routing."""
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://researka.org")
    monkeypatch.setenv("OPENROUTER_X_TITLE", "Researka Research Agent")
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["referer"] = request.headers["HTTP-Referer"]
        captured["title"] = request.headers["X-Title"]
        return httpx.Response(200, json=_ok_body())

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(base_url="https://openrouter.ai/api/v1"),),
                client=client,
            )
        finally:
            await client.aclose()

    _run(go())
    assert captured == {
        "referer": "https://researka.org",
        "title": "Researka Research Agent",
    }


# --- Day 9.4: seed forwarding for zero-variance --------------------------


def test_chat_json_seed_forwarded_to_payload() -> None:
    """Day 9.4: the OpenAI-compatible `seed` parameter must reach the
    wire payload. With temperature 0 + same seed + same prompt, MiMo
    and OpenRouter return byte-identical responses — the foundation
    for zero-variance receipts."""
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
                seed=42,
            )
        finally:
            await client.aclose()

    _run(go())
    assert captured["payload"]["seed"] == 42


def test_chat_json_seed_omitted_when_none() -> None:
    """Default `seed=None` must NOT include the field in the payload —
    some providers reject explicit nulls. Backward-compatibility for
    pre-Day-9.4 callers."""
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(_spec(),),
                client=client,
            )
        finally:
            await client.aclose()

    _run(go())
    assert "seed" not in captured["payload"]


def test_chat_json_seed_forwarded_to_every_chain_spec() -> None:
    """Fallback path: when the primary fails and the chain advances to
    the secondary, the same seed must be forwarded. Otherwise the
    fallback would draw from a different RNG state and break
    determinism."""
    seen: list[int | None] = []

    def primary_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content).get("seed"))
        return httpx.Response(503, json={"error": "down"})

    def fallback_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content).get("seed"))
        return httpx.Response(200, json=_ok_body())

    def router(request: httpx.Request) -> httpx.Response:
        if "primary" in str(request.url):
            return primary_handler(request)
        return fallback_handler(request)

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(router))
        try:
            await chat_json(
                messages=[{"role": "user", "content": "hi"}],
                chain=(
                    _spec(base_url="https://primary.example/v1"),
                    _spec(base_url="https://fallback.example/v1"),
                ),
                client=client,
                seed=99,
            )
        finally:
            await client.aclose()

    _run(go())
    assert seen == [99, 99]


# --- build_extract_chain --------------------------------------------------


def _settings(
    minimax_key: str = "minimax-key", openrouter_key: str = "or-key",
    judge_model: str = "google/gemma-4-31b-it",
) -> Settings:
    return Settings(
        minimax_api_key=minimax_key,
        minimax_model="MiniMax-M3",
        minimax_base_url="https://api.minimax.io/anthropic",
        minimax_timeout_sec=30.0,
        openrouter_api_key=openrouter_key,
        openrouter_base_url="https://or.example/v1",
        judge_model=judge_model,
        fallback_model="mistralai/mistral-small-2603",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        bot_enabled=True, daily_cost_cap_usd=10.0,
        dashboard_host="127.0.0.1", dashboard_port=8791,
        runs_dir="runs",
    )


def test_build_extract_chain_yields_minimax_then_mistral() -> None:
    chain = build_extract_chain(_settings())
    assert len(chain) == 2
    assert chain[0].model == "MiniMax-M3"
    assert chain[1].model == "mistralai/mistral-small-2603"


def test_build_extract_chain_keeps_empty_keys_in_chain() -> None:
    """Specs with empty api_keys stay in the chain — chat_json skips them."""
    chain = build_extract_chain(_settings(minimax_key=""))
    assert len(chain) == 2
    assert chain[0].api_key == ""  # unset, will be skipped at call time
    assert chain[1].api_key == "or-key"


def test_build_extract_chain_uses_settings_timeout() -> None:
    s = _settings()
    chain = build_extract_chain(s)
    assert chain[0].timeout_sec == s.minimax_timeout_sec
    assert chain[1].timeout_sec == s.minimax_timeout_sec  # both share MiniMax timeout


def test_build_extract_chain_sets_retry_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_CALL_ATTEMPTS", "3")
    chain = build_extract_chain(_settings())
    assert [s.max_attempts for s in chain] == [3, 3]


# --- build_judge_chain (Day 5.3) -----------------------------------------


def test_build_judge_chain_excludes_writer_family() -> None:
    """Trust-spine rule (judge != writer): the judge chain must never contain
    the writer/extractor family. Gemma (primary) → Mistral (fallback); the
    MiniMax writer model is dropped so a provider outage can't route judging
    back to the writer (never let a model grade its own output)."""
    chain = build_judge_chain(_settings())
    models = [s.model for s in chain]
    assert models == ["google/gemma-4-31b-it", "mistralai/mistral-small-2603"]
    assert "MiniMax-M3" not in models


def test_build_judge_chain_keeps_empty_keys_but_drops_writer_family() -> None:
    """Non-writer specs with empty api_keys remain (chat_json skips them at
    call time); the writer-family spec is dropped regardless of key."""
    chain = build_judge_chain(_settings(openrouter_key=""))
    assert [s.model for s in chain] == [
        "google/gemma-4-31b-it",
        "mistralai/mistral-small-2603",
    ]
    assert all(s.api_key == "" for s in chain)  # both under OpenRouter


def test_build_judge_chain_drops_writer_family_judge_primary() -> None:
    """A judge_model misconfigured to the writer's family is dropped rather
    than allowed to grade its own output; the chain falls through to a
    non-writer model."""
    chain = build_judge_chain(_settings(judge_model="MiniMax-M3"))
    models = [s.model for s in chain]
    assert "MiniMax-M3" not in models
    assert "mistralai/mistral-small-2603" in models
