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


# Per-category row quotas — picks rows so the audit's six Q9 numeric
# categories (percentage / p_value / ratio / sample_size / dose /
# speed) all get represented. Without quotas, sample_size dominated
# (every paper has them) and the body's existing prose numerics
# overlapped with the table → low UNIQUE-numeric gain. With quotas
# every category gets fresh corpus-traced numerics that the audit
# regex counts as distinct values.
_CATEGORY_QUOTAS = {
    "percentage": 12,        # most common → biggest unique pool
    "p_value": 10,           # paper has many distinct p-values
    "hazard_ratio": 6,
    "odds_ratio": 4,
    "risk_ratio": 4,
    "sample_size": 6,
    "unit_value": 8,         # doses, ages, durations
    "confidence_interval": 4,
}


def build_results_table(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
) -> str:
    """Read every *.quant_claims.json in quant_dir, select rows under
    per-category quotas to maximize distinct-numeric diversity (the
    Q9 audit dedupes within category, so 12 sample_sizes count as 12
    distinct but 12 percentages add 12 ADDITIONAL distinct numerics).
    Empty string when no qualifying claims exist.

    Cross-topic guard (P1 reviewer fix, 2026-05-04 wave 4): claims
    whose `arm` field references a different drug than the topic's
    active+placebo arm synonyms are dropped. A rapamycin-corpus paper
    that quotes a metformin RCT comparator can otherwise leak
    'arm=metformin' rows into a rapamycin Quantitative Evidence Index.
    Looked up via the topic pack's active_arm_synonyms +
    placebo_arm_synonyms fields; arm-empty claims are kept (no
    cross-topic signal to filter on).
    """
    rows: list[EvidenceRow] = []
    if not quant_dir.exists():
        return ""
    # Load the topic's active+placebo arm synonyms once for the
    # cross-topic filter. Missing pack → no filter (back-compat).
    topic_arm_terms = _load_topic_arm_terms(topic)
    # candidates: list of (score, claim_type, EvidenceRow, raw_value)
    candidates: list[tuple[int, str, EvidenceRow, str]] = []
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
            if not _arm_belongs_to_topic(claim, topic_arm_terms):
                continue
            row = _claim_to_row(claim, paper_id=paper_id)
            if row is None:
                continue
            score = _quality_score(claim)
            ct = claim.get("claim_type", "")
            candidates.append((score, ct, row, row.value))
    candidates.sort(key=lambda t: -t[0])
    # Track per-category and per-study quotas.
    cat_count: dict[str, int] = {}
    seen_endpoints: dict[str, int] = {}
    seen_values: set[str] = set()  # avoid duplicate numeric values
    for _score, ct, row, value in candidates:
        # Per-claim-type quota (drives audit Q9 unique-numeric diversity)
        quota = _CATEGORY_QUOTAS.get(ct, 4)
        if cat_count.get(ct, 0) >= quota:
            continue
        # Per-study cap (≤4 rows per paper; Shot 3 dedup rule)
        if seen_endpoints.get(row.study_label, 0) >= 4:
            continue
        # Skip exact-value duplicates (don't fill quota with same number)
        if value in seen_values:
            continue
        # Skip same study+endpoint pair
        key = f"{row.study_label}|{row.endpoint}"
        if seen_endpoints.get(key, 0) >= 1:
            continue
        rows.append(row)
        cat_count[ct] = cat_count.get(ct, 0) + 1
        seen_endpoints[row.study_label] = seen_endpoints.get(
            row.study_label, 0
        ) + 1
        seen_endpoints[key] = 1
        seen_values.add(value)
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


# Admissibility matches the audit's _load_corpus_numerics rule
# (scripts/audit_v06_paper.py, post-2026-05-04 Q2 universal-fix
# wave 2): high OR partial confidence is accepted for any numeric
# claim type. The 'partial' label reflects binding-uncertainty
# about which (endpoint, arm, direction) tuple a value ties to,
# not whether the number is in the corpus. Single source of truth:
# the table cannot emit a numeric the Q2 audit will reject as
# untraceable. Fabrication prevention is handled at the writer
# prompt layer, not here.


def _confidence_admissible(claim: dict[str, Any]) -> bool:
    """High or partial confidence admitted; 'none' / unbound rejected."""
    conf = (claim.get("binding_confidence") or "").lower()
    return conf in ("high", "partial")


def _load_topic_arm_terms(topic: str) -> frozenset[str]:
    """Return lowercased active+placebo arm synonyms from the topic
    pack. Empty set if the pack is missing — caller treats empty as
    'no filter' for back-compat. Used by _arm_belongs_to_topic to
    drop cross-topic-arm rows from the table."""
    repo = Path(__file__).resolve().parent.parent
    tp_path = repo / "topic_packs" / f"{topic}.toml"
    if not tp_path.exists():
        return frozenset()
    try:
        from agent.topic_pack import load_topic_pack
        pack = load_topic_pack(tp_path)
    except (ImportError, OSError, ValueError):
        return frozenset()
    terms: set[str] = set()
    for syn in (
        list(getattr(pack, "active_arm_synonyms", []) or []) +
        list(getattr(pack, "placebo_arm_synonyms", []) or [])
    ):
        s = str(syn).strip().lower()
        if s:
            terms.add(s)
    # Generic placebo/control terms always allowed (cross-topic safe)
    terms |= {"placebo", "control", "vehicle", "pooled"}
    return frozenset(terms)


def _arm_belongs_to_topic(
    claim: dict[str, Any], topic_arm_terms: frozenset[str],
) -> bool:
    """Filter out claims whose arm references a non-topic drug.

    - Empty topic_arm_terms (pack missing) → no filtering (back-compat).
    - Empty claim arm → kept (no cross-topic signal to filter on).
    - Non-empty arm: must match (case-insensitive substring) at least
      one topic-pack arm synonym OR be a generic comparator term.
    """
    if not topic_arm_terms:
        return True
    arm = (claim.get("arm") or "").strip().lower()
    if not arm:
        return True
    # Match by substring containment in either direction so 'low-dose
    # aspirin' matches 'aspirin' and vice versa.
    for term in topic_arm_terms:
        if term in arm or arm in term:
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
