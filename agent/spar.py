"""Run structured panel review with deterministic trace enforcement."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.schemas import (
    CitationTrace,
    ClaimGraph,
    GateOverride,
    JudgeReview,
    JudgeRole,
    SPARReview,
    SPARVerdict,
    assert_spar_invariants,
    compute_spar_verdict,
)
from agent.types import EvidenceItem

__all__ = [
    "SPARError",
    "PROMPT_VERSION",
    "run_spar",
    "render_brief",
    "reviews_to_dict",
]

logger = logging.getLogger(__name__)

PROMPT_VERSION = "spar/2026-04-28"


class SPARError(RuntimeError):
    """Raised when a valid three-judge review cannot be assembled."""


# --- Prompts --------------------------------------------------------------

_OUTPUT_SCHEMA_BLOCK = """Output a single JSON object with this exact shape:
{
  "verdict": "accept" or "reject",
  "score": integer 1-10,
  "rationale": "1-3 paragraphs of plain prose",
  "flagged_claims": ["C001", ...]   // claim_ids you found problems with; [] if none
}
No prose outside the JSON. No markdown fences."""

_AUDITOR_SYSTEM = f"""You are the EVIDENCE AUDITOR in a 3-judge research review panel.

Your role: scrutinize whether each claim is supported by the cited evidence.
Look for:
- Citations that fail their trace (nct_exists, p_value_in_text, alias_match,
  role_match, percentage_in_text). A failed trace is grounds for reject.
- Numeric values in claims that don't appear in the source abstracts.
- Claims marked direct that lack a published_results citation.
- Inconsistencies between trace results and claim assertions.

You do NOT debate domain merit (that's the Domain Skeptic).
You do NOT make the final call (that's the Final Judge).
You verify: does the evidence actually support what's claimed?

Reject if ANY claim has a failed trace or unsupported numeric.
Accept if all traces pass AND each claim accurately represents its citations.

{_OUTPUT_SCHEMA_BLOCK}"""

_SKEPTIC_SYSTEM = f"""You are the DOMAIN SKEPTIC in a 3-judge research review panel.

Your role: argue against the claims. You're a domain expert who's been
asked to find what's WRONG with the submission. Look for:
- Over-claiming: indirect / mechanistic evidence framed as direct.
- Missing caveats: confounders, sample-size issues, population specificity.
- Mechanism inflation: preclinical results extrapolated to human outcomes.
- Off-topic drift: evidence about a different drug, disease, or population.

You do NOT verify citation existence (that's the Evidence Auditor).
You do NOT make the final call (that's the Final Judge).
You ask: is the conclusion appropriately scoped given what the evidence supports?

Reject if any claim is over-scoped, hides a confounder, or extrapolates
beyond the evidence's domain. Accept if the claims are appropriately
calibrated to the evidence's strength AND its limits.

{_OUTPUT_SCHEMA_BLOCK}"""

_FINAL_SYSTEM = f"""You are the FINAL JUDGE in a 3-judge research review panel.

You see:
- The claim graph (claims + thesis)
- The citation trace results
- The Evidence Auditor's review + the Domain Skeptic's review

Your role: vote independently AFTER reading the other two, then explain
how you weighed dissent. You are NOT an override — your vote is the third
ballot, and the deterministic tie-break formula assigns the panel verdict
from all three votes:
  3-0 accept → accept_clean
  2-1 accept → accept_caveated (dissent always published)
  1-2 reject → reject_majority (dissent always published)
  0-3 reject → reject_critical

If you align with the prior two: your rationale should still address any
serious objection the others raised. If they SPLIT (one accept, one
reject): your rationale MUST explicitly explain the weight you gave each
side. The audit trail depends on this — a Final Judge who breaks a tie
without showing their reasoning corrupts the panel's legitimacy.

{_OUTPUT_SCHEMA_BLOCK}"""

_SYSTEM_PROMPTS: Mapping[JudgeRole, str] = {
    "evidence_auditor": _AUDITOR_SYSTEM,
    "domain_skeptic": _SKEPTIC_SYSTEM,
    "final_judge": _FINAL_SYSTEM,
}


# --- Brief rendering ------------------------------------------------------


_BRIEF_ABSTRACT_CHAR_LIMIT = 2000


def render_brief(
    graph: ClaimGraph,
    traces: Sequence[CitationTrace],
    *,
    topic: str,
    submission_id: str,
    items_by_ref: "Mapping[int, EvidenceItem] | None" = None,
) -> str:
    """Render the graph, traces, and optional source abstracts for judges."""
    thesis = next(
        (c for c in graph.claims if c.claim_id == graph.thesis_claim_id),
        None,
    )
    thesis_line = (
        f"THESIS: [{thesis.claim_id}] {thesis.text!r}"
        if thesis else
        f"THESIS: <claim_id={graph.thesis_claim_id} not in claims — INVARIANT VIOLATED>"
    )
    claims_block = "\n".join(
        f"  [{c.claim_id} | {c.directness} | {c.evidence_tier} | {c.confidence}] {c.text!r}"
        f"\n    supporting_refs={list(c.supporting_refs)}"
        for c in graph.claims
    )
    traces_block = (
        "\n".join(
            f"  [{t.trace_type} ref={t.ref} on {t.claim_id}] "
            f"{'PASS' if t.passed else 'FAIL'}: {t.detail}"
            for t in traces
        ) or "  (no citation traces — citation_trace not run)"
    )
    abstracts_block = ""
    if items_by_ref:
        cited_refs = sorted(
            {r for c in graph.claims for r in c.supporting_refs}
        )
        rendered = []
        for ref in cited_refs:
            item = items_by_ref.get(ref)
            if item is None:
                continue
            src = item.source
            abstract = (item.abstract or "")[:_BRIEF_ABSTRACT_CHAR_LIMIT]
            truncated = (
                "" if len(item.abstract or "") <= _BRIEF_ABSTRACT_CHAR_LIMIT
                else f" [truncated to {_BRIEF_ABSTRACT_CHAR_LIMIT} chars]"
            )
            ident_bits = [f"role={item.role}", f"design={item.design}"]
            if src.pmid:
                ident_bits.append(f"pmid={src.pmid}")
            if src.doi:
                ident_bits.append(f"doi={src.doi}")
            if src.nct:
                ident_bits.append(f"nct={src.nct}")
            ident = ", ".join(ident_bits)
            rendered.append(
                f"  [{ref}] {src.title!r}\n"
                f"    ({ident}){truncated}\n"
                f"    abstract: {abstract!r}"
            )
        if rendered:
            abstracts_block = (
                f"\n\nEVIDENCE ABSTRACTS ({len(rendered)}):\n"
                + "\n".join(rendered)
            )
    return (
        f"TOPIC: {topic}\n"
        f"SUBMISSION ID: {submission_id}\n\n"
        f"{thesis_line}\n\n"
        f"CLAIMS ({len(graph.claims)}):\n{claims_block}\n\n"
        f"CITATION TRACES ({len(traces)}):\n{traces_block}"
        f"{abstracts_block}"
    )


def _render_panel_context(
    auditor: JudgeReview, skeptic: JudgeReview,
) -> str:
    """Append-block for the Final Judge prompt — what the other two said."""
    return (
        "PANEL CONTEXT (for the Final Judge):\n\n"
        f"Evidence Auditor — verdict={auditor.verdict}, score={auditor.score}, "
        f"flagged={list(auditor.flagged_claims)}\n"
        f"Rationale: {auditor.rationale}\n\n"
        f"Domain Skeptic — verdict={skeptic.verdict}, score={skeptic.score}, "
        f"flagged={list(skeptic.flagged_claims)}\n"
        f"Rationale: {skeptic.rationale}"
    )


# --- Judge call + parse ---------------------------------------------------


def _parse_judge_review(
    parsed: Mapping[str, Any],
    *,
    judge_role: JudgeRole,
    model: str,
) -> JudgeReview:
    """Validate one judge's JSON response."""
    verdict = parsed.get("verdict")
    if verdict not in ("accept", "reject"):
        raise SPARError(
            f"judge={judge_role}: verdict must be 'accept' or 'reject'; "
            f"got {verdict!r}"
        )
    raw_score = parsed.get("score")
    if not isinstance(raw_score, int) or not (1 <= raw_score <= 10):
        raise SPARError(
            f"judge={judge_role}: score must be int 1-10; got {raw_score!r}"
        )
    rationale = parsed.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise SPARError(f"judge={judge_role}: rationale must be non-empty string")
    flagged_raw = parsed.get("flagged_claims", [])
    if not isinstance(flagged_raw, list):
        raise SPARError(
            f"judge={judge_role}: flagged_claims must be a list; "
            f"got {type(flagged_raw).__name__}"
        )
    # Strict: any non-string entry rejects the whole review. Pre-fix this
    # silently filtered, hiding malformed signal — a judge that emits
    # `[42, null]` is broken and the orchestrator should know, not patch.
    bad_entries = [c for c in flagged_raw if not isinstance(c, str)]
    if bad_entries:
        raise SPARError(
            f"judge={judge_role}: flagged_claims must contain only strings; "
            f"got non-string entries {bad_entries[:3]!r}"
        )
    return JudgeReview(
        judge_role=judge_role, model=model, verdict=verdict,
        score=raw_score, rationale=rationale.strip(),
        flagged_claims=tuple(flagged_raw),
    )


async def _run_judge(
    role: JudgeRole,
    user_prompt: str,
    *,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient,
    ledger: CostLedger | None,
    temperature: float,
    seed: int | None = None,
) -> JudgeReview:
    """Single judge call: chat_json → parse → JudgeReview."""
    response = await chat_json(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPTS[role]},
            {"role": "user", "content": user_prompt},
        ],
        chain=chain,
        client=client,
        ledger=ledger,
        temperature=temperature,
        seed=seed,
    )
    return _parse_judge_review(
        response.parsed, judge_role=role, model=response.model,
    )


# --- Dissent identification ----------------------------------------------


def _identify_dissent(
    reviews: tuple[JudgeReview, JudgeReview, JudgeReview],
    verdict: SPARVerdict,
) -> JudgeReview | None:
    """Return the minority review for a 2-1 split."""
    if verdict in ("accept_clean", "reject_critical"):
        return None
    minority_verdict = "reject" if verdict == "accept_caveated" else "accept"
    return next((r for r in reviews if r.verdict == minority_verdict), None)


def _validate_flagged_against_graph(
    reviews: tuple[JudgeReview, ...],
    graph: ClaimGraph,
) -> None:
    """Reject reviews that flag claim IDs absent from the graph."""
    valid_ids = {c.claim_id for c in graph.claims}
    for r in reviews:
        unknown = [cid for cid in r.flagged_claims if cid not in valid_ids]
        if unknown:
            raise SPARError(
                f"judge={r.judge_role}: flagged_claims contain ids not in "
                f"the ClaimGraph: {unknown!r}. Valid ids: {sorted(valid_ids)!r}."
            )


def _enforce_trace_gate(
    panel_verdict: SPARVerdict,
    traces: Sequence[CitationTrace],
    graph: ClaimGraph | None = None,
) -> GateOverride | None:
    """Override accepting panels when traces fail or lack full coverage."""
    if panel_verdict not in ("accept_clean", "accept_caveated"):
        return None
    failed = [t for t in traces if not t.passed]
    covered = {(t.claim_id, t.ref) for t in traces}
    missing = (
        [] if graph is None else [
            (claim.claim_id, ref)
            for claim in graph.claims
            for ref in claim.supporting_refs
            if (claim.claim_id, ref) not in covered
        ]
    )
    unsupported = (
        [] if graph is None else [
            claim.claim_id for claim in graph.claims
            if not claim.supporting_refs
        ]
    )
    if not failed and not missing and not unsupported:
        return None
    if failed:
        sample = failed[0]
        detail = (
            f"{len(failed)} citation trace(s) failed (e.g., "
            f"{sample.trace_type} on claim={sample.claim_id} "
            f"ref={sample.ref}: {sample.detail!r})"
        )
    else:
        detail = (
            f"trace coverage is incomplete: {len(missing)} claim/ref pair(s) "
            f"missing and {len(unsupported)} claim(s) have no supporting refs"
        )
    rationale = (
        f"Trust-spine trace gate triggered: panel returned "
        f"{panel_verdict!r} but {detail}. Verdict forced to reject_critical."
    )
    return GateOverride(
        pre_gate_verdict=panel_verdict,
        failed_trace_count=len(failed) + len(missing) + len(unsupported),
        rationale=rationale,
    )


# --- Orchestrator ---------------------------------------------------------


async def run_spar(
    graph: ClaimGraph,
    traces: Sequence[CitationTrace],
    *,
    topic: str,
    submission_id: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    temperature: float = 0.2,
    seed: int | None = None,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
) -> SPARReview:
    """Run the fail-loud three-judge panel with deterministic seeding."""
    base_brief = render_brief(
        graph, traces, topic=topic, submission_id=submission_id,
        items_by_ref=items_by_ref,
    )

    # When seed is set, force temperature to 0.0 — seed has no
    # determinism contract at the default 0.2.
    effective_temp = 0.0 if seed is not None else temperature

    # Per-judge seed derivation. Auditor=+1, Skeptic=+2, Final=+3.
    auditor_seed = None if seed is None else (seed * 1000003 + 1) & 0xFFFFFFFF
    skeptic_seed = None if seed is None else (seed * 1000003 + 2) & 0xFFFFFFFF
    final_seed = None if seed is None else (seed * 1000003 + 3) & 0xFFFFFFFF

    own_client = client is None
    c = client or httpx.AsyncClient()
    try:
        auditor, skeptic = await asyncio.gather(
            _run_judge(
                "evidence_auditor", base_brief,
                chain=chain, client=c, ledger=ledger,
                temperature=effective_temp, seed=auditor_seed,
            ),
            _run_judge(
                "domain_skeptic", base_brief,
                chain=chain, client=c, ledger=ledger,
                temperature=effective_temp, seed=skeptic_seed,
            ),
        )
        final_user_prompt = (
            base_brief + "\n\n" + _render_panel_context(auditor, skeptic)
        )
        final_judge = await _run_judge(
            "final_judge", final_user_prompt,
            chain=chain, client=c, ledger=ledger,
            temperature=effective_temp, seed=final_seed,
        )
    finally:
        if own_client:
            await c.aclose()

    reviews = (auditor, skeptic, final_judge)
    # Validate flagged_claims against the actual graph before constructing
    # the SPARReview — a hallucinated claim_id is a parse-level violation
    # that wouldn't be caught by the schema invariants.
    _validate_flagged_against_graph(reviews, graph)

    panel_verdict = compute_spar_verdict(reviews)
    gate = _enforce_trace_gate(panel_verdict, traces, graph)
    if gate is not None:
        # Trust-spine gate triggered: panel votes preserved; verdict
        # forced to reject_critical; dissent suppressed (the gate's
        # rejection is structurally distinct from any panel minority).
        canonical_verdict: SPARVerdict = "reject_critical"
        dissent: JudgeReview | None = None
        resolution = (
            f"{final_judge.rationale}\n\n[Trace-gate override] "
            f"{gate.rationale}"
        )
    else:
        canonical_verdict = panel_verdict
        dissent = _identify_dissent(reviews, panel_verdict)
        resolution = final_judge.rationale

    spar_review = SPARReview(
        submission_id=submission_id,
        reviews=reviews,
        verdict=canonical_verdict,
        dissent=dissent,
        final_judge_resolution=resolution,
        gate_override=gate,
    )
    # Defense-in-depth: the schema invariant re-checks vote-vs-verdict
    # consistency, dissent membership, role uniqueness, AND the
    # gate-override consistency rules.
    assert_spar_invariants(spar_review)
    return spar_review


def reviews_to_dict(review: SPARReview) -> dict[str, Any]:
    """JSON-serializable wire shape for `runs/<topic>/spar_review.json`."""
    return {
        "submission_id": review.submission_id,
        "verdict": review.verdict,
        "reviews": [
            {
                "judge_role": r.judge_role,
                "model": r.model,
                "verdict": r.verdict,
                "score": r.score,
                "rationale": r.rationale,
                "flagged_claims": list(r.flagged_claims),
            }
            for r in review.reviews
        ],
        "dissent": (
            {
                "judge_role": review.dissent.judge_role,
                "verdict": review.dissent.verdict,
                "rationale": review.dissent.rationale,
                "flagged_claims": list(review.dissent.flagged_claims),
            }
            if review.dissent else None
        ),
        "final_judge_resolution": review.final_judge_resolution,
        "gate_override": (
            {
                "pre_gate_verdict": review.gate_override.pre_gate_verdict,
                "failed_trace_count": review.gate_override.failed_trace_count,
                "rationale": review.gate_override.rationale,
            }
            if review.gate_override else None
        ),
        "prompt_version": PROMPT_VERSION,
    }
