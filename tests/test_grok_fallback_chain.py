"""Tests for the DeepSeek → Mistral Small fallback chain in
scripts/grok_reviewer.py. NEVER skip the final-layer review."""
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


def test_primary_used_when_available() -> None:
    """When the primary responds normally, Mistral is never called."""
    client = MagicMock()
    client.post = AsyncMock(return_value=_mock_chat_response(
        "deepseek/deepseek-v4-pro", {"patches": []},
    ))
    parsed, model_used, cost = asyncio.run(
        grok_reviewer._call_with_fallback(
            "sys", "user", "deepseek/deepseek-v4-pro",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "deepseek/deepseek-v4-pro"
    assert client.post.call_count == 1
    assert cost > 0


def test_mistral_fallback_when_primary_fails() -> None:
    """When primary throws (HTTP error / parse failure), Mistral is the
    next call. Pipeline never silently skips final-layer review."""
    client = MagicMock()
    grok_failure = httpx.HTTPError("OpenRouter 503")
    mistral_success = _mock_chat_response(
        "mistralai/mistral-small-2603", {"patches": []},
    )
    client.post = AsyncMock(side_effect=[grok_failure, mistral_success])
    parsed, model_used, cost = asyncio.run(
        grok_reviewer._call_with_fallback(
            "sys", "user", "deepseek/deepseek-v4-pro",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "mistralai/mistral-small-2603"
    assert client.post.call_count == 2
    # Mistral pricing (0.20/0.60 per Mtok), still > 0
    assert cost > 0


def test_both_failures_raises() -> None:
    """If BOTH primary and fallback fail, raise so the pipeline can record
    the gap rather than silently skip review."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.HTTPError("OpenRouter down"))
    try:
        asyncio.run(grok_reviewer._call_with_fallback(
            "sys", "user", "deepseek/deepseek-v4-pro",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        ))
        raise AssertionError("expected RuntimeError on dual-failure")
    except RuntimeError as exc:
        assert "both" in str(exc).lower()


def test_prompt_uses_body_citations_when_registry_provided() -> None:
    """Fix #11: when citation_registry is passed, the user prompt
    surfaces clean Author-Year tokens to the reviewer, NOT internal receipt_id
    handles. Pre-fix reviewer was reverting clean citations because the
    prompt said 'use ONLY these for citations' next to receipt_ids."""
    from dataclasses import dataclass

    @dataclass
    class _Entry:
        body_citation: str
        reference_id: str = "R01"
        receipt_id: str = ""

    manifest = {
        "receipts": [
            {
                "receipt_id": "PMC12978362_molecular_mechanisms_of_metformin",
                "outcome_class": "longevity",
                "effect_direction": "positive",
                "evidence_tier": "C1",
            },
        ],
    }
    registry = {
        "PMC12978362_molecular_mechanisms_of_metformin":
            _Entry(body_citation="Vujović 2026"),
    }
    _system, user = grok_reviewer._build_grok_prompt(
        "## Body\n\nText.", manifest, {"p1_pass": True, "score_out_of_10": 9},
        citation_registry=registry,
    )
    # Clean Author-Year token shown
    assert "Vujović 2026" in user
    # Long internal handle NOT shown in the citation list
    assert "PMC12978362_molecular_mechanisms_of_metformin" not in user
    # Header reflects new framing
    assert "Allowed body citations" in user


def test_prompt_keeps_same_background_citation_with_distinct_numerics() -> None:
    """A single background citation can define multiple canonical
    thresholds. Grok must see each token+numeric pair; deduping only by
    citation token hides legitimate values and causes false P1 strips."""
    _system, user = grok_reviewer._build_grok_prompt(
        "## Body\n\nCruz-Jentoft 2019 reports 16 kg and 27 kg thresholds.",
        {"receipts": [], "topic": "caloric_restriction"},
        {"p1_pass": True, "score_out_of_10": 10},
        citation_registry={},
    )
    assert "- Cruz-Jentoft 2019: 16 kg" in user
    assert "- Cruz-Jentoft 2019: 27 kg" in user


def test_prompt_falls_back_to_receipt_ids_without_registry() -> None:
    """Backward compat: callers that don't pass citation_registry get
    the legacy receipt_id-based prompt (just to keep old call sites
    working; new orchestrator always passes the registry)."""
    manifest = {
        "receipts": [
            {
                "receipt_id": "Walton_2019_MASTERS_metformin_blunts",
                "outcome_class": "muscle_function",
                "effect_direction": "negative",
                "evidence_tier": "A1",
            },
        ],
    }
    _system, user = grok_reviewer._build_grok_prompt(
        "## Body\n\nText.", manifest, {"p1_pass": True, "score_out_of_10": 9},
        citation_registry=None,
    )
    # Falls back to receipt_id form
    assert "Walton_2019_MASTERS_metformin_blunts" in user
    assert "Receipt list" in user


def test_cost_estimate_is_real_not_zero() -> None:
    """Pre-fix cost was a hardcoded 0.0 placeholder. Verify the cost
    function actually computes something for known models."""
    deepseek_cost = grok_reviewer._estimate_cost(
        "deepseek/deepseek-v4-pro", 1_000_000, 100_000,
    )
    # DeepSeek V4 Pro: $0.435/Mtok in, $0.87/Mtok out.
    assert 0.50 < deepseek_cost < 0.60, f"unexpected deepseek cost: {deepseek_cost}"
    grok_cost = grok_reviewer._estimate_cost("x-ai/grok-4.3", 1_000_000, 100_000)
    # Grok 4.3: $3/Mtok in, $15/Mtok out → $3 + $1.5 = $4.50
    assert 4.0 < grok_cost < 5.0, f"unexpected grok cost: {grok_cost}"
    mistral_cost = grok_reviewer._estimate_cost(
        "mistralai/mistral-small-2603", 1_000_000, 100_000,
    )
    # Mistral: $0.15/Mtok in, $0.60/Mtok out → $0.15 + $0.06 = $0.21
    assert 0.20 < mistral_cost < 0.22, f"unexpected mistral cost: {mistral_cost}"
    unknown_cost = grok_reviewer._estimate_cost("foo/bar-99", 1_000_000, 100_000)
    assert unknown_cost == 0.0  # no pricing table → 0
