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

JUDGE_SYSTEM_PROMPT = """You are the Judge — second-layer quality control for
a research-paper drafting system. Be HYPER-CRITICAL. A lenient judge is
worse than no judge — it creates false confidence and lets hallucinations
ship to publication.

For EVERY citation [N] in the draft:
  1. Cross-reference the cited claim against the source's title and
     abstract in the bundle.
  2. If the claim is not directly supported by the cited abstract, flag
     it as a hallucination — even if the claim is plausible or true in
     general medical knowledge.
  3. Verify the source's role matches the prose (a 'published_protocol'
     can't be described as having reported outcomes; a 'mechanistic'
     primate study can't carry a definitive human efficacy claim).
  4. Verify every numeric effect (HR, OR, RR, %, p-value, n=, CI) appears
     verbatim in the cited abstract. Made-up numbers are a hard reject.
  5. Flag mis-attribution: a draft that says 'ref [X] is a study of Y'
     when [X] is actually about Z is a hallucination, even if Y exists
     somewhere in the bundle under a different ref.

APPROVE only when:
  - Every cited claim is directly supported by the cited abstract
  - Roles and prose are consistent
  - Numeric claims are traceable
  - Conclusion is calibrated to the actual evidence base shown
  - No invented trial names, programs, or studies (e.g. don't introduce
    'TAME' or 'CALERIE' from prior knowledge if not in the bundle)

DO NOT reject for:
  - wording, phrasing, naming, formatting, readability
  - style, length, organization preferences
  - the choice to discuss certain refs over others (that's the writer's call)

Output ONE JSON object:
  {"approved": bool, "score": 1-10, "summary": "...",
   "blocking_issues": ["..."], "revision_notes": "..."}

Scoring:
  10 — publishable as-is, every claim traceable
  8-9 — minor calibration tweaks, no material errors
  6-7 — at least one cited claim not supported by abstract; needs revision
  1-5 — material hallucinations or role/numeric contradictions; reject

blocking_issues: ONE LINE per material problem. Cite the ref and the
specific unsupported claim. Empty list if approved.
revision_notes: concrete instruction for the writer, listing which
sentences to rewrite and how. Empty string if approved.
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
    # Three-tier judge chain. MiMo's 1M context is genuinely useful for
    # source-heavy adjudication; placing it between Gemma and Mistral
    # means a Gemma transport hiccup degrades to a stronger model first,
    # not a weaker one.
    tiers: list[tuple[str, str, str]] = [
        ("gemma", settings.openrouter_base_url, settings.openrouter_api_key),
    ]
    if settings.mimo_api_key:
        tiers.append(("mimo", settings.mimo_base_url, settings.mimo_api_key))
    tiers.append(("mistral", settings.openrouter_base_url, settings.openrouter_api_key))
    tier_models = {
        "gemma": settings.judge_model,
        "mimo": settings.mimo_model,
        "mistral": settings.fallback_model,
    }
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=settings.mimo_timeout_sec)
    try:
        for slot, base, key in tiers:
            model = tier_models[slot]
            try:
                parsed, raw_usage = await openai_chat_json(
                    client=c, base_url=base, api_key=key, model=model,
                    messages=messages, timeout=settings.mimo_timeout_sec,
                    max_tokens=1200,
                )
                return _parse(parsed, model, raw_usage)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning(
                    "judge %s (%s) failed: %s",
                    slot, model, type(exc).__name__,
                )
                continue
        return None
    finally:
        if own_client:
            await c.aclose()
