"""Small writer-loop helpers extracted from agent/paper_writer.py.

Three utilities used by every per-section render path:

  call_llm_section      one timed JSON LLM call (returns parsed dict
                        or None on timeout/malformed)
  section_word_count    body word count (excluding heading line)
  build_retry_prompt    appends an explicit "you under-produced; floor
                        is N" guidance block when a retry is needed

Extracted to honor the 600 LOC per-file hard cap in agent/. No new
behaviour — just a relocation."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.synthesis_schemas import SynthesisSection

logger = logging.getLogger(__name__)


# Per-LLM-call timeout. If a single section call (including chain
# fallback to Ministral) takes longer than this, treat it as a hang
# and let the retry loop move on. 240s = MiMo full 180s budget plus
# ~60s headroom for a Ministral fallback round-trip.
PER_CALL_TIMEOUT_SEC = 240.0


async def call_llm_section(
    *,
    system_prompt: str,
    user_prompt: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
) -> dict | None:
    """One LLM call returning a parsed JSON dict (or None if malformed
    or timed out). Per-call timeout enforced via asyncio.wait_for."""
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
                temperature=0.0,
                seed=seed,
            ),
            timeout=PER_CALL_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "paper_writer LLM call exceeded %.0fs timeout — moving on",
            PER_CALL_TIMEOUT_SEC,
        )
        return None
    if isinstance(response.parsed, dict):
        return response.parsed
    return None


def section_word_count(section: SynthesisSection) -> int:
    """Count words in the section body, excluding the heading line."""
    lines = section.body_md.split("\n")
    body = "\n".join(lines[1:]) if lines else ""
    return len(body.split())


def build_retry_prompt(
    base_user_prompt: str,
    *,
    section_name: str,
    target_floor: int,
    last_word_count: int,
) -> str:
    """Append explicit retry guidance when a section under-produced.

    Empirically, LLMs default to concise output even when prompts
    request length. A retry that names the under-production and the
    floor is much more likely to hit the target than a fresh call."""
    return (
        base_user_prompt
        + f"\n\nRETRY GUIDANCE: the previous attempt at the "
        f"{section_name.upper()} section produced only {last_word_count} "
        f"words. The minimum word count is {target_floor}. "
        f"Re-write the section now with at least {target_floor} words "
        f"of substantive prose. Concretely: produce more paragraphs, "
        f"and make each paragraph longer (8-12 sentences each instead "
        f"of 3-5). Do NOT default to summary mode. The reader needs "
        f"the full publishable density."
    )


__all__ = [
    "PER_CALL_TIMEOUT_SEC",
    "build_retry_prompt",
    "call_llm_section",
    "section_word_count",
]
