"""Synthesis thesis tournament — Day 10.3.

Given N claim receipts and a TensionMatrix, propose K thesis
candidates via LLM, validate each candidate against the trust
contract, and pick the winner deterministically.

The trust contract for synthesis theses (stricter than the schema-
level invariants in synthesis_schemas.assert_synthesis_invariants):

  1. text non-empty, ≤30 words (the reference papers' theses are
     14-25 words; longer theses overclaim)
  2. receipt_ids_referenced ⊂ input receipt_ids (no LLM-fabricated
     ids — the synthesis-layer analogue of spar.py's
     `_validate_flagged_against_graph`)
  3. ≥3 distinct receipts referenced (single-trial generalization
     is the most common synthesis failure mode; require breadth)
  4. ≥1 non-orthogonal tension addressed (when the matrix has any
     non-orthogonal pairs — otherwise the synthesis is just a list,
     not a synthesis)
  5. no numerics absent from any receipt's `p_values` or thesis_text
     (no new numerics may enter the synthesis layer)

Picker rank (lower tuple = better):
  (-receipts_referenced, -tensions_addressed, +word_count, claim_id)

So: most receipts wins, more tensions addressed wins, brevity wins.
Ties broken alphabetically by candidate text (deterministic re-runs).

Failure mode: if no candidate validates, fall back to a deterministic
stub thesis ("[topic] evidence is mixed across the [N] receipts
examined") so the synthesis paper still ships. The stub carries an
explicit `picker_rationale = "all candidates rejected"` so audit
code can flag the run for re-prompting.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.synthesis_schemas import (
    ReceiptSummary,
    SynthesisThesis,
    SynthesisThesisCandidate,
    TensionMatrix,
)

__all__ = [
    "THESIS_PROMPT_VERSION",
    "ThesisRejection",
    "build_thesis_user_prompt",
    "validate_thesis_candidate",
    "pick_synthesis_thesis",
    "synthesize_thesis",
    "SYSTEM_PROMPT",
    "build_fallback_thesis",
]

THESIS_PROMPT_VERSION = "synthesis-thesis/2026-04-29"

_MAX_THESIS_WORDS = 30
_REQUIRED_RECEIPT_REFERENCES = 3
_DEFAULT_K = 3


# --- Prompts --------------------------------------------------------------


SYSTEM_PROMPT = """You synthesize multiple structured EVIDENCE RECEIPTS
into ONE cross-source thesis sentence.

Each receipt represents one source-paper cluster from a real
retrieval. You will receive: receipts (with id, thesis text, outcome
class, evidence tier, directness, effect direction, key p-values) and
a tension matrix (which receipt-pairs agree, disagree, or have an
indirectness gap).

Output ONE JSON object with this exact shape:

{
  "candidates": [
    {
      "text": "<≤30-word integrating thesis sentence>",
      "receipt_ids_referenced": ["r-a", "r-b", "r-c"],
      "tensions_addressed": ["<verbatim tension summary from input>"]
    },
    ...K candidates total
  ]
}

Candidate rules (every candidate must satisfy all):
1. ≤30 words. Reference papers are 14-25 words; longer means overclaim.
2. Reference at least 3 distinct receipt_ids from the input — synthesis
   means "across sources", not "single trial wrapped in prose".
3. Address at least 1 non-orthogonal tension from the input matrix.
   Name the tension by its summary text (verbatim copy).
4. Do NOT introduce numerics absent from the receipts. If you cite a
   p-value or HR, it must come from one of the receipt's `p_values` or
   `thesis_text` fields.
5. Use hedge language for contested evidence. If the matrix shows
   a disagreement or null_vs_positive tension, the thesis must NOT
   claim consensus.

Diversity rules (across the K candidates):
- Candidates should differ in framing, not just word choice. Prefer:
  candidate 1 emphasizes the strongest agreement,
  candidate 2 surfaces the strongest tension,
  candidate 3 frames the indirectness gap.

Output JSON only. No prose outside the JSON."""


def build_thesis_user_prompt(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    topic: str,
    k: int = _DEFAULT_K,
) -> str:
    """Render the user-message body deterministically. Same inputs →
    same prompt → same LLM response (when the provider honors seed)."""
    lines: list[str] = [
        f"Topic: {topic}",
        f"K (number of candidates required): {k}",
        "",
        "RECEIPTS:",
    ]
    for r in receipts:
        lines.append(
            f"  - id: {r.receipt_id}\n"
            f"    thesis: {r.thesis_text}\n"
            f"    outcome_class: {r.outcome_class}\n"
            f"    directness: {r.directness}; tier: {r.evidence_tier}\n"
            f"    effect_direction: {r.effect_direction}\n"
            f"    spar_verdict: {r.spar_verdict}\n"
            f"    p_values: {list(r.p_values)}"
        )

    non_orth = matrix.non_orthogonal()
    lines.extend(["", "TENSIONS (non-orthogonal pairs):"])
    if not non_orth:
        lines.append("  (no non-orthogonal pairs — receipts cover distinct outcomes)")
    else:
        for t in non_orth:
            lines.append(
                f"  - {t.kind} ({t.outcome_class}, severity {t.severity}): {t.summary}"
            )

    lines.extend(["", f"Output {k} thesis candidates per the system prompt."])
    return "\n".join(lines)


# --- Validation -----------------------------------------------------------


# Numeric tokens we screen for "no new numerics" — p-values, percentages,
# HR/OR/RR/etc. The check is: every numeric in the candidate text must
# appear in at least one receipt's union(p_values, thesis_text).
_NUMERIC_TOKEN_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


@dataclass(frozen=True, slots=True)
class ThesisRejection:
    """Why a candidate was rejected. Kept on the picker output for
    audit visibility."""
    candidate_text: str
    reason: str


def _extract_numerics(text: str) -> list[str]:
    """Pull every numeric token out of `text` for substring comparison."""
    return [_normalize(m.group(0)) for m in _NUMERIC_TOKEN_RE.finditer(text)]


def _receipt_numeric_corpus(receipts: Sequence[ReceiptSummary]) -> str:
    """Concatenated normalized text of all receipts' p_values + thesis."""
    parts: list[str] = []
    for r in receipts:
        parts.extend(r.p_values)
        parts.append(r.thesis_text)
    return _normalize(" ".join(parts))


def validate_thesis_candidate(
    candidate: SynthesisThesisCandidate,
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
) -> ThesisRejection | None:
    """Pure deterministic validator. None = candidate is acceptable;
    a ThesisRejection means the candidate fails the contract.

    Order of checks: cheap and load-bearing first so failures are
    informative.
    """
    # 1. Text shape
    if not candidate.text.strip():
        return ThesisRejection(candidate.text, "empty_text")
    if candidate.word_count > _MAX_THESIS_WORDS:
        return ThesisRejection(
            candidate.text,
            f"too_long:{candidate.word_count}>{_MAX_THESIS_WORDS}",
        )

    # 2. Receipt ids must be a subset of the input
    receipt_ids = {r.receipt_id for r in receipts}
    referenced = set(candidate.receipt_ids_referenced)
    unknown = referenced - receipt_ids
    if unknown:
        return ThesisRejection(
            candidate.text,
            f"unknown_receipt_ids:{sorted(unknown)}",
        )

    # 3. ≥3 distinct receipts
    if len(referenced) < _REQUIRED_RECEIPT_REFERENCES:
        return ThesisRejection(
            candidate.text,
            f"too_few_receipts:{len(referenced)}<{_REQUIRED_RECEIPT_REFERENCES}",
        )

    # 4. ≥1 non-orthogonal tension addressed (only if matrix has any).
    # Day 10.9 — tolerate paraphrase: a candidate addresses a tension
    # if EITHER (a) `tensions_addressed` contains the verbatim summary,
    # OR (b) `receipt_ids_referenced` covers both receipt_ids of any
    # non-orthogonal pair (the thesis is integrating that pair). Reason:
    # with multi-receipt corpora the tension summaries embed long
    # receipt-id prefixes (e.g. `metformin-multi-001-2026-04-29T...-c06`)
    # and LLMs almost always paraphrase to compact form, leaving the
    # verbatim-only rule unsatisfiable on heterogeneous real corpora.
    non_orth_pairs = matrix.non_orthogonal()
    if non_orth_pairs:
        non_orth_summaries = {t.summary for t in non_orth_pairs}
        addressed_set = set(candidate.tensions_addressed)
        verbatim_match = bool(addressed_set & non_orth_summaries)
        ref_set = set(candidate.receipt_ids_referenced)
        pair_covered = any(
            t.receipt_a_id in ref_set and t.receipt_b_id in ref_set
            for t in non_orth_pairs
        )
        if not (verbatim_match or pair_covered):
            return ThesisRejection(
                candidate.text,
                "no_tension_addressed",
            )

    # 5. No new numerics
    candidate_numerics = _extract_numerics(candidate.text)
    if candidate_numerics:
        corpus = _receipt_numeric_corpus(receipts)
        for tok in candidate_numerics:
            if tok not in corpus:
                return ThesisRejection(
                    candidate.text,
                    f"novel_numeric:{tok!r}",
                )

    return None


# --- Picker ---------------------------------------------------------------


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def pick_synthesis_thesis(
    candidates: Sequence[SynthesisThesisCandidate],
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    topic: str = "",
) -> SynthesisThesis:
    """Validate every candidate, pick the best valid one, build a
    SynthesisThesis with rejected candidates preserved for audit.

    Ranking key (lower is better):
      (-receipts_referenced_count, -tensions_addressed_count,
       +word_count, candidate.text)

    So more receipts wins → more tensions wins → shorter wins → text
    alpha order is the deterministic tiebreaker.

    When NO candidate validates, falls back to a deterministic stub
    thesis (`build_fallback_thesis`) and records "all candidates
    rejected" in the picker rationale.
    """
    accepted: list[SynthesisThesisCandidate] = []
    rejected: list[SynthesisThesisCandidate] = []
    rejection_reasons: list[ThesisRejection] = []

    for cand in candidates:
        rej = validate_thesis_candidate(cand, receipts, matrix)
        if rej is None:
            accepted.append(cand)
        else:
            rejected.append(cand)
            rejection_reasons.append(rej)

    if not accepted:
        return build_fallback_thesis(
            receipts, matrix, topic=topic,
            rejected=tuple(rejected),
            rejection_reasons=tuple(rejection_reasons),
        )

    def sort_key(c: SynthesisThesisCandidate) -> tuple[int, int, int, str]:
        return (
            -len(set(c.receipt_ids_referenced)),
            -len(set(c.tensions_addressed)),
            c.word_count,
            c.text,
        )

    accepted_sorted = sorted(accepted, key=sort_key)
    winner = accepted_sorted[0]
    losers = tuple(accepted_sorted[1:]) + tuple(rejected)

    rationale_parts = [
        f"picked from {len(candidates)} candidates",
        f"{len(set(winner.receipt_ids_referenced))} receipts",
        f"{len(set(winner.tensions_addressed))} tensions",
        f"{winner.word_count} words",
    ]
    if rejection_reasons:
        # Surface up to 2 rejection reasons in the rationale for
        # visibility — full list is in `rejected_candidates`.
        sample = "; ".join(r.reason for r in rejection_reasons[:2])
        rationale_parts.append(f"{len(rejection_reasons)} rejected ({sample})")

    return SynthesisThesis(
        text=winner.text,
        receipt_ids_referenced=winner.receipt_ids_referenced,
        tensions_addressed=winner.tensions_addressed,
        rejected_candidates=losers,
        picker_rationale=" | ".join(rationale_parts),
    )


def build_fallback_thesis(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    topic: str = "",
    rejected: Sequence[SynthesisThesisCandidate] = (),
    rejection_reasons: Sequence[ThesisRejection] = (),
) -> SynthesisThesis:
    """Deterministic stub thesis when no candidate validates.

    Shape: "[topic] evidence is mixed across [N] receipts examined,
    with [tension shape] across direct human trials and mechanistic
    studies." Conservative by design — the audit-checklist Q1
    (borderline-p hedging) and Q5 (indirect-for-longevity discipline)
    must still pass.
    """
    n = len(receipts)
    non_orth = matrix.non_orthogonal()
    if non_orth:
        tensions_clause = (
            f"with {len(non_orth)} non-orthogonal tension(s) across the cluster"
        )
        addressed = (non_orth[0].summary,)
    else:
        tensions_clause = "with receipts covering distinct outcomes"
        addressed = ()
    text = (
        f"{topic or 'evidence'} synthesis across {n} receipts is mixed, "
        f"{tensions_clause}; the integrating thesis defaults to a "
        f"hedged summary because all LLM candidates failed validation."
    )
    rationale = (
        f"all {len(rejected)} candidates rejected — fallback stub used"
        if rejected else "no candidates supplied — fallback stub used"
    )
    return SynthesisThesis(
        text=text,
        receipt_ids_referenced=tuple(r.receipt_id for r in receipts),
        tensions_addressed=addressed,
        rejected_candidates=tuple(rejected),
        picker_rationale=rationale,
    )


# --- LLM-driven proposal --------------------------------------------------


def _parse_candidates_from_response(
    parsed: dict,
) -> list[SynthesisThesisCandidate]:
    """Parse the LLM JSON response into SynthesisThesisCandidate
    objects. Defensive — silently drops malformed entries (the
    picker handles "no valid candidate" with a fallback stub)."""
    raw = parsed.get("candidates")
    if not isinstance(raw, list):
        return []
    out: list[SynthesisThesisCandidate] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        ids = entry.get("receipt_ids_referenced", [])
        tensions = entry.get("tensions_addressed", [])
        if not isinstance(text, str) or not isinstance(ids, list):
            continue
        if not isinstance(tensions, list):
            tensions = []
        out.append(SynthesisThesisCandidate(
            text=text.strip(),
            receipt_ids_referenced=tuple(
                str(i) for i in ids if isinstance(i, str)
            ),
            tensions_addressed=tuple(
                str(t) for t in tensions if isinstance(t, str)
            ),
            word_count=_word_count(text),
        ))
    return out


async def synthesize_thesis(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    chain: Sequence[CallSpec],
    topic: str,
    k: int = _DEFAULT_K,
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
) -> SynthesisThesis:
    """Drive the full thesis tournament: LLM proposes K candidates,
    code disposes, picker selects.

    `seed` (Day 9.4 plumbing carried over): when set, forwarded to
    chat_json so the LLM call is reproducible. `ledger` accumulates
    cost.

    Returns a SynthesisThesis — ALWAYS, even when every candidate is
    rejected (falls back to deterministic stub). The synthesis writer
    can render either way.
    """
    user_prompt = build_thesis_user_prompt(
        receipts, matrix, topic=topic, k=k,
    )
    response = await chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        chain=chain,
        client=client,
        ledger=ledger,
        temperature=0.0,  # synthesis-layer determinism contract
        seed=seed,
    )
    parsed = response.parsed if isinstance(response.parsed, dict) else {}
    candidates = _parse_candidates_from_response(parsed)
    return pick_synthesis_thesis(
        candidates, receipts, matrix, topic=topic,
    )
