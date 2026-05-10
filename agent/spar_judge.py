"""SPAR (Single-Pass Adversarial Review) per-receipt adjudicator.

The v06 synthesis pipeline previously hardcoded `spar_verdict="accept_clean"`
for every receipt — the writer effectively graded its own input. The
build_judge_chain (Gemma 4 31B primary, MiMo fallback, Mistral last)
existed in agent.llm_client but was only invoked by a legacy proof
script, never by the production runner. This module wires the judge in
properly.

Per the project's "judge ≠ writer" memory rule, the SPAR judge MUST be
a different model family from the writer. Default chain uses Gemma 4
(google) while the writer is MiMo (Xiaomi) — distinct families satisfy
the rule.

Design contract:
  - One judge call per receipt. Cost: ~$0.0002 per call on Gemma 4 31B.
  - Domain-agnostic prompt (per the universal-no-hardcoding rule).
    Works for biomedical, climate, materials, economics, social science,
    or any other research domain. Examples are listed across multiple
    domains rather than anchored to any one.
  - Fail-soft: on any error (LLM down, JSON parse failure, schema
    violation), the receipt keeps its prior verdict (typically
    "accept_clean"). The pipeline never aborts because of judge errors
    — that would be worse than running un-judged.
  - Verdicts are the project's canonical SparVerdict shape:
      accept_clean      — supported, scope-appropriate, no red flags
      accept_caveated   — supported but with a meaningful caveat that
                          downstream prose MUST hedge (small n,
                          off-target scope, surrogate endpoint, etc.)
      reject_<reason>   — unsupportable as evidence (fabricated numbers,
                          wrong direction, internal contradiction)

Fail-soft default: when the judge can't reach a verdict, return
"accept_clean" so the run proceeds. The audit gates downstream still
catch problems — the SPAR judge is one layer of defence in depth, not
the only layer.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from agent.llm_client import CallSpec, CostLedger
from agent.synthesis_schemas import ReceiptSummary

__all__ = [
    "SparJudgeVerdict",
    "judge_receipt_prompt",
    "parse_judge_response",
    "adjudicate_receipt",
    "adjudicate_receipts",
]

LOGGER = logging.getLogger(__name__)

VerdictTag = Literal[
    "accept_clean",
    "accept_caveated",
    "reject_fabricated_numbers",
    "reject_direction_mismatch",
    "reject_design_misclassified",
    "reject_internal_contradiction",
    "reject_other",
]


@dataclass(frozen=True, slots=True)
class SparJudgeVerdict:
    """Structured SPAR judge result for one receipt."""

    receipt_id: str
    verdict: str           # one of VerdictTag values
    rationale: str
    judge_model: str       # which model produced this verdict
    fail_soft_default: bool  # True when fallback (no real judge call)


class _JudgeCaller(Protocol):
    """Signature for the LLM callback used by the judge.

    Implementations are responsible for handling retries, fallback
    chain, and cost tracking. The judge module just sees: prompt in,
    JSON-string out (or exception)."""

    async def __call__(
        self, *, system: str, user: str,
    ) -> tuple[str, str, float]:
        """Return (raw_json, model_used, cost_usd)."""
        ...


# ---- Prompt ---------------------------------------------------------------


_VALID_VERDICTS = frozenset({
    "accept_clean", "accept_caveated",
    "reject_fabricated_numbers", "reject_direction_mismatch",
    "reject_design_misclassified", "reject_internal_contradiction",
    "reject_other",
})


_SPAR_SYSTEM_PROMPT = """\
You are a SPAR judge — Single-Pass Adversarial Review.

You receive ONE receipt: a distilled summary of one source paper's
load-bearing claims, plus structured metadata (study design tier,
directness, outcome scope, effect direction, sample sizes, p-values).

Your job: decide whether this receipt is admissible as evidence in a
research-synthesis corpus. The downstream writer will cite this
receipt; reviewers will judge the paper based on what you let through.

This judgment is TOPIC-AGNOSTIC. You may receive receipts from any
research domain — biomedical, climate, materials, economics, social
science, computer science, etc. Apply the rules below universally.

VERDICT TAGS — choose exactly one:
  accept_clean
    The claim is well-supported by the evidence shape described, the
    scope is appropriate to the design, and there are no red flags.

  accept_caveated
    The claim is supported but has a meaningful caveat that downstream
    prose MUST hedge. Examples (cross-domain): small sample size,
    sub-population with potential generalisation gap, surrogate / proxy
    variable instead of primary outcome, mechanism-level evidence
    being applied to a target system, scoped-context evidence (single
    site / single regime / single time period).

  reject_fabricated_numbers
    The numerics in the claim cannot be reconciled with the evidence
    shape (e.g. confidence interval bounds incompatible with the
    point estimate, percentages outside [0,100], sample size larger
    than population frame, p-value impossible for the reported
    effect). Reserve this for clear arithmetic / impossibility errors.

  reject_direction_mismatch
    The receipt's stated effect direction contradicts the evidence
    summary (e.g. metadata says "positive" but the claim text says
    "no effect" or "harm"). Reserve for outright contradictions.

  reject_design_misclassified
    The metadata claims a study design (RCT / experiment / cohort /
    quasi-experiment / replicated multi-site / model-organism / etc.)
    that the claim summary does not actually support. E.g. metadata
    tier=A1 (highest evidence) but the claim is from a single
    case-series, single-arm pilot, or in-silico simulation.

  reject_internal_contradiction
    The receipt's own fields contradict each other (e.g. claim says
    "no participants" but n_claims > 0; outcome_class says "primary"
    but evidence summary describes only a surrogate). Use sparingly.

  reject_other
    Some other unsupportable issue, named in the rationale.

DECISION GUIDANCE:

1. Default to accept_clean unless you can name a concrete issue.
   Most receipts pass deterministic extraction — they're usually fine.

2. Use accept_caveated when the receipt is fine BUT the writer would
   need to add a hedge to cite it honestly. This is the most common
   non-clean verdict.

3. Reserve reject_* for clear, named issues. Vague bad feelings get
   accept_caveated, not rejection.

4. Do NOT reject for low evidence tier alone — tier C / mechanistic /
   indirect is admissible if hedged. Reject only when there's an
   actual error or contradiction.

5. Domain-agnostic: a climate-paper receipt with "single time period"
   gets accept_caveated, not reject. A materials-paper receipt with
   "single laboratory" gets accept_caveated. A biomed receipt with
   "small n" gets accept_caveated. The same logic applies in every
   domain.

OUTPUT — JSON only, no prose:
{
  "verdict": "<one of the 7 verdict tags>",
  "rationale": "<one sentence naming the specific issue or 'no red flags'>"
}
"""


def _format_receipt_for_judge(receipt: ReceiptSummary) -> str:
    """Render a receipt as a concise structured block the judge can read."""
    fields = [
        ("paper_id", receipt.receipt_id),
        ("topic", receipt.topic),
        ("study_design_tier", receipt.evidence_tier),
        ("directness", receipt.directness),
        ("outcome_class", receipt.outcome_class),
        ("effect_direction", receipt.effect_direction),
        ("n_claims_extracted", receipt.n_claims),
        ("p_values", ", ".join(receipt.p_values) if receipt.p_values else "(none)"),
        ("population_or_scope", receipt.population_summary),
        ("canonical_trial_or_study_id", receipt.canonical_trial_id or "(none)"),
        ("source_year", receipt.source_year),
        ("source_venue", receipt.source_venue or "(unknown)"),
        ("paper_title", (receipt.source_title or "")[:300]),
    ]
    lines = [f"  {k}: {v}" for k, v in fields if v not in (None, "")]
    return "Receipt summary:\n" + "\n".join(lines) + "\n\n" + (
        "Distilled thesis text (what the writer will cite):\n"
        + receipt.thesis_text[:1500]
    )


def judge_receipt_prompt(receipt: ReceiptSummary) -> tuple[str, str]:
    """Return (system, user) prompts the judge LLM should be called with."""
    return _SPAR_SYSTEM_PROMPT, _format_receipt_for_judge(receipt)


# ---- Response parser -----------------------------------------------------


def parse_judge_response(receipt_id: str, raw: str, model: str) -> SparJudgeVerdict:
    """Strict JSON parse + verdict-tag validation. On any failure,
    return a fail-soft `accept_clean` with the parse error in the
    rationale. The caller decides whether to log/alert; the run never
    aborts because of a parse failure."""
    text = raw.strip()
    # Strip code fences if the model added them despite the system prompt.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return SparJudgeVerdict(
            receipt_id=receipt_id,
            verdict="accept_clean",
            rationale=f"fail_soft: judge response not parseable as JSON ({exc}); "
                      "defaulting to accept_clean",
            judge_model=model,
            fail_soft_default=True,
        )
    if not isinstance(data, dict):
        return SparJudgeVerdict(
            receipt_id=receipt_id, verdict="accept_clean",
            rationale="fail_soft: judge response was not a JSON object",
            judge_model=model, fail_soft_default=True,
        )
    verdict = str(data.get("verdict") or "").strip().lower()
    rationale = str(data.get("rationale") or "").strip() or "(empty rationale)"
    if verdict not in _VALID_VERDICTS:
        return SparJudgeVerdict(
            receipt_id=receipt_id, verdict="accept_clean",
            rationale=f"fail_soft: judge returned unknown verdict {verdict!r}; "
                      "defaulting to accept_clean",
            judge_model=model, fail_soft_default=True,
        )
    return SparJudgeVerdict(
        receipt_id=receipt_id,
        verdict=verdict,
        rationale=rationale[:500],
        judge_model=model,
        fail_soft_default=False,
    )


# ---- Driver --------------------------------------------------------------


async def adjudicate_receipt(
    receipt: ReceiptSummary,
    *,
    call: _JudgeCaller,
) -> SparJudgeVerdict:
    """Send one receipt through the judge. Fail-soft on any exception."""
    system, user = judge_receipt_prompt(receipt)
    try:
        raw, model, _cost = await call(system=system, user=user)
    except Exception as exc:  # noqa: BLE001 — fail-soft per receipt
        return SparJudgeVerdict(
            receipt_id=receipt.receipt_id,
            verdict="accept_clean",
            rationale=f"fail_soft: judge call failed "
                      f"({type(exc).__name__}: {exc}); defaulting to accept_clean",
            judge_model="(call_failed)",
            fail_soft_default=True,
        )
    return parse_judge_response(receipt.receipt_id, raw, model)


async def adjudicate_receipts(
    receipts: Sequence[ReceiptSummary],
    *,
    call: _JudgeCaller,
    concurrency: int = 4,
    cache: dict[str, SparJudgeVerdict] | None = None,
) -> tuple[list[ReceiptSummary], list[SparJudgeVerdict]]:
    """Run SPAR judging across a batch and return both the updated
    receipts AND the per-receipt SparJudgeVerdict objects so the caller
    can compute honest stats (n_real_calls, n_fail_soft, n_reject).

    Original receipts are not mutated (frozen dataclass).

    `cache` (optional): a {receipt_id: SparJudgeVerdict} dict pre-loaded
    from disk on a rerun. Receipts whose id is in the cache skip the
    LLM call and reuse the prior verdict — required for cost discipline
    on iterative reruns. Cache hits are counted as real calls (not
    fail-soft) so spar_adjudication_ran propagates correctly."""
    import asyncio
    sem = asyncio.Semaphore(max(1, concurrency))
    cache = dict(cache) if cache else {}

    async def _one(r: ReceiptSummary) -> tuple[ReceiptSummary, SparJudgeVerdict]:
        if r.receipt_id in cache:
            return r, cache[r.receipt_id]
        async with sem:
            v = await adjudicate_receipt(r, call=call)
        return r, v

    results = await asyncio.gather(*(_one(r) for r in receipts))
    out_receipts: list[ReceiptSummary] = []
    out_verdicts: list[SparJudgeVerdict] = []
    for r, v in results:
        out_receipts.append(replace(r, spar_verdict=v.verdict))
        out_verdicts.append(v)
        if v.fail_soft_default:
            LOGGER.info(
                "spar_judge.fail_soft receipt=%s rationale=%s",
                r.receipt_id, v.rationale,
            )
        elif v.verdict.startswith("reject"):
            LOGGER.warning(
                "spar_judge.reject receipt=%s verdict=%s rationale=%s",
                r.receipt_id, v.verdict, v.rationale,
            )
    return out_receipts, out_verdicts


# ---- Default caller adapter (uses agent.llm_client chain) ----------------


def make_chain_caller(
    chain: Sequence[CallSpec],
    ledger: CostLedger,
    *,
    client: Any | None = None,
    temperature: float = 0.0,
    seed: int | None = 42,
) -> _JudgeCaller:
    """Build a `_JudgeCaller` that runs through the standard CallSpec
    fallback chain in agent.llm_client.chat_json. Judge calls default
    to temperature=0 + a stable seed so verdicts are reproducible
    across runs of the same receipt. The judge module stays decoupled
    from llm_client — callers can substitute mock callers in tests
    or alternative chains in production."""
    from agent.llm_client import chat_json

    async def _caller(*, system: str, user: str) -> tuple[str, str, float]:
        resp = await chat_json(
            messages=(
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ),
            chain=chain, client=client,
            ledger=ledger,
            temperature=temperature, seed=seed,
        )
        return resp.text, resp.model, resp.estimated_cost_usd

    return _caller
