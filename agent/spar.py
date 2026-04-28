"""SPAR — Structured Panel Adjudication Review.

Three role-bound LLM judges adjudicate a ClaimGraph + its citation traces:

  Evidence Auditor  — scrutinizes whether each claim is supported by its
                      cited evidence (trace failures, numeric mismatches,
                      role/claim consistency). Does NOT debate the
                      domain merit — that's the Domain Skeptic.
  Domain Skeptic    — domain expert critic. Looks for over-claiming,
                      missing caveats, mechanism-inflation,
                      off-topic drift. Does NOT verify citations.
  Final Judge       — integrates both prior reviews, votes independently,
                      and EXPLICITLY weighs dissent in the rationale.

Each judge votes accept/reject. The verdict is the deterministic
`compute_spar_verdict` tally — Final Judge is one of three votes, not
an override. Dissent (the minority voice in any 2-1 split) is always
published per `SPARReview` schema invariants.

Auditor + Skeptic run in parallel; Final Judge runs after both so it
can see them as panel context. Mock-tested via httpx.MockTransport;
opt-in live smoke lives in `scripts/e2e_spar_smoke.py` (Day 4.4).
"""
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
    JudgeReview,
    JudgeRole,
    SPARReview,
    SPARVerdict,
    assert_spar_invariants,
    compute_spar_verdict,
)

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
    """Raised when a judge response can't be parsed into a JudgeReview, or
    when the panel can't be assembled into a structurally valid SPARReview."""


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


def render_brief(
    graph: ClaimGraph,
    traces: Sequence[CitationTrace],
    *,
    topic: str,
    submission_id: str,
) -> str:
    """Render the claim graph + traces as a judge-readable text block.

    Public so tests can inspect prompt determinism + run logs can show
    exactly what the judges saw.
    """
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
    return (
        f"TOPIC: {topic}\n"
        f"SUBMISSION ID: {submission_id}\n\n"
        f"{thesis_line}\n\n"
        f"CLAIMS ({len(graph.claims)}):\n{claims_block}\n\n"
        f"CITATION TRACES ({len(traces)}):\n{traces_block}"
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
    """Validate the LLM's JSON against the JudgeReview schema.

    Raises SPARError for malformed output (the panel can't proceed
    without three valid reviews; caller can retry the whole SPAR pass).
    """
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
    flagged = tuple(c for c in flagged_raw if isinstance(c, str))
    return JudgeReview(
        judge_role=judge_role, model=model, verdict=verdict,
        score=raw_score, rationale=rationale.strip(),
        flagged_claims=flagged,
    )


async def _run_judge(
    role: JudgeRole,
    user_prompt: str,
    *,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient,
    ledger: CostLedger | None,
    temperature: float,
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
    )
    return _parse_judge_review(
        response.parsed, judge_role=role, model=response.model,
    )


# --- Dissent identification ----------------------------------------------


def _identify_dissent(
    reviews: tuple[JudgeReview, JudgeReview, JudgeReview],
    verdict: SPARVerdict,
) -> JudgeReview | None:
    """Return the minority-voice review for a 2-1 split, else None.

    Unanimous (3-0 / 0-3) → None. The schema invariant
    `assert_spar_invariants` re-validates this matches the votes.
    """
    if verdict in ("accept_clean", "reject_critical"):
        return None
    minority_verdict = "reject" if verdict == "accept_caveated" else "accept"
    return next((r for r in reviews if r.verdict == minority_verdict), None)


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
) -> SPARReview:
    """Run the 3-judge panel; return a structurally valid SPARReview.

    Auditor + Skeptic run in parallel (independent inputs). Final Judge
    runs after both so it can see their reviews as panel context.

    Raises SPARError on any judge parse/transport failure — a caller
    that wants resilience can wrap with retry, but the default is
    fail-loud so trust-spine failures don't get silently swallowed.
    """
    base_brief = render_brief(
        graph, traces, topic=topic, submission_id=submission_id,
    )

    own_client = client is None
    c = client or httpx.AsyncClient()
    try:
        auditor, skeptic = await asyncio.gather(
            _run_judge(
                "evidence_auditor", base_brief,
                chain=chain, client=c, ledger=ledger,
                temperature=temperature,
            ),
            _run_judge(
                "domain_skeptic", base_brief,
                chain=chain, client=c, ledger=ledger,
                temperature=temperature,
            ),
        )
        final_user_prompt = (
            base_brief + "\n\n" + _render_panel_context(auditor, skeptic)
        )
        final_judge = await _run_judge(
            "final_judge", final_user_prompt,
            chain=chain, client=c, ledger=ledger,
            temperature=temperature,
        )
    finally:
        if own_client:
            await c.aclose()

    reviews = (auditor, skeptic, final_judge)
    verdict = compute_spar_verdict(reviews)
    dissent = _identify_dissent(reviews, verdict)
    spar_review = SPARReview(
        submission_id=submission_id,
        reviews=reviews,
        verdict=verdict,
        dissent=dissent,
        final_judge_resolution=final_judge.rationale,
    )
    # Defense-in-depth: the schema invariant re-checks vote-vs-verdict
    # consistency, dissent membership, role uniqueness. A bug in
    # _identify_dissent or compute_spar_verdict surfaces here.
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
        "prompt_version": PROMPT_VERSION,
    }
