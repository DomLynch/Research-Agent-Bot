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
import re
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


_CLAIM_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_CLAIM_USER = (
    "Below is a paper's ABSTRACT and the rest of the manuscript. List any abstract "
    "claim the manuscript's own evidence does NOT support, or that overstates it "
    "(too strong / unhedged given mixed or indirect evidence) — the most common "
    "reason an abstract is sent back for revision. Do not list neutral "
    "corpus-composition summaries (evidence-tier counts, outcome-bucket summaries, "
    "or disagreement counts) unless they assert efficacy or causal benefit. Reply with JSON "
    '{{"unsupported": [<verbatim claim>, ...]}} — empty if every abstract claim '
    "is supported and appropriately hedged.\n\n"
    "ABSTRACT:\n{abstract}\n\n=== REST OF MANUSCRIPT ===\n{body}"
)
_PROFILE_SUMMARY_RE = re.compile(
    r"\b("
    r"evidence profile contains|no sources classified primarily as|"
    r"positive (?:study-level )?signals (?:concentrate|concentrated|cluster|are summarized|are represented)|"
    r"no single positive outcome class dominates|"
    r"null signals (?:in|cluster)|negative signals (?:in|cluster)|"
    r"cross-study disagreement"
    r")\b",
    re.I,
)


def _abstract(paper_md: str) -> str:
    m = re.search(r"^##\s+Abstract\b.*?\n(.*?)(?=^##\s)", paper_md, re.M | re.S)
    return m.group(1).strip() if m else ""


def unsupported_abstract_claims(
    paper_md: str,
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Abstract claims the manuscript's evidence does not support / overstates
    (paper-qa contradiction-check borrow). Empty when the abstract is supported,
    or fail-open ([]) on any error/malformed verdict. Bounded: one judge call."""
    abstract = _abstract(paper_md)
    if not abstract:
        return []
    body = paper_md.replace(abstract, "", 1)
    try:
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _CLAIM_SYS},
                {"role": "user", "content": _CLAIM_USER.format(abstract=abstract[:6000], body=body[:18000])},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        claims = resp.parsed.get("unsupported", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open
    if not isinstance(claims, list):
        return []
    return [
        claim for c in claims
        if (claim := str(c).strip()) and not _PROFILE_SUMMARY_RE.search(claim)
    ]
