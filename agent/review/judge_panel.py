"""Three-agent peer review panel for Researka submissions.

Architecture:
  Methodology Judge  — scores search strategy, scope, directness, PRISMA compliance
  Evidence Judge     — scores bundle quality, numeric grounding, citation accuracy
  Claims Judge       — scores overclaim risk, verb-role discipline, hedge calibration
         |
         v
  Adjudicator  —  synthesizes -> {verdict: accept|revise|reject, reasons, required_fixes}

Inputs:  draft_artifact (dict from drafter.draft())
Outputs: PanelReview (structured JSON)

Not wired into production yet. Callable via:
    from agent.review.judge_panel import review_draft
    review = review_draft(draft_artifact)
"""
from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from agent.provider import MimoClient


# ---- Data contracts ----

Axis = Literal[
    "search_strategy", "scope_discipline", "directness", "prisma_compliance",
    "bundle_quality", "numeric_grounding", "citation_accuracy",
    "overclaim_risk", "verb_role_discipline", "hedge_calibration",
]

JudgeRole = Literal["methodology", "evidence", "claims"]

Verdict = Literal["accept", "minor_revision", "major_revision", "reject"]


class AxisScore(TypedDict):
    axis: str          # one of Axis values
    score: int         #1-5
    rationale: str


class JudgeReview(TypedDict):
    role: JudgeRole
    axis_scores: list[AxisScore]
    strengths: list[str]
    weaknesses: list[str]
    recommendation: Verdict
    rationale: str


class PanelReview(TypedDict):
    judges: list[JudgeReview]
    adjudicated_verdict: Verdict
    adjudicator_rationale: str
    required_fixes: list[str]   # specific actionable items
    aggregate_score: float      # mean of all axis scores, 1.0-5.0


# ---- Judge prompts ----

_METHODOLOGY_RUBRIC = """You are a peer-review methodology judge for a rapid evidence synthesis.

Score the draft on FOUR axes (1-5 each):

search_strategy:
  5 = explicit search date, database list, full query strings, flow counts
  3 = generic "we searched" language, some details present
  1 = no discernible search methodology described

scope_discipline:
  5 = retained evidence tightly matches declared criteria (year, population, study type)
  3 = scope mostly followed, some off-scope items leak in
  1 = scope declared but ignored -- major mismatch between criteria and bundle

directness:
  5 = bundle is 80%+ directly about the declared topic/intervention/population
  3 = mix of direct and indirect; tangential items present
  1 = bundle dominated by indirect or off-topic material

prisma_compliance:
  5 = PRISMA-style flow diagram or counts present (retrieved -> screened -> included with reasons)
  3 = partial flow (counts but missing exclusion reasons)
  1 = no flow accounting at all

Return JSON only, exact shape:
{
  "role": "methodology",
  "axis_scores": [
    {"axis": "search_strategy", "score": 1-5, "rationale": "short explanation"},
    {"axis": "scope_discipline", "score": 1-5, "rationale": "..."},
    {"axis": "directness", "score": 1-5, "rationale": "..."},
    {"axis": "prisma_compliance", "score": 1-5, "rationale": "..."}
  ],
  "strengths": ["bullet 1", "bullet 2"],
  "weaknesses": ["bullet 1", "bullet 2"],
  "recommendation": "accept" | "minor_revision" | "major_revision" | "reject",
  "rationale": "one paragraph explaining the recommendation"
}
"""


_EVIDENCE_RUBRIC = """You are a peer-review evidence judge for a rapid evidence synthesis.

Score the draft on THREE axes (1-5 each):

bundle_quality:
  5 = >=12 sources, mix of reviews + primary + trials, recent, high-quality venues
  3 = 8-11 sources, reasonable quality, moderate balance
  1 = <8 sources OR dominated by low-quality/non-peer-reviewed/protocol-only items

numeric_grounding:
  5 = Key Findings cite multiple specific numeric effects (HR, %, p, N) with source references
  3 = Some numeric claims present but uneven or generic
  1 = No numeric claims; prose only

citation_accuracy:
  5 = Every cited claim traces to the referenced source; no hallucinated numbers
  3 = Mostly accurate; some claims hard to verify in sources
  1 = Multiple claims don't match sources OR fabricated numbers detectable

Return JSON only, exact shape:
{
  "role": "evidence",
  "axis_scores": [
    {"axis": "bundle_quality", "score": 1-5, "rationale": "..."},
    {"axis": "numeric_grounding", "score": 1-5, "rationale": "..."},
    {"axis": "citation_accuracy", "score": 1-5, "rationale": "..."}
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "recommendation": "accept" | "minor_revision" | "major_revision" | "reject",
  "rationale": "one paragraph"
}
"""


_CLAIMS_RUBRIC = """You are a peer-review claims judge for a rapid evidence synthesis.

Score the draft on THREE axes (1-5 each):

overclaim_risk:
  5 = Conclusions strictly bounded by evidence; no extrapolation
  3 = Minor overclaim in places; generally cautious
  1 = Significant overclaim -- conclusions go far beyond what evidence supports

verb_role_discipline:
  5 = All citation verbs match source type (published RCT -> "found/reported", registry -> "is investigating", animal -> hedged, review -> "reviews")
  3 = Mostly correct; 1-2 verb-role mismatches
  1 = Multiple verb-role violations (e.g. published RCT cited as "is evaluating")

hedge_calibration:
  5 = Hedges present where evidence is weak; absent where strong
  3 = Hedging roughly appropriate; some over- or under-hedging
  1 = Hedges missing from weak-evidence claims OR over-hedged strong evidence

Return JSON only, exact shape:
{
  "role": "claims",
  "axis_scores": [
    {"axis": "overclaim_risk", "score": 1-5, "rationale": "..."},
    {"axis": "verb_role_discipline", "score": 1-5, "rationale": "..."},
    {"axis": "hedge_calibration", "score": 1-5, "rationale": "..."}
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "recommendation": "accept" | "minor_revision" | "major_revision" | "reject",
  "rationale": "one paragraph"
}
"""


def _draft_as_review_input(draft: dict[str, Any]) -> str:
    """Format a draft artifact into review-ready text."""
    title = draft.get("title", "Untitled")
    abstract = draft.get("abstract", "")
    sections = draft.get("sections", {}) or {}
    bundle = draft.get("source_bundle", []) or []

    parts = [f"TITLE: {title}\n\nABSTRACT: {abstract}\n"]
    for heading, body in sections.items():
        parts.append(f"\n## {heading}\n\n{body}\n")
    parts.append(f"\n## Source Bundle ({len(bundle)} items)\n")
    for i, item in enumerate(bundle, start=1):
        t = (item.get("title") or "")[:120]
        y = item.get("year", "?")
        et = item.get("evidence_type", "?")
        d = item.get("directness", "?")
        card = item.get("card") or {}
        grade = card.get("evidence_grade", "?")
        parts.append(f"[{i}] ({y}) [{et}/{d}/GRADE-{grade}] {t}")
    return "\n".join(parts)


def _run_judge(
    role: JudgeRole,
    rubric: str,
    draft_text: str,
    provider: Any,
) -> JudgeReview:
    """Call MiMo with the rubric, parse response, return JudgeReview."""
    result, _ = provider.complete_json(
        system_prompt=rubric,
        user_prompt=f"Review this rapid evidence synthesis draft:\n\n{draft_text}",
    )
    return _normalize_judge_review(result, role)


def _normalize_judge_review(raw: dict[str, Any], role: JudgeRole) -> JudgeReview:
    """Coerce LLM JSON into JudgeReview shape with safe defaults."""
    axis_scores_raw = raw.get("axis_scores") or []
    axis_scores: list[AxisScore] = []
    for item in axis_scores_raw if isinstance(axis_scores_raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            score = int(item.get("score", 3))
        except (TypeError, ValueError):
            score = 3
        axis_scores.append({
            "axis": str(item.get("axis") or "unknown"),
            "score": max(1, min(score, 5)),
            "rationale": str(item.get("rationale") or "")[:500],
        })

    rec = str(raw.get("recommendation") or "minor_revision").lower()
    if rec not in ("accept", "minor_revision", "major_revision", "reject"):
        rec = "minor_revision"

    return {
        "role": role,
        "axis_scores": axis_scores,
        "strengths": [str(s)[:300] for s in (raw.get("strengths") or [])[:5]
                      if isinstance(s, str)],
        "weaknesses": [str(w)[:300] for w in (raw.get("weaknesses") or [])[:5]
                       if isinstance(w, str)],
        "recommendation": rec,  # type: ignore
        "rationale": str(raw.get("rationale") or "")[:800],
    }


_ADJUDICATOR_PROMPT = """You are the peer-review adjudicator for a rapid evidence synthesis.

Three judges have submitted their reviews. Your job:
  1. Synthesize the three verdicts into a single PANEL verdict.
  2. List required fixes (specific, actionable) in priority order.
  3. Explain the adjudication briefly.

Verdict rules:
  - If any judge says "reject" AND at least one other says "major_revision" or worse -> reject
  - If majority (2+) say "major_revision" -> major_revision
  - If majority (2+) say "minor_revision" OR any say "major_revision" -> minor_revision
  - If all three say "accept" -> accept
  - Otherwise -> minor_revision (default to caution)

Return JSON only, exact shape:
{
  "adjudicated_verdict": "accept" | "minor_revision" | "major_revision" | "reject",
  "adjudicator_rationale": "one paragraph explaining the synthesis",
  "required_fixes": [
    "specific actionable fix 1",
    "specific actionable fix 2",
    "..."
  ]
}
"""


def _adjudicate(judges: list[JudgeReview], provider: Any) -> tuple[Verdict, str, list[str]]:
    """Run the adjudicator over three judge reviews."""
    user = "Judge reviews:\n\n" + json.dumps(judges, indent=2, default=str)
    result, _ = provider.complete_json(
        system_prompt=_ADJUDICATOR_PROMPT,
        user_prompt=user,
    )
    verdict = str(result.get("adjudicated_verdict") or "minor_revision").lower()
    if verdict not in ("accept", "minor_revision", "major_revision", "reject"):
        verdict = "minor_revision"
    rationale = str(result.get("adjudicator_rationale") or "")[:1200]
    fixes_raw = result.get("required_fixes") or []
    fixes = [str(f)[:400] for f in fixes_raw[:10] if isinstance(f, str)]
    return verdict, rationale, fixes  # type: ignore


def _aggregate_score(judges: list[JudgeReview]) -> float:
    """Mean of all axis scores across all judges. Returns 1.0-5.0."""
    all_scores: list[int] = []
    for j in judges:
        for ax in j.get("axis_scores", []):
            all_scores.append(ax["score"])
    if not all_scores:
        return 0.0
    return round(sum(all_scores) / len(all_scores), 2)


# ---- Public API ----

def review_draft(
    draft: dict[str, Any],
    *,
    provider: Any | None = None,
) -> PanelReview:
    """Run the three-judge panel + adjudicator over a draft artifact.

    Args:
        draft: Draft artifact from drafter.draft() -- expects keys:
               title, abstract, sections (dict), source_bundle (list).
        provider: MimoClient (or compatible). Defaults to MimoClient.from_env().

    Returns:
        PanelReview with three judge verdicts + adjudicator verdict + fixes.

    Cost: ~4 MimoClient calls (3 judges + 1 adjudicator).
          At ~2000 input + 600 output tokens each, roughly $0.003 per review.
    """
    if provider is None:
        provider = MimoClient.from_env()

    draft_text = _draft_as_review_input(draft)

    judges: list[JudgeReview] = []
    for role, rubric in (
        ("methodology", _METHODOLOGY_RUBRIC),
        ("evidence", _EVIDENCE_RUBRIC),
        ("claims", _CLAIMS_RUBRIC),
    ):
        judges.append(_run_judge(role, rubric, draft_text, provider))  # type: ignore

    verdict, adj_rationale, fixes = _adjudicate(judges, provider)

    return {
        "judges": judges,
        "adjudicated_verdict": verdict,
        "adjudicator_rationale": adj_rationale,
        "required_fixes": fixes,
        "aggregate_score": _aggregate_score(judges),
    }
