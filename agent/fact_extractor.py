"""LLM fact extraction — abstracts → typed Facts. The first LLM in the spine.

Hard rule: LLM PROPOSES. CODE DISPOSES. The LLM never proposes `ref` (pinned
to `item.source.ref`) or `kind` (pinned by `_kind_for_role(item.role)`).
Code disposes via: schema check on `claim`, `validators.check_verb_ban`
(planted case 1's 5th defense), `validators.check_p_value_in_source`
(planted case 3 at extraction time), and within-item dedupe.

`off_domain` items are SKIPPED — no LLM call, no cost. Day 3.4 wraps this
into the run orchestrator with `compile_claims` + `assert_invariants`.
Returns `(accepted_facts, rejections)` so run logs show what was proposed
and why rejections happened.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from agent.llm_client import (
    CallSpec,
    CostLedger,
    LLMError,
    chat_json,
)
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, Fact, FactKind
from agent.validators import PVALUE_RE, check_p_value_in_source, check_verb_ban

# A bare p-value decimal: `0.NNN` or `.NNN`. Matches the (digits) capture
# of `validators.PVALUE_RE` in shape — both must agree on what counts as
# a recognizable p-value or the field-trace can vacuously succeed against
# a malformed proposal ('NS', 'not reported', '0', '1.2', etc.).
_PVALUE_DECIMAL_RE = re.compile(r"^0?\.(\d+)$")

__all__ = [
    "FactRejection",
    "PROMPT_VERSION",
    "build_user_prompt",
    "extract_facts_from_bundle",
    "extract_facts_from_item",
]

logger = logging.getLogger(__name__)

PROMPT_VERSION = "fact-extractor/2026-04-27"

_MAX_CLAIM_LEN = 500


SYSTEM_PROMPT = """You extract structured FACTS from a single research-paper abstract.

You may propose ONLY facts explicitly stated in the abstract. Do NOT
infer, generalize, or import knowledge from outside the abstract.

Output one JSON object with this exact shape:
{
  "facts": [
    {
      "claim": "single declarative sentence paraphrasing the abstract",
      "outcome": "endpoint name like 'lean body mass' or null",
      "estimate": "verbatim effect size like '+5.2 kg' or 'HR 0.79' or null",
      "p_value": "verbatim like '0.003' or '<0.001' or null",
      "ci": "verbatim CI like '0.66-0.95' or null"
    }
  ]
}

Rules:
1. `claim` is REQUIRED — non-empty string under 500 characters. Every
   other field is optional; emit null when the abstract doesn't state it.
2. `p_value`, `estimate`, `ci` must be VERBATIM from the abstract — do
   not reformat or convert units.
3. `claim` must be self-contained — no '[N]' citation brackets.
4. If the abstract describes a PROTOCOL or registered study with NO
   reported outcomes, describe DESIGN only. Never use 'showed',
   'demonstrated', 'reduced', 'improved', 'lowered', 'increased' —
   those imply outcomes the paper has not reported.
5. For REVIEWS, summarize pooled findings; attribute to the review,
   not the underlying trials. For MECHANISTIC / preclinical abstracts,
   describe the mechanism only and do not claim human relevance unless
   the abstract makes that claim itself.

No prose outside the JSON. No markdown fences."""


def build_user_prompt(item: EvidenceItem, topic: str) -> str:
    """Render the user-message body for a given evidence item.

    Public so tests + run logs can inspect the prompt deterministically.
    """
    src = item.source
    venue = f", venue={src.venue!r}" if src.venue else ""
    return (
        f"Topic: {topic}\n\n"
        f"Source [{src.ref}] (role={item.role}, design={item.design}, "
        f"year={src.year}{venue}):\n"
        f"Title: {src.title}\n"
        f"Abstract: {item.abstract}\n\n"
        f"Extract facts about {topic} from this abstract. If the abstract "
        f"is unrelated to {topic}, return an empty facts list."
    )


@dataclass(frozen=True, slots=True)
class FactRejection:
    """A proposal that didn't survive code-disposes. `proposed` is {} for
    non-LLM rejections (empty_abstract, llm_error). `reason` is a
    colon-prefixed code suitable for grouping in the run log."""
    item_ref: int
    proposed: Mapping[str, Any]
    reason: str


# ----- Pinning + validation ----------------------------------------------


def _kind_for_role(role: str) -> FactKind | None:
    """Pin Fact.kind from EvidenceItem.role per types.py invariant.
    None for off_domain (no pairing rule) — caller should skip."""
    if role == "published_results":
        return "result"
    if role in ("published_protocol", "registered_pending"):
        return "protocol"
    if role in ("review", "mechanistic"):
        return "context"
    return None


def _coerce_str_or_none(value: Any) -> str | None:
    """Strings → trimmed string (or None if blank); anything else → None.
    LLMs occasionally emit numbers / JSON null where Fact wants str|None."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _trace_field_in_source(value: str, abstract: str) -> bool:
    """Whitespace-normalized, case-insensitive substring match.

    Used for `estimate` and `ci` — the prompt requires verbatim, but real
    LLMs collapse whitespace inconsistently. Normalize both sides before
    matching so 'HR  0.79' (LLM, double space) traces against 'HR 0.79'
    (abstract). False on miss; True on hit.
    """
    needle = " ".join(value.split()).lower()
    if not needle:
        return True
    haystack = " ".join(abstract.split()).lower()
    return needle in haystack


def _check_p_value_field(p_value: str, abstract: str) -> bool:
    """Verify proposed `p_value` is a real p-value AND traces to abstract.

    Two-stage check (3.2c-fix-2 closes the v1 bypass where only the second
    stage ran):
      1. **Grammar gate:** strip optional leading 'p'/'P' and an optional
         operator (`<`, `>`, `=`). What remains MUST match `0?.NNN`. Any
         non-decimal value ('NS', 'not reported', '0', '1.2', 'abc') is
         rejected here — without this, the synthetic 'p=NS' fed into
         `check_p_value_in_source` finds no PVALUE_RE matches and
         vacuously succeeds, slipping unsupported numerics into Fact.
      2. **Source trace:** the (operator, digits) tuple this proposal
         claims must appear verbatim in the abstract — same tuple shape
         that PVALUE_RE extracts. Default operator is '=' when the
         field is a bare decimal.
    """
    pv = p_value.strip()
    if pv.lower().startswith("p"):
        pv = pv[1:].strip()
    operator = "="
    if pv.startswith(("<", ">", "=")):
        operator = pv[0]
        pv = pv[1:].strip()
    m = _PVALUE_DECIMAL_RE.match(pv)
    if m is None:
        return False
    proposed = (operator, m.group(1))
    return proposed in set(PVALUE_RE.findall(abstract))


def _validate_proposed(
    proposed: Mapping[str, Any],
    *,
    item: EvidenceItem,
    pack: TopicPack,
    require_source_trace: bool,
) -> tuple[Fact | None, str | None]:
    """Apply code-disposes to a single LLM-proposed fact dict.

    Returns (Fact, None) on accept, (None, reason_code) on reject.

    `require_source_trace=True` enforces FOUR layers of source-tracing
    (closes the v1 gap where only claim-embedded p-values were checked):
      1. p-values embedded in claim text → check_p_value_in_source
      2. proposed `p_value` field (bare or operator+number) → synthesized
         and re-checked via the same regex layer
      3. proposed `estimate` field → whitespace-normalized substring match
      4. proposed `ci` field → whitespace-normalized substring match
    """
    raw_claim = proposed.get("claim")
    if not isinstance(raw_claim, str) or not raw_claim.strip():
        return None, "missing_or_empty_claim"
    claim_text = raw_claim.strip()
    if len(claim_text) > _MAX_CLAIM_LEN:
        return None, "claim_too_long"

    kind = _kind_for_role(item.role)
    if kind is None:
        # off_domain or unrecognized — caller should have skipped, but
        # defense-in-depth: don't construct a Fact that can't pair.
        return None, f"no_kind_for_role:{item.role}"

    verb_fail = check_verb_ban(claim_text, item, pack)
    if verb_fail is not None:
        return None, f"verb_ban:{verb_fail.code}"

    p_value = _coerce_str_or_none(proposed.get("p_value"))
    estimate = _coerce_str_or_none(proposed.get("estimate"))
    ci = _coerce_str_or_none(proposed.get("ci"))
    outcome = _coerce_str_or_none(proposed.get("outcome"))

    if require_source_trace:
        # 1. p-values embedded in claim text
        pval_in_claim = check_p_value_in_source(claim_text, item.abstract)
        if pval_in_claim is not None:
            return None, f"p_value_not_in_source:{pval_in_claim.code}"
        # 2. p_value field — bypasses claim-text check when LLM puts the
        # number in the structured field instead of inside the prose.
        if p_value is not None and not _check_p_value_field(p_value, item.abstract):
            return None, "p_value_field_not_in_source"
        # 3. estimate — verbatim per prompt; whitespace-normalized match
        if estimate is not None and not _trace_field_in_source(estimate, item.abstract):
            return None, "estimate_not_in_source"
        # 4. ci — verbatim per prompt; whitespace-normalized match
        if ci is not None and not _trace_field_in_source(ci, item.abstract):
            return None, "ci_not_in_source"

    return Fact(
        ref=item.source.ref,
        kind=kind,
        claim=claim_text,
        outcome=outcome,
        estimate=estimate,
        p_value=p_value,
        ci=ci,
    ), None


# ----- Per-item extraction -----------------------------------------------


async def extract_facts_from_item(
    item: EvidenceItem,
    *,
    pack: TopicPack,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    require_source_trace: bool = True,
    temperature: float = 0.0,
) -> tuple[list[Fact], list[FactRejection]]:
    """Extract facts from one abstract via the LLM chain.

    Skips off_domain items (no LLM call). Empty / whitespace-only
    abstracts produce a single 'empty_abstract' rejection so the
    orchestrator can flag them.

    Temperature defaults to 0.0 — fact extraction is a precision task;
    creative variability is a failure mode here.
    """
    if _kind_for_role(item.role) is None:
        return [], []

    if not item.abstract or not item.abstract.strip():
        return [], [FactRejection(
            item_ref=item.source.ref, proposed={},
            reason="empty_abstract",
        )]

    messages: list[Mapping[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(item, pack.topic)},
    ]

    try:
        response = await chat_json(
            messages=messages,
            chain=chain,
            client=client,
            ledger=ledger,
            temperature=temperature,
        )
    except LLMError as exc:
        return [], [FactRejection(
            item_ref=item.source.ref, proposed={},
            reason=f"llm_error:{exc}",
        )]

    parsed = response.parsed
    raw_facts = parsed.get("facts") if isinstance(parsed, Mapping) else None
    if raw_facts is None:
        return [], [FactRejection(
            item_ref=item.source.ref,
            proposed=dict(parsed) if isinstance(parsed, Mapping) else {},
            reason="missing_facts_field",
        )]
    if not isinstance(raw_facts, list):
        return [], [FactRejection(
            item_ref=item.source.ref,
            proposed={"facts_was": type(raw_facts).__name__},
            reason="facts_field_not_a_list",
        )]

    accepted: list[Fact] = []
    rejected: list[FactRejection] = []
    seen: set[str] = set()
    for raw in raw_facts:
        if not isinstance(raw, Mapping):
            rejected.append(FactRejection(
                item_ref=item.source.ref,
                proposed={"value_type": type(raw).__name__},
                reason="not_a_dict",
            ))
            continue
        fact, reason = _validate_proposed(
            raw, item=item, pack=pack,
            require_source_trace=require_source_trace,
        )
        if fact is None:
            rejected.append(FactRejection(
                item_ref=item.source.ref,
                proposed=dict(raw),
                reason=reason or "unknown",
            ))
            continue
        norm = fact.claim.lower()
        if norm in seen:
            rejected.append(FactRejection(
                item_ref=item.source.ref,
                proposed=dict(raw),
                reason="duplicate_claim",
            ))
            continue
        seen.add(norm)
        accepted.append(fact)

    return accepted, rejected


# ----- Bundle-level fan-out ----------------------------------------------


async def extract_facts_from_bundle(
    items: Sequence[EvidenceItem],
    *,
    pack: TopicPack,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    require_source_trace: bool = True,
    temperature: float = 0.0,
    max_concurrency: int = 4,
) -> tuple[list[Fact], list[FactRejection]]:
    """Extract facts across a bundle, parallel-bounded by max_concurrency.

    Items run concurrently up to `max_concurrency` at once. Output order
    matches input order: facts from item[0] precede facts from item[1].
    Within each item, the LLM's emit order is preserved.
    """
    if not items:
        return [], []

    own_client = client is None
    c = client or httpx.AsyncClient()
    sem = asyncio.Semaphore(max_concurrency)

    async def one(item: EvidenceItem) -> tuple[list[Fact], list[FactRejection]]:
        async with sem:
            return await extract_facts_from_item(
                item, pack=pack, chain=chain, client=c, ledger=ledger,
                require_source_trace=require_source_trace,
                temperature=temperature,
            )

    try:
        per_item = await asyncio.gather(*(one(it) for it in items))
    finally:
        if own_client:
            await c.aclose()

    all_facts: list[Fact] = []
    all_rejections: list[FactRejection] = []
    for accepted, rejected in per_item:
        all_facts.extend(accepted)
        all_rejections.extend(rejected)
    return all_facts, all_rejections
