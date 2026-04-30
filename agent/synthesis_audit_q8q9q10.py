"""Day 10.17 audit checks Q8/Q9/Q10.

Extracted from agent/synthesis_audit.py to keep that module under the
600 per-file LOC cap. These three checks were added after the 10.17a
empirical run surfaced the gap between "compliance score" (Q1-Q7) and
"defensible synthesis":

  Q8  rejected-evidence leakage  — load-bearing
  Q9  receipt-id format          — typo catcher (not load-bearing)
  Q10 claim-strength discipline   — load-bearing

All three are pure regex / set-membership checks. No LLM in the audit
loop. They share two private helpers (`_split_body_by_headings` and a
shared receipt-id regex) so co-locating them keeps related logic
together.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from agent.synthesis_schemas import (
    QualityCheckResult,
    ReceiptSummary,
    SynthesisPaper,
)

__all__ = ["check_q8", "check_q9", "check_q10"]


# --- Shared helpers ------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


# Receipt-id format: at least 4 hyphen-separated alphanumeric segments.
# Used by both Q9 (validity check) and Q10 (sentence-level citation
# detection). Tight enough to avoid NCT IDs, ISRCTN IDs, p-values,
# percentages, dates, and bare prose hyphenations.
_RECEIPT_ID_RE = re.compile(
    r"\b[a-z]+(?:-[a-z0-9]+){3,}\b", re.IGNORECASE,
)


# --- Q8 — quarantine leakage (load-bearing) ------------------------------


_Q8_QUARANTINE_SECTIONS = (
    "rejected / contested evidence",
    "rejected/contested evidence",
    "rejected evidence",
    "methods",
    "references",
)
_Q8_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)


def _split_body_by_headings(body: str) -> list[tuple[str, str]]:
    """Split markdown body by H2-H6 headings → list of
    (heading_lower, content) in document order."""
    headings = list(_Q8_HEADING_RE.finditer(body))
    if not headings:
        return [("", body)]
    out: list[tuple[str, str]] = []
    if headings[0].start() > 0:
        out.append(("", body[: headings[0].start()]))
    for i, m in enumerate(headings):
        title = m.group(2).strip().lower()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        out.append((title, body[start:end]))
    return out


def check_q8(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """Quarantined receipts may only appear in the Rejected/Contested,
    Methods, or References sections. Day 10.10 trust-spine rule:
    rejected evidence must not be cited in headline prose."""
    # Defensive: spar_verdict could be None or have unexpected casing
    # if a malformed receipt slips through; treat anything not starting
    # with "accept" (case-insensitive) as rejected.
    rejected = [
        r for r in receipts
        if not (r.spar_verdict or "").lower().startswith("accept")
    ]
    if not rejected:
        return QualityCheckResult(
            question_id="Q8-quarantine-leakage",
            question="Rejected receipts must not appear outside their section",
            passed=True,
            detail="no rejected receipts in corpus (N/A)",
            applicable=False,
        )
    rejected_ids = {r.receipt_id for r in rejected}
    leaks: list[str] = []
    for heading, content in _split_body_by_headings(paper.body_md):
        if any(s in heading for s in _Q8_QUARANTINE_SECTIONS):
            continue
        for rid in rejected_ids:
            if rid in content:
                leaks.append(f"{rid} cited under heading {heading!r}")
                break  # one leak per section is enough to flag
    leaks = sorted(set(leaks))
    return QualityCheckResult(
        question_id="Q8-quarantine-leakage",
        question="Rejected receipts must not appear outside their section",
        passed=not leaks,
        detail=(
            f"{len(rejected)} rejected receipts, all properly quarantined"
            if not leaks else "; ".join(leaks[:3])
        ),
    )


# --- Q9 — receipt-ID format validity -------------------------------------


def check_q9(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """Every inline receipt-id-shaped token in the body must match a
    real receipt_id. Catches dropped-character typos like cfab-01 vs
    cfab-c01 that the existing anchor validator misses (it only checks
    the structured `receipt_ids` field on each anchor, not the inline
    prose tokens)."""
    valid_ids = {r.receipt_id for r in receipts}
    if not valid_ids:
        return QualityCheckResult(
            question_id="Q9-receipt-id-format",
            question="Inline receipt-id tokens must match the corpus",
            passed=True, detail="empty corpus (N/A)", applicable=False,
        )
    valid_lower = {rid.lower() for rid in valid_ids}
    prefixes: set[str] = set()
    for rid in valid_ids:
        parts = rid.split("-")
        if len(parts) >= 3:
            prefixes.add("-".join(parts[:3]).lower())
    bad: list[str] = []
    for m in _RECEIPT_ID_RE.finditer(paper.body_md):
        tok = m.group(0)
        tok_l = tok.lower()
        if tok_l in valid_lower:
            continue
        if any(tok_l.startswith(p) for p in prefixes):
            bad.append(tok)
    bad = sorted(set(bad))
    return QualityCheckResult(
        question_id="Q9-receipt-id-format",
        question="Inline receipt-id tokens must match the corpus",
        passed=not bad,
        detail=(
            "all inline receipt-id tokens valid"
            if not bad else f"malformed: {bad[:3]}"
        ),
    )


# --- Q10 — claim-strength discipline (load-bearing) ----------------------


_Q10_CAUSAL_RE = re.compile(
    r"\b(?:improves?|causes?|drives?|explains?|"
    r"demonstrates?|confirms?|proves?|robust|potent)\b",
    re.IGNORECASE,
)
# EPISTEMIC hedges only — words that signal uncertainty about the
# claim itself. Scope qualifiers like "in model organisms" or
# "preclinically" describe the population/study type but do NOT hedge
# a causal claim and therefore must NOT count as hedges.
_Q10_HEDGES = (
    " may ", " might ", " could ", " appears to",
    " evidence suggests", " suggests",
    " consistent with", " associated with",
    " has been proposed", " in this corpus", " we interpret ",
    " hypothesized", " preliminary",
    " remains to be confirmed", " is not yet established",
)
_Q10_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")
# Strip `_Cited: \`...\`_` footer lines (citation metadata, not prose)
# before scanning so the sentence regex doesn't absorb them into
# surrounding prose and false-positive on the receipt IDs inside.
_Q10_CITED_FOOTER_RE = re.compile(r"^\s*_Cited:.*_\s*$", re.MULTILINE)


def check_q10(
    paper: SynthesisPaper, receipts: Sequence[ReceiptSummary],
) -> QualityCheckResult:
    """Sentences citing tier-C or mechanistic receipts that contain a
    causal verb MUST also contain an epistemic hedge. Day 10.17a
    reviewer consensus: the audit was passing 10/10 while the prose
    said "demonstrates" / "robust" / "potent" on tier-C model-organism
    or mechanistic evidence."""
    weak = {
        r.receipt_id for r in receipts
        if (r.evidence_tier or "").upper() == "C"
        or r.directness in ("mechanistic", "indirect")
    }
    if not weak:
        return QualityCheckResult(
            question_id="Q10-claim-strength-discipline",
            question="Tier-C / mechanistic claims need hedge if causal verb",
            passed=True,
            detail="no tier-C / mechanistic receipts in corpus (N/A)",
            applicable=False,
        )
    # Strip _Cited: footer lines so Q10's sentence regex doesn't
    # absorb citation metadata into surrounding prose and false-fail.
    body_for_scan = _Q10_CITED_FOOTER_RE.sub("", paper.body_md)
    failures: list[str] = []
    for m in _Q10_SENTENCE_RE.finditer(body_for_scan):
        sentence = m.group(0)
        cited = {tok.group(0) for tok in _RECEIPT_ID_RE.finditer(sentence)}
        if not (cited & weak):
            continue
        if not _Q10_CAUSAL_RE.search(sentence):
            continue
        sentence_norm = _normalize(sentence)
        if any(h.strip() in sentence_norm for h in _Q10_HEDGES):
            continue
        failures.append(sentence.strip()[:90])
    failures = sorted(set(failures))
    return QualityCheckResult(
        question_id="Q10-claim-strength-discipline",
        question="Tier-C / mechanistic claims need hedge if causal verb",
        passed=not failures,
        detail=(
            f"{len(weak)} weak-tier receipts, all sentences hedged"
            if not failures else f"unhedged: {failures[:2]}"
        ),
    )
