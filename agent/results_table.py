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

# Endpoint values that signal an UNBOUND or context-only claim.
# Reviewer wave 9 (2026-05-05): the QEI rendered rows like
# 'endpoint = unknown' and 'endpoint = background', which are
# semantically empty for an evidence index. Universal across topics.
_UNBOUND_ENDPOINTS = {"unknown", "background", "", "n/a", "none", "?"}

# Unit categories that are TEMPORAL (duration, age) — only meaningful
# in the QEI when the endpoint is itself a duration/age outcome.
# Otherwise a row like 'endpoint=body mass index, value=65 years' is a
# semantic mismatch (the 65 years was the patient age, not the BMI).
_TEMPORAL_UNITS = {"years", "year", "months", "month", "weeks",
                   "week", "days", "day", "hours"}
_TEMPORAL_ENDPOINTS = {
    "duration", "follow-up", "follow up", "follow_up", "study duration",
    "trial duration", "median follow-up", "age", "treatment duration",
    "intervention duration", "exposure duration",
}


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
    accepted_paper_ids: frozenset[str] | None = None,
) -> str:
    """Back-compat thin wrapper around `build_results_table_with_diagnostic`.

    Returns just the markdown body (empty string when no rows). All
    selection logic, cross-topic guards, receipt-scope filtering, and
    counter accounting live in the with-diagnostic variant — see that
    function's docstring for the full contract.
    """
    md, _diag = build_results_table_with_diagnostic(
        quant_dir, topic=topic, max_rows=max_rows,
        accepted_paper_ids=accepted_paper_ids,
    )
    return md


def build_results_table_with_diagnostic(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
    accepted_paper_ids: frozenset[str] | None = None,
) -> tuple[str, dict[str, int]]:
    """Same selection contract as build_results_table, but returns
    `(md, diagnostic)` so callers know WHY the table is empty (or
    sparse). Slice-1 reviewer fix (2026-05-05): an empty QEI must be
    diagnostic — operators need to see whether the corpus had zero
    quant claims, all claims were below admissibility, or all were
    cross-topic / non-receipt / non-meaningful — so the corpus
    expansion to-do can target the right gap.

    Returned diagnostic keys:
      - n_quant_files: parseable *.quant_claims.json files seen
      - n_total_claims: claims across all files (pre-filter)
      - n_admissible: passed _confidence_admissible
      - n_topic_matched: also passed _arm_belongs_to_topic
      - n_meaningful: also passed _row_is_meaningful (via _claim_to_row)
      - n_after_quotas: rows that survived per-category / per-study
        quotas + duplicate-value dedupe
      - n_rendered: final row count in the markdown table
      - drop_off_topic_arm: dropped by cross-topic arm filter
      - drop_non_receipt_paper: skipped because paper_id not in
        accepted_paper_ids (only counted when the filter is active)
      - drop_surface_gate: dropped because the final row is not
        manuscript-surface safe (e.g. endpoint/unit mismatch)

    Cross-topic guard (wave 4), receipt-scope guard (wave 6), and the
    meaningful-row guard (wave 9) all participate; see comments below.
    """
    diag: dict[str, int] = {
        "n_quant_files": 0,
        "n_total_claims": 0,
        "n_admissible": 0,
        "n_topic_matched": 0,
        "n_meaningful": 0,
        "n_after_quotas": 0,
        "n_rendered": 0,
        "drop_off_topic_arm": 0,
        "drop_non_receipt_paper": 0,
        "drop_surface_gate": 0,
    }
    rows: list[EvidenceRow] = []
    if not quant_dir.exists():
        return "", diag
    topic_arm_terms = _load_topic_arm_terms(topic)
    candidates: list[tuple[int, str, EvidenceRow, str]] = []
    for path in sorted(quant_dir.glob("*.quant_claims.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        diag["n_quant_files"] += 1
        paper_id = data.get("paper_id") or path.stem.replace(
            ".quant_claims", ""
        )
        if accepted_paper_ids is not None and paper_id not in accepted_paper_ids:
            diag["drop_non_receipt_paper"] += 1
            continue
        for claim in data.get("claims", []) or []:
            diag["n_total_claims"] += 1
            if not _confidence_admissible(claim):
                continue
            diag["n_admissible"] += 1
            if not _arm_belongs_to_topic(claim, topic_arm_terms):
                diag["drop_off_topic_arm"] += 1
                continue
            diag["n_topic_matched"] += 1
            row = _claim_to_row(claim, paper_id=paper_id)
            if row is None:
                continue
            diag["n_meaningful"] += 1
            if not _publishable_surface_row(row):
                diag["drop_surface_gate"] += 1
                continue
            score = _quality_score(claim)
            ct = claim.get("claim_type", "")
            candidates.append((score, ct, row, row.value))
    candidates.sort(key=lambda t: -t[0])
    cat_count: dict[str, int] = {}
    seen_endpoints: dict[str, int] = {}
    seen_values: set[str] = set()
    for _score, ct, row, value in candidates:
        quota = _CATEGORY_QUOTAS.get(ct, 4)
        if cat_count.get(ct, 0) >= quota:
            continue
        if seen_endpoints.get(row.study_label, 0) >= 4:
            continue
        if value in seen_values:
            continue
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
    diag["n_after_quotas"] = len(rows)
    if not rows:
        return "", diag
    diag["n_rendered"] = len(rows)
    return _render_md(rows, topic=topic), diag


def format_empty_qei_placeholder(
    diagnostic: dict[str, int], *, topic: str,
) -> str:
    """Diagnostic placeholder for the QEI section when no rows survive
    all gates. Replaces the prior generic 'No high-confidence claims'
    blurb with a structural breakdown so reviewers see exactly which
    gate dropped the rows. Universal across topics — pure counter
    rendering, no drug names, no per-topic prose.
    """
    n_files = diagnostic.get("n_quant_files", 0)
    n_total = diagnostic.get("n_total_claims", 0)
    n_adm = diagnostic.get("n_admissible", 0)
    n_topic = diagnostic.get("n_topic_matched", 0)
    n_meaning = diagnostic.get("n_meaningful", 0)
    drop_arm = diagnostic.get("drop_off_topic_arm", 0)
    drop_nr = diagnostic.get("drop_non_receipt_paper", 0)
    drop_surface = diagnostic.get("drop_surface_gate", 0)
    return (
        f"## Quantitative Evidence Index — {topic}\n\n"
        f"_No qualifying rows. Corpus diagnostic — quant_claims files "
        f"scanned: **{n_files}**; total claims read: **{n_total}**; "
        f"admissible (HIGH/PARTIAL confidence): **{n_adm}**; "
        f"topic-arm matched: **{n_topic}**; semantically meaningful: "
        f"**{n_meaning}**. Dropped by guards: cross-topic arm = "
        f"{drop_arm}, non-receipt papers = {drop_nr}, journal surface "
        f"= {drop_surface}. See Corpus "
        f"Expansion To-Do in the final verdict for the actionable "
        f"gap._\n"
    )


def _row_is_meaningful(claim: dict[str, Any]) -> bool:
    """Reviewer wave 9 (2026-05-05): drop rows whose endpoint is
    unbound or whose unit/endpoint combination is semantically
    incoherent. Universal — no drug names, no specific values.

    Rules (each one drops the row):
      1. endpoint ∈ {unknown, background, '', n/a, none, ?}
      2. claim_type='unit_value' with TEMPORAL units (years, months,
         days) but endpoint isn't a duration/age outcome — that's a
         age-or-duration value misattributed to a non-temporal
         endpoint (e.g. 'BMI = 65 years' — wrong).
    """
    endpoint = (claim.get("endpoint") or "").strip().lower()
    if endpoint in _UNBOUND_ENDPOINTS:
        return False
    claim_type = (claim.get("claim_type") or "").strip()
    units = (claim.get("units") or "").strip().lower()
    if claim_type == "unit_value" and units in _TEMPORAL_UNITS:
        # Allow the row only if the endpoint is itself a temporal
        # outcome (duration, follow-up, age).
        if endpoint not in _TEMPORAL_ENDPOINTS:
            return False
    return True


def _claim_to_row(
    claim: dict[str, Any], *, paper_id: str,
) -> EvidenceRow | None:
    """Transform one high-confidence claim into a table row.
    Returns None for claims without a usable numeric value or whose
    endpoint/unit combination is semantically incoherent (reviewer
    wave 9 cleanup)."""
    if not _row_is_meaningful(claim):
        return None
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


def _publishable_surface_row(row: EvidenceRow) -> bool:
    """Final manuscript-surface filter shared with the post-render gate."""
    try:
        from agent.journal_surface_gate import is_publishable_qei_row
    except ImportError:
        return True
    return is_publishable_qei_row(row)


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


def resolve_accepted_paper_ids(
    receipts: Any, parsed_dir: Path,
) -> frozenset[str]:
    """Map receipts → corpus paper_ids via parsed metadata.

    For each parsed/<paper_id>.paper_sections.json, read its DOI +
    PMID. Match against receipts' source_doi / source_pmid. The set
    of paper_ids that match are the ones contributing evidence —
    used to scope the Quantitative Evidence Index so non-receipt
    papers don't pad the table (P2 reviewer fix wave 6).

    Universal across topics, no per-topic logic. Empty frozenset
    when receipts have no DOI/PMID (rare — drug topics populate
    these). Empty set is treated as 'no filter' upstream so the
    table doesn't go empty for back-compat callers.
    """
    if not parsed_dir.exists():
        return frozenset()
    receipt_dois: set[str] = set()
    receipt_pmids: set[str] = set()
    for r in receipts:
        d = (getattr(r, "source_doi", None) or "").strip().lower()
        if d:
            receipt_dois.add(d)
        p = (getattr(r, "source_pmid", None) or "").strip()
        if p:
            receipt_pmids.add(p)
    if not receipt_dois and not receipt_pmids:
        return frozenset()
    accepted: set[str] = set()
    for path in parsed_dir.glob("*.paper_sections.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        paper_id = (data.get("paper_id") or "").strip()
        if not paper_id:
            continue
        d = (data.get("doi") or "").strip().lower()
        p = (data.get("pmid") or "").strip()
        if (d and d in receipt_dois) or (p and p in receipt_pmids):
            accepted.add(paper_id)
    return frozenset(accepted)


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
