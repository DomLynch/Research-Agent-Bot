"""Synthesis quality audit — Day 10.5 — Q1-Q7 against the 7-paper corpus.

Audits a rendered SynthesisPaper against the deterministic
quality-checklist in `agent/prompts/judge_quality_checklist.md`.
Each question is keyed to a specific reference paper from
`docs/quality-reference/metformin/README.md`.

Day 10 ship gate: score ≥ 8.5/10 AND no failure on Q1, Q3, Q5
(the load-bearing trust-spine questions).

All checks are deterministic regex / anchor inspections — no LLM in
the audit loop. The synthesis layer's LLM contracts already enforce
the per-sentence claim binding; this module verifies those contracts
were honored end-to-end on the rendered paper.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from agent.synthesis_schemas import (
    QualityCheckResult,
    ReceiptSummary,
    SynthesisPaper,
    SynthesisQualityAudit,
)

__all__ = [
    "audit_synthesis_paper",
    "Q_LOAD_BEARING_IDS",
    "AUDIT_VERSION",
    "DAY10_SCORE_FLOOR",
]

AUDIT_VERSION = "synthesis-audit/2026-04-29"
DAY10_SCORE_FLOOR = 8.5

Q_LOAD_BEARING_IDS = (
    "Q1-konopka-p008-hedging",
    "Q3-mohammed-direct-vs-indirect",
    "Q5-mohammed-healthspan-discipline",
)


# --- Helpers --------------------------------------------------------------


_PVALUE_RE = re.compile(r"\bp\s*([=<>])\s*0?\.(\d+)", re.IGNORECASE)
_NUMERIC_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_TRANSITION_PHRASES = (
    "mechanistically",
    "in vitro",
    "preclinically",
    "in contrast",
    "however,",
    "by contrast",
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _split_paragraphs(body: str) -> list[str]:
    """Split markdown into paragraphs (separated by blank lines)."""
    return [p.strip() for p in _PARAGRAPH_RE.split(body) if p.strip()]


# --- Q1 — Konopka borderline-p hedging ------------------------------------


def _check_q1(paper: SynthesisPaper) -> QualityCheckResult:
    """No "significant"/"demonstrated"/"showed"/"established" within
    80 chars of any p-value ≥ 0.05 in the paper body."""
    body = paper.body_md
    bad_words = ("significant", "demonstrated", "showed", "established")
    failures: list[str] = []
    for m in _PVALUE_RE.finditer(body):
        op, digits = m.group(1), m.group(2)
        try:
            value = float(f"0.{digits}")
        except ValueError:
            continue
        # Borderline p ≥ 0.05 with op `=` or `>` (i.e. not significant)
        if op in {"=", ">"} and value >= 0.05:
            window_start = max(0, m.start() - 80)
            window_end = min(len(body), m.end() + 80)
            window = body[window_start:window_end].lower()
            for word in bad_words:
                if word in window:
                    failures.append(
                        f"'{word}' near p{op}0.{digits}: ...{body[window_start:window_end].strip()}..."
                    )
                    break
    return QualityCheckResult(
        question_id="Q1-konopka-p008-hedging",
        question="Borderline p-values must not be rounded to 'significant'",
        passed=not failures,
        detail=(
            "no borderline p-value rounded to significant"
            if not failures else "; ".join(failures[:2])
        ),
    )


# --- Q2 — Witham null acknowledgment --------------------------------------


_NULL_LANGUAGE = (
    "no significant difference",
    "did not improve",
    "did not reduce",
    "did not differ",
    "null",
    "no benefit",
    "comparable risk",
    "comparable",
)


def _check_q2(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """For every null-effect receipt, the paper must acknowledge the
    null in the Synthesis or Tensions section."""
    null_receipts = [r for r in receipts if r.effect_direction == "null"]
    if not null_receipts:
        return QualityCheckResult(
            question_id="Q2-witham-null-acknowledgment",
            question="Null primary endpoints must be acknowledged",
            passed=True, detail="no null receipts in corpus",
        )
    syn_or_tension = "\n".join(
        s.body_md for s in paper.sections
        if s.name in ("synthesis", "tensions")
    )
    syn_norm = _normalize(syn_or_tension)
    failures: list[str] = []
    for r in null_receipts:
        rid_present = r.receipt_id in syn_or_tension
        any_null_phrase = any(
            phrase in syn_norm for phrase in _NULL_LANGUAGE
        )
        if rid_present and not any_null_phrase:
            failures.append(
                f"{r.receipt_id} cited but no null-language phrase in section"
            )
        elif not rid_present:
            # Receipt is null but never cited at all in synthesis/tensions
            failures.append(
                f"{r.receipt_id} (null) not cited in synthesis/tensions"
            )
    return QualityCheckResult(
        question_id="Q2-witham-null-acknowledgment",
        question="Null primary endpoints must be acknowledged",
        passed=not failures,
        detail=(
            f"{len(null_receipts)} null receipts, all acknowledged"
            if not failures else "; ".join(failures[:2])
        ),
    )


# --- Q3 — Mohammed direct vs indirect separation --------------------------


def _check_q3(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """For every paragraph in the Synthesis section that anchors on
    mixed directness (some direct, some mechanistic/indirect), require
    a transition phrase."""
    syn_section = next(
        (s for s in paper.sections if s.name == "synthesis"), None,
    )
    if syn_section is None:
        return QualityCheckResult(
            question_id="Q3-mohammed-direct-vs-indirect",
            question="Mixed-directness paragraphs need transition language",
            passed=True, detail="no synthesis section",
        )
    receipts_by_id = {r.receipt_id: r for r in receipts}
    failures: list[str] = []
    # Each anchor in the synthesis section is one sentence; check
    # mixed-directness anchor sets.
    for anchor in syn_section.anchors:
        directnesses = {
            receipts_by_id[rid].directness
            for rid in anchor.receipt_ids
            if rid in receipts_by_id
        }
        if "direct" in directnesses and (
            "mechanistic" in directnesses or "indirect" in directnesses
        ):
            sentence_norm = _normalize(anchor.sentence)
            if not any(t in sentence_norm for t in _TRANSITION_PHRASES):
                failures.append(
                    f"mixed-directness sentence missing transition: {anchor.sentence[:80]}"
                )
    return QualityCheckResult(
        question_id="Q3-mohammed-direct-vs-indirect",
        question="Mixed-directness paragraphs need transition language",
        passed=not failures,
        detail=(
            "no mixed-directness paragraphs need correction"
            if not failures else "; ".join(failures[:2])
        ),
    )


# --- Q4 — MILES replication gap -------------------------------------------


_REPLICATION_PHRASES = (
    "remains to be validated",
    "single-trial",
    "single trial",
    "single-cohort",
    "replication required",
    "external validation",
    "small sample",
    "needs replication",
)


def _check_q4(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """If thesis references ≤2 receipts AND the corpus is thin
    (≤4 claims each), Limitations section must include a replication
    phrase."""
    n_receipts = len(paper.thesis.receipt_ids_referenced)
    thin_corpus = all(r.n_claims <= 4 for r in receipts)
    if n_receipts > 2 or not thin_corpus:
        return QualityCheckResult(
            question_id="Q4-miles-replication-gap",
            question="Single-trial / thin theses must name replication gap",
            passed=True,
            detail=f"thesis references {n_receipts} receipts, corpus is "
                   f"{'thin' if thin_corpus else 'rich'}",
        )
    lim_section = next(
        (s for s in paper.sections if s.name == "limitations"), None,
    )
    lim_norm = _normalize(lim_section.body_md) if lim_section else ""
    has_phrase = any(p in lim_norm for p in _REPLICATION_PHRASES)
    return QualityCheckResult(
        question_id="Q4-miles-replication-gap",
        question="Single-trial / thin theses must name replication gap",
        passed=has_phrase,
        detail=(
            "replication phrase present"
            if has_phrase
            else "no replication phrase in Limitations"
        ),
    )


# --- Q5 — Mohammed healthspan discipline ----------------------------------


_HEALTHSPAN_CLAIMS = (
    "extends lifespan",
    "longevity benefit",
    "increases healthspan",
    "geroprotective",
    "extends life",
)
_HEDGE_TOKENS = (
    "may",
    "remains unproven",
    "indirect",
    "potentially",
    "could",
    "suggests",
)


def _check_q5(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """No bare healthspan/longevity claims unless a direct A1/A2
    longevity receipt is present, OR a hedge qualifier is nearby."""
    has_direct_longevity = any(
        r.outcome_class == "longevity"
        and r.directness == "direct"
        and r.evidence_tier in {"A1", "A2"}
        for r in receipts
    )
    body_norm = _normalize(paper.body_md)
    failures: list[str] = []
    for claim in _HEALTHSPAN_CLAIMS:
        if claim not in body_norm:
            continue
        if has_direct_longevity:
            # Direct longevity evidence in corpus → claim is fine.
            continue
        # No direct longevity evidence — claim needs a hedge nearby
        idx = body_norm.find(claim)
        window = body_norm[max(0, idx - 80):idx + len(claim) + 80]
        if not any(h in window for h in _HEDGE_TOKENS):
            failures.append(f"'{claim}' without hedge or direct longevity receipt")
    return QualityCheckResult(
        question_id="Q5-mohammed-healthspan-discipline",
        question="Healthspan claims need direct longevity receipt OR hedge",
        passed=not failures,
        detail=(
            "no unhedged healthspan claims"
            if not failures else "; ".join(failures[:2])
        ),
    )


# --- Q6 — Witham adverse-event surfacing ----------------------------------


def _check_q6(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    safety_receipts = [r for r in receipts if r.outcome_class == "safety"]
    if not safety_receipts:
        return QualityCheckResult(
            question_id="Q6-witham-adverse-event-surfacing",
            question="Safety receipts must appear in Tensions or Limitations",
            passed=True, detail="no safety receipts in corpus",
        )
    target_text = "\n".join(
        s.body_md for s in paper.sections
        if s.name in ("tensions", "limitations")
    )
    failures = [
        r.receipt_id for r in safety_receipts
        if r.receipt_id not in target_text
    ]
    return QualityCheckResult(
        question_id="Q6-witham-adverse-event-surfacing",
        question="Safety receipts must appear in Tensions or Limitations",
        passed=not failures,
        detail=(
            f"{len(safety_receipts)} safety receipts, all surfaced"
            if not failures else f"missing: {failures}"
        ),
    )


# --- Q7 — MASTERS numeric fidelity ----------------------------------------


def _check_q7(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """Every numeric token in the rendered paper must appear in some
    receipt's p_values or thesis_text. Closes any path that bypassed
    the per-sentence validator."""
    receipt_corpus = _normalize(" ".join(
        " ".join(r.p_values) + " " + r.thesis_text
        for r in receipts
    ))
    failures: list[str] = []
    for m in _NUMERIC_RE.finditer(paper.body_md):
        tok = _normalize(m.group(0))
        if tok not in receipt_corpus:
            failures.append(tok)
    # De-duplicate
    failures = sorted(set(failures))
    return QualityCheckResult(
        question_id="Q7-masters-numeric-fidelity",
        question="Every numeric token must come from some receipt",
        passed=not failures,
        detail=(
            "no novel numerics"
            if not failures else f"novel tokens: {failures[:5]}"
        ),
    )


# --- Aggregator -----------------------------------------------------------


def audit_synthesis_paper(
    paper: SynthesisPaper,
    receipts: Sequence[ReceiptSummary],
) -> SynthesisQualityAudit:
    """Run all 7 checks and aggregate.

    score = passed_count / total_count * 10
    Day 10 ship: score ≥ 8.5 AND no failure on the load-bearing IDs.
    """
    checks = (
        _check_q1(paper),
        _check_q2(paper, receipts),
        _check_q3(paper, receipts),
        _check_q4(paper, receipts),
        _check_q5(paper, receipts),
        _check_q6(paper, receipts),
        _check_q7(paper, receipts),
    )
    passed = sum(1 for c in checks if c.passed)
    score = passed / len(checks) * 10
    load_bearing_pass = all(
        c.passed for c in checks if c.question_id in Q_LOAD_BEARING_IDS
    )
    if score >= DAY10_SCORE_FLOOR and load_bearing_pass:
        notes = (
            f"{passed}/{len(checks)} checks passed; ship-criterion met "
            f"(score ≥ {DAY10_SCORE_FLOOR} AND load-bearing Q1/Q3/Q5 pass)"
        )
    elif not load_bearing_pass:
        failed_load = [
            c.question_id for c in checks
            if c.question_id in Q_LOAD_BEARING_IDS and not c.passed
        ]
        notes = (
            f"{passed}/{len(checks)} checks passed; LOAD-BEARING FAIL "
            f"{failed_load} — ship blocked regardless of score"
        )
    else:
        notes = (
            f"{passed}/{len(checks)} checks passed; score {score:.1f} below "
            f"floor {DAY10_SCORE_FLOOR}"
        )
    return SynthesisQualityAudit(
        submission_id=paper.submission_id,
        checks=checks,
        score=round(score, 2),
        notes=notes,
    )
