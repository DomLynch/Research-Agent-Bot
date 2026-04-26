"""MiMo writer — takes a typed bundle, returns structured draft JSON.

The LLM never decides role / citation / numeric facts. The bundle is the
ground truth and the prompt forbids contradicting it. QA validates the
output against bundle invariants. If QA rejects, draft.py re-calls write_draft
with a `correction=...` argument that appends the failure as a user message.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent.settings import Settings
from agent.types import EvidenceItem

PROMPT_VERSION = "research-agent-v1/2026-04-26"

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Pricing for cost estimation (MiMo 2.5 Pro, USD per 1K tokens).
_INPUT_PRICE_PER_1K = 0.00014
_OUTPUT_PRICE_PER_1K = 0.00028

SYSTEM_PROMPT = """You are a research-paper drafter for a peer-review-adjacent
publication system. Strict rules — violation produces a rejected draft.

Citations
- Every factual claim must end with a citation [N] where N is a source ref
  from the provided bundle.
- You MUST NOT invent citation refs. Use only [N] for refs that appear in the bundle.
- You MUST NOT add citations beyond the bundle.

Roles (the bundle tells you each source's role; do not contradict it)
- role=published_results: a study with reported outcomes — describe them.
- role=published_protocol or registered_pending: a registered trial without
  reported outcomes. NEVER write 'showed', 'demonstrated', 'reduced',
  'improved' for these refs. Describe them as upcoming/pending.
- role=review: a literature synthesis — attribute pooled findings to the
  review, not to a single trial.
- role=mechanistic: preclinical (cell/animal). Hedge any human-relevance
  claim explicitly. Tier C evidence cannot carry a headline efficacy claim.

Numbers
- You MUST NOT invent effect sizes, p-values, confidence intervals, sample
  sizes, or follow-up durations. Only quote numbers that appear in the cited
  source's abstract.
- If no numeric effect is in the abstract, state qualitatively only ('an
  improvement in X was reported').

Output: exactly ONE JSON object. No prose outside the JSON. No markdown fences."""

USER_PROMPT_TEMPLATE = """Topic: {topic}
Domain: {domain}
Criteria: {criteria}

Bundle ({n_sources} sources, sorted by direct/tier):
{bundle_block}

Produce a research-grade draft as a JSON object with this exact shape:
{{
  "title": "Concise paper title (under 140 chars)",
  "abstract": ["3-6 cited sentences"],
  "sections": {{
    "introduction": ["sentences with [N] cites"],
    "methods": ["how this review was conducted; sources covered; year window if any"],
    "findings": ["substance — synthesize what direct/published_results sources show"],
    "limitations": ["honest gaps: indirect-only sources, small samples, missing populations"],
    "conclusion": ["calibrated takeaway given the evidence quality"]
  }}
}}
"""


@dataclass(frozen=True, slots=True)
class WriterUsage:
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    model: str
    prompt_version: str


def _format_item(item: EvidenceItem) -> str:
    s = item.source
    abstract = (item.abstract or "")[:1200]
    venue = f" venue={s.venue!r}" if s.venue else ""
    return (
        f"[{s.ref}] role={item.role} design={item.design} tier={item.tier} "
        f"direct={item.direct} year={s.year}{venue}\n"
        f"    title: {s.title}\n"
        f"    abstract: {abstract}\n"
    )


def _build_user_prompt(
    items: list[EvidenceItem], topic: str, domain: str, criteria: str
) -> str:
    tier_order = {"A1": 0, "A2": 1, "B": 2, "C": 3}
    sorted_items = sorted(
        items,
        key=lambda it: (not it.direct, tier_order.get(it.tier, 9), it.source.ref),
    )
    return USER_PROMPT_TEMPLATE.format(
        topic=topic,
        domain=domain,
        criteria=criteria,
        n_sources=len(items),
        bundle_block="\n".join(_format_item(it) for it in sorted_items),
    )


def _strip(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.search(cleaned)
    return fence.group(1).strip() if fence else cleaned


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first valid JSON object out of an LLM response."""
    cleaned = _strip(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            obj, _ = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("LLM response contained no JSON object")


async def write_draft(
    items: list[EvidenceItem],
    topic: str,
    domain: str,
    criteria: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
    correction: str | None = None,
) -> tuple[dict[str, Any], WriterUsage]:
    """Call MiMo. Returns (parsed_json, usage).

    `correction` appends a user message instructing a fix — used by draft.py
    on QA-rejection retry.
    """
    if not settings.mimo_api_key:
        raise RuntimeError("MIMO_API_KEY is not set")

    user_prompt = _build_user_prompt(items, topic, domain, criteria)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    if correction:
        messages.append({
            "role": "user",
            "content": f"REJECTED. Fix: {correction}\nReturn the same JSON shape, corrected.",
        })

    body_payload = {
        "model": settings.mimo_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {settings.mimo_api_key}",
        "Content-Type": "application/json",
    }
    url = settings.mimo_base_url.rstrip("/") + "/chat/completions"

    own_client = client is None
    c = client or httpx.AsyncClient(timeout=settings.mimo_timeout_sec)
    try:
        response = await c.post(url, json=body_payload, headers=headers)
        response.raise_for_status()
        body = response.json()
    finally:
        if own_client:
            await c.aclose()

    choice = body["choices"][0]["message"]
    text = choice.get("content") or choice.get("reasoning_content") or "{}"
    parsed = extract_json(text)

    usage_raw = body.get("usage", {}) or {}
    in_tok = int(usage_raw.get("prompt_tokens", 0) or 0)
    out_tok = int(usage_raw.get("completion_tokens", 0) or 0)
    usage = WriterUsage(
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=(
            in_tok / 1000 * _INPUT_PRICE_PER_1K
            + out_tok / 1000 * _OUTPUT_PRICE_PER_1K
        ),
        model=settings.mimo_model,
        prompt_version=PROMPT_VERSION,
    )
    return parsed, usage
