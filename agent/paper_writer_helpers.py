from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.synthesis_schemas import SynthesisSection

logger = logging.getLogger(__name__)


# Per-LLM-call timeout: MiMo 180s plus fallback headroom.
PER_CALL_TIMEOUT_SEC = 240.0
SECTION_TIMEOUT_RETRIES = 1

_RENDERED_CITED_RE = re.compile(
    r"(?m)^[ \t]*_Cited:\s*`[^`\n]+`(?:\s*,\s*`[^`\n]+`)*_[ \t]*\n?"
)


async def call_llm_section(
    *,
    system_prompt: str,
    user_prompt: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
) -> dict | None:
    for attempt in range(SECTION_TIMEOUT_RETRIES + 1):
        try:
            response = await asyncio.wait_for(
                chat_json(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    chain=chain,
                    client=client,
                    ledger=ledger,
                    temperature=0.5,
                    seed=seed,
                ),
                timeout=PER_CALL_TIMEOUT_SEC,
            )
            break
        except asyncio.TimeoutError:
            if attempt < SECTION_TIMEOUT_RETRIES:
                logger.warning(
                    "paper_writer LLM call exceeded %.0fs timeout — retrying once",
                    PER_CALL_TIMEOUT_SEC,
                )
                continue
            logger.warning(
                "paper_writer LLM call exceeded %.0fs timeout — moving on",
                PER_CALL_TIMEOUT_SEC,
            )
            return None
    if isinstance(response.parsed, dict):
        return response.parsed
    return None


def section_word_count(section: SynthesisSection) -> int:
    """Count a section body the way journal_surface_gate will.

    The writer retries a section until this count clears SECTION_WORD_FLOORS,
    but it used to count `body.split()` over text still carrying the
    per-paragraph "_Cited: `id`_" markers the builder appends. The gate counts
    \\b\\w+\\b over full_paper.md, i.e. AFTER render strips those markers.

    Measured on a live run: the writer saw 964 words and stopped retrying; the
    gate then saw 680 against an 850 floor and failed the manuscript. No content
    was lost -- the writer was satisfied by text the gate never sees. Counting
    the same text by the same rule makes the retry loop optimise the number that
    is actually enforced.
    """
    lines = section.body_md.split("\n")
    body = "\n".join(lines[1:]) if lines else ""
    return len(re.findall(r"\b\w+\b", strip_rendered_citation_markers(body)))


def strip_rendered_citation_markers(markdown: str) -> str:
    return _RENDERED_CITED_RE.sub("", markdown)


def build_retry_prompt(
    base_user_prompt: str,
    *,
    section_name: str,
    target_floor: int,
    last_word_count: int,
) -> str:
    return (
        base_user_prompt
        + f"\n\nRETRY GUIDANCE: the previous attempt at the "
        f"{section_name.upper()} section produced only {last_word_count} "
        f"words. The minimum word count is {target_floor}. "
        f"Re-write the section now with at least {target_floor} words "
        f"of substantive prose. Concretely: produce more paragraphs, "
        f"and make each paragraph longer (8-12 sentences each instead "
        f"of 3-5). Do NOT default to summary mode. The reader needs "
        f"the full publishable density.\n"
        f"CRITICAL: every numeric value you write must appear verbatim in "
        f"the sources given above. Any number that does not is dropped along "
        f"with the whole paragraph containing it, which is why the previous "
        f"attempt came back short. If you cannot source a figure, describe "
        f"the finding in words instead of inventing a value. Longer prose "
        f"with no new numbers beats precise-looking prose that is discarded."
    )


__all__ = [
    "PER_CALL_TIMEOUT_SEC",
    "SECTION_TIMEOUT_RETRIES",
    "build_retry_prompt",
    "call_llm_section",
    "section_word_count",
    "strip_rendered_citation_markers",
]
