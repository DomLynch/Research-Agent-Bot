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

PROMPT_VERSION = "fact-extractor/2026-04-28-strict-substring"

_MAX_CLAIM_LEN = 500


SYSTEM_PROMPT = """You extract structured FACTS from a single research-paper abstract.

Each fact you emit is anchored to a VERBATIM SOURCE QUOTE from the
abstract — you do not paraphrase the central claim. You only choose
WHICH spans of the abstract to surface and tag them with structured
numeric fields. Code uses your `source_quote` directly as the claim
text; novel prose cannot enter the pipeline through this stage.

Output one JSON object with this exact shape:
{
  "facts": [
    {
      "source_quote": "verbatim span copied from the abstract — typically a single claim-bearing sentence or fragment, ≤500 chars",
      "outcome": "endpoint name like 'lean body mass' or null",
      "estimate": "CONTIGUOUS substring of source_quote like '+5.2 kg' or 'HR 0.79' — or null if not a clean substring",
      "p_value": "CONTIGUOUS substring of source_quote like '0.003' or '<0.001' — or null if not a clean substring",
      "ci": "CONTIGUOUS substring of source_quote like '0.66-0.95' — or null if not a clean substring"
    }
  ]
}

Rules:
1. `source_quote` is REQUIRED — a verbatim span COPIED from the
   abstract. Whitespace differences are tolerated; semantic edits are
   NOT. Code rejects any quote that doesn't appear verbatim in the
   abstract.
2. `estimate`, `p_value`, `ci` MUST appear as a CONTIGUOUS substring of
   the source_quote you chose. If you cannot copy a clean contiguous
   substring, set the field to null. DO NOT rephrase. DO NOT compute.
   DO NOT combine values from multiple spans. DO NOT split a value out
   of a parenthetical.
   - GOOD: source_quote contains "(HR 0.79; 95% CI 0.66-0.95; p=0.003)"
     → you may emit estimate="HR 0.79" if "HR 0.79" appears as a clean
     contiguous substring of the quote, OR set estimate=null otherwise.
   - BAD: source_quote contains "(RR, 0.94; 95% CI, 0.90-0.99) and 10
     years (RR, 0.91; 95% CI, 0.87-0.94)" → emitting
     estimate="RR, 0.94 at 5 years; RR, 0.91 at 10 years" is REPHRASING
     and will be rejected. Set estimate=null instead.
   - BAD: source_quote says "30% lower risk of death" → emitting
     estimate="HR 0.70" is COMPUTATION (30% lower → HR 0.70) and will
     be rejected. Set estimate=null instead.
   - When in doubt, set the field to null. A null structured field with
     a verifiable source_quote is ALWAYS preferred over a rejected fact.
3. The `source_quote` should be self-contained and ≤500 chars; no
   '[N]' citation brackets.
4. Choose source_quotes that are claim-bearing — the SUBSTANCE of the
   paper's findings, not boilerplate. For PROTOCOL or registered
   studies, quote the design / objective spans, not outcome spans.
   For REVIEWS, quote pooled-finding spans. For MECHANISTIC / preclinical
   abstracts, quote mechanism spans, not human-outcome speculation.

No prose outside the JSON. No markdown fences."""


def build_user_prompt(item: EvidenceItem, topic: str) -> str:
    """Render the user-message body for a given evidence item.

    Public so tests + run logs can inspect the prompt deterministically.
    """
    src = item.source
    venue = f", venue={src.venue!r}" if src.venue else ""
    role_hint = (
        " This source has role='published_results' — the abstract WILL contain"
        " reported findings (effect sizes, p-values, ORs, HRs, percentages,"
        " etc.). Extract at least one source_quote covering a primary finding."
        if item.role == "published_results" else
        " This source has role='published_protocol' or 'registered_pending' —"
        " quote design/objective spans, not outcome spans."
        if item.role in ("published_protocol", "registered_pending") else
        ""
    )
    return (
        f"Topic: {topic}\n\n"
        f"Source [{src.ref}] (role={item.role}, design={item.design}, "
        f"year={src.year}{venue}):\n"
        f"Title: {src.title}\n"
        f"Abstract: {item.abstract}\n\n"
        f"Extract facts about {topic} from this abstract.{role_hint}\n"
        f"Return an empty facts list ONLY when the abstract is genuinely"
        f" off-topic (does not mention {topic} or any of its standard"
        f" aliases). When the abstract IS about {topic}:\n"
        f" - surface every distinct claim-bearing quote: a separate fact"
        f"   per primary outcome, per secondary outcome, per trial phase,"
        f"   per arm comparison. Do not collapse multiple findings into"
        f"   one quote — code dedupes byte-identical quotes, so finer"
        f"   granularity is strictly safer than coarser.\n"
        f" - do not stop at one fact when the abstract reports multiple"
        f"   findings. A typical RCT abstract yields 3-8 distinct facts.\n"
        f" - emit at least one fact when the abstract is on-topic, even if"
        f"   you have to set every metadata field (estimate / p_value / ci)"
        f"   to null — better one bare quote than a silent drop."
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


def _normalize_unicode(text: str) -> str:
    """Normalize Unicode punctuation that British medical journals use.

    Day 8.0: PROTECTOR (Lancet Healthy Longevity) writes p-values as
    `p=0·02` with MIDDLE DOT (U+00B7), not ASCII period. The LLM
    reasonably rewrites to `0.02` but the substring trace fails. Apply
    the same normalization to both sides so the trust-spine substring
    checks treat `0·02` and `0.02` as the same numeric. Same for en-dash
    / em-dash → hyphen (CIs like `0·391–0·922` use en-dash).
    """
    return (
        text
        .replace("·", ".")  # middle dot
        .replace("–", "-")  # en-dash
        .replace("—", "-")  # em-dash
        .replace("−", "-")  # minus sign
    )


def _trace_field_in_source(value: str, abstract: str) -> bool:
    """Whitespace-normalized, case-insensitive substring match.

    Used for `estimate` and `ci` — the prompt requires verbatim, but real
    LLMs collapse whitespace inconsistently. Normalize both sides before
    matching so 'HR  0.79' (LLM, double space) traces against 'HR 0.79'
    (abstract). Day 8.0: also normalize Unicode middle-dot → period and
    en-dash → hyphen for British-journal-format compatibility. False
    on miss; True on hit.
    """
    needle = " ".join(_normalize_unicode(value).split()).lower()
    if not needle:
        return True
    haystack = " ".join(_normalize_unicode(abstract).split()).lower()
    return needle in haystack


def _quote_in_abstract(quote: str, abstract: str) -> bool:
    """Verify a verbatim source quote appears in the abstract.

    Whitespace-normalized + case-insensitive: tolerates the LLM's
    typical reformatting (collapsed whitespace, sentence-case
    differences) while rejecting any semantic edit. Day 8.0: also
    normalizes Unicode middle-dot / en-dash / em-dash so a quote
    rendered with ASCII punctuation traces against a British-journal
    abstract that uses Unicode equivalents. This is the
    Day 5.2-fix P1 replacement for the previous bag-of-words overlap
    gate, which accepted endpoint swaps like "Metformin reduced
    dementia" against an abstract that only said "Metformin reduced
    HbA1c". With this stricter check, the claim text is BY
    CONSTRUCTION a verbatim span of the source — there's no
    novel-claim attack surface at the extraction stage.
    """
    needle = " ".join(_normalize_unicode(quote).split()).lower()
    if not needle:
        return False
    haystack = " ".join(_normalize_unicode(abstract).split()).lower()
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
    pv = _normalize_unicode(p_value).strip()
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
    return proposed in set(PVALUE_RE.findall(_normalize_unicode(abstract)))


def _validate_proposed(
    proposed: Mapping[str, Any],
    *,
    item: EvidenceItem,
    pack: TopicPack,
    require_source_trace: bool,
) -> tuple[Fact | None, str | None]:
    """Apply code-disposes to a single LLM-proposed fact dict.

    Returns (Fact, None) on accept, (None, reason_code) on reject.

    The LLM emits `source_quote` — a verbatim span from the abstract —
    NOT a freeform claim. Code uses the verified quote as `Fact.claim`,
    closing the novel-claim attack surface at the extraction stage
    (Day 5.2-fix P1; previous bag-of-words overlap gate accepted
    endpoint swaps like "Metformin reduced dementia" against an
    HbA1c abstract).

    `require_source_trace=True` enforces source-tracing layers:
      0. source_quote appears verbatim in the abstract (Day 5.2-fix P1)
      1. p-values embedded in the quote → check_p_value_in_source
      2. proposed `p_value` field → synthesized + PVALUE_RE-traced
      3. proposed `estimate` / `ci` fields → kept only when they appear
         as substrings of the verified source_quote; otherwise NULLED.
         Day 8.2 (reviewer P2): nulling instead of rejecting the whole
         fact preserves the verified quote while keeping unverified
         metadata out of the audit log. The receipt's structured fields
         now match the trust contract: present iff verified.
    """
    raw_quote = proposed.get("source_quote")
    if not isinstance(raw_quote, str) or not raw_quote.strip():
        return None, "missing_or_empty_source_quote"
    quote = raw_quote.strip()
    if len(quote) > _MAX_CLAIM_LEN:
        return None, "source_quote_too_long"

    kind = _kind_for_role(item.role)
    if kind is None:
        # off_domain or unrecognized — caller should have skipped, but
        # defense-in-depth: don't construct a Fact that can't pair.
        return None, f"no_kind_for_role:{item.role}"

    verb_fail = check_verb_ban(quote, item, pack)
    if verb_fail is not None:
        return None, f"verb_ban:{verb_fail.code}"

    p_value = _coerce_str_or_none(proposed.get("p_value"))
    estimate = _coerce_str_or_none(proposed.get("estimate"))
    ci = _coerce_str_or_none(proposed.get("ci"))
    outcome = _coerce_str_or_none(proposed.get("outcome"))

    if require_source_trace:
        # 0. Source quote MUST appear verbatim in the abstract
        # (whitespace-normalized, case-insensitive).
        if not _quote_in_abstract(quote, item.abstract):
            return None, "source_quote_not_in_abstract"
        # 1. p-values embedded in the quote
        pval_in_quote = check_p_value_in_source(quote, item.abstract)
        if pval_in_quote is not None:
            return None, f"p_value_not_in_source:{pval_in_quote.code}"
        # 2. p_value field — bypasses quote-text check when LLM puts the
        # number in the structured field instead of inside the quote.
        if p_value is not None and not _check_p_value_field(p_value, item.abstract):
            return None, "p_value_field_not_in_source"
        # 3. estimate / ci — null instead of reject when they don't trace
        # to the VERIFIED source_quote (not the full abstract). Day 8.2
        # closes the reviewer P2 gap: pre-fix, an LLM could write an
        # arbitrary 'HR 0.10' into Fact.estimate and it would flow into
        # fact_extraction_log.json as if it were source-backed metadata.
        # Now we keep the verified quote (which IS the trust anchor) but
        # null any estimate/ci that isn't a contiguous substring of it.
        if estimate is not None and not _trace_field_in_source(estimate, quote):
            estimate = None
        if ci is not None and not _trace_field_in_source(ci, quote):
            ci = None

    return Fact(
        ref=item.source.ref,
        kind=kind,
        claim=quote,
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
    seed: int | None = None,
) -> tuple[list[Fact], list[FactRejection]]:
    """Extract facts from one abstract via the LLM chain.

    Skips off_domain items (no LLM call). Empty / whitespace-only
    abstracts produce a single 'empty_abstract' rejection so the
    orchestrator can flag them.

    Temperature defaults to 0.0 — fact extraction is a precision task;
    creative variability is a failure mode here. Day 9.4 adds `seed`:
    pass an int and the LLM call becomes deterministic (same prompt
    + temp 0 + seed → byte-identical response). The orchestrator
    derives a per-item seed from a base value so each abstract gets a
    distinct seed (otherwise every claim would be drawn against the
    same RNG state, which doesn't help convergence).
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
            seed=seed,
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

    # Day 6.1c: an empty facts list from the LLM for a results-role
    # item is a documented "no findings extractable" signal — log it
    # as a synthetic rejection so the orchestrator can tolerate it as
    # a documented orphan rather than treating it as a silent drop.
    # Review/mechanistic items don't require facts, so empty there is
    # genuinely fine and we don't pollute the log.
    if not raw_facts and item.role in ("published_results", "published_protocol", "registered_pending"):
        return [], [FactRejection(
            item_ref=item.source.ref, proposed={},
            reason="llm_returned_empty_facts_for_results_role",
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
    seed: int | None = None,
) -> tuple[list[Fact], list[FactRejection]]:
    """Extract facts across a bundle, parallel-bounded by max_concurrency.

    Items run concurrently up to `max_concurrency` at once. Output order
    matches input order: facts from item[0] precede facts from item[1].
    Within each item, the LLM's emit order is preserved.

    Day 9.4: when `seed` is set, each item gets a per-item seed derived
    from `(seed, item.source.ref)` — a stable hash of the base seed and
    the deterministic ref index. Same base seed + same items → same
    per-item seeds → same LLM responses → byte-identical receipts.
    """
    if not items:
        return [], []

    own_client = client is None
    c = client or httpx.AsyncClient()
    sem = asyncio.Semaphore(max_concurrency)

    async def one(item: EvidenceItem) -> tuple[list[Fact], list[FactRejection]]:
        async with sem:
            # Per-item seed derivation: same base seed → same per-item
            # seeds. ref is a deterministic 1-based int from retrieve.py
            # so ref+seed is a stable, collision-free derivation.
            item_seed = None if seed is None else (seed * 100003 + item.source.ref) & 0xFFFFFFFF
            return await extract_facts_from_item(
                item, pack=pack, chain=chain, client=c, ledger=ledger,
                require_source_trace=require_source_trace,
                temperature=temperature,
                seed=item_seed,
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
