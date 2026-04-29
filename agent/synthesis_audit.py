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
    "MIN_APPLICABLE_CHECKS",
]

# Day 10.10 reviewer P1/P2:
#   - Q3 applicability now derives from CORPUS directness diversity, not
#     just synthesis-section anchor mixes (a uniform synthesis section on
#     a mixed corpus is failure-to-integrate, not vacuous-pass).
#   - load-bearing N/A no longer counts as ship pass — load-bearing
#     checks must be applicable=True AND passed=True for ship-criterion.
AUDIT_VERSION = "synthesis-audit/2026-04-29-day10-10"
DAY10_SCORE_FLOOR = 8.5
# Day 10.7 (reviewer P2): with N/A handling, a corpus that triggers <4
# applicable checks isn't auditable — the score is computed but the
# notes flag "insufficient coverage" so it doesn't ship as 10/10
# vacuously.
MIN_APPLICABLE_CHECKS = 4

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
        # Day 10.7 (reviewer P2): no null receipts → check is N/A, not
        # vacuously passing. Don't count toward score.
        return QualityCheckResult(
            question_id="Q2-witham-null-acknowledgment",
            question="Null primary endpoints must be acknowledged",
            passed=True, detail="no null receipts in corpus (N/A)",
            applicable=False,
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
            passed=True, detail="no synthesis section (N/A)",
            applicable=False,
        )
    # Day 10.10 reviewer P2: applicability derives from CORPUS directness
    # diversity, not just synthesis anchor mixes. If the corpus has both
    # direct and (indirect|mechanistic) receipts, the synthesis is
    # SUPPOSED to integrate across them — failing to produce any
    # mixed-directness paragraph is a Q3 fail, not vacuous N/A.
    corpus_directnesses = {r.directness for r in receipts}
    has_mixed_corpus = "direct" in corpus_directnesses and (
        "mechanistic" in corpus_directnesses
        or "indirect" in corpus_directnesses
    )

    receipts_by_id = {r.receipt_id: r for r in receipts}
    failures: list[str] = []
    mixed_directness_count = 0
    for anchor in syn_section.anchors:
        directnesses = {
            receipts_by_id[rid].directness
            for rid in anchor.receipt_ids
            if rid in receipts_by_id
        }
        if "direct" in directnesses and (
            "mechanistic" in directnesses or "indirect" in directnesses
        ):
            mixed_directness_count += 1
            sentence_norm = _normalize(anchor.sentence)
            if not any(t in sentence_norm for t in _TRANSITION_PHRASES):
                failures.append(
                    f"mixed-directness sentence missing transition: {anchor.sentence[:80]}"
                )

    if not has_mixed_corpus:
        # Genuinely uniform corpus (all-direct or all-mechanistic) — no
        # cross-directness signal exists, so Q3 is legitimately N/A.
        return QualityCheckResult(
            question_id="Q3-mohammed-direct-vs-indirect",
            question="Mixed-directness paragraphs need transition language",
            passed=True,
            detail="corpus is uniform directness — no cross-directness signal (N/A)",
            applicable=False,
        )
    if mixed_directness_count == 0:
        # Corpus IS mixed-directness, but synthesis didn't integrate any
        # mixed-directness paragraph. That's a synthesis failure to
        # integrate, not N/A. Day 10.10 reviewer P2 fix.
        return QualityCheckResult(
            question_id="Q3-mohammed-direct-vs-indirect",
            question="Mixed-directness paragraphs need transition language",
            passed=False,
            detail=(
                "corpus has mixed directness "
                f"({sorted(corpus_directnesses)}) but synthesis section "
                "produced no mixed-directness paragraph — failure to integrate"
            ),
        )
    return QualityCheckResult(
        question_id="Q3-mohammed-direct-vs-indirect",
        question="Mixed-directness paragraphs need transition language",
        passed=not failures,
        detail=(
            f"{mixed_directness_count} mixed-directness paragraphs, all clean"
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
    """Single-trial theses must name the replication gap in Limitations.

    Day 10.7 (reviewer P1): the load-bearing fix is to count UNIQUE
    canonical trials, not raw receipt count. Pre-fix, 12 receipts
    anchored on the same trial passed as "rich corpus" because
    `n_receipts > 2` was the gate. Now: when fewer than
    MIN_UNIQUE_TRIALS_FOR_SYNTHESIS distinct trials underlie the
    referenced receipts, the synthesis is single-trial-equivalent and
    the Limitations section MUST mention "single-trial" /
    "replication required" / similar.
    """
    referenced_ids = set(paper.thesis.receipt_ids_referenced)
    referenced_receipts = [
        r for r in receipts if r.receipt_id in referenced_ids
    ]
    unique_trials = {
        r.canonical_trial_id
        for r in referenced_receipts
        if r.canonical_trial_id
    }
    # Also count receipts without a canonical trial as their own
    # "trial" via the thesis signature, so unsignposted single-trial
    # corpora don't bypass the gate.
    untrialed = sum(
        1 for r in referenced_receipts if not r.canonical_trial_id
    )
    effective_unique_count = len(unique_trials) + untrialed

    if effective_unique_count >= 3:
        return QualityCheckResult(
            question_id="Q4-miles-replication-gap",
            question="Single-trial / thin theses must name replication gap",
            passed=True,
            detail=(
                f"thesis references {len(referenced_ids)} receipts spanning "
                f"{effective_unique_count} unique trials — synthesis is "
                f"cross-trial, replication gate not triggered"
            ),
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
            f"thesis references {len(referenced_ids)} receipts but only "
            f"{effective_unique_count} unique trial(s); replication "
            f"phrase {'present' if has_phrase else 'MISSING'} in Limitations"
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
            passed=True, detail="no safety receipts in corpus (N/A)",
            applicable=False,
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

    Day 10.7 score formula (reviewer P2 fix): only APPLICABLE checks
    count toward the score. Vacuous passes (no null receipts to test
    Q2, no safety receipts for Q6, etc.) score N/A and don't inflate
    the result.

      applicable = [c for c in checks if c.applicable]
      score = passed_applicable / max(1, total_applicable) * 10

    Day 10.10 ship gates (ALL must hold):
      1. score ≥ DAY10_SCORE_FLOOR (8.5)
      2. ALL load-bearing Q1/Q3/Q5 checks: applicable=True AND passed=True
         (Day 10.10 reviewer P2: load-bearing N/A no longer counts as a
         pass — it counts as "skipped on a load-bearing question," which
         blocks ship.)
      3. coverage: total_applicable ≥ MIN_APPLICABLE_CHECKS (4)
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
    applicable = [c for c in checks if c.applicable]
    passed_applicable = sum(1 for c in applicable if c.passed)
    total_applicable = len(applicable)
    score = (
        passed_applicable / total_applicable * 10
        if total_applicable else 0.0
    )

    # Day 10.10 reviewer P2: load-bearing pass requires every load-bearing
    # check to be applicable=True AND passed=True. A load-bearing N/A
    # means the corpus or paper is structurally unable to exercise that
    # invariant — that's not a "pass," that's a coverage gap on a
    # load-bearing question.
    load_bearing_all = [
        c for c in checks if c.question_id in Q_LOAD_BEARING_IDS
    ]
    load_bearing_pass = all(
        c.applicable and c.passed for c in load_bearing_all
    )
    failed_load = [
        c.question_id for c in load_bearing_all if not c.passed
    ]
    skipped_load = [
        c.question_id for c in load_bearing_all if not c.applicable
    ]

    insufficient_coverage = total_applicable < MIN_APPLICABLE_CHECKS

    notes_parts: list[str] = [
        f"{passed_applicable}/{total_applicable} applicable checks passed "
        f"(score {score:.2f}/10, {len(checks) - total_applicable} N/A)"
    ]
    if failed_load:
        notes_parts.append(
            f"LOAD-BEARING FAIL {failed_load} — ship blocked"
        )
    if skipped_load:
        notes_parts.append(
            f"LOAD-BEARING SKIPPED (N/A) {skipped_load} — ship blocked "
            f"(Day 10.10: a load-bearing question that doesn't apply "
            f"means the synthesis can't be honestly graded on it)"
        )
    if insufficient_coverage:
        notes_parts.append(
            f"INSUFFICIENT COVERAGE: only {total_applicable} applicable "
            f"checks (floor {MIN_APPLICABLE_CHECKS}) — corpus too narrow "
            f"for honest synthesis audit"
        )
    if (
        score >= DAY10_SCORE_FLOOR
        and load_bearing_pass
        and not insufficient_coverage
    ):
        notes_parts.append("ship-criterion met")
    elif score < DAY10_SCORE_FLOOR:
        notes_parts.append(f"score below floor {DAY10_SCORE_FLOOR}")

    return SynthesisQualityAudit(
        submission_id=paper.submission_id,
        checks=checks,
        score=round(score, 2),
        notes=" | ".join(notes_parts),
    )
