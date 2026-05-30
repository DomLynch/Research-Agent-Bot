"""LLM coverage judge: verify each enumerated Researka revision ask is
MATERIALLY addressed in the rendered paper before submit.

Uses the SPAR judge chain (Gemma primary — a different model family than the
MiMo writer, per the judge!=writer rule). Fail-open: any judge/infra error or
a malformed verdict returns no unmet asks, so an LLM outage can never block the
whole submission pipeline. Topic-agnostic — the asks come verbatim from
Researka; no per-topic knowledge.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent.llm_client import LLMError, LLMResponse, build_judge_chain, chat_json
from agent.settings import load_settings

_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_USER = (
    "Below are {n} required revisions and a manuscript. For EACH revision, in "
    "order, decide whether the manuscript MATERIALLY addresses it — a substantive "
    "change, not merely repeating the words. Reply with JSON "
    '{{"addressed": [<one boolean per revision, in the same order>]}}.\n\n'
    "REQUIRED REVISIONS:\n{asks}\n\n=== MANUSCRIPT ===\n{paper}"
)


def _excerpt(paper_md: str, head: int = 16000, tail: int = 8000) -> str:
    """Head + tail of the paper so the judge sees both the abstract/intro and
    the conclusion/limitations — where reviewer asks concentrate — without
    paying for the full ~50k-word body."""
    if len(paper_md) <= head + tail:
        return paper_md
    return f"{paper_md[:head]}\n\n[... middle omitted ...]\n\n{paper_md[-tail:]}"


def unmet_asks(
    paper_md: str,
    asks: Sequence[str],
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Return the asks NOT materially addressed by the paper. Empty when every
    ask is met — or fail-open ([]) on any error or malformed verdict."""
    clean = [a.strip() for a in asks if a and a.strip()]
    if not clean:
        return []
    try:
        numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(clean, 1))
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": _USER.format(n=len(clean), asks=numbered, paper=_excerpt(paper_md))},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        flags = resp.parsed.get("addressed", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open — never block submit on a judge/infra failure
    if not isinstance(flags, list) or len(flags) != len(clean):
        return []  # malformed verdict — fail-open
    return [a for a, ok in zip(clean, flags, strict=True) if not ok]
