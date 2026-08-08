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
