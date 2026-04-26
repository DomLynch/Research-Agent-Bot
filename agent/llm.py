"""MiMo writer + shared OpenAI-compatible chat helper.

The LLM never decides role / citation / numeric facts. The bundle is the
ground truth and the prompt forbids contradicting it. QA validates the
output against bundle invariants. If QA rejects, draft.py re-calls write_draft
with a `correction=...` argument that appends the failure as a user message.

If MiMo errors (timeout, 5xx, malformed JSON), the writer falls back to
the OpenRouter shared model (Ministral by default) when OPENROUTER_API_KEY
is set. This is the same helper that judge.py uses for Gemma + its fallback.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent.bundle import DEFAULT_WRITER_BUDGET, rank_for_writer
from agent.settings import Settings
from agent.types import EvidenceItem

PROMPT_VERSION = "research-agent-v1/2026-04-26"

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Pricing for cost estimation (MiMo 2.5 Pro, USD per 1K tokens).
_INPUT_PRICE_PER_1K = 0.00014
_OUTPUT_PRICE_PER_1K = 0.00028

logger = logging.getLogger(__name__)

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

Evidence hierarchy
- LEAD the synthesis with refs marked direct=true. Those are the studies
  that actually answer the question.
- Treat refs marked direct=false as BACKGROUND ONLY — useful for mechanism
  or related-context, never as evidence FOR the question. Do not let them
  carry the headline finding.
- If direct evidence is thin, say so explicitly in the Findings/Limitations
  sections. Do NOT pad with background to compensate.
- For role=registered_pending and role=published_protocol, describe as
  pending/in-progress; never frame as published efficacy.

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
    """Build the writer prompt from the top-N ranked subset of the bundle.

    The full bundle still flows to render (evidence table + bibliography);
    the LLM sees only the strongest evidence so it doesn't drown in old
    mechanistic noise. Top-N truncation is bundle.rank_for_writer's job.
    """
    ranked = rank_for_writer(items, n=DEFAULT_WRITER_BUDGET)
    return USER_PROMPT_TEMPLATE.format(
        topic=topic,
        domain=domain,
        criteria=criteria,
        n_sources=len(ranked),
        bundle_block="\n".join(_format_item(it) for it in ranked),
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


async def openai_chat_json(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 60.0,
    max_tokens: int | None = None,
    enforce_json: bool = True,
    temperature: float = 0.2,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Generic OpenAI-compatible chat-completion call returning JSON content.

    Both MiMo (writer) and OpenRouter (judge + fallbacks) speak this protocol.
    `enforce_json=False` drops `response_format: json_object` from the request
    — required for OpenRouter models that don't list it as supported (e.g.
    google/gemma-4-31b-it). The prompt + extract_json handle robust JSON
    recovery from prose/fence-wrapped output, so this is safe.

    Returns (parsed_json, raw_usage_dict).
    """
    if not api_key:
        raise RuntimeError(f"missing api_key for model={model}")
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    if enforce_json:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"
    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]["message"]
    text = choice.get("content") or choice.get("reasoning_content") or "{}"
    parsed = extract_json(text)
    usage = body.get("usage", {}) or {}
    return parsed, {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
    }


async def write_draft(
    items: list[EvidenceItem],
    topic: str,
    domain: str,
    criteria: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
    correction: str | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], WriterUsage]:
    """Call MiMo. Falls back to OpenRouter (Ministral) on transport/parse error
    when OPENROUTER_API_KEY is set. Returns (parsed_json, usage).

    `correction` appends a user message instructing a fix.
    `previous_draft` (when retrying) is the rejected draft — included verbatim
    so the LLM can edit surgically rather than rewrite from scratch with the
    same prior-knowledge biases (which is why HR 0.54 etc. kept appearing
    on retries even after the failure was reported).
    """
    if not settings.mimo_api_key and not settings.openrouter_api_key:
        raise RuntimeError("MIMO_API_KEY (or OPENROUTER_API_KEY for fallback) required")

    user_prompt = _build_user_prompt(items, topic, domain, criteria)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    if correction:
        prior = (
            "Previous draft (edit surgically — do NOT rewrite from scratch):\n"
            f"{json.dumps(previous_draft, indent=2, ensure_ascii=False)}\n\n"
            if previous_draft else ""
        )
        messages.append({
            "role": "user",
            "content": (
                "Your previous draft was REJECTED. Issues:\n"
                f"{correction}\n\n"
                f"{prior}"
                "Editing rules:\n"
                "- For [number_not_in_source]: REMOVE the invented number from "
                "the sentence and replace with qualitative language: "
                "'an effect was reported', 'a benefit was observed', "
                "'no significant effect was found'. Do NOT substitute another "
                "number unless you can quote it verbatim from the cited abstract.\n"
                "- For [protocol_described_as_results] / "
                "[results_described_as_pending]: rewrite the sentence to match "
                "the ref's role from the bundle.\n"
                "- For [citation_unresolved]: use only refs that exist in the bundle.\n"
                "- Keep every UNFLAGGED sentence and citation unchanged.\n"
                "- Return the same JSON shape, fully corrected."
            ),
        })

    # Lower temperature on the correction retry — the failure mode is the
    # LLM pulling numbers from prior knowledge ("HR 0.54"), and 0.2 still
    # leaves room for that variability. 0.05 keeps the retry close to the
    # prior draft modulo the flagged edits.
    temperature = 0.05 if correction else 0.2

    own_client = client is None
    c = client or httpx.AsyncClient(timeout=settings.mimo_timeout_sec)
    try:
        # Primary: MiMo
        if settings.mimo_api_key:
            try:
                parsed, raw_usage = await openai_chat_json(
                    client=c,
                    base_url=settings.mimo_base_url,
                    api_key=settings.mimo_api_key,
                    model=settings.mimo_model,
                    messages=messages,
                    timeout=settings.mimo_timeout_sec,
                    temperature=temperature,
                )
                return parsed, _usage(raw_usage, settings.mimo_model)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                if not settings.openrouter_api_key:
                    raise
                logger.warning(
                    "writer primary %s failed (%s: %s); falling back to %s",
                    settings.mimo_model, type(exc).__name__, exc, settings.fallback_model,
                )
        # Fallback: OpenRouter shared model (Ministral)
        parsed, raw_usage = await openai_chat_json(
            client=c,
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.fallback_model,
            messages=messages,
            timeout=settings.mimo_timeout_sec,
            temperature=temperature,
        )
        return parsed, _usage(raw_usage, settings.fallback_model)
    finally:
        if own_client:
            await c.aclose()


def _usage(raw: dict[str, int], model: str) -> WriterUsage:
    in_tok = int(raw.get("input_tokens", 0))
    out_tok = int(raw.get("output_tokens", 0))
    return WriterUsage(
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=(
            in_tok / 1000 * _INPUT_PRICE_PER_1K
            + out_tok / 1000 * _OUTPUT_PRICE_PER_1K
        ),
        model=model,
        prompt_version=PROMPT_VERSION,
    )
