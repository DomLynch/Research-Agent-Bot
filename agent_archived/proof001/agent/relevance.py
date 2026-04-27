"""LLM relevance pre-filter — three-tier fallback chain.

Tier 1: MiMo 2.5 Pro            (primary; same model the writer uses)
Tier 2: Gemma 4 via OpenRouter   (semantic-judgment second opinion)
Tier 3: Mistral Small via OpenRouter (last-resort fallback)

Single batch call per tier — never re-runs once a tier returned a usable
classification. Returns None when no tier produces output, in which case
the caller keeps the deterministic direct flag (graceful skip).

Per ref the LLM emits one of:
  core       — direct human evidence on the question
  background — mechanistic / preclinical / general-context paper
  excluded   — wrong condition / population / outcome

Caller maps:
  excluded -> direct=False, strict=False (forced out of writer top-N)
  core     -> direct=True (overrides regex if too strict)
  background or unclassified -> deterministic value preserved
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Literal

import httpx

from agent.llm import openai_chat_json
from agent.settings import Settings
from agent.types import EvidenceItem

logger = logging.getLogger(__name__)

Relevance = Literal["core", "background", "excluded"]
_VALID = {"core", "background", "excluded"}
_MIN_COVERAGE = 0.5  # accept tier output if it classified >= half the bundle

SYSTEM_PROMPT = """You classify research sources by relevance to ONE question.

Output ONE label per source:
  core       — direct HUMAN evidence on the question (RCT, observational
               cohort, systematic review or meta-analysis on the right
               population AND outcome). Posted-results trials count.
  background — mechanistic / preclinical / animal / cell-line / pure
               pharmacokinetics / general drug-mechanism review without
               aging or longevity framing
  excluded   — different clinical condition (PCOS for an aging question,
               cancer for a longevity question, pediatric for older-adult
               questions), wrong population, wrong outcome, or
               formulation / tablet-swallowing / pharmacokinetic studies

Strict rules:
- Animal studies (mice, rats, primates, monkeys, cynomolgus) are NEVER
  core, even if the title mentions 'aging'. They are background.
- Cancer therapy papers are EXCLUDED for longevity questions unless the
  question is specifically cancer-aging.
- Pediatric/adolescent papers are EXCLUDED for older-adult questions.
- Mechanism reviews are background unless they synthesize HUMAN evidence
  on the specific outcome.

Output exactly ONE JSON object:
  {"classifications": {"<ref>": "core|background|excluded", ...}}
Cover every ref."""


def _build_user_prompt(items: list[EvidenceItem], topic: str, domain: str) -> str:
    lines = [
        f"[{it.source.ref}] role={it.role} year={it.source.year} "
        f"src={it.source.source}: {it.source.title[:140]}\n"
        f"  abstract: {(it.abstract or '')[:280]}"
        for it in items
    ]
    return (
        f"Question: synthesis of '{topic}' in domain '{domain}'.\n\n"
        f"Bundle ({len(items)} sources). Classify each ref:\n"
        + "\n".join(lines)
    )


def _parse(payload: dict) -> dict[int, Relevance]:
    raw = payload.get("classifications") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, Relevance] = {}
    for k, v in raw.items():
        try:
            ref = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, str) and v in _VALID:
            out[ref] = v  # type: ignore[assignment]
    return out


async def _try_one(
    *, client: httpx.AsyncClient, base_url: str, api_key: str, model: str,
    messages: list[dict[str, str]], timeout: float,
) -> dict[int, Relevance] | None:
    """One LLM attempt. Returns None on transport/parse error."""
    try:
        parsed, _ = await openai_chat_json(
            client=client, base_url=base_url, api_key=api_key, model=model,
            messages=messages, timeout=timeout, max_tokens=2000,
        )
        return _parse(parsed)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("relevance %s failed: %s", model, type(exc).__name__)
        return None


async def classify_relevance(
    items: list[EvidenceItem],
    topic: str,
    domain: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> dict[int, Relevance] | None:
    """Three-tier classifier. None if every tier fails or no API keys set."""
    if not items:
        return None
    if not settings.mimo_api_key and not settings.openrouter_api_key:
        return None

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(items, topic, domain)},
    ]
    needed = max(1, int(len(items) * _MIN_COVERAGE))

    tiers: list[tuple[str, str, str]] = []
    if settings.mimo_api_key:
        tiers.append(("mimo", settings.mimo_base_url, settings.mimo_api_key))
    if settings.openrouter_api_key:
        tiers.append(("gemma", settings.openrouter_base_url, settings.openrouter_api_key))
        tiers.append(("mistral", settings.openrouter_base_url, settings.openrouter_api_key))
    tier_models = {
        "mimo": settings.mimo_model,
        "gemma": settings.judge_model,
        "mistral": settings.fallback_model,
    }

    own = client is None
    c = client or httpx.AsyncClient(timeout=settings.mimo_timeout_sec)
    try:
        for slot, base, key in tiers:
            result = await _try_one(
                client=c, base_url=base, api_key=key,
                model=tier_models[slot], messages=messages,
                timeout=settings.mimo_timeout_sec,
            )
            if result and len(result) >= needed:
                logger.info(
                    "relevance %s classified %d/%d", slot, len(result), len(items),
                )
                return result
        return None
    finally:
        if own:
            await c.aclose()


def apply_classifications(
    items: list[EvidenceItem],
    classifications: dict[int, Relevance],
) -> list[EvidenceItem]:
    """Override direct based on LLM verdict; preserve deterministic value otherwise."""
    out: list[EvidenceItem] = []
    for it in items:
        rel = classifications.get(it.source.ref)
        if rel == "excluded":
            out.append(replace(it, direct=False, strict=False))
        elif rel == "core":
            out.append(replace(it, direct=True))
        else:
            out.append(it)
    return out
