"""Tests for the Grok 4.3 → Mistral Small fallback chain in
scripts/grok_reviewer.py — the user mandate is: Grok primary, Mistral
only if Grok / OpenRouter is unreachable. NEVER skip the final-layer
review."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import grok_reviewer  # noqa: E402


def _mock_chat_response(
    model: str, content_json: dict, in_tok: int = 100, out_tok: int = 200,
) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={
        "choices": [{"message": {"content": json.dumps(content_json)}}],
        "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok},
        "model": model,
    })
    return response


def test_grok_primary_used_when_available() -> None:
    """When Grok responds normally, Mistral is never called."""
    client = MagicMock()
    client.post = AsyncMock(return_value=_mock_chat_response(
        "x-ai/grok-4.3", {"patches": []},
    ))
    parsed, model_used, cost = asyncio.run(
        grok_reviewer._call_with_fallback(
            "sys", "user", "x-ai/grok-4.3",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "x-ai/grok-4.3"
    assert client.post.call_count == 1
    # Cost should be Grok's pricing (3/15 per Mtok), not zero
    assert cost > 0


def test_mistral_fallback_when_grok_fails() -> None:
    """When Grok throws (HTTP error / parse failure), Mistral is the
    next call. Pipeline never silently skips final-layer review."""
    client = MagicMock()
    grok_failure = httpx.HTTPError("OpenRouter 503")
    mistral_success = _mock_chat_response(
        "mistralai/mistral-small-2603", {"patches": []},
    )
    client.post = AsyncMock(side_effect=[grok_failure, mistral_success])
    parsed, model_used, cost = asyncio.run(
        grok_reviewer._call_with_fallback(
            "sys", "user", "x-ai/grok-4.3",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "mistralai/mistral-small-2603"
    assert client.post.call_count == 2
    # Mistral pricing (0.20/0.60 per Mtok), still > 0
    assert cost > 0


def test_both_failures_raises() -> None:
    """If BOTH Grok and Mistral fail, raise so the pipeline can record
    the gap rather than silently skip review."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.HTTPError("OpenRouter down"))
    try:
        asyncio.run(grok_reviewer._call_with_fallback(
            "sys", "user", "x-ai/grok-4.3",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        ))
        raise AssertionError("expected RuntimeError on dual-failure")
    except RuntimeError as exc:
        assert "both" in str(exc).lower()


def test_cost_estimate_is_real_not_zero() -> None:
    """Pre-fix cost was a hardcoded 0.0 placeholder. Verify the cost
    function actually computes something for known models."""
    grok_cost = grok_reviewer._estimate_cost("x-ai/grok-4.3", 1_000_000, 100_000)
    # Grok 4.3: $3/Mtok in, $15/Mtok out → $3 + $1.5 = $4.50
    assert 4.0 < grok_cost < 5.0, f"unexpected grok cost: {grok_cost}"
    mistral_cost = grok_reviewer._estimate_cost(
        "mistralai/mistral-small-2603", 1_000_000, 100_000,
    )
    # Mistral: $0.20/Mtok in, $0.60/Mtok out → $0.20 + $0.06 = $0.26
    assert 0.20 < mistral_cost < 0.30, f"unexpected mistral cost: {mistral_cost}"
    unknown_cost = grok_reviewer._estimate_cost("foo/bar-99", 1_000_000, 100_000)
    assert unknown_cost == 0.0  # no pricing table → 0
