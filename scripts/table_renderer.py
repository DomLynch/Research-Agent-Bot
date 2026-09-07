"""Deterministic manuscript evidence tables and public evidence snapshots."""
from __future__ import annotations

import re
from typing import Any

from agent.statistical_consistency import nominal_significance


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


def _public_label(value: Any) -> str:
    """Human-readable display for internal enum/claim labels."""
    s = _public_value(value).strip()
    labels = {
        "ci": "confidence interval",
        "cross_domain": "cross-domain",
        "contextual_other": "contextual adjacent evidence",
        "mean_sd": "mean ± SD",
        "null_vs_positive": "null vs positive",
        "null_vs_negative": "null vs negative",
        "p_value": "p-value",
        "sample_size": "sample size",
        "unit_value": "unit value",
    }
    if s in labels:
        return labels[s]
    return s.replace("_", " ")


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


def _parse_p_value(p: str) -> float | None:
    m = re.search(r"\d*\.?\d+(?:[eE][-+]?\d+)?", p)
    if not m:
        return None
    try:
        return float(m.group(0))
    except (ValueError, TypeError):
        return None


def _smallest_p_string(pvals: list[str]) -> str:
    """Most-significant (smallest) p-value string from a list, or '—'."""
    cleaned = [p.strip() for p in pvals if p and p.strip()]
    if not cleaned:
        return "—"
    parsed = [(f, p) for p in cleaned if (f := _parse_p_value(p)) is not None]
    # If nothing parses as a number, emit "—" rather than a non-p-value string
    # (e.g. CI notation) — honours the "or '—'" contract for both callers.
    return min(parsed, key=lambda t: t[0])[1] if parsed else "—"


def _representative_p_value(r: object) -> str:
    """Smallest (most-significant) p-value from receipt's p_values."""
    return _smallest_p_string(list(getattr(r, "p_values", None) or ()))


def _p_value_signatures(text: str) -> set[tuple[str, float]]:
    operators = {"≤": "<=", "≥": ">="}
    return {
        (operators.get(operator, operator), float(value))
        for operator, value in re.findall(
            r"\bp\s*(<=|>=|<|>|=|≤|≥)\s*(\d*\.?\d+(?:[eE][-+]?\d+)?)",
            text,
            re.I,
        )
    }


def _representative_p_value_coherent(r: object) -> str:
    """Select an excerpt-grounded p-value coherent with the coded direction."""
    direction = str(getattr(r, "effect_direction", "") or "").lower()
    if direction in {"mixed", "unclear"}:
        return "—"
    pvals = [p for p in (getattr(r, "p_values", None) or ()) if p and p.strip()]
    thesis = str(getattr(r, "thesis_text", "") or "")
    if thesis:
        supported = _p_value_signatures(thesis)
        pvals = [
            p for p in pvals
            if _p_value_signatures(p) & supported
        ]
    if direction == "null":
        pvals = [p for p in pvals if not _has_significant_p_value(p)]
    return _smallest_p_string(pvals)


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
    """Render one evidence-hierarchy row per included source."""
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
        # Fix #21 follow-up: Q9 numeric-density check requires the
        # literal `n=NN` form (regex `\b[nN]\s*=\s*\d+`). Bare
        # numeric "120" doesn't match. Render `n=120` so the
        # corpus-traced sample size counts toward Q9.
        n_cell = (
            f"n={n_str}" if n_str not in ("—", "n/a")
            and n_str[:1].isdigit()
            else n_str
        )
        tier = _safe(getattr(r, "evidence_tier", None), "—")
        rows.append(_row(
            _safe(getattr(r, "receipt_id", None), "—"),
            _design_from_tier(tier),
            tier,
            n_cell,
            pop_label,
            _public_label(getattr(r, "outcome_class", None)),
            _public_label(getattr(r, "effect_direction", None)),
            _safe(getattr(r, "directness", None), "—"),
            _safe(getattr(r, "canonical_trial_id", None), "—"),
            _representative_p_value_coherent(r),
            _n_claims(r),
        ))
    return header + "\n".join(rows) + "\n"


# --- Table 2: Per-Study Endpoint Evidence (DENSE) -----------------------


def _has_significant_p_value(stat: str) -> bool:
    return nominal_significance(stat) is True


def _interpretation(direction: str, outcome: str, stat: str = "") -> str:
    """One-line plain-English interpretation per direction × outcome.

    Templated to keep the renderer pure-deterministic — no LLM. The
    output reads naturally so a reader can scan the column without
    needing a glossary."""
    if stat and stat != "—":
        if direction == "null" and _has_significant_p_value(stat):
            return "significant statistic; receipt-level direction remains null"
        return f"reported statistic; receipt summary remains {direction}"
    return f"source-level direction code: {direction}; endpoint benefit is not established by this code"


def _display_direction(direction: str, stat: str = "") -> str:
    if stat and stat != "—":
        if direction == "null" and _has_significant_p_value(stat):
            return "significant statistic"
        return f"{direction} summary"
    return direction


def render_table_2_endpoint_evidence(receipts: list) -> str:
    """Render source p-values, or an honest claim-count fallback, by endpoint."""
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
        endpoint_display = _public_label(endpoint)
        direction_display_base = _public_label(direction)
        pvals = [p for p in (getattr(r, "p_values", None) or ()) if p]
        if not pvals:
            interp = _interpretation(direction, endpoint_display)
            rows.append(_row(
                endpoint_display, study, "—", direction_display_base,
                directness, tier, interp,
            ))
            continue
        for p in pvals:
            stat = p.strip() or "—"
            interp = _interpretation(direction, endpoint_display, stat)
            direction_display = _public_label(_display_direction(direction, stat))
            rows.append(_row(
                endpoint_display, study, stat, direction_display,
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
    return f"{_public_label(kind)} ({sev_label})"


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
            _public_label(kind),
            str(sev),
            _safe(getattr(t, "receipt_a_id", None), "—"),
            _safe(getattr(t, "receipt_b_id", None), "—"),
            _public_label(getattr(t, "outcome_class", None)),
            _public_label(getattr(t, "summary", None)),
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


# Fix #26: which RoB framework applies per study tier. Reviewers
# expect to see the named tool, not just generic "RoB". Cochrane
# RoB-2 for RCTs, ROBINS-I for observational, SYRCLE's risk-of-bias
# tool for animal studies, AMSTAR-2-style for systematic reviews.
_ROB_TOOL_BY_TIER: dict[str, str] = {
    "A1": "Cochrane RoB-2",
    "A2": "Cochrane RoB-2",
    "B1": "AMSTAR-2 (review)",
    "B2": "ROBINS-I",
    "C1": "SYRCLE (animal)",
    "C2": "SYRCLE (in-vitro)",
    "unknown": "n/a",
}


def _rob_tool(tier: str) -> str:
    return _ROB_TOOL_BY_TIER.get(tier, _ROB_TOOL_BY_TIER["unknown"])


# Fix #26: overall RoB roll-up from per-domain grades. Worst-of
# semantics — any 'high' on a load-bearing domain (allocation,
# blinding, attrition, outcome measurement) bumps to 'high overall'.
# Otherwise plurality-vote across non-`n/a` domains.
_LOAD_BEARING_INDICES = (0, 1, 2, 3)  # allocation, blinding, attrition, outcome


def _overall_rob(domains: tuple[str, ...]) -> str:
    """Worst-of overall risk of bias across per-domain grades."""
    if not domains:
        return "unclear"
    load_bearing = [domains[i] for i in _LOAD_BEARING_INDICES
                    if i < len(domains)]
    if any(g == "high" for g in load_bearing):
        return "high"
    non_na = [g for g in domains if g != "n/a"]
    if not non_na:
        return "n/a"
    counts: dict[str, int] = {}
    for g in non_na:
        counts[g] = counts.get(g, 0) + 1
    return max(counts, key=lambda k: counts[k])


# Fix #24: weight-in-synthesis label per receipt — what reviewers
# actually want from a RoB table. Templated from
# (tier × directness × overall_rob) so the trust spine is
# preserved (deterministic, no LLM, no I/O).
def _weight_in_synthesis(
    tier: str, directness: str, overall_rob: str,
) -> str:
    """Synthesised qualitative weight for the study's contribution."""
    t = (tier or "unknown").upper()
    d = (directness or "").lower()
    r = (overall_rob or "unclear").lower()
    if r == "high":
        return "**hypothesis-generating** (high RoB on load-bearing domain)"
    if t == "A1" and d == "direct":
        return "**load-bearing** (direct clinical RCT)"
    if t == "A2" or (t == "A1" and d == "mechanistic"):
        return "**mechanistic** (human RCT, biomarker endpoint)"
    if t == "B1":
        return "**supporting** (synthesis evidence)"
    if t == "B2":
        return "**contextual** (observational signal)"
    if t in ("C1", "C2"):
        return "**hypothesis-generating** (preclinical mechanism)"
    return "**unweighted** (insufficient metadata)"


def render_table_4_evidence_limitations(receipts: list) -> str:
    """Table 4 (supplemental) — design-level evidence weighting.

    Per-tier defaults are pipeline-level (derived from evidence_tier
    metadata, NOT extracted from source text). The caveat above the table
    makes this explicit so a reviewer does not mistake it for a formal
    per-paper risk-of-bias assessment from the source PDFs.

    Fix #24 + #26: adds Tool column (which RoB framework applies),
    Overall RoB column (worst-of roll-up across per-domain grades),
    and Weight-in-Synthesis column (qualitative contribution label
    derived from tier × directness × overall_rob). Together these
    turn the table from a 7-domain grade dump into the actual
    evidence-weighting table reviewers expect."""
    header_cells = (
        ["Citation", "Tier", "Tool"]
        + list(_ROB_DOMAIN_HEADERS)
        + ["Overall RoB", "Weight in synthesis", "Effect direction notes"]
    )
    sep_cells = ["---"] * len(header_cells)
    header = (
        "## Table 4 (supplemental): Design-Level Evidence Weighting "
        "Heuristic\n\n"
        "*Per-domain grades are derived from each study's evidence tier "
        "(A1/A2/B1/B2/C1/C2) — they capture design-level limitations, "
        "NOT a formal per-paper risk-of-bias assessment from the source "
        "text. Domains follow design-family categories for randomized, "
        "observational, animal, and systematic-review evidence; "
        "`n/a` indicates the domain is not meaningful for that design "
        "(e.g. blinding for an observational cohort). The "
        "**Weight in synthesis** column is the qualitative weighting "
        "the synthesis applies to each receipt — derived from "
        "tier × directness × overall RoB.*\n\n"
        + _row(*header_cells) + "\n"
        + _row(*sep_cells) + "\n"
    )
    rows: list[str] = []
    for r in receipts:
        tier = getattr(r, "evidence_tier", "") or "unknown"
        domains = _rob_domains(tier)
        overall = _overall_rob(domains)
        directness = getattr(r, "directness", "") or ""
        weight = _weight_in_synthesis(tier, directness, overall)
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
            [_safe(getattr(r, "receipt_id", None), "—"),
             tier, _rob_tool(tier)]
            + list(domains)
            + [overall, weight, note]
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


# --- Table 5 (supplemental): Per-Paper Numeric Index --------------------


# Claim types we surface, in priority order. p_value first because
# it's the load-bearing inferential statistic; percentage second
# because it's the most common effect-size form; unit_value third
# (doses, durations, etc.).
_CLAIM_TYPE_PRIORITY: tuple[str, ...] = (
    "p_value", "percentage", "ratio", "ci", "unit_value",
    "mean_sd", "sample_size",
)
_MALFORMED_NUMERIC_RE = re.compile(
    r"(?<![\d,])0{2,}(?:\.\d+)?\s*"
    r"(?:mg/day|mg|g|mcg|µg|μg|ng|kg|m/s|mmHg)\b",
    re.IGNORECASE,
)


def _format_claim_value(claim: dict) -> str:
    """Render a single claim's numeric value in its canonical inline
    form. Q9-counted patterns: `p < 0.05`, `30%`, `n=120`, `850 mg`."""
    raw = (claim.get("raw_text") or "").strip()
    if not raw:
        return "—"
    units = (claim.get("units") or "").strip()
    # If raw already contains units (e.g. "850 mg"), keep as-is
    if units and units in raw:
        return raw
    # Sample-size claims need explicit `n=NN` form for Q9 to count
    if claim.get("claim_type") == "sample_size":
        if "=" not in raw:
            return f"n={raw.lstrip('n').lstrip('=').strip()}"
    return raw


def _publishable_numeric_claim(claim: dict) -> bool:
    raw = (claim.get("raw_text") or "").strip()
    units = (claim.get("units") or "").strip()
    return _MALFORMED_NUMERIC_RE.search(f"{raw} {units}") is None


def _select_top_claims(
    claims: list[dict], top_n: int = 5,
) -> list[dict]:
    """Pick the top-N claims for a paper, prioritising one of each
    canonical claim_type in priority order so the surface is varied
    (avoids 5 p-values from the same study)."""
    if not claims:
        return []
    publishable = [c for c in claims if _publishable_numeric_claim(c)]
    by_type: dict[str, list[dict]] = {}
    for c in publishable:
        ct = c.get("claim_type", "")
        by_type.setdefault(ct, []).append(c)
    selected: list[dict] = []
    # First pass: one of each priority type
    for ct in _CLAIM_TYPE_PRIORITY:
        if ct in by_type and by_type[ct]:
            selected.append(by_type[ct][0])
            if len(selected) >= top_n:
                break
    # Second pass: fill remaining slots with any unused claims
    if len(selected) < top_n:
        seen_ids = {c.get("claim_id") for c in selected}
        for c in publishable:
            if c.get("claim_id") in seen_ids:
                continue
            selected.append(c)
            if len(selected) >= top_n:
                break
    return selected


def render_table_5_numeric_index(
    receipts: list,
    claims_by_citation: dict | None = None,
    top_n: int = 5,
) -> str:
    """Table 5 (supplemental) — top-N quantitative claims per paper.

    Surfaces the underlying corpus numerics that power Q2 trace —
    one row per (paper × claim) tuple. For 15 papers × 5 claims =
    75 rows of structured numerics. Each row's `Value` cell uses the
    canonical inline form (`p < 0.05`, `30%`, `n=120`, `850 mg`) so
    Q9 numeric-density patterns count it.

    `claims_by_citation` maps body_citation (e.g. 'Walton 2019') to
    the paper's full claims list (loaded from
    docs/quality-reference/<topic>/quant_claims/<receipt_id>.json
    by the orchestrator). When None or empty, the table renders a
    placeholder row noting the data isn't wired in (defensive — so
    test harnesses without claim data don't crash)."""
    header = (
        "## Table 5 (supplemental): Per-Paper Numeric Index\n\n"
        "*Top-N quantitative claims per paper — the underlying "
        "corpus numerics that power Q2 trace and Q9 density. One row "
        "per (paper × claim) tuple, prioritised by claim type "
        "(p-value > percentage > ratio > unit-value).*\n\n"
        + _row(
            "Citation", "Section", "Type", "Value", "Units",
        )
        + "\n"
        + _row(*(["---"] * 5)) + "\n"
    )
    if not claims_by_citation:
        return header + _row(
            "—", "—", "—", "no claims index supplied", "—",
        ) + "\n"
    rows: list[str] = []
    for r in receipts:
        body_cite = _safe(getattr(r, "receipt_id", None), "—")
        claims = claims_by_citation.get(body_cite, [])
        top = _select_top_claims(claims, top_n=top_n)
        if not top:
            continue
        for c in top:
            rows.append(_row(
                body_cite,
                _safe(c.get("source_section"), "—"),
                _public_label(c.get("claim_type")),
                _format_claim_value(c),
                _safe(c.get("units"), "—"),
            ))
    if not rows:
        return header + _row(
            "—", "—", "—", "no claims found for any receipt", "—",
        ) + "\n"
    return header + "\n".join(rows) + "\n"


def _inline_cell(value: Any) -> str:
    return _public_value(value).replace("|", "/").replace("\n", " ").strip()


_MISSING_PUBLIC_VALUES = {
    "", "-", "—", "–", "none", "n/a", "na", "unknown", "not extracted",
    "not_extracted", "not available", "not reported",
}


def _is_missing_public_value(value: Any) -> bool:
    raw = str(value or "").strip()
    if raw.lower() in _MISSING_PUBLIC_VALUES:
        return True
    return bool(re.match(r"^correct(?:ing|ion)?\s+\d{4}[a-z]?$", raw, re.I))


def _public_value(value: Any, default: str = "—") -> str:
    return default if _is_missing_public_value(value) else str(value)


def _included_study_fill_rate(receipts: list) -> float:
    fields = (
        "receipt_id", "evidence_tier", "directness",
        "outcome_class", "effect_direction",
    )
    total = len(receipts) * len(fields)
    if not total:
        return 1.0
    filled = sum(
        1
        for receipt in receipts
        for field in fields
        if not _is_missing_public_value(getattr(receipt, field, None))
    )
    return filled / total


def _source_list_label(receipt: Any, idx: int) -> str:
    for field in ("receipt_id", "source_title", "title"):
        value = getattr(receipt, field, None)
        if not _is_missing_public_value(value):
            return _inline_cell(value)
    return f"Included source {idx}"


def _render_compact_source_list(receipts: list) -> list[str]:
    lines = [
        "### Included Sources",
        "",
        "Structured study fields were sparsely extracted, so the public manuscript lists sources rather than rendering an incomplete study table.",
        "",
    ]
    for idx, r in enumerate(_rank_receipts_for_public(receipts, 10), start=1):
        bits = [_source_list_label(r, idx)]
        if not _is_missing_public_value(getattr(r, "source_venue", None)):
            bits.append(_inline_cell(getattr(r, "source_venue")))
        if not _is_missing_public_value(getattr(r, "source_year", None)):
            bits.append(str(getattr(r, "source_year")))
        if not _is_missing_public_value(getattr(r, "source_doi", None)):
            bits.append(f"DOI {_inline_cell(getattr(r, 'source_doi'))}")
        lines.append("- " + "; ".join(bits) + ".")
    return lines


def _classification_criteria_lines() -> list[str]:
    return [
        "### Classification Criteria",
        "",
        "- **Outcome class** is assigned from the source's bound endpoint, population, and claim text; adjacent/background sources are separated from clinical outcome slices.",
        "- **Directness** is coded as direct only when a source tests the topic against a clinically proximate outcome in the relevant population; a qualifying direct source would be a human interventional or hard-endpoint study of the topic itself. Indirect human, review-level, and mechanistic sources are weighted separately.",
        "- **Directional signal** is counted within the assigned outcome class only. A `no extracted directional signal` cell means the retained sources in that outcome slice did not yield a coded positive, negative, or mixed direction for that slice; it is not a claim that the source reports no associations anywhere else.",
        "- **Evidence tier** follows the deterministic tier/directness taxonomy used in the receipt builder; the prose writer cannot move a source between classes after receipts are frozen.",
        "",
    ]


def _classification_map_lines(receipts: list, *, limit: int = 40) -> list[str]:
    rows = _rank_receipts_for_public(receipts, limit)
    if not rows:
        return []
    lines = [
        "### Source Classification Map",
        "",
        "Each retained source is mapped to its public evidence role so the evidence landscape can be checked without opening the supplement.",
        "",
    ]
    for idx, r in enumerate(rows, start=1):
        label = _source_list_label(r, idx)
        outcome = _public_label(getattr(r, "outcome_class", "—"))
        directness = _inline_cell(getattr(r, "directness", "—"))
        tier = _inline_cell(getattr(r, "evidence_tier", "—"))
        direction = _public_label(getattr(r, "effect_direction", "—"))
        claims = _inline_cell(getattr(r, "n_claims", "—"))
        lines.append(
            f"- {label}: outcome={outcome}; directness={directness}; "
            f"tier={tier}; direction={direction}; claims={claims}."
        )
    return lines


def _rank_receipts_for_public(receipts: list, limit: int) -> list:
    tier_weight = {"A1": 5, "A2": 4, "B1": 3, "B2": 2, "C1": 1, "C2": 1}
    return sorted(
        receipts,
        key=lambda r: (
            -tier_weight.get(_safe(getattr(r, "evidence_tier", None), "").upper(), 0),
            str(getattr(r, "directness", "")) != "direct",
            -int(getattr(r, "n_claims", 0) or 0),
            str(getattr(r, "receipt_id", "")),
        ),
    )[:limit]


def _public_tension_lines(matrix: object | None, limit: int) -> list[str]:
    if matrix is None:
        return ["- No tension matrix was supplied for this run."]
    pairs = sorted(
        list(getattr(matrix, "non_orthogonal", lambda: [])()),
        key=lambda t: (-int(getattr(t, "severity", 0) or 0), str(getattr(t, "kind", ""))),
    )[:limit]
    if not pairs:
        return ["- No load-bearing cross-study tensions were detected."]
    return [
        "- "
        + f"Severity {int(getattr(t, 'severity', 0) or 0)} "
        + f"{_public_label(getattr(t, 'kind', 'tension'))}: "
        + f"{_inline_cell(getattr(t, 'receipt_a_id', '—'))} vs "
        + f"{_inline_cell(getattr(t, 'receipt_b_id', '—'))}; "
        + _inline_cell(getattr(t, "summary", "bounded disagreement."))
        for t in pairs
    ]


def render_public_evidence_snapshot(
    receipts: list,
    matrix: object | None = None,
    *,
    max_studies: int = 10,
    max_tensions: int = 8,
) -> str:
    """Compact manuscript-facing evidence view; full tables stay in supplement."""
    if not receipts:
        return ""
    lines = [
        "## Evidence Snapshot",
        "",
        "The manuscript foregrounds the load-bearing evidence; the full evidence tables remain in the supplement.",
        "",
    ]
    ranked = _rank_receipts_for_public(receipts, max_studies)
    if _included_study_fill_rate(ranked) < 0.5:
        lines.extend(_render_compact_source_list(ranked))
    else:
        lines.extend(["### Load-Bearing Included Studies", ""])
        for r in ranked:
            p_value = _representative_p_value_coherent(r)
            bits = [
                _inline_cell(getattr(r, "receipt_id", "—")),
                f"tier={_inline_cell(getattr(r, 'evidence_tier', '—'))}",
                f"directness={_inline_cell(getattr(r, 'directness', '—'))}",
                f"endpoint={_public_label(getattr(r, 'outcome_class', '—'))}",
                f"direction={_public_label(getattr(r, 'effect_direction', '—'))}",
            ]
            if p_value != "—":
                bits.append(f"representative statistic={_inline_cell(p_value)}")
            lines.append("- " + "; ".join(bits) + ".")
    lines.extend(["", *_classification_map_lines(receipts), ""])
    lines.extend(_classification_criteria_lines())
    lines.extend(["", "### Load-Bearing Tensions", "", *_public_tension_lines(matrix, max_tensions), ""])
    return "\n".join(lines)


# --- Top-level renderer --------------------------------------------------


def render_all_tables(
    receipts: list,
    matrix: object | None = None,
    claims_by_citation: dict | None = None,
) -> str:
    """Render all five tables back-to-back as a single markdown block.

    Includes a leading pointer sentence (reviewer-fix P2) so the body
    prose has a natural reference site for the structured evidence.

    `matrix` is the TensionMatrix from build_tension_matrix; when
    omitted Table 3 reports 'no matrix supplied' rather than failing.
    `claims_by_citation` is the per-paper claims index from the
    orchestrator; when omitted Table 5 reports 'no claims index'.
    Returns empty string when receipts is empty."""
    if not receipts:
        return ""
    pointer = (
        "## Structured Evidence Tables\n\n"
        "*The following tables present the structured evidence "
        "summary referenced throughout this paper. Numbers live in "
        "the tables; prose references them. Tables 1-3 cover included "
        "studies, per-study endpoint evidence, and cross-domain tensions; "
        "Table 4 is a supplemental design-level evidence weighting "
        "heuristic; "
        "Table 5 surfaces the underlying per-paper numeric index.*\n\n"
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
        + "\n"
        + render_table_5_numeric_index(receipts, claims_by_citation)
    )


__all__ = [
    "render_all_tables",
    "render_table_1_included_studies",
    "render_table_2_endpoint_evidence",
    "render_table_3_cross_domain_tensions",
    "render_table_4_evidence_limitations",
    "render_table_5_numeric_index",
    "render_public_evidence_snapshot",
]
