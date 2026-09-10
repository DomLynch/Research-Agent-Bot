from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.journal_surface_gate import _SECTION_CEILINGS
from agent.synthesis_schemas import SynthesisSection
from agent.paper_writer_prompts import PUBLICATION_REQUIREMENTS

logger = logging.getLogger(__name__)


# Minimum wrapper budget; allow the configured provider call to finish first.
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
    timeout = max(PER_CALL_TIMEOUT_SEC, max((spec.timeout_sec for spec in chain), default=0) + 60)
    for attempt in range(SECTION_TIMEOUT_RETRIES + 1):
        try:
            response = await asyncio.wait_for(
                chat_json(
                    messages=[
                        {"role": "system", "content": PUBLICATION_REQUIREMENTS + "\n" + system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    chain=chain,
                    client=client,
                    ledger=ledger,
                    temperature=0.5,
                    seed=seed,
                ),
                timeout=timeout,
            )
            break
        except asyncio.TimeoutError:
            if attempt < SECTION_TIMEOUT_RETRIES:
                logger.warning(
                    "paper_writer LLM call exceeded %.0fs timeout — retrying once",
                    timeout,
                )
                continue
            logger.warning(
                "paper_writer LLM call exceeded %.0fs timeout — moving on",
                timeout,
            )
            return None
    return response.parsed if isinstance(response.parsed, dict) else None


def section_word_count(section: SynthesisSection) -> int:
    """Count rendered body words exactly as the surface gate does.

    Exclude the heading and internal citation metadata from the retry target.
    """
    lines = section.body_md.split("\n")
    body = "\n".join(lines[1:]) if lines else ""
    return len(re.findall(r"\b\w+\b", strip_rendered_citation_markers(body)))


def strip_rendered_citation_markers(markdown: str) -> str:
    return _RENDERED_CITED_RE.sub("", markdown)


def log_section_done(name: str, section: SynthesisSection) -> None:
    print(f"[paper_writer] {name:25} done - {section_word_count(section)} words", flush=True)


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
        f"of substantive prose. Add evidence-grounded paragraphs; do not "
        f"stretch one paragraph across sources. Every empirical sentence "
        f"must include an exact accepted receipt_id inline and list it in "
        f"receipt_ids; split when support differs. Preserve the section's JSON schema "
        f"and qualitative-only rules. Numeric values must appear verbatim in the sources "
        f"cited for that sentence. Describe supported findings qualitatively instead of inventing "
        f"numbers. Never invent evidence to meet a word target."
    )


def ceiling_retry_prompt(base: str, heading: str, words: int, floor: int) -> str | None:
    ceiling = _SECTION_CEILINGS.get(heading.removeprefix("## "))
    if ceiling is None or words <= ceiling:
        return None
    return (
        f"{base}\n\nLENGTH RETRY REQUIRED: {heading} had {words} words. "
        f"Write {floor}-{ceiling} words, preserving supported findings, citations "
        "and qualifications. Remove repetition, not evidence. Keep the JSON schema."
    )


__all__ = [
    "PER_CALL_TIMEOUT_SEC",
    "SECTION_TIMEOUT_RETRIES",
    "build_retry_prompt",
    "call_llm_section",
    "section_word_count",
    "strip_rendered_citation_markers",
]
