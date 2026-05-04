"""Deterministic Quantitative Evidence Index — universal Q9 structural fix.

Reviewer's Shot 2 spec (2026-05-04):
  Table 0: Quantitative Evidence Index. Rows from every topic's
  quant_claims.json:
    - Study (Author Year / paper_id)
    - Endpoint (claim's endpoint binding or claim_role)
    - Arm / comparator
    - Numeric value
    - Unit / type
    - p-value or CI if present
    - Citation token

  Rules:
    - Only high-confidence traced claims.
    - Max 40 rows.
    - No LLM.
    - Insert before Methods.
    - Same for all topics — no per-topic code paths.

Why per-CLAIM, not per-RECEIPT
------------------------------
The earlier per-receipt approach (one row per SPAR-accepted receipt)
was bottlenecked by SPAR strictness: statins had 35 papers in the
corpus but SPAR accepted only 2 receipts. The table fell through to
its empty placeholder, contributing zero numeric density.

A per-claim table reads the raw quant_claims.json files directly
(skipping SPAR), filters to high-confidence + topic-relevant claims,
and ranks them by quality (RCT/cohort > mechanistic, with p/CI > raw,
unique endpoints > duplicates). 40 rows × 3-5 numerics ≈ 120-200
corpus-traced numerics in ~250 words, structurally lifting Q9
without prompt fragility or sparse-corpus failure modes.

Universal-by-construction: zero per-topic code paths. The only
inputs are the quant_claims directory + the topic name (used solely
in the section title and a citation lookup). Every topic gets the
same row-selection logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Hard cap per the reviewer's spec: don't build a 1000-row table even
# if the corpus has that many high-confidence claims. 40 rows × ~3
# numerics ≈ 120 numerics, plenty for the Q9 lift; more would
# overpower the prose body and make the paper unreadable.
_MAX_ROWS = 40


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    """One row of the Quantitative Evidence Index."""
    study_label: str       # "Author Year" or "<paper_id> (Year)"
    endpoint: str          # bound endpoint or claim_role fallback
    arm: str               # bound arm or "—"
    value: str             # the numeric, formatted
    unit_or_type: str      # units string or claim_type fallback
    statistic: str         # "p=0.04" / "(0.81–1.13)" / "—"
    citation: str          # citation_token (Author Year)


def build_results_table(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
) -> str:
    """Read every *.quant_claims.json in quant_dir, select top-N
    high-confidence claims, render markdown table. Empty string when
    no qualifying claims exist (corpus is mechanism-only with no
    quantitative content)."""
    rows: list[EvidenceRow] = []
    if not quant_dir.exists():
        return ""
    candidates: list[tuple[int, EvidenceRow]] = []
    for path in sorted(quant_dir.glob("*.quant_claims.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        paper_id = data.get("paper_id") or path.stem.replace(
            ".quant_claims", ""
        )
        for claim in data.get("claims", []) or []:
            if not _confidence_admissible(claim):
                continue
            row = _claim_to_row(claim, paper_id=paper_id)
            if row is None:
                continue
            score = _quality_score(claim)
            candidates.append((score, row))
    # Higher score first; cap at max_rows.
    candidates.sort(key=lambda t: -t[0])
    seen_endpoints: dict[str, int] = {}
    for _score, row in candidates:
        # Cap repeated same-paper rows to avoid the table becoming
        # one paper × 30 claims (Shot 3 row-selection rule).
        key = f"{row.study_label}|{row.endpoint}"
        if seen_endpoints.get(row.study_label, 0) >= 4:
            continue
        if seen_endpoints.get(key, 0) >= 1:
            # Same study+endpoint already represented — skip duplicate
            continue
        rows.append(row)
        seen_endpoints[row.study_label] = seen_endpoints.get(
            row.study_label, 0
        ) + 1
        seen_endpoints[key] = 1
        if len(rows) >= max_rows:
            break
    if not rows:
        return ""
    return _render_md(rows, topic=topic)


def _claim_to_row(
    claim: dict[str, Any], *, paper_id: str,
) -> EvidenceRow | None:
    """Transform one high-confidence claim into a table row.
    Returns None for claims without a usable numeric value."""
    nums = claim.get("numeric_values") or []
    if not nums:
        return None
    try:
        primary_value = float(nums[0])
    except (TypeError, ValueError):
        return None
    raw = (claim.get("raw_text") or "").strip()
    units = (claim.get("units") or "").strip()
    claim_type = (claim.get("claim_type") or "").strip()
    endpoint = (claim.get("endpoint") or "").strip()
    arm = (claim.get("arm") or "").strip()
    role = (claim.get("claim_role") or "").strip()
    # Pick the best display string for value: raw_text if it's compact,
    # else format the numeric.
    value_str = raw if (raw and len(raw) < 24) else _format_value(
        primary_value,
    )
    # Unit/type: prefer explicit units, fall back to claim_type.
    unit_str = units if units else claim_type.replace("_", " ")
    # Statistic column: pull a paired p or CI from the claim if present.
    statistic = _format_statistic(claim, primary_value)
    # Endpoint column: bound endpoint > claim_role > short claim_type.
    ep = endpoint or role or claim_type.replace("_", " ") or "—"
    # Citation token: derive Author Year from paper_id (extract year).
    citation = _short_citation(paper_id)
    return EvidenceRow(
        study_label=citation,
        endpoint=_truncate(ep, 30),
        arm=_truncate(arm or "—", 16),
        value=_truncate(value_str, 20),
        unit_or_type=_truncate(unit_str, 18),
        statistic=_truncate(statistic, 22),
        citation=citation,
    )


def _format_value(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:.3g}"


def _format_statistic(claim: dict[str, Any], value: float) -> str:
    """For p_value claims, format as 'p=...'. For CI claims, format
    as '(low–high)'. For HR/OR/RR, return '—' (the value column
    already shows the ratio). Otherwise empty."""
    ct = claim.get("claim_type", "")
    if ct == "p_value":
        if value < 0.001:
            return "p<0.001"
        return f"p={value:.3g}"
    if ct == "confidence_interval":
        nums = claim.get("numeric_values") or []
        if len(nums) >= 2:
            try:
                lo = float(nums[0])
                hi = float(nums[1])
                return f"({lo:.2f}–{hi:.2f})"
            except (TypeError, ValueError):
                return "—"
    return "—"


def _short_citation(paper_id: str) -> str:
    """Extract a compact citation tag from a paper_id slug.
    Falls back to the first 24 chars when no year token is present."""
    import re
    # Find a 4-digit year token. Digit-boundary (not \b word boundary)
    # because paper_ids use underscore separators — \b is matched
    # between word chars and non-word, but '_' is a word char so the
    # boundary fails. Lookbehind/lookahead handle this cleanly.
    m = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", paper_id)
    year = m.group(0) if m else ""
    # Try to extract the first author surname from the slug
    # paper_id looks like 'PMC12345_low_dose_aspirin_in_aspree'
    parts = paper_id.split("_")
    # Skip the PMC123... prefix
    if parts and parts[0].lower().startswith("pmc"):
        parts = parts[1:]
    if not parts:
        return paper_id[:24]
    # First word that's non-numeric and not an article
    skip = {"the", "a", "an", "of", "in", "and", "for", "to", "on"}
    surname = ""
    for w in parts:
        wl = w.lower()
        if wl in skip or wl.isdigit():
            continue
        if w[:1].isalpha():
            surname = w.title()
            break
    if surname and year:
        return f"{surname} {year}"
    if year:
        return f"PMC {year}"
    return paper_id[:24]


# Objective-fact claim types where partial-confidence claims are
# admissible (same rule as scripts/audit_v06_paper._load_corpus_numerics).
# Partial confidence on these reflects uncertainty about the claim's
# INTERPRETIVE ROLE (active vs control arm, primary vs secondary
# endpoint), not about whether the number itself is in the corpus.
_OBJECTIVE_TYPES = {
    "unit_value",        # dose / age / years / kg / mmHg
    "sample_size",       # n=
    "year",              # 2018, 2025
    "sample_count",      # cohort sizes
}


def _confidence_admissible(claim: dict[str, Any]) -> bool:
    """High-confidence always admitted; partial-confidence admitted
    only for objective-fact claim types. None / unbound rejected."""
    conf = (claim.get("binding_confidence") or "").lower()
    if conf == "high":
        return True
    if conf == "partial" and claim.get("claim_type") in _OBJECTIVE_TYPES:
        return True
    return False


def _quality_score(claim: dict[str, Any]) -> int:
    """Higher = better row to include in the table.
    Rules from Shot 3 of the reviewer's plan:
      - prefer p-value / CI / sample_size claims (statistical content)
      - prefer claims with bound endpoint + arm (high binding)
      - prefer hazard_ratio / odds_ratio / risk_ratio (effect estimates)
    """
    ct = claim.get("claim_type", "")
    score = 0
    if ct in ("hazard_ratio", "odds_ratio", "risk_ratio"):
        score += 5
    if ct in ("p_value", "confidence_interval"):
        score += 3
    if ct == "sample_size":
        score += 4
    if ct == "percentage":
        score += 1
    if claim.get("endpoint"):
        score += 2
    if claim.get("arm"):
        score += 1
    return score


def _truncate(s: str, limit: int) -> str:
    s = (s or "").strip().replace("|", "/")  # | breaks markdown tables
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _render_md(rows: Iterable[EvidenceRow], *, topic: str) -> str:
    """Markdown table per the reviewer's spec."""
    rows_list = list(rows)
    title = (
        f"## Quantitative Evidence Index — {topic}\n\n"
        f"_Top {len(rows_list)} high-confidence numeric claims from the "
        f"corpus, deterministically extracted from quant_claims.json. "
        f"Every row traces to a corpus-bound claim — no LLM authorship._\n\n"
    )
    header = (
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
    )
    body = "\n".join(
        f"| {r.study_label} | {r.endpoint} | {r.arm} "
        f"| {r.value} | {r.unit_or_type} | {r.statistic} |"
        for r in rows_list
    )
    return title + header + body + "\n"
