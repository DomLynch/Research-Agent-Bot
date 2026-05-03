"""Fix #6 + Fix #21: Deterministic per-paper evidence tables.

Pre-fix: Q9 numeric density failed because the writer had to inject
all numerics inline in prose (4.3/1k vs 8.0 target). PhD-style review
papers solve this with structured tables: numbers live in tables, prose
references them.

Fix #21 reshape (per the asymmetric-fix reviewer guidance):

  Table 1 — Included Studies
    Citation | Design | Tier | N | Population | Endpoint | Direction
    | Directness | Trial ID | Representative p-value | n claims

  Table 2 — Per-Study Endpoint Evidence
    One row per (study × p-value) → DENSE numerics carrier.
    Endpoint | Study | p/CI | Direction | Directness | Tier
    | Interpretation

  Table 3 — Cross-Domain Tensions
    One row per non-orthogonal pair from the TensionMatrix.
    Tension kind | Severity | Receipt A | Receipt B | Outcome class
    | Summary | Practical implication

  Table 4 (supplemental) — Per-Domain Risk of Bias
    Cochrane RoB-2 / ROBINS-I-style per-tier domain grades
    (allocation, blinding, attrition, …). Kept from Fix #14 for
    PhD-grade reviewer credibility.

Architecture: pure deterministic, no LLM, no I/O. Operates on a list
of ReceiptSummary objects (post-citation-substitution if Fix #3 ran)
and (optionally) the TensionMatrix from build_tension_matrix.

Reviewer-pass v2 hardening (preserved):
  - N-extraction uses regex with range support (`n=120-150`) and
    handles missing `n=` / reversed-order population strings.
  - Markdown escaping covers pipe + newline + backtick + carriage
    return so cell content can never break row parsing.
  - Tables 1/2 use the `Citation` column header consistently; the
    underlying citation strings are sourced from the same upstream
    body_citation that the References block uses (no drift)."""
from __future__ import annotations

import re
from typing import Any


# Reviewer-fix P1: complete cell-content sanitization so newlines
# don't fork the row, backticks don't toggle code mode, and pipes
# don't open new cells. Carriage returns also stripped.
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


# --- Reused helpers from Fix #6 -----------------------------------------


_N_RE = re.compile(r"n\s*=\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)
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

    Subgroup/subset n= no longer over-counts (only sums when each
    match has an arm-context keyword nearby). Otherwise returns the
    largest single match — the total cohort dominates."""
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
        n_str = range_strings[0]
    elif arm_count >= 2 and not range_strings:
        n_str = str(sum(int_values))
    elif range_strings and len(int_values) > 1:
        n_str = f"{max(int_values)} (+ranges)"
    else:
        n_str = str(max(int_values)) if int_values else "—"
    cleaned = _N_RE.sub("", population_summary).strip()
    cleaned = re.sub(r"[,;]\s*[,;]+", ",", cleaned)
    cleaned = re.sub(r"^[,;\s]+|[,;\s]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if cleaned:
        segments = [s.strip() for s in cleaned.split(",") if s.strip()]
        pop_label = max(segments, key=len) if segments else "—"
    else:
        pop_label = "—"
    return n_str, pop_label or "—"


def _representative_p_value(r: object) -> str:
    """Smallest (most-significant) p-value from receipt's p_values."""
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
    """High-confidence-claim count for a receipt."""
    n = getattr(r, "n_claims", None)
    return str(n) if isinstance(n, int) and n > 0 else "—"


# --- Fix #21 new: design label from evidence_tier ------------------------


_DESIGN_BY_TIER: dict[str, str] = {
    "A1": "RCT (clinical)",
    "A2": "RCT (mechanistic)",
    "B1": "Review / meta-analysis",
    "B2": "Observational",
    "C1": "Preclinical (animal/in vitro)",
    "C2": "Preclinical (cell-only)",
    "mixed": "Mixed cluster",
}


def _design_from_tier(tier: str | None) -> str:
    """Map evidence_tier → human-readable study design label.

    Used in Table 1 to give the reader a one-glance design read
    (RCT vs review vs preclinical) without needing to memorise the
    A1/A2/B/C tier code."""
    if not tier:
        return "—"
    return _DESIGN_BY_TIER.get(tier, tier)


# --- Table 1: Included Studies ------------------------------------------


def render_table_1_included_studies(receipts: list) -> str:
    """Table 1 — one row per source paper.

    Columns: Citation | Design | Tier | N | Population | Endpoint
    | Direction | Directness | Trial ID | Representative p-value
    | n claims

    Fix #21 added: Design column (derived from evidence_tier) so the
    reader sees study type at a glance. Trial ID is the canonical
    NCT/ISRCTN. Representative p-value + n claims come from the
    Fix #12 numeric-density boost."""
    header = (
        "## Table 1: Included Studies\n\n"
        + _row(
            "Citation", "Design", "Tier", "N", "Population",
            "Endpoint", "Direction", "Directness",
            "Trial ID", "Representative p-value", "n claims",
        )
        + "\n"
        + _row(*(["---"] * 11)) + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        pop_raw = getattr(r, "population_summary", None) or "—"
        n_str, pop_label = _split_population_n(pop_raw)
        tier = _safe(getattr(r, "evidence_tier", None), "—")
        rows.append(_row(
            _safe(getattr(r, "receipt_id", None), "—"),
            _design_from_tier(tier),
            tier,
            n_str,
            pop_label,
            _safe(getattr(r, "outcome_class", None), "—"),
            _safe(getattr(r, "effect_direction", None), "—"),
            _safe(getattr(r, "directness", None), "—"),
            _safe(getattr(r, "canonical_trial_id", None), "—"),
            _representative_p_value(r),
            _n_claims(r),
        ))
    return header + "\n".join(rows) + "\n"


# --- Table 2: Per-Study Endpoint Evidence (DENSE) -----------------------


def _interpretation(direction: str, outcome: str) -> str:
    """One-line plain-English interpretation per direction × outcome.

    Templated to keep the renderer pure-deterministic — no LLM. The
    output reads naturally so a reader can scan the column without
    needing a glossary."""
    if direction == "positive":
        return f"improves {outcome}"
    if direction == "negative":
        return f"worsens {outcome}"
    if direction == "null":
        return f"no significant effect on {outcome}"
    if direction == "mixed":
        return f"mixed signal on {outcome}"
    return f"unclear effect on {outcome}"


def render_table_2_endpoint_evidence(receipts: list) -> str:
    """Table 2 — one row per (study × p-value) tuple.

    Columns: Endpoint | Study | p/CI | Direction | Directness | Tier
    | Interpretation

    Fix #21 reshape: previous layout aggregated by outcome_class
    (one row per endpoint). The new dense layout produces one row per
    (study, p-value) — for a corpus of 15 studies × ~3 p-values each
    that is ~45 rows of structured numerics, materially raising Q9
    density without prose bloat. Studies with no p-values still
    contribute one row with `—` so the reader sees the gap."""
    header = (
        "## Table 2: Per-Study Endpoint Evidence\n\n"
        + _row(
            "Endpoint", "Study", "p/CI", "Direction",
            "Directness", "Tier", "Interpretation",
        )
        + "\n"
        + _row(*(["---"] * 7)) + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        study = _safe(getattr(r, "receipt_id", None), "—")
        endpoint = _safe(getattr(r, "outcome_class", None), "—")
        direction = _safe(getattr(r, "effect_direction", None), "—")
        directness = _safe(getattr(r, "directness", None), "—")
        tier = _safe(getattr(r, "evidence_tier", None), "—")
        interp = _interpretation(direction, endpoint)
        pvals = [p for p in (getattr(r, "p_values", None) or ()) if p]
        if not pvals:
            rows.append(_row(
                endpoint, study, "—", direction, directness, tier, interp,
            ))
            continue
        for p in pvals:
            rows.append(_row(
                endpoint, study, p.strip() or "—", direction,
                directness, tier, interp,
            ))
    return header + "\n".join(rows) + "\n"


# --- Table 3: Cross-Domain Tensions -------------------------------------


def _tension_implication(kind: str, severity: int) -> str:
    """One-line practical implication per (kind, severity) tuple."""
    sev_label = "load-bearing" if severity >= 4 else (
        "notable" if severity >= 2 else "minor"
    )
    if kind == "directionality_disagreement":
        return f"opposite directions ({sev_label}) — needs explicit hedge"
    if kind == "magnitude_disagreement":
        return f"effect-size gap ({sev_label}) — quantitative reconciliation"
    if kind == "directness_mismatch":
        return f"directness mismatch ({sev_label}) — generalisability caveat"
    if kind == "tier_mismatch":
        return f"tier gap ({sev_label}) — weight clinical evidence higher"
    return f"{kind} ({sev_label})"


def render_table_3_cross_domain_tensions(matrix: object | None) -> str:
    """Table 3 — one row per non-orthogonal Tension pair.

    Columns: Tension kind | Severity | Receipt A | Receipt B
    | Outcome class | Summary | Practical implication

    Source: TensionMatrix.non_orthogonal() (severity ≥ 1). For the
    metformin corpus this is ~40 rows of tagged disagreement / gap
    pairs — exactly the structured-tension exposition a PhD reviewer
    expects to see explicitly rather than buried in prose. Returns
    just the heading + 'no tensions' line when matrix is None or
    empty (defensive for unit-tests that don't build a matrix)."""
    header = (
        "## Table 3: Cross-Domain Tensions\n\n"
        + _row(
            "Tension kind", "Severity", "Receipt A", "Receipt B",
            "Outcome class", "Summary", "Practical implication",
        )
        + "\n"
        + _row(*(["---"] * 7)) + "\n"
    )
    if matrix is None:
        return header + _row(
            "—", "—", "—", "—", "—", "no matrix supplied", "—",
        ) + "\n"
    pairs = list(getattr(matrix, "non_orthogonal", lambda: [])())
    if not pairs:
        return header + _row(
            "—", "—", "—", "—", "—",
            "no non-orthogonal tensions in matrix", "—",
        ) + "\n"
    rows: list[str] = []
    for t in pairs:
        kind = _safe(getattr(t, "kind", None), "—")
        sev = getattr(t, "severity", 0) or 0
        rows.append(_row(
            kind,
            str(sev),
            _safe(getattr(t, "receipt_a_id", None), "—"),
            _safe(getattr(t, "receipt_b_id", None), "—"),
            _safe(getattr(t, "outcome_class", None), "—"),
            _safe(getattr(t, "summary", None), "—"),
            _tension_implication(kind, int(sev)),
        ))
    return header + "\n".join(rows) + "\n"


# --- Table 4 (supplemental): Per-Domain Risk of Bias --------------------


# Domain → grade. Each tier gets a tuple matching the column order:
# (Allocation, Blinding, Attrition, Outcome measurement, Reporting,
# Confounding control, Generalizability).
_ROB_DOMAINS_BY_TIER: dict[str, tuple[str, ...]] = {
    "A1": ("low", "low", "moderate", "low", "low",
           "low", "moderate"),
    "A2": ("low", "moderate", "moderate", "moderate", "low",
           "low", "high"),
    "B1": ("unclear", "unclear", "unclear", "unclear", "moderate",
           "moderate", "moderate"),
    "B2": ("n/a", "n/a", "moderate", "moderate", "moderate",
           "high", "moderate"),
    "C1": ("low", "n/a", "low", "moderate", "moderate",
           "n/a", "high"),
    "C2": ("n/a", "n/a", "n/a", "n/a", "moderate",
           "n/a", "high"),
    "unknown": ("unclear",) * 7,
}
_ROB_DOMAIN_HEADERS: tuple[str, ...] = (
    "Allocation", "Blinding", "Attrition",
    "Outcome measurement", "Reporting",
    "Confounding control", "Generalizability",
)


def _rob_domains(tier: str) -> tuple[str, ...]:
    return _ROB_DOMAINS_BY_TIER.get(tier, _ROB_DOMAINS_BY_TIER["unknown"])


def render_table_4_evidence_limitations(receipts: list) -> str:
    """Table 4 (supplemental) — per-study × per-domain RoB grades.

    Cochrane RoB-2 / ROBINS-I terminology where applicable. Per-tier
    defaults are pipeline-level (derived from evidence_tier metadata,
    NOT extracted from source text) — caveat above the table makes
    this explicit so a Cochrane-trained reviewer doesn't mistake it
    for a per-paper assessment from the source PDFs."""
    header_cells = (
        ["Citation", "Tier"]
        + list(_ROB_DOMAIN_HEADERS)
        + ["Effect direction notes"]
    )
    sep_cells = ["---"] * len(header_cells)
    header = (
        "## Table 4 (supplemental): Per-Domain Risk of Bias\n\n"
        "*Per-domain grades are derived from each study's evidence "
        "tier (A1/A2/B1/B2/C1/C2) — they capture design-level "
        "limitations, NOT a per-paper Cochrane RoB-2 / ROBINS-I "
        "assessment from the source text. Domains follow Cochrane "
        "RoB-2 (RCTs) and ROBINS-I (observational) terminology where "
        "applicable; `n/a` indicates the domain is not meaningful for "
        "that design (e.g. blinding for an observational cohort).*\n\n"
        + _row(*header_cells) + "\n"
        + _row(*sep_cells) + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        tier = getattr(r, "evidence_tier", "") or "unknown"
        domains = _rob_domains(tier)
        direction = getattr(r, "effect_direction", None) or "unclear"
        if direction == "null":
            note = "primary endpoint did not reach significance"
        elif direction == "mixed":
            note = "internal contradiction across endpoints"
        elif direction == "unclear":
            note = "signed claims without significance signal"
        else:
            note = f"{direction} effect — see Tables 1/2"
        cells = (
            [_safe(getattr(r, "receipt_id", None), "—"), tier]
            + list(domains) + [note]
        )
        rows.append(_row(*cells))
    return header + "\n".join(rows) + "\n"


# --- Helpers (kept from Fix #6 for downstream callers) ------------------


def _aggregate_net_direction(receipts: list) -> str:
    """Roll-up direction across multiple studies in the same outcome
    class. Distinct semantic axis from the pairwise TensionMatrix:
    here we report 'what does the body of evidence look like in
    aggregate', NOT 'do these two studies agree'.

    Algorithm:
      - All studies same direction → that direction
      - Any mixed-finding study → mixed (study-level contradiction)
      - Positive AND negative significant directions → mixed
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


# Backward-compat alias: Fix #14 used the name `render_table_3_…` for
# the per-domain RoB table; Fix #21 promoted it to Table 4 (supplemental)
# to make room for the cross-domain-tensions table at slot 3. Existing
# callers (and tests written against the Fix #14 contract) continue to
# import render_table_3_evidence_limitations.
render_table_3_evidence_limitations = render_table_4_evidence_limitations


# --- Top-level renderer --------------------------------------------------


def render_all_tables(receipts: list, matrix: object | None = None) -> str:
    """Render all four tables back-to-back as a single markdown block.

    Includes a leading pointer sentence (reviewer-fix P2) so the body
    prose has a natural reference site for the structured evidence.

    `matrix` is the TensionMatrix from build_tension_matrix; when
    omitted Table 3 reports 'no matrix supplied' rather than failing.
    Returns empty string when receipts is empty."""
    if not receipts:
        return ""
    pointer = (
        "## Structured Evidence Tables\n\n"
        "*The following tables present the deterministic evidence "
        "summary referenced throughout this paper. Numbers live in "
        "the tables; prose references them. Tables 1-3 follow the "
        "Researka v1 schema (included studies, per-study endpoint "
        "evidence, cross-domain tensions); Table 4 is a supplemental "
        "Cochrane RoB-2 / ROBINS-I per-domain risk-of-bias roll-up.*\n\n"
    )
    return (
        pointer
        + render_table_1_included_studies(receipts)
        + "\n"
        + render_table_2_endpoint_evidence(receipts)
        + "\n"
        + render_table_3_cross_domain_tensions(matrix)
        + "\n"
        + render_table_4_evidence_limitations(receipts)
    )


__all__ = [
    "render_all_tables",
    "render_table_1_included_studies",
    "render_table_2_endpoint_evidence",
    "render_table_3_cross_domain_tensions",
    "render_table_4_evidence_limitations",
]
