"""Fix #6: Deterministic 3-table renderer (included studies / endpoint
evidence / evidence limitations).

Pre-fix: Q9 numeric density failed because the writer had to inject
all numerics inline in prose (5.5/1k vs 8.0 target). PhD-style review
papers solve this with structured tables: numbers live in tables, prose
references them. Tables also force the cross-paper structural rigor
the reviewer flagged as missing (no risk-of-bias table, no endpoint
evidence table, no included-studies table).

Fix: render the 3 tables deterministically from receipts + the upstream
fixes (citation_registry + evidence_taxonomy + effect_direction). The
writer never touches tables. Tables are appended to the paper before
the References section; readers see them immediately after the prose
sections.

Architecture: pure deterministic, no LLM, no I/O. Operates on a list
of ReceiptSummary objects (post-citation-substitution if Fix #3 ran).

Reviewer-pass v2 hardening:
  - N-extraction uses regex with range support (`n=120-150`) and
    handles missing `n=` / reversed-order population strings.
  - Markdown escaping covers pipe + newline + backtick + carriage
    return so cell content can never break row parsing.
  - Tables 1/3 use the `Citation` column header consistently; the
    underlying citation strings are sourced from the same upstream
    body_citation that the References block uses (no drift).
  - Aggregator semantics + table label clarified: "Predominant
    direction" with footnote on how it differs from the pairwise
    TensionMatrix kind."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


# Reviewer-fix P1: complete cell-content sanitization so newlines
# don't fork the row, backticks don't toggle code mode, and pipes
# don't open new cells. Carriage returns also stripped (Windows line
# endings in source data).
def _row(*cells: str) -> str:
    """Render one markdown table row from cell strings, escaping every
    char that would otherwise break markdown table parsing."""
    sanitized = []
    for c in cells:
        s = c if c is not None else ""
        s = s.replace("\r", "").replace("\n", " ")
        s = s.replace("|", "\\|")
        s = s.replace("`", "\\`")
        sanitized.append(s.strip())
    return "| " + " | ".join(sanitized) + " |"


def _safe(v: Any, default: str = "n/a") -> str:
    """Render a possibly-None value as a non-empty string."""
    if v is None or v == "":
        return default
    return str(v)


# Reviewer-fix P1: regex-based N extraction. Examples:
#   "older adults, n=120"           → ("120",  "older adults")
#   "n=120, older adults"           → ("120",  "older adults")  reversed
#   "n=120-150, older adults"       → ("120-150", "older adults")  range
#   "n=120 (treatment), n=60 (placebo)"
#                                   → ("180",  "older adults") arm-summed
#   "n=120 (subset analysis, n=15)" → ("120",  "older adults")  largest
#                                                               (no arm sum)
#   "older adults"                  → ("—",    "older adults")
_N_RE = re.compile(r"n\s*=\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)
# Arm-context keywords. We sum n= values across MULTIPLE matches only
# when each match has an arm-context word within ~20 chars (treatment +
# placebo = total cohort). Otherwise (subgroup, subset, follow-up, etc.)
# we return the largest single match — the total cohort dominates.
_ARM_CONTEXT_RE = re.compile(
    r"\b(treatment|placebo|intervention|control|arm|active|"
    r"experimental|comparator)\b",
    re.IGNORECASE,
)


def _has_arm_context(haystack: str, span: tuple[int, int]) -> bool:
    """True if an arm keyword appears within 20 chars of the span."""
    start = max(0, span[0] - 20)
    end = min(len(haystack), span[1] + 20)
    return bool(_ARM_CONTEXT_RE.search(haystack[start:end]))


def _split_population_n(population_summary: str) -> tuple[str, str]:
    """Split a population_summary string into (N_string, pop_label).

    P1 reviewer fix v2 (2nd-pass): subset/nested `n=` no longer over-
    counts. We only SUM matches when each match has an arm-context
    keyword (treatment, placebo, intervention, control) nearby — that
    pattern represents two arms of a trial. Otherwise (subgroup,
    subset, follow-up annotation), we return the largest single match
    so the total cohort dominates."""
    if not population_summary or population_summary == "—":
        return "—", "—"

    matches = list(_N_RE.finditer(population_summary))
    if not matches:
        label = population_summary.split(",")[0].strip()
        return "—", label or "—"

    int_values: list[int] = []
    range_strings: list[str] = []
    arm_count = 0
    for m in matches:
        try:
            v_lo = int(m.group(1))
        except ValueError:
            continue
        if m.group(2):
            try:
                v_hi = int(m.group(2))
            except ValueError:
                v_hi = v_lo
            range_strings.append(f"{v_lo}-{v_hi}")
            int_values.append(max(v_lo, v_hi))
        else:
            int_values.append(v_lo)
        if _has_arm_context(population_summary, m.span()):
            arm_count += 1

    if not int_values and not range_strings:
        n_str = "—"
    elif range_strings and len(matches) == 1:
        # Single range match → preserve verbatim
        n_str = range_strings[0]
    elif arm_count >= 2 and not range_strings:
        # Multiple arm-context matches with no ranges → sum (the
        # canonical treatment + placebo = total pattern)
        n_str = str(sum(int_values))
    elif range_strings and len(int_values) > 1:
        # Range + other values → show the largest single value with
        # explicit annotation that ranges are present, so we never
        # silently drop information
        n_str = f"{max(int_values)} (+ranges)"
    else:
        # Subset / subgroup / multi-without-arm-context → largest wins
        n_str = str(max(int_values)) if int_values else "—"

    # Strip the `n=...` substring(s) from the population label.
    cleaned = _N_RE.sub("", population_summary).strip()
    cleaned = re.sub(r"[,;]\s*[,;]+", ",", cleaned)
    cleaned = re.sub(r"^[,;\s]+|[,;\s]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    # Reviewer-fix P2: pick the LONGEST non-empty comma segment as the
    # label, not the first — when n= is mid-string the first segment
    # may be truncated ("older adults" out of "older adults, with
    # diabetes" loses the qualifier).
    if cleaned:
        segments = [s.strip() for s in cleaned.split(",") if s.strip()]
        pop_label = max(segments, key=len) if segments else "—"
    else:
        pop_label = "—"
    return n_str, pop_label or "—"


def _representative_p_value(r: object) -> str:
    """Smallest (most-significant) p-value from receipt's p_values
    list. Pre-fix returned the FIRST entry which was iteration-order
    dependent → non-deterministic across runs and not aligned with
    what a clinician would cite as 'representative.' Reviewer P2.

    Returns the raw p-value string (e.g. 'p < 0.001') or '—'.
    Falls back to first non-empty entry if no entries parse."""
    pvals = [p.strip() for p in (getattr(r, "p_values", None) or ())
             if p and p.strip()]
    if not pvals:
        return "—"
    parsed: list[tuple[float, str]] = []
    for p in pvals:
        m = re.search(r"\d*\.?\d+(?:[eE][-+]?\d+)?", p)
        if not m:
            continue
        try:
            parsed.append((float(m.group(0)), p))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return pvals[0]
    parsed.sort(key=lambda t: t[0])
    return parsed[0][1]


def _n_claims(r: object) -> str:
    """High-confidence-claim count for a receipt — a measure of
    evidence density already in the manifest."""
    n = getattr(r, "n_claims", None)
    return str(n) if isinstance(n, int) and n > 0 else "—"


def render_table_1_included_studies(receipts: list) -> str:
    """Table 1 — one row per source paper. Columns: Citation | Tier |
    Directness | N | Population | Outcome class | Effect direction |
    Representative p-value | n claims | Trial ID.

    Fix #12: added Representative p-value + n claims columns to
    surface numerics the writer already aggregated. Lifts Q9
    numeric density without prose bloat (per the reviewer's
    'tables-not-paragraphs' guidance)."""
    header = (
        "## Table 1: Included Studies\n\n"
        + _row(
            "Citation", "Tier", "Directness", "N",
            "Population", "Outcome class", "Effect direction",
            "Representative p-value", "n claims", "Trial ID",
        )
        + "\n"
        + _row(
            "---", "---", "---", "---", "---",
            "---", "---", "---", "---", "---",
        )
        + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        pop_raw = getattr(r, "population_summary", None) or "—"
        n_str, pop_label = _split_population_n(pop_raw)
        rows.append(_row(
            _safe(getattr(r, "receipt_id", None), "—"),
            _safe(getattr(r, "evidence_tier", None), "—"),
            _safe(getattr(r, "directness", None), "—"),
            n_str,
            pop_label,
            _safe(getattr(r, "outcome_class", None), "—"),
            _safe(getattr(r, "effect_direction", None), "—"),
            _representative_p_value(r),
            _n_claims(r),
            _safe(getattr(r, "canonical_trial_id", None), "—"),
        ))
    return header + "\n".join(rows) + "\n"


def render_table_2_endpoint_evidence(receipts: list) -> str:
    """Table 2 — one row per outcome class, aggregating across studies.
    Columns: Outcome class | # studies | # direct | # mechanistic |
    # null | # mixed | Net direction."""
    by_outcome: dict[str, list] = defaultdict(list)
    for r in receipts:
        oc = getattr(r, "outcome_class", None) or "unspecified"
        by_outcome[oc].append(r)

    # Reviewer-fix P1 #4 + label honesty: "Predominant direction"
    # makes explicit this is an aggregate roll-up, not the same axis
    # as the pairwise TensionMatrix kind. Footnote follows the table.
    header = (
        "## Table 2: Endpoint Evidence Aggregation\n\n"
        + _row(
            "Outcome class", "# studies", "Direct (A1/A2)",
            "Mechanistic (C)", "Null", "Mixed", "Predominant direction",
        )
        + "\n"
        + _row("---", "---", "---", "---", "---", "---", "---")
        + "\n"
    )
    rows: list[str] = []
    for oc in sorted(by_outcome):
        receipts_for_oc = by_outcome[oc]
        n_total = len(receipts_for_oc)
        n_direct = sum(
            1 for r in receipts_for_oc
            if (getattr(r, "evidence_tier", "") or "").startswith("A")
        )
        n_mech = sum(
            1 for r in receipts_for_oc
            if (getattr(r, "evidence_tier", "") or "").startswith("C")
        )
        n_null = sum(
            1 for r in receipts_for_oc
            if getattr(r, "effect_direction", None) == "null"
        )
        n_mixed = sum(
            1 for r in receipts_for_oc
            if getattr(r, "effect_direction", None) == "mixed"
        )
        net = _aggregate_net_direction(receipts_for_oc)
        rows.append(_row(
            oc, str(n_total), str(n_direct),
            str(n_mech), str(n_null), str(n_mixed), net,
        ))
    return header + "\n".join(rows) + "\n"


def _aggregate_net_direction(receipts: list) -> str:
    """Roll-up direction across multiple studies in the same outcome
    class. Distinct semantic axis from the pairwise TensionMatrix:
    here we report 'what does the body of evidence look like in
    aggregate', NOT 'do these two studies agree'.

    Algorithm:
      - All studies same direction → that direction (handles
        all-null, all-mixed, all-positive uniformly)
      - Any mixed-finding study → mixed (the class has internal
        contradiction at the study level)
      - Positive AND negative significant directions present → mixed
        (cross-study disagreement)
      - Majority direction → that direction
      - Tie → unclear"""
    directions = [
        getattr(r, "effect_direction", None) or "unclear" for r in receipts
    ]
    if not directions:
        return "unclear"
    unique = set(directions)
    if len(unique) == 1:
        return directions[0]
    if "mixed" in unique:
        return "mixed"
    pos = sum(1 for d in directions if d == "positive")
    neg = sum(1 for d in directions if d == "negative")
    if pos and neg:
        return "mixed"
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "unclear"


# Risk-of-bias / confounding assessment heuristics. Per-tier defaults
# the reviewer would expect a PhD-grade evidence-synthesis paper to
# include — derived deterministically from evidence_tier so prose
# doesn't need to invent assessments.
_TIER_RISK_OF_BIAS: dict[str, str] = {
    "A1": "low — randomization protects against confounding",
    "A2": "low — randomization; mechanistic endpoint may not reflect "
          "clinical effect",
    "B1": "varies — depends on included studies' tier mix",
    "B2": "high — confounding by indication, healthy-user bias possible",
    "C1": "moderate — preclinical extrapolation to humans uncertain",
    "C2": "moderate — review-of-mechanism, no primary data",
    "unknown": "unknown — metadata insufficient to grade",
}
_TIER_GENERALIZABILITY: dict[str, str] = {
    "A1": "trial population only; external validity needs replication",
    "A2": "trial population only; mechanistic findings may not generalize",
    "B1": "depends on included studies",
    "B2": "human population observed; selection effects possible",
    "C1": "model organism only; human relevance requires translation",
    "C2": "no primary population — generalizability not applicable",
    "unknown": "unknown",
}


def render_table_3_evidence_limitations(receipts: list) -> str:
    """Table 3 — one row per study; risk-of-bias, confounding,
    generalizability assessments derived deterministically from
    evidence_tier.

    Reviewer-fix P2: the column is labelled `Risk of bias (tier
    proxy)` and a caveat above the table makes the pipeline-level
    limitation explicit — this is a tier-derived heuristic, NOT a
    per-domain Cochrane RoB-2 grading."""
    header = (
        "## Table 3: Evidence Limitations\n\n"
        "*Risk-of-bias values are tier-derived heuristics, NOT a "
        "per-domain Cochrane RoB-2 assessment. For tier B1 (systematic "
        "reviews) the assessment depends on the inner studies' tier "
        "mix, which is not represented in this pipeline.*\n\n"
        + _row(
            "Citation", "Tier", "Risk of bias (tier proxy)",
            "Generalizability", "Effect direction notes",
        )
        + "\n"
        + _row("---", "---", "---", "---", "---")
        + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        tier = getattr(r, "evidence_tier", "") or "unknown"
        rob = _TIER_RISK_OF_BIAS.get(tier, "unknown")
        gen = _TIER_GENERALIZABILITY.get(tier, "unknown")
        direction = getattr(r, "effect_direction", None) or "unclear"
        # Direction-specific note
        if direction == "null":
            note = "primary endpoint did not reach significance"
        elif direction == "mixed":
            note = "internal contradiction across endpoints"
        elif direction == "unclear":
            note = "signed claims without significance signal"
        else:
            note = f"{direction} effect — see Tables 1/2"
        rows.append(_row(
            _safe(getattr(r, "receipt_id", None), "—"),
            tier, rob, gen, note,
        ))
    return header + "\n".join(rows) + "\n"


def render_all_tables(receipts: list) -> str:
    """Render all three tables back-to-back as a single markdown block.

    Includes a leading pointer sentence (reviewer-fix P2) so the body
    prose has a natural reference site for the structured evidence.
    A footnote between Tables 2 and 3 clarifies the semantic
    difference between the table aggregator and the pairwise
    TensionMatrix kind (avoids the contradictory-verdict trap).

    Returns empty string when receipts is empty."""
    if not receipts:
        return ""
    pointer = (
        "## Structured Evidence Tables\n\n"
        "*The following three tables present the deterministic "
        "evidence summary referenced throughout this paper. Numbers "
        "live in the tables; prose references them.*\n\n"
    )
    semantic_note = (
        "*Note: 'Predominant direction' is an aggregate roll-up "
        "across studies in the same outcome class. It is a different "
        "semantic axis from the pairwise TensionMatrix kind discussed "
        "in the prose — two studies both classified as `mixed` will "
        "appear here as `mixed` (study-level contradiction in each) "
        "but as `agreement` in the matrix (both share the same "
        "study-level conclusion).*\n\n"
    )
    return (
        pointer
        + render_table_1_included_studies(receipts)
        + "\n"
        + render_table_2_endpoint_evidence(receipts)
        + "\n"
        + semantic_note
        + render_table_3_evidence_limitations(receipts)
    )
