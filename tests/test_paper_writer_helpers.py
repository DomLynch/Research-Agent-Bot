from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agent import paper_writer_helpers as helpers


@pytest.mark.asyncio
async def test_call_llm_section_retries_one_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_chat_json(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.TimeoutError
        return SimpleNamespace(parsed={"section": "ok"})

    monkeypatch.setattr(helpers, "chat_json", fake_chat_json)

    out = await helpers.call_llm_section(
        system_prompt="sys",
        user_prompt="user",
        chain=(),
        client=None,
        ledger=None,
        seed=None,
    )

    assert out == {"section": "ok"}
    assert calls == 2


@pytest.mark.asyncio
async def test_call_llm_section_returns_none_after_retry_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_chat_json(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        raise asyncio.TimeoutError

    monkeypatch.setattr(helpers, "chat_json", fake_chat_json)

    out = await helpers.call_llm_section(
        system_prompt="sys",
        user_prompt="user",
        chain=(),
        client=None,
        ledger=None,
        seed=None,
    )

    assert out is None
    assert calls == helpers.SECTION_TIMEOUT_RETRIES + 1


def test_retry_prompt_forbids_unsourced_numbers() -> None:
    """The retry must not just ask for MORE prose.

    Asking only for length made each retry emit more invented numerics, every
    paragraph containing one was dropped by the anchor guard, and the section
    came back at zero -- so the retry made the failure worse. Observed live as
    novel_numeric rejections across all 5 cross-domain paragraphs.
    """
    from agent.paper_writer_helpers import build_retry_prompt

    prompt = build_retry_prompt(
        "BASE", section_name="cross_domain_synthesis",
        target_floor=850, last_word_count=14,
    )
    lowered = prompt.lower()
    assert "850" in prompt and "14" in prompt
    assert "must appear verbatim in the sources" in lowered
    assert "instead of inventing" in lowered


def test_unsourced_number_is_dropped_and_the_retry_says_why() -> None:
    """End-to-end: the guard drops the paragraph, the retry names the cause.

    Asking only for length made each retry emit more invented numerics, every
    paragraph carrying one was dropped, and the section returned zero words.
    The guard must still drop them (never weaken it) AND the retry must tell the
    model that is what happened.
    """
    from agent.paper_writer_builders import _accepted_numeric_tokens, _check_anchored_paragraph
    from agent.paper_writer_helpers import build_retry_prompt
    from agent.synthesis_schemas import ReceiptSummary

    receipt = ReceiptSummary(
        receipt_id="r1", receipt_path="/tmp/r1", topic="t",
        thesis_text="The trial reported no change.", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None, evidence_tier="A1",
        directness="direct", outcome_class="cardiometabolic", effect_direction="null",
        p_values=(), population_summary="adults",
    )
    accepted = _accepted_numeric_tokens([receipt])

    # An invented figure must still cost the paragraph.
    ok, reason = _check_anchored_paragraph(
        "Weight fell by 7.4kg.", ["r1"], {"r1"}, accepted,
    )
    assert not ok and "novel_numeric" in reason, reason

    # The same finding stated without a number must survive.
    ok_words, reason_words = _check_anchored_paragraph(
        "Weight fell in the treatment arm.", ["r1"], {"r1"}, accepted,
    )
    assert ok_words, reason_words

    # And the retry must tell the model that is the rule.
    retry = build_retry_prompt(
        "BASE", section_name="cross_domain_synthesis",
        target_floor=850, last_word_count=0,
    ).lower()
    assert "must appear verbatim in the sources" in retry
    assert "instead of inventing" in retry
