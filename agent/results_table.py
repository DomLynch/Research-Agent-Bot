"""Deterministic Quantitative Evidence Index rendering."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.outcome_class_remap import outcome_display
from agent.publication_evidence import _record_text, exact_source_quote

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


def _owned_result_sentence(sentence: str, record: dict[str, Any]) -> bool:
    """A source-local quote can still describe another study's findings."""
    if re.search(
        r"\[\s*\d+(?:\s*[,;\-–]\s*\d+)*\s*\]|\bet al\.|"
        r"\b(?:previous|prior|earlier|other|published)\s+(?:[\w-]+\s+){0,2}(?:stud(?:y|ies)|reports?|trials?|cohorts?|research|evidence)\b|"
        r"\bno evidence that\b", sentence, re.I,
    ):
        return False
    sections = record.get("sections", {})
    if not isinstance(sections, dict):
        return False
    for name, text in sections.items():
        if str(name).lower() in {"abstract", "results", "conclusion"} or (
            str(name).lower() == "discussion" and re.search(r"\b(?:we|our|this study|present study)\b", sentence, re.I)
        ):
            if exact_source_quote(sentence, _record_text(text)):
                return True
    return False


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    study_label: str       # "Author Year" or "<paper_id> (Year)"
    endpoint: str          # bound endpoint or claim_role fallback
    arm: str               # bound arm or "—"
    value: str             # the numeric, formatted
    unit_or_type: str      # units string or claim_type fallback
    statistic: str         # "p=0.04" / "(0.81–1.13)" / "—"
    citation: str          # citation_token (Author Year)
    source_context: str = ""
    source_value: str = ""


def build_results_table(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
    accepted_paper_ids: frozenset[str] | None = None,
    citation_tokens_by_paper_id: Mapping[str, str] | None = None,
    quarantine_path: Path | None = None, parsed_dir: Path | None = None,
) -> str:
    return build_results_table_with_diagnostic(
        quant_dir, topic=topic, max_rows=max_rows,
        accepted_paper_ids=accepted_paper_ids,
        citation_tokens_by_paper_id=citation_tokens_by_paper_id,
        quarantine_path=quarantine_path, parsed_dir=parsed_dir,
    )[0]


def _source_result_claim(
    claim: dict[str, Any], source_text: str, normalized_source: str, record: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    sentence = exact_source_quote(
        re.sub(r"(?<=\d)\u2013(?=\d)", "-", str(claim.get("sentence") or "")), normalized_source,
    )
    match = re.search(
        r"(?:^|[.!?]\s+)(" + re.escape(sentence) + r")(?=$|\s)", normalized_source,
    ) if sentence and sentence.endswith((".", "!", "?")) else None
    if not match:
        return claim, "drop_surface_gate"
    claim = {**claim, "sentence": source_text[slice(*match.span(1))]}
    return claim, "" if _owned_result_sentence(str(claim["sentence"]), record) else "drop_unowned_result"


def build_results_table_with_diagnostic(
    quant_dir: Path, *, topic: str, max_rows: int = _MAX_ROWS,
    accepted_paper_ids: frozenset[str] | None = None,
    citation_tokens_by_paper_id: Mapping[str, str] | None = None,
    quarantine_path: Path | None = None, parsed_dir: Path | None = None,
) -> tuple[str, dict[str, int]]:
    """Return QEI markdown plus drop counters."""
    diag = dict.fromkeys((
        "n_quant_files", "n_total_claims", "n_admissible", "n_topic_matched",
        "n_meaningful", "n_after_quotas", "n_rendered", "drop_off_topic_arm",
        "drop_non_receipt_paper", "drop_surface_gate",
        "drop_missing_canonical_citation", "drop_unowned_result",
    ), 0)
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
        source_text = ""
        record = {}
        if parsed_dir is not None:
            try:
                record = json.loads((parsed_dir / f"{paper_id}.paper_sections.json").read_text())
                source_text = " ".join(_record_text(record.get("sections", {})).split())
            except (OSError, ValueError, AttributeError):
                pass
        # Range-dash equivalence is length-preserving; render the original source span.
        normalized_source = re.sub(r"(?<=\d)\u2013(?=\d)", "-", source_text)
        for claim in data.get("claims", []) or []:
            diag["n_total_claims"] += 1
            if parsed_dir is not None:
                claim, reason = _source_result_claim(claim, source_text, normalized_source, record)
                if reason:
                    diag[reason] += 1
                    quarantined.append(_qei_quarantine_entry(paper_id, claim, reason))
                    continue
            if not _confidence_admissible(claim):
                continue
            diag["n_admissible"] += 1
            if not _arm_belongs_to_topic(claim, topic_arm_terms):
                diag["drop_off_topic_arm"] += 1
                continue
            diag["n_topic_matched"] += 1
            token = (
                (citation_tokens_by_paper_id.get(paper_id) or "").strip()
                if citation_tokens_by_paper_id is not None else None
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
            value_key = f"{row.source_value}|{row.unit_or_type}"
            candidates.append((score, ct, row, value_key))
    rows = _select_result_rows(candidates, max_rows)
    diag["n_after_quotas"] = len(rows)
    _write_qei_quarantine(quarantine_path, quarantined)
    if not rows:
        return "", diag
    diag["n_rendered"] = len(rows)
    return _render_md(rows, topic=topic), diag


def _select_result_rows(candidates: list[tuple[int, str, EvidenceRow, str]], max_rows: int) -> list[EvidenceRow]:
    rows: list[EvidenceRow] = []
    candidates.sort(key=lambda t: -t[0])
    seen_endpoints: dict[str, int] = {}
    seen_statements: set[tuple[str, str]] = set()
    for _score, _ct, row, _value in candidates:
        statement = (row.study_label, row.source_context)
        if seen_endpoints.get(row.study_label, 0) >= 4:
            continue
        if statement in seen_statements:
            continue
        key = f"{row.study_label}|{row.endpoint}"
        if seen_endpoints.get(key, 0) >= 1:
            continue
        rows.append(row)
        seen_statements.add(statement)
        seen_endpoints[row.study_label] = seen_endpoints.get(
            row.study_label, 0
        ) + 1
        seen_endpoints[key] = 1
        if len(rows) >= max_rows:
            break
    return rows


def format_empty_qei_placeholder(
    diagnostic: dict[str, int], *, topic: str,
) -> str:
    """Report the actual gate drop counts when no QEI rows survive."""
    counts = {key: diagnostic.get(key, 0) for key in (
        "n_quant_files", "n_total_claims", "n_admissible", "n_topic_matched", "n_meaningful",
        "drop_off_topic_arm", "drop_non_receipt_paper", "drop_surface_gate", "drop_missing_canonical_citation",
    )}
    return f"## Quantitative Evidence Index — {topic}\n\n" + (
        "_No qualifying rows. Corpus diagnostic — quant_claims files scanned: **{n_quant_files}**; "
        "total claims read: **{n_total_claims}**; admissible (HIGH/PARTIAL confidence): **{n_admissible}**; "
        "topic-arm matched: **{n_topic_matched}**; semantically meaningful: **{n_meaningful}**. "
        "Dropped by guards: cross-topic arm = {drop_off_topic_arm}, non-receipt papers = {drop_non_receipt_paper}, "
        "journal surface = {drop_surface_gate}, missing canonical citation = {drop_missing_canonical_citation}. "
        "See Corpus Expansion To-Do in the final verdict for the actionable gap._\n"
    ).format_map(counts)


def _row_is_meaningful(claim: dict[str, Any]) -> bool:
    """Reject unbound endpoints, incompatible units and non-result numerics."""
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
    return _statistic_is_result(claim_type, raw, sent, context)


def _statistic_is_result(claim_type: str, raw: str, sent: str, context: str) -> bool:
    if raw and re.search(r"±\s*" + re.escape(raw).replace(r"\ ", r"\s*") + r"(?!\w|\.\d)", sent, re.I):
        return False
    if re.search(r"\bbaseline\b", sent, re.I) and re.search(
        r"\b(?:similar|comparable|balanced|(?:not|no)\b.{0,35}\bdiffer\w*)\b", sent, re.I,
    ) and not re.search(
        r"\b(?:adjust\w*|chang\w*|reduc\w*|decreas\w*|increas\w*|improv\w*|follow[ -]?up|after|post\w*)\b", sent, re.I,
    ):
        return False
    if claim_type == "percentage" and raw == "95%" and "95% ci" in context:
        return False
    if claim_type == "percentage" and (
        "heterogeneity" in context
        or re.search(r"\bi\s*(?:2|²)\b", context)
    ):
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
    """Keep only meaningful claims with a usable numeric value."""
    if not _row_is_meaningful(claim):
        return None
    nums = claim.get("numeric_values") or []
    if not nums:
        return None
    try:
        float(nums[0])
    except (TypeError, ValueError):
        return None
    raw = " ".join(str(claim.get("raw_text") or "").split()).replace("|", "&#124;")
    unit_str = (claim.get("units") or "").strip() or _public_label(claim.get("claim_type") or "")
    citation = citation_token or _short_citation(paper_id)
    return EvidenceRow(
        study_label=citation,
        endpoint=_truncate(claim["endpoint"], 30),
        arm=_truncate(claim.get("arm") or "—", 24),
        value=raw,
        unit_or_type=_truncate(unit_str, 18),
        statistic="—",
        citation=citation,
        source_context=" ".join(str(claim.get("sentence") or "").split()).replace("|", "&#124;"),
        source_value=raw,
    )


def _qei_quarantine_entry(
    paper_id: str, claim: dict[str, Any], reason: str,
) -> dict[str, str]:
    return {
        "reason": reason,
        "paper_id": paper_id,
        **{key: str(claim.get(key) or "") for key in ("endpoint", "arm", "claim_type", "raw_text", "sentence")},
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


def _public_label(value: str) -> str:
    labels = {"ci": "confidence interval", "mean_sd": "mean ± SD", "p_value": "p-value",
              "sample_size": "sample size", "unit_value": "unit value"}
    s = (value or "").strip()
    return labels.get(s, outcome_display(s).lower())


def _short_citation(paper_id: str) -> str:
    """Extract a compact citation tag from a paper_id slug.
    Falls back to the first 24 chars when no year token is present."""
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
    surname = next(
        (w.title() for w in parts
         if w.lower() not in skip and not w.isdigit() and w[:1].isalpha()),
        "",
    )
    return f"{surname or 'PMC'} {year}" if year else paper_id[:24]


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
    return (claim.get("binding_confidence") or "").lower() in ("high", "partial")


def resolve_accepted_paper_ids(
    receipts: Any, parsed_dir: Path,
) -> frozenset[str]:
    """Match DOI/PMID identities; an empty set means no matched evidence."""
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
    """Load topic and comparator terms; a missing pack supplies no arm filter."""
    repo = Path(__file__).resolve().parent.parent
    tp_path = repo / "topic_packs" / f"{topic}.toml"
    try:
        from agent.topic_pack import load_topic_pack
        pack = load_topic_pack(tp_path)
    except (ImportError, OSError, ValueError):
        return frozenset()
    terms = {
        s for field in ("active_arm_synonyms", "placebo_arm_synonyms")
        for syn in (getattr(pack, field, []) or [])
        if (s := str(syn).strip().lower())
    }
    # Generic placebo/control terms always allowed (cross-topic safe)
    terms |= {"placebo", "control", "vehicle", "pooled"}
    return frozenset(terms)


def _arm_belongs_to_topic(
    claim: dict[str, Any], topic_arm_terms: frozenset[str],
) -> bool:
    """Require a topic/comparator match when both arm and topic terms are known."""
    arm = (claim.get("arm") or "").strip().lower()
    # Match by substring containment in either direction so 'low-dose
    # aspirin' matches 'aspirin' and vice versa.
    return not topic_arm_terms or not arm or any(term in arm or arm in term for term in topic_arm_terms)


def _quality_score(claim: dict[str, Any]) -> int:
    """Rank statistical information and bound endpoints/arms above bare values."""
    score = {
        **dict.fromkeys(_RATIO_CLAIM_TYPES, 5),
        "p_value": 3,
        "confidence_interval": 3,
        "sample_size": 4,
        "percentage": 1,
    }.get(claim.get("claim_type", ""), 0)
    return score + 2 * bool(claim.get("endpoint")) + bool(claim.get("arm"))


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
        "_Quantitative Evidence Index: source excerpts with numerical statements. "
        "The quoted context retains the population, comparator and endpoint; "
        "source-local text alone does not establish study ownership; background-study quotations are excluded._\n\n"
    )
    header = (
        "| Study | Source context | Raw statistic |\n"
        "|---|---|---|\n"
    )
    body = "\n".join(
        f"| {r.study_label} | {r.source_context} | {r.source_value} |"
        for r in rows_list
    )
    return title + header + body + "\n"
