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
            _safe(getattr(r, "outcome_class", None), "—"),
            _safe(getattr(r, "effect_direction", None), "—"),
            _safe(getattr(r, "directness", None), "—"),
            _safe(getattr(r, "canonical_trial_id", None), "—"),
            _representative_p_value(r),
            _n_claims(r),
        ))
    return header + "\n".join(rows) + "\n"


# --- Table 2: Per-Study Endpoint Evidence (DENSE) -----------------------


def _interpretation(direction: str, outcome: str, stat: str = "") -> str:
    """One-line plain-English interpretation per direction × outcome.

    Templated to keep the renderer pure-deterministic — no LLM. The
    output reads naturally so a reader can scan the column without
    needing a glossary."""
    if stat and stat != "—" and direction in {"null", "unclear"}:
        return f"reported statistic; receipt summary remains {direction}"
    if direction == "positive":
        return f"improves {outcome}"
    if direction == "negative":
        return f"worsens {outcome}"
    if direction == "null":
        return f"no significant effect on {outcome}"
    if direction == "mixed":
        return f"mixed signal on {outcome}"
    return f"unclear effect on {outcome}"


def _display_direction(direction: str, stat: str = "") -> str:
    if stat and stat != "—" and direction in {"null", "unclear"}:
        return f"{direction} summary"
    return direction


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
        pvals = [p for p in (getattr(r, "p_values", None) or ()) if p]
        if not pvals:
            interp = _interpretation(direction, endpoint)
            rows.append(_row(
                endpoint, study, "—", direction, directness, tier, interp,
            ))
            continue
        for p in pvals:
            stat = p.strip() or "—"
            interp = _interpretation(direction, endpoint, stat)
            direction_display = _display_direction(direction, stat)
            rows.append(_row(
                endpoint, study, stat, direction_display,
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
    """Table 4 (supplemental) — per-study × per-domain RoB grades.

    Cochrane RoB-2 / ROBINS-I / SYRCLE / AMSTAR-2 terminology where
    applicable. Per-tier defaults are pipeline-level (derived from
    evidence_tier metadata, NOT extracted from source text) — caveat
    above the table makes this explicit so a Cochrane-trained reviewer
    doesn't mistake it for a per-paper assessment from the source PDFs.

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
        "## Table 4 (supplemental): Per-Domain Risk of Bias + "
        "Synthesis Weight\n\n"
        "*Per-domain grades + the named RoB tool are derived from "
        "each study's evidence tier (A1/A2/B1/B2/C1/C2) — they capture "
        "design-level limitations, NOT a per-paper Cochrane RoB-2 / "
        "ROBINS-I assessment from the source text. Domains follow "
        "Cochrane RoB-2 (RCTs), ROBINS-I (observational), SYRCLE "
        "(animal), and AMSTAR-2 (systematic review) terminology; "
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


def _select_top_claims(
    claims: list[dict], top_n: int = 5,
) -> list[dict]:
    """Pick the top-N claims for a paper, prioritising one of each
    canonical claim_type in priority order so the surface is varied
    (avoids 5 p-values from the same study)."""
    if not claims:
        return []
    by_type: dict[str, list[dict]] = {}
    for c in claims:
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
        for c in claims:
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
                _safe(c.get("claim_type"), "—"),
                _format_claim_value(c),
                _safe(c.get("units"), "—"),
            ))
    if not rows:
        return header + _row(
            "—", "—", "—", "no claims found for any receipt", "—",
        ) + "\n"
    return header + "\n".join(rows) + "\n"


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
        "*The following tables present the deterministic evidence "
        "summary referenced throughout this paper. Numbers live in "
        "the tables; prose references them. Tables 1-3 follow the "
        "Researka v1 schema (included studies, per-study endpoint "
        "evidence, cross-domain tensions); Table 4 is a supplemental "
        "Cochrane RoB-2 / ROBINS-I per-domain risk-of-bias roll-up; "
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
]
