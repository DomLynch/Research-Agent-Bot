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
_OBJECTIVE_PARTIAL_TYPES = {
    "unit_value", "sample_size", "year", "sample_count",
}
_REPORTABLE_NUMERIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "percentage",
        re.compile(
            r"\b(\d+\.?\d*)\s*%(?!\s*(?:CI|confidence\s+interval))",
            flags=re.IGNORECASE,
        ),
    ),
    ("p_value", re.compile(r"\b[Pp]\s*[<>=]\s*(0?\.\d+)\b")),
    ("grouped_number", re.compile(r"\b(\d{1,3}(?:[,\s]\d{3})+)\b")),
    (
        "brief_count",
        re.compile(
            r"\b(\d+(?:[,\s]\d{3})*)\s+(?:included\s+)?"
            r"(?:source\s+papers?|sources?|receipts?|claims?|tensions?|"
            r"cross-study\s+disagreements|curated\s+reference\s+papers)\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "ratio",
        re.compile(
            r"\b(?:aHR|aOR|HR|OR|RR|RRR|IRR|SHR|SMR)\s*[=:]\s*"
            r"(\d+\.?\d*)"
        ),
    ),
    ("sample_size", re.compile(r"\b[nN]\s*=\s*(\d+)\b")),
    ("dose", re.compile(r"\b(\d+\.?\d*)\s*(?:mg|g|kg|μg|mcg|mL)\b")),
    ("speed", re.compile(r"\b(\d+\.?\d*)\s*m\s*/\s*s\b")),
)
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d)[,\s](?=\d{3}\b)")


def canonical_numeric(value: str) -> str:
    return _THOUSANDS_SEP_RE.sub("", str(value).strip().lower())


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


_NO_CHANGE_NONZERO_PAREN_RE = re.compile(
    r"\bno\s+(?:meaningful\s+|clear\s+|significant\s+)?change\b"
    r"[^.]{0,140}?\((?!\s*p\s*[<=>])([^)]*\d+\.?\d*[^)]*)\)",
    flags=re.IGNORECASE,
)


def _check_no_change_nonzero_parenthetical(
    sentence: str,
) -> NumericIssue | None:
    """Flag 'no change ... (0.13 m/s)' style sentences.

    Parenthetical nonzero outcome values attached to a no-change claim
    are ambiguous at best and often invert the source context. P-values
    and confidence intervals are allowed; unit-bound outcome values are
    not."""
    m = _NO_CHANGE_NONZERO_PAREN_RE.search(sentence)
    if not m:
        return None
    paren = m.group(1).lower()
    if "ci" in paren or "confidence interval" in paren:
        return None
    unit_bound = re.search(
        r"\b\d+\.?\d*\s*(?:m/s|kg|mg|%|mmhg|points?|scores?|units?)\b",
        paren,
        flags=re.IGNORECASE,
    )
    if not unit_bound:
        return None
    value_match = re.match(r"\d+\.?\d*", unit_bound.group(0))
    if value_match is None:
        return None
    try:
        value = float(value_match.group(0))
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return NumericIssue(
        sentence=sentence,
        issue_type="no_change_nonzero_parenthetical",
        severity="P1",
        detail=(
            "Sentence frames an outcome as 'no change' while attaching "
            f"a nonzero unit-bound parenthetical value ({unit_bound.group(0)!r}). "
            "This is ambiguous source-context framing; strip the sentence."
        ),
    )


# --- Slice 7 step 1: prose source-context numeric guard --------------
#
# The reviewer-flagged class: prose attributes a numeric to a citation
# but the citation's source paper doesn't actually contain that number.
# Q2 (numeric-integrity audit) catches "number must exist somewhere
# in the corpus pool" but not "number must exist in the SPECIFIC
# cited paper's source context." A drift like:
#
#   "Mannick 2014 reported 5 mg weekly dosing"  ← actual paper
#   "Mannick 2014 reported 50 mg weekly dosing" ← prose drift
#
# would pass Q2 (50 mg appears somewhere in the corpus) but fail
# source-context fidelity.

# Citation token: "Author YYYY" (plus optional [a-z] suffix).
# Author can include a single hyphenated second part (Cruz-Jentoft).
_CITATION_TOKEN_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:-[A-Z][a-zA-Z]+)?)\s+(\d{4}[a-z]?)\b",
)

# Loose numeric extractor for source-context drift check. Picks up
# every standalone number plus simple unit-bound numerics. Conservative
# (we'd rather miss a number than false-positive an honest sentence).
_DRIFT_NUMERIC_RE = re.compile(
    r"(?<![\w.])(\d+\.\d+|\.\d+|\d+)\s*"
    r"(?:%|mg|g|kg|mL|L|m/s|months?|years?|weeks?|days?|"
    r"mmHg|bpm|U/L)?",
)
_NUMERIC_RANGE_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
    r"(\d+(?:\.\d+)?)\s*(%)?",
    flags=re.IGNORECASE,
)
_HEDGE_WORD_RE = re.compile(
    r"\b(?:approximately|roughly|around|about|nearly|over|under|"
    r"more\s+than|less\s+than)\b",
    flags=re.IGNORECASE,
)
_EDITORIAL_FRACTION_RE = re.compile(
    r"\b(?:approximately|roughly|around|about|nearly|over|under|"
    r"more\s+than|less\s+than)\s+(?:a\s+|one\s+)?"
    r"(?:half|quarter|third|one[-\s]third|one[-\s]quarter|"
    r"two[-\s]thirds|three[-\s]quarters)\b",
    flags=re.IGNORECASE,
)
_PAREN_NUMERIC_RE = re.compile(r"\([^)]*\d+(?:\.\d+)?\s*%?[^)]*\)")

# Tolerance for numeric equality — "0.13" vs "0.130" or "5" vs "5.0"
# count as the same number. Tighter than ±5% to keep this a fidelity
# check, not a fuzzy match.
_NUMERIC_EPSILON = 1e-6


def _build_citation_role_index(
    *, manifest: dict | None,
    bg_lit_registry: dict | None,
    quant_claims_dir,
) -> dict[str, dict[str, set[str]]]:
    """Build {citation_token: {numeric_variant: {role, ...}}}.

    For each numeric in the cited paper's source context, record
    every ROLE it appears in (population baseline, change_score,
    threshold, outcome value, etc.). The drift check uses this to
    catch the failure mode where prose attributes a numeric to the
    right citation but the WRONG role (e.g. prose says 'baseline
    0.13 m/s' but Witham 2025 has 0.13 only as a change-score, not
    a baseline).

    Receipts: claim['claim_role'] (population / effect / baseline /
    change_score / threshold / outcome / etc.) drives the role tag.
    Background literature: bg_lit entries get role='canonical'
    (single-role, since bg_lit is a flat numeric registry).

    Empty role set for a value → no role data; caller falls back to
    membership-only check (back-compat, fail-soft)."""
    import json as _json
    from pathlib import Path as _Path
    out: dict[str, dict[str, set[str]]] = {}
    if bg_lit_registry:
        for entry in bg_lit_registry.values():
            tok = (entry.get("citation_token") or "").strip()
            num = (entry.get("numeric") or "").strip()
            if not tok:
                continue
            slot = out.setdefault(tok, {})
            if num:
                for variant in _numeric_variants(num):
                    slot.setdefault(variant, set()).add("canonical")
    if manifest is None:
        return out
    receipts = manifest.get("receipts") or []
    qc_dir = _Path(quant_claims_dir) if quant_claims_dir else None
    for r in receipts:
        tok = (
            r.get("citation_token") or r.get("receipt_id") or ""
        ).strip()
        if not tok:
            continue
        slot = out.setdefault(tok, {})
        paper_id = (r.get("paper_id") or r.get("receipt_id") or "")
        if not paper_id or qc_dir is None or not qc_dir.exists():
            continue
        qc_path = qc_dir / f"{paper_id}.quant_claims.json"
        if not qc_path.exists():
            continue
        try:
            data = _json.loads(qc_path.read_text())
        except (OSError, ValueError):
            continue
        for claim in data.get("claims", []) or []:
            role = (claim.get("claim_role") or "").strip().lower() or "outcome"
            for v in claim.get("numeric_values", []) or []:
                vstr = str(v) if isinstance(v, (int, float)) else v
                if not isinstance(vstr, str):
                    continue
                for variant in _numeric_variants(vstr):
                    slot.setdefault(variant, set()).add(role)
    return out


def _build_citation_allowed_numerics(
    *, manifest: dict | None,
    bg_lit_registry: dict | None,
    quant_claims_dir,
) -> dict[str, set[str]]:
    """Slice 7 step 1 back-compat alias. Returns the value-set view
    of the role index (collapses roles, keeps just the numerics)
    so the existing membership-only fallback path keeps working."""
    role_index = _build_citation_role_index(
        manifest=manifest, bg_lit_registry=bg_lit_registry,
        quant_claims_dir=quant_claims_dir,
    )
    return {tok: set(slot.keys()) for tok, slot in role_index.items()}


def _manifest_structural_numerics(manifest: dict | None) -> set[str]:
    if not isinstance(manifest, dict):
        return set()
    keys = (
        "n_receipts", "n_high_confidence_claims_total",
        "n_non_orthogonal_tensions", "total_words",
    )
    out = {
        canonical_numeric(str(manifest[k]))
        for k in keys
        if isinstance(manifest.get(k), (int, float))
    }
    counts = ((manifest.get("receipt_funnel") or {}).get("counts") or {})
    if isinstance(counts, dict):
        out.update(
            canonical_numeric(str(v))
            for v in counts.values()
            if isinstance(v, (int, float))
        )
    return out


def _build_global_allowed_numerics(
    *, manifest: dict | None, bg_lit_registry: dict | None, quant_claims_dir,
) -> set[str]:
    """Strict prose-wide numeric pool.

    Citation-bound drift catches "right number, wrong source" cases.
    This pool catches citationless reportable numerics before Q2 has to
    ship-block the final artifact.
    """
    out: set[str] = set()
    out.update(_manifest_structural_numerics(manifest))
    if isinstance(bg_lit_registry, dict):
        for entry in bg_lit_registry.values():
            num = (entry.get("numeric") or "").strip()
            if num:
                out.update(_numeric_variants(canonical_numeric(num)))
    if not quant_claims_dir:
        return out
    try:
        from pathlib import Path as _Path
        import json as _json
        qcd = _Path(quant_claims_dir)
        paths = tuple(qcd.glob("*.quant_claims.json")) if qcd.exists() else ()
    except (OSError, TypeError, ValueError):
        return out
    for path in paths:
        try:
            data = _json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for claim in data.get("claims", []) or []:
            confidence = (claim.get("binding_confidence") or "").lower()
            claim_type = claim.get("claim_type") or ""
            if confidence != "high" and not (
                confidence == "partial"
                and claim_type in _OBJECTIVE_PARTIAL_TYPES
            ):
                continue
            for value in claim.get("numeric_values", []) or []:
                out.update(_numeric_variants(canonical_numeric(str(value))))
    return out


def _untraceable_reportable_numerics(
    sentence: str, allowed_numerics: set[str],
) -> list[str]:
    if not allowed_numerics:
        return []
    clean = re.sub(
        r"\b(?:95|99|99\.9|90)\s*%\s*CI\b", "",
        sentence, flags=re.IGNORECASE,
    )
    bad: set[str] = set()
    for category, pattern in _REPORTABLE_NUMERIC_PATTERNS:
        if category == "p_value":
            # Significance thresholds (p < 0.05 / 0.01 / 0.001 ...) are
            # statistical convention, not corpus-traceable data values, so they
            # are never "untraceable" against the citationless numeric pool.
            # Citation-bound drift still catches a p-value with the wrong source.
            continue
        for value in set(pattern.findall(clean)):
            if category == "percentage":
                try:
                    if not (1.0 < float(canonical_numeric(value)) < 1000):
                        continue
                except (TypeError, ValueError):
                    continue
            if not (_numeric_variants(canonical_numeric(value)) & allowed_numerics):
                bad.add(value)
    return sorted(bad)


def _numeric_variants(value: str) -> set[str]:
    """Return canonical string variants of a numeric so '5' / '5.0' /
    '0.05' / '0.0500' / '5 mg' / '0.8 m/s' compare equal. Defensive
    against quant_claims extraction that may store either ints or
    floats, and bg_lit entries that store numerics with units appended
    ('0.8 m/s', '14%', '5 mg').
    """
    raw = str(value).strip()
    if raw.startswith(".") and len(raw) > 1:
        raw = f"0{raw}"
    out: set[str] = {raw}
    # Strip a trailing unit to extract the bare numeric.
    m = re.match(r"^(\d+\.?\d*)\s*", raw)
    bare = m.group(1) if m else raw
    out.add(bare)
    try:
        f = float(bare)
    except (TypeError, ValueError):
        return out
    out.add(str(f))
    if f.is_integer():
        out.add(str(int(f)))
    if "." in str(f):
        stripped = str(f).rstrip("0").rstrip(".")
        if stripped:
            out.add(stripped)
    return out


def _numeric_float(value: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", value)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _registered_citations_in_sentence(
    sentence: str,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> list[str]:
    out: list[str] = []
    for c in _CITATION_TOKEN_RE.finditer(sentence):
        token = f"{c.group(1)} {c.group(2)}"
        if token in citation_role_index and token not in out:
            out.append(token)
    return out


def _token_numeric_values(
    token: str,
    citation_role_index: dict[str, dict[str, set[str]]],
    *,
    percent_only: bool,
) -> list[float]:
    values: list[float] = []
    for raw in citation_role_index.get(token, {}):
        if percent_only and "%" not in raw:
            continue
        value = _numeric_float(raw)
        if value is not None:
            values.append(value)
    return values


def _range_contract_passes(
    sentence: str,
    num_pos: int,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> bool:
    """Allow editorial cross-paper ranges when the cited registry
    values support the stated bounds.

    Example: "outcomes fell within an 8-15% range (A 2020, B 2021)"
    is valid only if at least two cited papers have percent values
    inside the range and those values span the stated lower/upper
    bounds within a small rounding tolerance.
    """
    for m in _NUMERIC_RANGE_RE.finditer(sentence):
        if not (m.start() <= num_pos <= m.end()):
            continue
        low = _numeric_float(m.group(1))
        high = _numeric_float(m.group(2))
        if low is None or high is None:
            return False
        if low > high:
            low, high = high, low
        tokens = _registered_citations_in_sentence(
            sentence, citation_role_index,
        )
        if len(tokens) < 2:
            return False
        in_range: list[float] = []
        for token in tokens:
            vals = _token_numeric_values(
                token, citation_role_index,
                percent_only=bool(m.group(3)),
            )
            vals = [v for v in vals if low <= v <= high]
            if vals:
                in_range.append(vals[0])
        if len(in_range) < 2:
            return False
        span = max(high - low, 1.0)
        tol = max(0.5, span * 0.05)
        return min(in_range) <= low + tol and max(in_range) >= high - tol
    return False


def _hedged_numeric_parenthetical_passes(
    sentence: str,
    num_pos: int,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> bool:
    before = sentence[max(0, num_pos - 28):num_pos]
    if not _HEDGE_WORD_RE.search(before):
        return False
    after = sentence[num_pos:min(len(sentence), num_pos + 120)]
    parens = _PAREN_NUMERIC_RE.findall(after)
    if not parens:
        return False
    variants = {
        variant
        for paren in parens
        for nm in _DRIFT_NUMERIC_RE.finditer(paren)
        for variant in _numeric_variants(nm.group(0))
    }
    if not variants:
        return False
    for token in _registered_citations_in_sentence(
        sentence, citation_role_index,
    ):
        if variants & set(citation_role_index[token].keys()):
            return True
    return False


def _check_editorial_numeric_contract(
    sentence: str,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> NumericIssue | None:
    """Path A contract: prose may use editorial numeric phrasing
    only when the exact registry value is visible inline.

    This catches phrases such as "approximately one-third" when the
    sentence does not include a parenthetical exact value like
    "(31%)". It is intentionally narrow: only citation-bearing
    sentences are checked, and only common spelled-fraction phrasings
    are treated as numeric claims.
    """
    if not _registered_citations_in_sentence(sentence, citation_role_index):
        return None
    for m in _EDITORIAL_FRACTION_RE.finditer(sentence):
        after = sentence[m.end():min(len(sentence), m.end() + 100)]
        if _PAREN_NUMERIC_RE.search(after):
            continue
        return NumericIssue(
            sentence=sentence,
            issue_type="numeric_claim_contract",
            severity="P1",
            detail=(
                "Editorial numeric phrasing requires an inline exact "
                "registry value in parentheses."
            ),
            suggested_fix=(
                "Add the canonical value in parentheses or strip the "
                "sentence."
            ),
        )
    return None


def _check_unanchored_hedged_numeric_contract(
    sentence: str,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> NumericIssue | None:
    """Path A for citationless prose: approximate numeric claims are
    allowed only when every numeric is present in the registry.

    Abstracts often omit citations, but they still cannot introduce
    rounded values that Q2 cannot trace. This narrow check only fires
    for hedge-bearing sentences ("approximately", "roughly", etc.)
    with no citation token, which is the high-risk editorial-summary
    case.
    """
    if not citation_role_index:
        return None
    if _CITATION_TOKEN_RE.search(sentence):
        return None
    registered = {
        variant
        for slot in citation_role_index.values()
        for raw, roles in slot.items()
        if roles - {"unknown", "background", "protocol", "population_descriptor"}
        for variant in _numeric_variants(raw)
    }
    for m in _DRIFT_NUMERIC_RE.finditer(sentence):
        raw = m.group(1)
        before = sentence[max(0, m.start() - 32):m.start()]
        if not _HEDGE_WORD_RE.search(before):
            continue
        try:
            f = float(raw)
        except (TypeError, ValueError):
            continue
        if 1900 <= f <= 2100 and "." not in raw:
            continue
        if not (_numeric_variants(raw) & registered):
            return NumericIssue(
                sentence=sentence,
                issue_type="numeric_claim_contract",
                severity="P1",
                detail=(
                    "Citationless approximate numeric sentence contains "
                    f"unregistered value '{raw}'."
                ),
                suggested_fix=(
                    "Use exact registry values or strip the sentence."
                ),
            )
    return None


_DRIFT_PROXIMITY_WINDOW = 180  # chars; any citation within this distance is candidate

# Slice 7 P1b: prose-role classifier. Each prose numeric belongs
# to one role; the drift check compares the prose role to the source
# claim_role for the same numeric value. Universal across topics +
# domains (regex on English structural cues, no per-domain values).
_PROSE_ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    # baseline: "baseline X = N" / "starting X = N" / "pre-treatment N"
    (r"\b(?:baseline|starting|pre[\-\s]?treatment|"
     r"initial|enrolment|enrollment)\b", "baseline"),
    # population: "participants aged N" / "n = N participants"
    (r"\b(?:participants?|patients?|subjects?|sample\s+size|"
     r"enrolled|recruited|aged?)\b", "population"),
    # change_score: "change of N" / "improvement by N" / "reduction"
    (r"\b(?:change|delta|difference|increase|decrease|improvement|"
     r"reduction|decline|shift)\s+(?:of|by|in|from\s+baseline)?\b",
     "change_score"),
    # threshold: "threshold of N" / "above N" / "below N"
    (r"\b(?:threshold|cut[\-\s]?off|cutoff|below|above|"
     r"less\s+than|greater\s+than|exceeds?|falls?\s+(?:at\s+or\s+)?"
     r"(?:below|above))\b", "threshold"),
    (r"\b(?:dose|dosing|mg|mcg|µg|g/day|mg/day|once\s+daily|"
     r"weekly|administered|treated\s+with)\b", "dose"),
    # outcome / effect: "p = N" / "HR = N" / "reported N"
    (r"\b(?:reported|observed|p\s*[<=>]|hr\s*=|or\s*=|rr\s*=|"
     r"effect\s+size|outcome|primary\s+endpoint)\b", "effect"),
)


def _classify_prose_numeric_role(
    sentence: str, num_pos: int, num: str,
) -> str:
    """Classify a prose numeric's role from the local sentence
    context. Window: 60 chars before + 30 chars after the numeric.
    Returns 'baseline' / 'population' / 'change_score' / 'threshold'
    / 'effect' / 'outcome' (default).
    Universal — operates on structural English cues only."""
    start = max(0, num_pos - 60)
    end = min(len(sentence), num_pos + len(num) + 30)
    window = sentence[start:end].lower()
    # A numeric immediately followed by a time unit is a study DURATION
    # (design parameter), never a participant count — so "enrolled ... over 12
    # months" must not render as "a population descriptor of 12 months". Ages
    # ("aged 65 years", "65-year-old") are the one time-unit case that IS a
    # population descriptor, so they are exempted. Universal — structural cues.
    tail = sentence[num_pos + len(num): num_pos + len(num) + 14].lower()
    followed_by_time = re.match(
        r"\s*[-–—]?\s*(?:month|year|week|day|hour|wk|yr|mo)s?\b", tail,
    )
    is_age = re.search(r"\b(?:aged?|years?\s+of\s+age|year[-\s]old)\b", window)
    is_duration = bool(followed_by_time) and not is_age
    # Order matters: more specific patterns checked first
    for pattern, role in _PROSE_ROLE_PATTERNS:
        if role == "population" and is_duration:
            continue
        if re.search(pattern, window, flags=re.IGNORECASE):
            return role
    return "outcome"


# Roles considered compatible (one of these in source means the
# prose role is acceptable). Universal — biomedical / management /
# economics all share these primitive role kinds.
_ROLE_COMPATIBILITY: dict[str, frozenset[str]] = {
    # baseline/population: pre-treatment cohort descriptors. ROLE
    # drift fires when prose frames a numeric as baseline but the
    # source tags it as a change_score or effect (the metformin
    # 0.13 m/s gait-speed class — Witham 2025 has 0.13 as effect,
    # not baseline). Excluding 'effect' / 'change_score' from
    # baseline-compat is the load-bearing decision.
    "baseline": frozenset(("baseline", "population", "outcome")),
    "population": frozenset(("population", "baseline", "outcome")),
    "change_score": frozenset(("change_score", "effect", "outcome")),
    "threshold": frozenset(("threshold", "canonical")),
    "dose": frozenset(("dose", "unit_value", "outcome", "effect")),
    "effect": frozenset(("effect", "change_score", "outcome")),
    # 'outcome' is the most permissive default (used when prose
    # role is unclassifiable); accepts most source roles to keep
    # false-positive rate low on ambiguous prose.
    "outcome": frozenset((
        "outcome", "effect", "population", "baseline",
        "change_score", "dose", "unit_value", "canonical",
    )),
}


def _roles_match(prose_role: str, source_roles: set[str]) -> bool:
    """A prose role accepts any of its compatible source roles.
    Special cases:
      - source_roles empty (no role data) → pass (fail-soft)
      - 'canonical' in source_roles (bg_lit registry numeric, which
        is a flat fact without role interpretation) → pass for any
        prose role. bg_lit numerics like 'Harrison 2009 / 14% mouse
        lifespan' are legitimately quotable as a change_score in
        prose even though they're tagged canonical in the registry."""
    if not source_roles:
        return True
    if "canonical" in source_roles:
        return True
    compatible = _ROLE_COMPATIBILITY.get(
        prose_role, frozenset(("outcome",)),
    )
    return bool(compatible & source_roles)


def _check_source_context_drift(
    sentence: str,
    citation_role_index: dict[str, dict[str, set[str]]],
) -> NumericIssue | None:
    """For each numeric, gather citations within
    _DRIFT_PROXIMITY_WINDOW chars; the drift check now compares
    prose ROLE to source CLAIM_ROLE per matching numeric value.

    Two failure modes:
      VALUE drift: numeric absent from every nearby citation's
                   source context (the original Slice 7 P1 check)
      ROLE drift:  numeric present in source but tagged with a
                   different role than the prose used (P1b: 'prose
                   says baseline 0.13 m/s but Witham has 0.13 only
                   as a change_score').

    Both fire as severity=P1, issue_type='source_context_drift'.
    Universal across topics + domains."""
    if not citation_role_index:
        return None
    cite_matches = list(_CITATION_TOKEN_RE.finditer(sentence))
    if not cite_matches:
        return None
    num_positions: list[tuple[int, str]] = []
    for m in _DRIFT_NUMERIC_RE.finditer(sentence):
        raw = m.group(1)
        try:
            f = float(raw)
        except (TypeError, ValueError):
            continue
        if 1900 <= f <= 2100 and "." not in raw:
            continue
        num_positions.append((m.start(), raw))
    if not num_positions:
        return None

    def _midpoint(match) -> int:
        return (match.start() + match.end()) // 2

    for num_pos, num in num_positions:
        nearby = [
            c for c in cite_matches
            if abs(_midpoint(c) - num_pos) <= _DRIFT_PROXIMITY_WINDOW
        ]
        if not nearby:
            continue
        nearby_keyed = [
            (f"{c.group(1)} {c.group(2)}", c) for c in nearby
        ]
        closest_any = min(
            nearby_keyed,
            key=lambda kc: abs(_midpoint(kc[1]) - num_pos),
        )
        # If the number is closest to a citation we do not have source
        # context for, fail soft instead of attributing it to a farther
        # registered citation. This covers guideline/canon side-claims
        # like "ADA 2024 target of 7%" or "Anisimov 2008 benchmark"
        # in sentences that also cite receipt papers.
        if closest_any[0] not in citation_role_index:
            continue
        post_unknown = [
            (k, c) for k, c in nearby_keyed
            if c.start() > num_pos
            and c.start() - num_pos <= 80
            and k not in citation_role_index
        ]
        if post_unknown:
            continue
        registered = [
            (k, c) for k, c in nearby_keyed
            if k in citation_role_index
        ]
        if not registered:
            continue
        variants = _numeric_variants(num)
        # 1. Value-membership check (Slice 7 P1)
        any_value_match = any(
            variants & set(citation_role_index[k].keys())
            for k, _ in registered
        )
        if not any_value_match:
            if _range_contract_passes(
                sentence, num_pos, citation_role_index,
            ) or _hedged_numeric_parenthetical_passes(
                sentence, num_pos, citation_role_index,
            ):
                continue
            closest_reg = min(
                registered,
                key=lambda kc: abs(_midpoint(kc[1]) - num_pos),
            )
            return NumericIssue(
                sentence=sentence,
                issue_type="source_context_drift",
                severity="P1",
                detail=(
                    f"Numeric '{num}' near citation(s) "
                    f"{[k for k, _ in registered]} but not present "
                    f"in any of their source contexts. Closest: "
                    f"{closest_reg[0]}."
                ),
                suggested_fix=(
                    "Verify the cited paper or strip the sentence."
                ),
            )
        # 2. Role-match check (Slice 7 P1b — the deeper drift)
        prose_role = _classify_prose_numeric_role(
            sentence, num_pos, num,
        )
        role_passed = False
        all_source_roles: set[str] = set()
        matched_token = None
        for k, _ in registered:
            for variant in variants:
                source_roles = citation_role_index[k].get(variant)
                if source_roles is None:
                    continue
                all_source_roles |= source_roles
                if _roles_match(prose_role, source_roles):
                    role_passed = True
                    break
                else:
                    matched_token = matched_token or k
            if role_passed:
                break
        if not role_passed and all_source_roles:
            return NumericIssue(
                sentence=sentence,
                issue_type="source_context_drift",
                severity="P1",
                detail=(
                    f"ROLE drift: prose uses '{num}' as "
                    f"'{prose_role}' but source "
                    f"({matched_token}) tags it as "
                    f"{sorted(all_source_roles)}. Numeric exists "
                    f"in cited paper but with different "
                    f"interpretive role."
                ),
                suggested_fix=(
                    "Verify the cited paper's claim role or strip "
                    "the sentence."
                ),
            )
    return None


def _strip_references_section(paper_md: str) -> str:
    """Slice 7 step 1: drift check is meaningless inside the
    References section (PMIDs / DOIs / volumes / years are not
    claim numerics). Strip everything from the first
    '## References' / '## Bibliography' heading to end before
    running the drift scan."""
    import re as _re
    m = _re.search(
        r"^##\s+(References|Bibliography|Reference\s+List)\s*$",
        paper_md, _re.MULTILINE | _re.IGNORECASE,
    )
    if m:
        return paper_md[: m.start()]
    return paper_md


def _strip_citation_footer_lines(paper_md: str) -> str:
    """Remove deterministic `_Cited:` footer lines before prose-role
    scanning. They are citation metadata, not prose, and can otherwise
    merge adjacent section text into one synthetic sentence."""
    return "\n".join(
        line for line in paper_md.splitlines()
        if not line.strip().startswith("_Cited:")
    )


def _strip_markdown_table_lines(paper_md: str) -> str:
    return "\n".join(
        line for line in paper_md.splitlines()
        if not line.lstrip().startswith("|")
    )


_NON_PROSE_GUARD_SECTION_RE = re.compile(
    r"^##\s+(?:Quantitative Evidence Index\b|Structured Evidence "
    r"Tables\b|What This Synthesis Adds\b|Evidence Snapshot\b|Table\s+\d+\b|"
    r"Table\s+\d+\s*\(|References\b)",
    flags=re.IGNORECASE,
)


def _strip_non_prose_guard_sections(paper_md: str) -> str:
    """Drop deterministic tables/QEI/references before prose-role
    scanning. These sections contain dense citation/numeric matrices,
    not sentences; scanning them creates false drift checks and
    quadratic work on large corpora."""
    lines = paper_md.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            skipping = bool(_NON_PROSE_GUARD_SECTION_RE.match(line))
        if not skipping:
            out.append(line)
    return "\n".join(out)


# Figure / Table / Section / Equation references — skip the drift
# check on sentences that mention these (they cite a paper element,
# not a claim numeric).
_NON_CLAIM_PROXIMITY_RE = re.compile(
    r"\b(?:Figure|Fig\.|Table|Tab\.|Section|Sec\.|Equation|Eq\.|"
    r"Chapter|Appendix)\s+\d",
    flags=re.IGNORECASE,
)


def scan_paper(
    paper_md: str, *,
    manifest: dict | None = None,
    bg_lit_registry: dict | None = None,
    quant_claims_dir=None,
) -> list[NumericIssue]:
    """Run all numeric-role checks across every sentence in the
    paper. Returns flat list of issues — caller decides how to
    report (audit P1 list, auto-strip, etc.).

    Slice 7 step 1: optional `manifest` + `bg_lit_registry` +
    `quant_claims_dir` enable the source-context drift check.
    The drift check runs on the body only (References section
    stripped) and skips Figure/Table/Equation reference sentences."""
    issues: list[NumericIssue] = []
    # Slice 7 P1b: drift now uses a {token: {numeric: {roles}}}
    # role index instead of the flat {token: {numerics}} set so the
    # check can distinguish VALUE drift from ROLE drift. Both fire
    # at severity=P1, issue_type='source_context_drift'.
    citation_role_index = _build_citation_role_index(
        manifest=manifest,
        bg_lit_registry=bg_lit_registry,
        quant_claims_dir=quant_claims_dir,
    )
    global_allowed_numerics = _build_global_allowed_numerics(
        manifest=manifest,
        bg_lit_registry=bg_lit_registry,
        quant_claims_dir=quant_claims_dir,
    )
    prose_md = _strip_markdown_table_lines(_strip_citation_footer_lines(
        _strip_non_prose_guard_sections(paper_md),
    ))
    body_for_drift = _strip_references_section(prose_md)
    drift_sentences = set(_split_sentences(body_for_drift))
    for sentence in _split_sentences(prose_md):
        unanchored_contract = _check_unanchored_hedged_numeric_contract(
            sentence, citation_role_index,
        )
        if unanchored_contract:
            issues.append(unanchored_contract)
            continue
        contract_issue = _check_editorial_numeric_contract(
            sentence, citation_role_index,
        )
        if contract_issue:
            issues.append(contract_issue)
            continue
        for check in (
            _check_arithmetic_violations,
            _check_role_mismatch,
            _check_no_change_nonzero_parenthetical,
            _check_malformed_subject,
        ):
            issue = check(sentence)
            if issue:
                issues.append(issue)
                break  # one issue per sentence is enough to fail it
        else:
            # Drift check: body only, skip Figure/Table/Eq refs.
            if (
                sentence in drift_sentences
                and not _NON_CLAIM_PROXIMITY_RE.search(sentence)
            ):
                issue = _check_source_context_drift(
                    sentence, citation_role_index,
                )
                if issue:
                    issues.append(issue)
                    continue
            bad_nums = _untraceable_reportable_numerics(
                sentence, global_allowed_numerics,
            )
            if bad_nums:
                issues.append(NumericIssue(
                    sentence=sentence,
                    issue_type="untraceable_numeric",
                    severity="P1",
                    detail=(
                        "Reportable prose numeric(s) not present in the "
                        f"strict corpus numeric pool: {bad_nums[:3]}"
                    ),
                    suggested_fix=(
                        "Strip the sentence or replace the numeric with a "
                        "registered corpus value."
                    ),
                ))
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


def repair_source_context_drift_sentences(
    paper_md: str,
    issues: Iterable[NumericIssue],
    *,
    manifest: dict | None = None,
    bg_lit_registry: dict | None = None,
    quant_claims_dir=None,
) -> tuple[str, int]:
    """Repair ROLE-drift sentences before deletion.

    The rewrite is intentionally conservative: it preserves only the
    cited token and offending numeric, restates the source role, and
    is accepted only if a fresh Numeric Role Guard scan passes.
    """
    out = paper_md
    n = 0
    for issue in issues:
        if (
            issue.severity != "P1"
            or issue.issue_type != "source_context_drift"
            or "ROLE drift" not in issue.detail
            or issue.sentence not in out
        ):
            continue
        repaired = _role_aligned_repair_sentence(issue)
        if not repaired:
            continue
        new_issues = scan_paper(
            repaired,
            manifest=manifest,
            bg_lit_registry=bg_lit_registry,
            quant_claims_dir=quant_claims_dir,
        )
        if any(i.severity == "P1" for i in new_issues):
            continue
        out = out.replace(issue.sentence, repaired, 1)
        n += 1
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, n


def _role_aligned_repair_sentence(issue: NumericIssue) -> str:
    m = re.search(
        r"prose uses '([^']+)' as '([^']+)'.*?source "
        r"\(([^)]*)\) tags it as \[([^\]]+)\]",
        issue.detail,
    )
    if not m:
        return ""
    num, _prose_role, detail_token, roles_raw = m.groups()
    roles = re.findall(r"'([^']+)'", roles_raw)
    source_role = _preferred_repair_role(set(roles))
    token = detail_token if detail_token and detail_token != "None" else ""
    if not token:
        cm = _CITATION_TOKEN_RE.search(issue.sentence)
        token = f"{cm.group(1)} {cm.group(2)}" if cm else ""
    if not token or not source_role:
        return ""
    display_num = _display_numeric_with_unit(issue.sentence, num)
    if source_role == "dose" and not re.search(
        r"\b(?:mg|g|µg|ug|mL|IU|kg/day|mg/day|/day|/d)\b",
        display_num,
        flags=re.IGNORECASE,
    ):
        return ""
    if source_role == "effect" and re.search(
        rf"\b[Pp]\s*[<=>]\s*{re.escape(num)}\b",
        issue.sentence,
    ):
        return ""
    role_phrase = {
        "change_score": f"a change of {display_num}",
        "threshold": f"a threshold of {display_num}",
        "dose": f"a dose of {display_num}",
        "baseline": f"a baseline value of {display_num}",
        "population": f"a population descriptor of {display_num}",
        "effect": f"an effect estimate of {display_num}",
        "outcome": f"an outcome measure of {display_num}",
        "unit_value": f"an outcome measure of {display_num}",
    }.get(source_role, f"an outcome measure of {display_num}")
    return f"{token} reported {role_phrase}."


def _preferred_repair_role(roles: set[str]) -> str:
    for role in (
        "change_score", "threshold", "dose", "baseline",
        "population", "effect", "outcome", "unit_value",
    ):
        if role in roles:
            return role
    return next(iter(roles), "")


def _display_numeric_with_unit(sentence: str, num: str) -> str:
    m = re.search(
        rf"(?<!\d){re.escape(num)}(?:\s*(?:%|[A-Za-zµ/]+))?",
        sentence,
    )
    return m.group(0).strip() if m else num


__all__ = [
    "NumericIssue",
    "scan_paper",
    "repair_source_context_drift_sentences",
    "auto_strip_offending_sentences",
]
