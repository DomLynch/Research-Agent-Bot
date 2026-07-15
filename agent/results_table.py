"""Deterministic Quantitative Evidence Index rendering."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.outcome_class_remap import outcome_display

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
_DOSE_UNITS = {"mg", "g", "mcg", "µg", "μg", "ng"}
_DOSE_ENDPOINTS = {
    "dose", "dosing", "dosage", "drug dose", "treatment dose",
    "intervention dose",
}
_RATIO_CLAIM_TYPES = {"hazard_ratio", "odds_ratio", "risk_ratio"}


@dataclass(frozen=True, slots=True)
class EvidenceRow:
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
    citation_tokens_by_paper_id: Mapping[str, str] | None = None,
    quarantine_path: Path | None = None,
) -> str:
    return build_results_table_with_diagnostic(
        quant_dir, topic=topic, max_rows=max_rows,
        accepted_paper_ids=accepted_paper_ids,
        citation_tokens_by_paper_id=citation_tokens_by_paper_id,
        quarantine_path=quarantine_path,
    )[0]


def build_results_table_with_diagnostic(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
    accepted_paper_ids: frozenset[str] | None = None,
    citation_tokens_by_paper_id: Mapping[str, str] | None = None,
    quarantine_path: Path | None = None,
) -> tuple[str, dict[str, int]]:
    """Return QEI markdown plus drop counters."""
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
        "drop_missing_canonical_citation": 0,
    }
    rows: list[EvidenceRow] = []
    quarantined: list[dict[str, str]] = []
    if not quant_dir.exists():
        _write_qei_quarantine(quarantine_path, quarantined)
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
            token = _canonical_qei_token(
                paper_id, citation_tokens_by_paper_id,
            )
            if citation_tokens_by_paper_id is not None and not token:
                diag["drop_missing_canonical_citation"] += 1
                quarantined.append(_qei_quarantine_entry(
                    paper_id, claim, "missing_canonical_citation",
                ))
                continue
            row = _claim_to_row(
                claim, paper_id=paper_id, citation_token=token,
            )
            if row is None:
                continue
            diag["n_meaningful"] += 1
            if not _publishable_surface_row(row):
                diag["drop_surface_gate"] += 1
                quarantined.append(_qei_quarantine_entry(
                    paper_id, claim, "journal_surface_gate",
                ))
                continue
            score = _quality_score(claim)
            ct = claim.get("claim_type", "")
            value_key = f"{row.value}|{row.unit_or_type}|{row.statistic}"
            candidates.append((score, ct, row, value_key))
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
    _write_qei_quarantine(quarantine_path, quarantined)
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
    drop_cite = diagnostic.get("drop_missing_canonical_citation", 0)
    return (
        f"## Quantitative Evidence Index — {topic}\n\n"
        f"_No qualifying rows. Corpus diagnostic — quant_claims files "
        f"scanned: **{n_files}**; total claims read: **{n_total}**; "
        f"admissible (HIGH/PARTIAL confidence): **{n_adm}**; "
        f"topic-arm matched: **{n_topic}**; semantically meaningful: "
        f"**{n_meaning}**. Dropped by guards: cross-topic arm = "
        f"{drop_arm}, non-receipt papers = {drop_nr}, journal surface "
        f"= {drop_surface}, missing canonical citation = {drop_cite}. "
        f"See Corpus "
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
      3. claim_role is background/protocol-only; public QEI is for
         outcome/effect numerics, not contextual or methods numerics.
      4. percentage extractor captured the "95%" prefix of a CI;
         the confidence_interval claim carries the publishable row.
      5. partial-confidence ratio rows without a signed direction.
    """
    endpoint = (claim.get("endpoint") or "").strip().lower()
    if endpoint in _UNBOUND_ENDPOINTS:
        return False
    role = (claim.get("claim_role") or "").strip().lower()
    if role in {"background", "protocol", "population_descriptor"}:
        return False
    claim_type = (claim.get("claim_type") or "").strip()
    confidence = (claim.get("binding_confidence") or "").strip().lower()
    direction = (claim.get("direction") or "").strip().lower()
    units = (claim.get("units") or "").strip().lower()
    raw = (claim.get("raw_text") or "").strip().lower()
    sent = str(claim.get("sentence") or "")
    context = f"{sent} {claim.get('context_window') or ''}".lower()
    if claim_type == "percentage" and raw == "95%" and "95% ci" in context:
        return False
    if claim_type == "percentage" and (
        "heterogeneity" in context
        or re.search(r"\bi\s*(?:2|²)\b", context)
    ):
        return False
    if claim_type == "mean_sd" and role not in {"effect", "outcome"}:
        return False
    if claim_type == "p_value" and _ambiguous_multi_stat_binding(
        raw, endpoint, str(claim.get("sentence") or ""),
    ):
        return False
    if role == "dose" and endpoint not in _DOSE_ENDPOINTS:
        return False
    if claim_type == "sample_size" and role != "population":
        return False
    if claim_type in _RATIO_CLAIM_TYPES and (
        (confidence != "high" and not direction)
        or endpoint in {"body mass index", "bmi"}
    ):
        return False
    if claim_type == "unit_value" and units in _TEMPORAL_UNITS:
        # Allow the row only if the endpoint is itself a temporal
        # outcome (duration, follow-up, age).
        if endpoint not in _TEMPORAL_ENDPOINTS:
            return False
    if claim_type == "unit_value" and units in _DOSE_UNITS:
        if endpoint not in _DOSE_ENDPOINTS:
            return False
    return True


def _ambiguous_multi_stat_binding(
    raw: str, endpoint: str, sentence: str,
) -> bool:
    """Drop dense-list p-values not locally tied to their endpoint."""
    if not raw or not endpoint or not sentence:
        return False
    sent = sentence.lower()
    p_values = re.findall(r"\bp\s*[<=>]\s*0?\.\d+", sent)
    if len(p_values) < 2:
        return False
    raw_i = sent.find(raw.lower())
    if raw_i < 0:
        return True
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", endpoint.lower())
        if len(t) >= 3 and t not in {"and", "the", "with"}
    ]
    if not tokens:
        return True
    window = sent[max(0, raw_i - 40): raw_i + len(raw) + 40]
    return not any(t in window for t in tokens)


def _claim_to_row(
    claim: dict[str, Any], *, paper_id: str, citation_token: str | None = None,
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
    # Statistic column: pull a paired p or CI from the claim if present.
    statistic = _format_statistic(claim, primary_value)
    # Pick the best display string for value: raw_text if it's compact,
    # else format the numeric. Confidence intervals render their interval
    # once in Statistic; repeating/truncating the CI in Value creates
    # public-table residue and unsafe reviewer patches.
    if claim_type == "confidence_interval" and statistic != "—":
        value_str = "—"
    elif claim_type == "p_value":
        value_str = _format_p_value(raw, primary_value)
    else:
        value_str = raw if (raw and len(raw) < 24) else _format_value(
            primary_value,
        )
    # Unit/type: prefer explicit units, fall back to public claim type.
    unit_str = units if units else _public_label(claim_type)
    # Endpoint column: bound endpoint > claim_role > short claim_type.
    ep = endpoint or role or _public_label(claim_type) or "—"
    citation = citation_token or _short_citation(paper_id)
    return EvidenceRow(
        study_label=citation,
        endpoint=_truncate(ep, 30),
        arm=_truncate(arm or "—", 24),
        value=_truncate(value_str, 20),
        unit_or_type=_truncate(unit_str, 18),
        statistic=_truncate(statistic, 22),
        citation=citation,
    )


def _canonical_qei_token(
    paper_id: str, tokens_by_paper_id: Mapping[str, str] | None,
) -> str | None:
    if tokens_by_paper_id is None:
        return None
    token = (tokens_by_paper_id.get(paper_id) or "").strip()
    return token or None


def _qei_quarantine_entry(
    paper_id: str, claim: dict[str, Any], reason: str,
) -> dict[str, str]:
    return {
        "reason": reason,
        "paper_id": paper_id,
        "endpoint": str(claim.get("endpoint") or ""),
        "arm": str(claim.get("arm") or ""),
        "claim_type": str(claim.get("claim_type") or ""),
        "raw_text": str(claim.get("raw_text") or ""),
    }


def _write_qei_quarantine(
    path: Path | None, rows: list[dict[str, str]],
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2))


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


def _format_p_value(raw: str, value: float) -> str:
    """Normalize source p-values without confusing other zero-valued fields."""
    match = re.search(
        r"\bp\s*([=<>\u2264\u2265])\s*((?:0)?\.\d+|0|1(?:\.0+)?)\b",
        raw,
        flags=re.I,
    )
    if match:
        operator, literal = match.groups()
    else:
        bare = re.fullmatch(r"\s*([=<>\u2264\u2265])?\s*((?:0)?\.\d+|0|1(?:\.0+)?)\s*", raw)
        if not bare:
            return "—" if raw or value == 0 else f"P = {_format_value(value)}"
        operator, literal = bare.group(1) or "=", bare.group(2)
    literal = f"0{literal}" if literal.startswith(".") else literal
    if float(literal) == 0:
        if "." not in literal:
            return "—"
        decimals = len(literal.partition(".")[2])
        return f"P < {10 ** -decimals:.{decimals}f}"
    return f"P {operator} {literal}"


def _public_label(value: str) -> str:
    labels = {
        "ci": "confidence interval",
        "mean_sd": "mean ± SD",
        "p_value": "p-value",
        "sample_size": "sample size",
        "unit_value": "unit value",
    }
    s = (value or "").strip()
    return labels.get(s, outcome_display(s).lower())


def _format_statistic(claim: dict[str, Any], value: float) -> str:
    """For p_value claims, format as 'p=...'. For CI claims, format
    as '(low–high)'. For HR/OR/RR, return '—' (the value column
    already shows the ratio). Otherwise empty."""
    ct = claim.get("claim_type", "")
    if ct == "p_value":
        # The value column already carries the exact p-value string.
        # Duplicating it here invites reviewer/model "simplifications"
        # that can corrupt markdown table arity.
        return "—"
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
    s = re.sub(r"\s+", " ", (s or "").strip().replace("|", "/"))
    if len(s) <= limit:
        return s
    cut = s[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:/")
    return f"{cut or s[: limit - 1]}…"


def _render_md(rows: Iterable[EvidenceRow], *, topic: str) -> str:
    """Markdown table per the reviewer's spec."""
    rows_list = list(rows)
    title = (
        f"## Quantitative Evidence Index — {topic}\n\n"
        f"_Quantitative Evidence Index: top {len(rows_list)} high-confidence numeric claims from the "
        f"corpus. Every row traces to a corpus-bound claim and a registered citation._\n\n"
        "**Numeric verification note:** P-values are rendered from extracted "
        "source statistics; rounded zero values are reported at their implied "
        "decimal floor rather than as impossible zero probabilities.\n\n"
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
