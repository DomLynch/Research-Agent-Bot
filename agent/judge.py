"""Optional second-pass Judge (Gemma 4 via OpenRouter, Ministral fallback).

Runs ONLY after qa.qa() approves the draft. The Judge reads the structured
candidate JSON + the typed bundle and returns a verdict:
  approved=True    -> ship as-is
  approved=False + revision_notes -> draft.py triggers ONE writer revision
                                     pass with those notes, then re-QAs
                                     (no second judge call — bounded cost).

Material-only filter: cosmetic / wording / formatting nits are dropped, so
the Judge never blocks on style. This mirrors the legacy Spar non-material
filter and keeps the pattern faithful to its original intent.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from agent.llm import openai_chat_json
from agent.settings import Settings
from agent.types import EvidenceItem

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "research-agent-v1/judge-2026-04-26"

JUDGE_SYSTEM_PROMPT = """You are the Judge for a research-paper drafting system.
Your job: review a candidate draft for MATERIAL correctness against the
typed evidence bundle.

APPROVE if the draft:
  - Cites only refs from the bundle.
  - Describes each ref consistently with its declared role
    (results vs protocol vs review vs mechanistic).
  - Makes no headline efficacy claim from Tier C / mechanistic refs.
  - Quotes effect-size numbers that appear in the cited abstract.
  - Has a calibrated conclusion given the evidence quality.

REJECT only for material problems:
  - Over-claims, hallucinated effects, role/protocol contradictions,
    missed direct evidence, biased framing.

DO NOT reject for: wording, phrasing, naming, formatting, readability,
style, length, organization preferences.

Output ONE JSON object:
  {"approved": bool, "score": 1-10, "summary": "...",
   "blocking_issues": ["..."], "revision_notes": "..." }
- score: 1=ship-blocker, 10=publishable as-is.
- blocking_issues: short list of MATERIAL problems. Empty if approved.
- revision_notes: concrete instruction for the writer if approved=false.
                   Empty string if approved=true.
"""

# Cosmetic / non-material critique patterns — filtered out before deciding.
_NON_MATERIAL = re.compile(
    r"\b(naming|wording|phrasing|format(?:ting)?|style|readability|cosmetic|"
    r"nit(?:pick)?|comment|rename|sentence\s+structure|tone|prose\s+quality)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    approved: bool
    score: int
    summary: str
    blocking_issues: tuple[str, ...]
    revision_notes: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


_INPUT_PRICE_PER_1K = 0.00020   # rough OpenRouter pricing
_OUTPUT_PRICE_PER_1K = 0.00060


def _build_user_prompt(
    candidate: dict, items: list[EvidenceItem], topic: str, domain: str
) -> str:
    bundle_lines = [
        f"[{it.source.ref}] role={it.role} tier={it.tier} design={it.design} "
        f"direct={it.direct} year={it.source.year}: {it.source.title[:120]}"
        for it in items
    ]
    return (
        f"Topic: {topic}\nDomain: {domain}\n\n"
        "Evidence bundle:\n" + "\n".join(bundle_lines) + "\n\n"
        "Candidate draft (JSON):\n"
        + json.dumps(candidate, indent=2, ensure_ascii=False)
    )


def _filter_material(issues: list[str]) -> list[str]:
    return [i for i in issues if i.strip() and not _NON_MATERIAL.search(i)]


def _parse(payload: dict, model: str, raw_usage: dict[str, int]) -> JudgeVerdict:
    raw_issues = payload.get("blocking_issues") or []
    if isinstance(raw_issues, str):
        raw_issues = [raw_issues]
    issues = _filter_material([str(i) for i in raw_issues])
    revision_notes = str(payload.get("revision_notes") or "").strip()
    if revision_notes and _NON_MATERIAL.search(revision_notes):
        revision_notes = ""
    approved_raw = bool(payload.get("approved", False))
    # If the Judge said reject but every blocking_issue was filtered as
    # non-material, treat as approved.
    approved = approved_raw or (not issues and not revision_notes)
    in_tok = raw_usage.get("input_tokens", 0)
    out_tok = raw_usage.get("output_tokens", 0)
    return JudgeVerdict(
        approved=approved,
        score=int(payload.get("score") or (10 if approved else 5)),
        summary=str(payload.get("summary") or "").strip(),
        blocking_issues=tuple(issues),
        revision_notes=revision_notes if not approved else "",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=(
            in_tok / 1000 * _INPUT_PRICE_PER_1K
            + out_tok / 1000 * _OUTPUT_PRICE_PER_1K
        ),
    )


async def judge_draft(
    candidate: dict,
    items: list[EvidenceItem],
    topic: str,
    domain: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> JudgeVerdict | None:
    """Run the Judge. Returns None if OPENROUTER_API_KEY is missing
    (graceful degrade — caller treats as 'no opinion, ship as-is').

    Tries primary (Gemma 4); on transport/parse error, falls back to
    settings.fallback_model (Ministral).
    """
    if not settings.openrouter_api_key:
        logger.warning("judge skipped: OPENROUTER_API_KEY not set")
        return None

    user = _build_user_prompt(candidate, items, topic, domain)
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=settings.mimo_timeout_sec)
    try:
        for slot, model in (("primary", settings.judge_model),
                            ("fallback", settings.fallback_model)):
            try:
                parsed, raw_usage = await openai_chat_json(
                    client=c,
                    base_url=settings.openrouter_base_url,
                    api_key=settings.openrouter_api_key,
                    model=model,
                    messages=messages,
                    timeout=settings.mimo_timeout_sec,
                    max_tokens=1200,
                )
                return _parse(parsed, model, raw_usage)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                if slot == "primary":
                    logger.warning(
                        "judge primary %s failed (%s); falling back to %s",
                        model, type(exc).__name__, settings.fallback_model,
                    )
                    continue
                logger.warning("judge fallback %s also failed (%s); skipping", model, exc)
                return None
        return None
    finally:
        if own_client:
            await c.aclose()
