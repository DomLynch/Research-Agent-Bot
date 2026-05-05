"""Numeric Role Guard — universal class-level fix for numeric
mis-interpretation in synthesis prose.

Reviewer feedback (2026-05-05): the audit pipeline has shipped four
point-fixes for variants of "change-value misread as absolute value"
(Fix #54 anaphor, Fix #57 proximity, Fix #58 paragraph-threshold,
Fix #58c). Each closes a specific regex pattern; new variants keep
appearing. Example caught only on human review:

  "The observed change in the MET-PREVENT trial [0.13 m/s] falls at
  or below this [0.1 m/s] threshold, suggesting minimal clinical
  impact."

Two distinct errors here:
  (a) ROLE confusion — change-score compared to threshold (caught by
      earlier fixes when they fire; this slipped because the
      threshold IS a change threshold, so role-mismatch heuristic
      passes — but the COMPARISON is still wrong).
  (b) NUMERIC arithmetic — 0.13 ≤ 0.1 is mathematically false, so
      "falls at or below" is a science error regardless of role.

This module addresses BOTH error classes with universal regexes that
classify numerics by role (change_score / absolute_value / effect_size
/ p_value / sample_size / dose / duration / percentage / ratio) and
verify that comparisons between numerics are arithmetically valid.

Universal — no drug names, no specific values, no paper-specific
allowlists. Same code path for every topic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Words that signal a "change" framing for a numeric — change_score role
_CHANGE_WORDS = (
    "change", "delta", "difference", "increase", "decrease",
    "improvement", "reduction", "from baseline", "improvement of",
    "decline", "reverse", "shift", "increment",
)
# Words that signal an "absolute level" framing — absolute_value role
_ABSOLUTE_WORDS = (
    "level of", "absolute", "baseline value", "raw value",
)
# Threshold/cutoff words — these define a comparison reference
_THRESHOLD_WORDS = (
    "threshold", "cutoff", "cut-off", "boundary",
)
# Comparison framings — "X below Y", "X above Y" etc.
_BELOW_WORDS = (
    r"falls\s+(?:at\s+or\s+)?below", r"is\s+below", r"below\s+the",
    r"under\s+the", r"less\s+than", r"≤", r"<=",
    r"at\s+or\s+below", r"does\s+not\s+exceed",
)
_ABOVE_WORDS = (
    r"falls\s+(?:at\s+or\s+)?above", r"is\s+above", r"above\s+the",
    r"exceeds", r"greater\s+than", r"≥", r">=",
    r"at\s+or\s+above",
)
# Allowlist — phrases that SIGNAL the threshold being discussed is a
# change-threshold (MCID-style) rather than an absolute level. Broader
# than the original list to avoid auto-stripping legitimate
# recommendation/benchmark prose. Universal — no drug names.
_CHANGE_THRESHOLD_ALLOWLIST = (
    "clinically meaningful", "clinically relevant",
    "minimal clinically important difference", "MCID",
    "change threshold", "change-score threshold",
    "substantial change", "meaningful improvement",
    "meaningful decrease", "meaningful difference",
)

# Explicit comparison framings — required for role_mismatch to fire.
# Without this, sentences that merely MENTION change + threshold
# (e.g. recommendation/benchmark prose) get stripped as false
# positives. The role-mismatch P1 only fires when there's an actual
# below/above/falls-at comparison happening.
_EXPLICIT_COMPARISON_RE = re.compile(
    r"\b(?:falls?|is|are|sits?|lies?|stays?)\s+"
    r"(?:at\s+or\s+)?(?:below|above|under|over|less\s+than|greater\s+than)"
    r"|≤|≥|<=|>=|\bbelow\s+the\b|\babove\s+the\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NumericIssue:
    """One detected numeric-role issue. Severity P1 (auto-strip);
    severity P2 for malformed-sentence patterns."""
    sentence: str
    issue_type: str   # 'role_mismatch', 'arithmetic_violation', 'malformed_subject'
    severity: str     # 'P1' or 'P2'
    detail: str
    suggested_fix: str = "Strip the sentence (auto-fix)."


def _split_sentences(text: str) -> list[str]:
    """Cheap sentence splitter — preserves trailing punctuation.
    Handles common abbreviations (no., et al., e.g., i.e.)."""
    placeholders = (
        ("et al.", "et al<DOT>"),
        ("e.g.", "e<DOT>g<DOT>"),
        ("i.e.", "i<DOT>e<DOT>"),
        ("vs.", "vs<DOT>"),
        ("Dr.", "Dr<DOT>"),
        ("No.", "No<DOT>"),
    )
    s = text
    for orig, repl in placeholders:
        s = s.replace(orig, repl)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", s)
    out = []
    for p in parts:
        for orig, repl in placeholders:
            p = p.replace(repl, orig)
        out.append(p.strip())
    return [p for p in out if p]


def _has_change_framing(sentence: str) -> bool:
    """Loose check — used by role-mismatch as one of several signals."""
    s = sentence.lower()
    return any(w in s for w in _CHANGE_WORDS)


# Tighter check: a CHANGE WORD must be directly tied to a numeric
# value via 'of' / 'by' / 'in' (e.g. 'change of 0.13', 'improvement
# by 5 mmHg', 'decrease in 2 kg'). Generic 'could improve outcomes'
# does NOT qualify — it's descriptive methodology prose, not a
# change-score claim. Without this proximity requirement, the
# role-mismatch check hits many false positives in methods sections.
_CHANGE_NUMERIC_RE = re.compile(
    r"\b(?:change|delta|difference|increase|decrease|improvement|"
    r"reduction|decline|shift)\s+(?:of|by|in|from\s+baseline\s+of)?\s*"
    r"(?:approximately\s+|only\s+|just\s+)?(\d+\.?\d*)",
    flags=re.IGNORECASE,
)


def _has_change_framed_numeric(sentence: str) -> bool:
    """True iff a change-word is directly bound to a numeric value
    via 'of'/'by'/'in'. Tighter than _has_change_framing."""
    return bool(_CHANGE_NUMERIC_RE.search(sentence))


def _has_change_threshold(sentence: str) -> bool:
    s = sentence.lower()
    return any(w.lower() in s for w in _CHANGE_THRESHOLD_ALLOWLIST)


def _has_absolute_threshold(sentence: str) -> bool:
    """Signals an absolute-level threshold (frailty cutoff, BMI
    threshold, hypertension level) — distinct from a change threshold."""
    s = sentence.lower()
    has_threshold = any(w in s for w in _THRESHOLD_WORDS)
    if not has_threshold:
        return False
    # Without change-threshold allowlist, threshold is presumed absolute
    return not _has_change_threshold(sentence)


def _extract_numeric_pairs(
    sentence: str,
) -> list[tuple[float, str, float]]:
    """Find sentences with form 'X <comparison> Y' where X and Y are
    numeric values (with units like m/s, mg, %). Returns list of
    (X, comparison_word, Y) tuples for arithmetic validation.
    Empty list when no comparable pair is found."""
    # Match number + unit + comparison + number + unit
    # Conservative: only flag clear "X (below|at or below|exceeds) Y"
    # patterns where both X and Y have the same unit (so comparison
    # is well-defined).
    pairs: list[tuple[float, str, float]] = []
    # Optional determiner ("the" / "this" / "that") + value + optional unit.
    # `_UNIT` covers the common biomedical units we audit (m/s, mg, %, kg,
    # mmHg, kg/m²); add more conservatively (false positives more costly
    # than misses).
    _UNIT = r"(?:m/s|mg|%|kg/m²|kg|mmHg|μM|mcg)?"
    _DET = r"(?:(?:the|this|that)\s+)?"
    # Try below-comparisons first
    for cmp_pat in _BELOW_WORDS:
        m = re.search(
            rf"(\d+\.?\d*)\s*{_UNIT}[^.]*?{cmp_pat}\s+"
            rf"{_DET}(\d+\.?\d*)\s*{_UNIT}",
            sentence, flags=re.IGNORECASE,
        )
        if m:
            try:
                pairs.append((
                    float(m.group(1)), "below", float(m.group(2)),
                ))
            except (TypeError, ValueError):
                pass
    for cmp_pat in _ABOVE_WORDS:
        m = re.search(
            rf"(\d+\.?\d*)\s*{_UNIT}[^.]*?{cmp_pat}\s+"
            rf"{_DET}(\d+\.?\d*)\s*{_UNIT}",
            sentence, flags=re.IGNORECASE,
        )
        if m:
            try:
                pairs.append((
                    float(m.group(1)), "above", float(m.group(2)),
                ))
            except (TypeError, ValueError):
                pass
    return pairs


def _check_arithmetic_violations(
    sentence: str,
) -> NumericIssue | None:
    """Verify that 'X below Y' implies X ≤ Y (and vice versa).
    Catches the metformin '0.13 falls at or below 0.1' error pattern."""
    pairs = _extract_numeric_pairs(sentence)
    for x, cmp, y in pairs:
        if cmp == "below" and x > y:
            return NumericIssue(
                sentence=sentence,
                issue_type="arithmetic_violation",
                severity="P1",
                detail=(
                    f"Sentence claims {x} is below {y}, but {x} > {y}. "
                    f"Auto-strip — this is a science error regardless "
                    f"of context."
                ),
            )
        if cmp == "above" and x < y:
            return NumericIssue(
                sentence=sentence,
                issue_type="arithmetic_violation",
                severity="P1",
                detail=(
                    f"Sentence claims {x} is above {y}, but {x} < {y}."
                ),
            )
    return None


def _check_role_mismatch(sentence: str) -> NumericIssue | None:
    """Catches change-vs-absolute role mismatch (the case Fixes
    #54/57/58/58c each addressed for specific patterns).

    Conservative: requires BOTH (a) at least one numeric value with
    a recognized biomedical unit AND (b) the change keyword AND (c)
    the absolute-threshold keyword AND (d) NO change-threshold
    allowlist phrase. False-positive cost is high (auto-strips
    legitimate prose); all four conditions must hold."""
    # (a) Must have at least one numeric with a biomedical unit
    has_numeric = bool(re.search(
        r"\d+\.?\d*\s*(?:m/s|mg|%|kg/m²|kg|mmHg|μM|mcg)",
        sentence,
    ))
    if not has_numeric:
        return None
    # (b) Change framing must be DIRECTLY bound to a numeric
    # ("change of X", "improvement by Y") — not just generic
    # "could improve outcomes" prose
    if not _has_change_framed_numeric(sentence):
        return None
    if _has_change_threshold(sentence):
        return None  # change-vs-change-threshold is allowed
    if not _has_absolute_threshold(sentence):
        return None
    # (c) Requires EXPLICIT comparison framing (below/above/falls-at)
    # — without this, recommendation/benchmark prose that merely
    # discusses both change scores and absolute thresholds in the
    # same sentence gets stripped as false positives. Reviewer-
    # tightened: P1 fires only on the precise misread pattern.
    if not _EXPLICIT_COMPARISON_RE.search(sentence):
        return None
    return NumericIssue(
        sentence=sentence,
        issue_type="change_score_vs_absolute_threshold",
        severity="P1",
        detail=(
            "Sentence frames a numeric as a CHANGE score AND uses "
            "explicit below/above/falls-at language to compare it "
            "against an ABSOLUTE threshold (frailty cutoff, severity "
            "level, etc.). This is a publication-blocker science "
            "error: change scores cannot be meaningfully compared to "
            "absolute-level thresholds. Auto-strip."
        ),
    )


# Detect duplicate-subject repair artifacts:
# "the X group experienced ... for the X group was Y"
_DUPLICATE_SUBJECT_RE = re.compile(
    r"(?:the\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+group\s+\w+[^.]*?"
    r"for\s+the\s+\1\s+group\s+(?:was|were|is)",
    flags=re.IGNORECASE,
)


def _check_malformed_subject(sentence: str) -> NumericIssue | None:
    if _DUPLICATE_SUBJECT_RE.search(sentence):
        return NumericIssue(
            sentence=sentence,
            issue_type="malformed_subject",
            severity="P2",
            detail=(
                "Duplicate-subject repair artifact: 'the X group "
                "<verb>... for the X group <was/were>...'. Auto-fix: "
                "strip the second 'for the X group' clause."
            ),
            suggested_fix=(
                "Remove the duplicated 'for the X group' fragment."
            ),
        )
    return None


def scan_paper(paper_md: str) -> list[NumericIssue]:
    """Run all numeric-role checks across every sentence in the
    paper. Returns flat list of issues — caller decides how to
    report (audit P1 list, auto-strip, etc.)."""
    issues: list[NumericIssue] = []
    for sentence in _split_sentences(paper_md):
        for check in (
            _check_arithmetic_violations,
            _check_role_mismatch,
            _check_malformed_subject,
        ):
            issue = check(sentence)
            if issue:
                issues.append(issue)
                break  # one issue per sentence is enough to fail it
    return issues


def auto_strip_offending_sentences(
    paper_md: str, issues: Iterable[NumericIssue],
) -> tuple[str, int]:
    """Remove sentences flagged with severity P1. Returns
    (new_md, n_stripped). P2 issues left for the caller (they may
    require non-strip auto-fix like the duplicate-subject cleanup)."""
    bad_sentences = {
        i.sentence for i in issues if i.severity == "P1"
    }
    if not bad_sentences:
        return paper_md, 0
    out = paper_md
    n = 0
    for s in bad_sentences:
        if s in out:
            out = out.replace(s, "")
            n += 1
    # Collapse whitespace runs from the removal
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"  +", " ", out)
    return out, n


__all__ = [
    "NumericIssue",
    "scan_paper",
    "auto_strip_offending_sentences",
]
