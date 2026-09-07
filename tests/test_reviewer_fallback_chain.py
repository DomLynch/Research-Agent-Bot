"""Tests for the primary → fallback chain in
scripts/final_reviewer.py. NEVER skip the final-layer review."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import final_reviewer  # noqa: E402


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
        "google/gemini-3.1-flash-lite:exacto", {"patches": []},
    ))
    parsed, model_used, cost = asyncio.run(
        final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "google/gemini-3.1-flash-lite:exacto"
    assert client.post.call_count == 1
    payload = client.post.call_args.kwargs["json"]
    assert payload["reasoning"] == {"effort": "high", "exclude": True}
    assert cost > 0


def test_low_patch_long_paper_can_escalate() -> None:
    """the primary reviewer can be primary, but a suspiciously clean long paper can
    escalate to a stronger reviewer when explicitly configured."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        _mock_chat_response("google/gemini-3.1-flash-lite:exacto", {"patches": []}),
        _mock_chat_response(
            "x-ai/grok-4.3",
            {
                "patches": [
                    {
                        "id": "P01",
                        "patch_type": "formatting",
                        "severity": "P1",
                        "location": "Body",
                        "before": "artifact",
                        "after": "",
                        "reason": "Public artifact.",
                    }
                ]
            },
        ),
    ])

    patches, raw, model_used, cost = asyncio.run(
        final_reviewer.review_paper(
            "word " * 10_001,
            {"receipts": []},
            {"p1_pass": True, "score_out_of_10": 10},
            model="google/gemini-3.1-flash-lite:exacto",
            fallback_model="mistralai/mistral-small-2603",
            escalation_model="x-ai/grok-4.3",
            api_key="test-key",
            client=client,
        )
    )

    assert model_used == "google/gemini-3.1-flash-lite:exacto→x-ai/grok-4.3"
    assert client.post.call_count == 2
    assert len(patches) == 1
    assert patches[0].severity == "P1"
    assert cost > 0


def test_low_patch_short_paper_does_not_escalate() -> None:
    client = MagicMock()
    client.post = AsyncMock(return_value=_mock_chat_response(
        "google/gemini-3.1-flash-lite:exacto", {"patches": []},
    ))

    patches, _raw, model_used, _cost = asyncio.run(
        final_reviewer.review_paper(
            "short clean paper",
            {"receipts": []},
            {"p1_pass": True, "score_out_of_10": 10},
            model="google/gemini-3.1-flash-lite:exacto",
            fallback_model="mistralai/mistral-small-2603",
            escalation_model="x-ai/grok-4.3",
            api_key="test-key",
            client=client,
        )
    )

    assert model_used == "google/gemini-3.1-flash-lite:exacto"
    assert patches == []
    assert client.post.call_count == 1


def test_review_paper_retries_non_list_patches() -> None:
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        _mock_chat_response("google/gemini-3.1-flash-lite:exacto", {"patches": 0}),
        _mock_chat_response("google/gemini-3.1-flash-lite:exacto", {"patches": []}),
    ])

    patches, raw, _model_used, _cost = asyncio.run(
        final_reviewer.review_paper(
            "short clean paper",
            {"receipts": []},
            {"p1_pass": True, "score_out_of_10": 10},
            model="google/gemini-3.1-flash-lite:exacto",
            fallback_model="mistralai/mistral-small-2603",
            api_key="test-key",
            client=client,
        )
    )

    assert patches == []
    assert [a["ok"] for a in raw["_review_attempts"]] == [False, True]


def test_low_patch_escalation_preserves_review_on_invalid_patches() -> None:
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        _mock_chat_response("google/gemini-3.1-flash-lite:exacto", {"patches": []}),
        _mock_chat_response("x-ai/grok-4.3", {"patches": 0}),
    ])

    patches, raw, model_used, _cost = asyncio.run(
        final_reviewer.review_paper(
            "word " * 10_001,
            {"receipts": []},
            {"p1_pass": True, "score_out_of_10": 10},
            model="google/gemini-3.1-flash-lite:exacto",
            fallback_model="mistralai/mistral-small-2603",
            escalation_model="x-ai/grok-4.3",
            api_key="test-key",
            client=client,
        )
    )

    assert patches == []
    assert raw["low_patch_escalation_error"] == "ValueError"
    assert model_used == "google/gemini-3.1-flash-lite:exacto"


def test_primary_retry_recovers_before_mistral() -> None:
    """A transient primary parse miss should retry the primary before fallback."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=[
        ValueError("invalid primary JSON"),
        _mock_chat_response(
            "google/gemini-3.1-flash-lite:exacto", {"patches": []},
        ),
    ])
    parsed, model_used, cost = asyncio.run(
        final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "google/gemini-3.1-flash-lite:exacto"
    assert client.post.call_count == 2
    assert parsed["patches"] == []
    assert [a["ok"] for a in parsed["_review_attempts"]] == [False, True]
    assert cost > 0


def test_mistral_fallback_when_primary_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When primary throws (HTTP error / parse failure), Mistral is the
    next model after primary retries are exhausted."""
    monkeypatch.setattr(final_reviewer, "_PRIMARY_ATTEMPTS", 2)
    client = MagicMock()
    reviewer_failure = ValueError("invalid primary JSON")
    mistral_success = _mock_chat_response(
        "mistralai/mistral-small-2603", {"patches": []},
    )
    client.post = AsyncMock(side_effect=[
        reviewer_failure, reviewer_failure, mistral_success,
    ])
    parsed, model_used, cost = asyncio.run(
        final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "mistralai/mistral-small-2603"
    assert client.post.call_count == 3
    # Mistral pricing (0.20/0.60 per Mtok), still > 0
    assert cost > 0


def test_primary_wallclock_timeout_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung primary reviewer must not trap the revise lane indefinitely."""
    monkeypatch.setattr(final_reviewer, "_PRIMARY_ATTEMPTS", 1)
    monkeypatch.setattr(final_reviewer, "_review_call_timeout_sec", lambda: 0.01)

    class Client:
        calls = 0

        async def post(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(60)
            return _mock_chat_response(
                "mistralai/mistral-small-2603", {"patches": []},
            )

    client = Client()
    parsed, model_used, _cost = asyncio.run(
        final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "mistralai/mistral-small-2603"
    assert client.calls == 2
    assert parsed["_review_attempts"][0]["error_type"] == "TimeoutError"


def test_reviewer_extracts_json_from_prose_or_fence() -> None:
    """Gemini/OpenRouter may wrap JSON despite response_format=json_object."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={
        "choices": [
            {"message": {"content": "Here:\n```json\n{\"patches\": []}\n```"}}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200},
    })
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    parsed, model_used, _cost = asyncio.run(
        final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        )
    )
    assert model_used == "google/gemini-3.1-flash-lite:exacto"
    assert parsed["patches"] == []


def test_both_failures_raises() -> None:
    """If BOTH primary and fallback fail, raise so the pipeline can record
    the gap rather than silently skip review."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=ValueError("invalid provider response"))
    try:
        asyncio.run(final_reviewer._call_with_fallback(
            "sys", "user", "google/gemini-3.1-flash-lite:exacto",
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
    _system, user = final_reviewer._build_reviewer_prompt(
        "## Body\n\nText.", manifest, {"p1_pass": True, "score_out_of_10": 9},
        citation_registry=registry,
    )
    # Clean Author-Year token shown
    assert "Vujović 2026" in user
    # Long internal handle NOT shown in the citation list
    assert "PMC12978362_molecular_mechanisms_of_metformin" not in user
    # Header reflects new framing
    assert "Allowed body citations" in user


def test_review_and_repair_use_the_publication_policy() -> None:
    from agent.paper_writer_prompts import PUBLICATION_REQUIREMENTS
    import revision_coverage

    system, _ = final_reviewer._build_reviewer_prompt("paper", {"receipts": []}, {})
    repair, _ = final_reviewer._build_repair_prompt([], "paper")
    assert all(prompt.startswith(PUBLICATION_REQUIREMENTS) for prompt in (system, repair, revision_coverage._SYS))
    assert "4/5 in EACH" in system and "Optional style/wording suggestions are not publication blockers" in system


def test_prompt_keeps_same_background_citation_with_distinct_numerics() -> None:
    """A single background citation can define multiple canonical
    thresholds. The final-layer reviewer must see each token+numeric pair; deduping only by
    citation token hides legitimate values and causes false P1 strips."""
    _system, user = final_reviewer._build_reviewer_prompt(
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
    _system, user = final_reviewer._build_reviewer_prompt(
        "## Body\n\nText.", manifest, {"p1_pass": True, "score_out_of_10": 9},
        citation_registry=None,
    )
    # Falls back to receipt_id form
    assert "Walton_2019_MASTERS_metformin_blunts" in user
    assert "Receipt list" in user


def test_cost_estimate_is_real_not_zero() -> None:
    """Pre-fix cost was a hardcoded 0.0 placeholder. Verify the cost
    function actually computes something for known models."""
    gemini_cost = final_reviewer._estimate_cost(
        "google/gemini-3.1-flash-lite:exacto", 1_000_000, 100_000,
    )
    # Gemini 3.1 Flash Lite: $0.25/Mtok in, $1.50/Mtok out → $0.25 + $0.15 = $0.40
    assert 0.39 < gemini_cost < 0.41, f"unexpected Gemini cost: {gemini_cost}"
    escalation_cost = final_reviewer._estimate_cost("x-ai/grok-4.3", 1_000_000, 100_000)
    # Grok 4.3 escalation: $3/Mtok in, $15/Mtok out → $3 + $1.5 = $4.50
    assert 4.0 < escalation_cost < 5.0, f"unexpected escalation cost: {escalation_cost}"
    mistral_cost = final_reviewer._estimate_cost(
        "mistralai/mistral-small-2603", 1_000_000, 100_000,
    )
    # Mistral: $0.15/Mtok in, $0.60/Mtok out → $0.15 + $0.06 = $0.21
    assert 0.20 < mistral_cost < 0.22, f"unexpected mistral cost: {mistral_cost}"
    with pytest.raises(ValueError, match="no pricing configured"):
        final_reviewer._estimate_cost("foo/bar-99", 1_000_000, 100_000)


def test_unknown_model_fails_before_provider_call() -> None:
    client = MagicMock()
    client.post = AsyncMock()

    with pytest.raises(ValueError, match="no pricing configured"):
        asyncio.run(final_reviewer._call_with_fallback(
            "sys", "user", "unknown/model",
            "mistralai/mistral-small-2603",
            "test-key", "https://openrouter.ai/api/v1", client,
        ))
    client.post.assert_not_called()


def test_cost_cap_fails_before_provider_call() -> None:
    client = MagicMock()
    client.post = AsyncMock()

    with pytest.raises(RuntimeError, match="cost ceiling"):
        asyncio.run(final_reviewer.review_paper(
            "paper", {"receipts": []}, {"p1_pass": True},
            api_key="test-key", client=client, max_cost_usd=0.0,
        ))
    client.post.assert_not_called()


def test_cost_cap_defaults_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINAL_LAYER_MAX_COST_USD", raising=False)
    assert final_reviewer._review_cost_cap(None) == 1.0


def test_review_paper_honors_environment_provider_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FINAL_LAYER_REVIEWER_MODEL", "mistralai/mistral-small-2603",
    )
    monkeypatch.setenv(
        "FINAL_LAYER_FALLBACK_MODEL", "google/gemini-3.1-flash-lite:exacto",
    )
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1")
    monkeypatch.delenv("FINAL_LAYER_LOW_PATCH_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("FINAL_LAYER_MAX_COST_USD", raising=False)
    client = MagicMock()
    client.post = AsyncMock(return_value=_mock_chat_response(
        "mistralai/mistral-small-2603", {"patches": []},
    ))

    _patches, _raw, model_used, _cost = asyncio.run(
        final_reviewer.review_paper(
            "paper", {"receipts": []}, {"p1_pass": True},
            api_key="test-key", client=client,
        )
    )

    assert model_used == "mistralai/mistral-small-2603"
    assert client.post.call_args.args[0] == "https://router.example/v1/chat/completions"
    assert client.post.call_args.kwargs["json"]["model"] == model_used


def test_every_configured_reviewer_model_is_priced() -> None:
    """A model swap must fail here, not at exit 7 after a paper is rendered.

    _estimate_cost raises on unpriced models by design (cost must never silently
    read zero), but that fires mid-run once the paper is already written and paid
    for. Enumerating the config defaults keeps the blast radius in CI.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from agent.settings import load_settings

    settings = load_settings()
    configured = {
        settings.judge_model,
        settings.fallback_model,
        settings.final_layer_reviewer_model,
        final_reviewer._DEFAULT_REVIEWER_MODEL,
        final_reviewer._DEFAULT_FALLBACK_MODEL,
    }
    unpriced = sorted(configured - set(final_reviewer._PRICING_PER_MTOK))
    assert not unpriced, f"add pricing to _PRICING_PER_MTOK for: {unpriced}"
