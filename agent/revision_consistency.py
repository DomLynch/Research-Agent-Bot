"""Deterministic manuscript-consistency repairs requested by reviewers."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from agent.endpoint_evidence import endpoint_direction_map
from agent.evidence_lanes import derive_receipt_lane, effective_directness
from agent.synthesis import build_tension_matrix
from agent.synthesis_schemas import EffectDirection, OutcomeClass, ReceiptSummary

_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")
_TENSION_LEAD_RE = re.compile(
    rf"^(?:The clearest|Another|(?:The|A)\s+(?:{'|'.join(_ORDINALS)}))"
    r"(?=\s+(?:and\s+overarching\s+)?(?:cross-outcome\s+)?tension\b)",
    re.I,
)
_FRAMEWORK_NOTE = (
    "Framework boundary: No novel paper-level tradeoff framework is claimed; interpretation is limited "
    "to the retained source map and its explicitly traced endpoint-level findings."
)
_TENSION_AUDIT = (
    "Endpoint-direction audit: Load-bearing tensions below are recomputed only from shared endpoint-level "
    "direction codes. Source-level-only disagreements are excluded as coding-artifact possible and are "
    "not treated as load-bearing."
)
_FRAMEWORK_RE = re.compile(
    r"\bmetabolic[-\s\u2010-\u2015]+functional[-\s\u2010-\u2015]+tradeoff\s+framework\b",
    re.I,
)
_FRAMEWORK_HEADING_RE = re.compile(
    r"^##\s+metabolic[-\s\u2010-\u2015]+functional[-\s\u2010-\u2015]+tradeoff\s+framework\b"
    r".*?(?=^## |\Z)",
    re.M | re.S | re.I,
)
_FRAMEWORK_REPLACEMENT = "source-bounded metabolic and functional evidence contrast"
_FRAMEWORK_PROPOSAL_RE = re.compile(
    rf"\bwe\s+(?:propose|introduce|advance|present|develop)\s+(?:(?:the|a)\s+)?"
    rf"{re.escape(_FRAMEWORK_REPLACEMENT)}",
    re.I,
)
_FRAMEWORK_NOVELTY_RE = re.compile(
    rf"({re.escape(_FRAMEWORK_REPLACEMENT)})\s+as\s+(?:a\s+)?"
    r"(?:(?:novel|new|original)\s+)?(?:organizing\s+claim|model|framework|construct)",
    re.I,
)


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def _asks_tension_series(text: str) -> bool:
    return "tension" in text and any(token in text for token in ("renumber", "coherent 1 n", "correct ordinal"))


def _asks_claim_total(text: str) -> bool:
    return "claim" in text and "total" in text and any(
        token in text for token in ("reconcile", "internally consistent", "externally verifiable", "per source sums")
    )


def _asks_endpoint_tensions(text: str) -> bool:
    return "severity 4" in text and "tension" in text and any(
        token in text for token in ("per endpoint", "coding artifact", "per source direction")
    )


def _asks_framework_cleanup(text: str) -> bool:
    return (
        "framework" in text
        and any(token in text for token in ("remove", "rephrase", "unsupported organizing claim"))
        and any(token in text for token in ("metabolic functional tradeoff", "unsupported organizing claim"))
    )


def _asks_substantive_background(text: str) -> bool:
    return "background" in text and any(
        token in text for token in ("substantive", "biological", "clinical rationale", "before the methodological")
    )


def ask_known(ask: str, _rows: Sequence[dict[str, Any]] | None = None) -> bool:
    text = _normalise(ask)
    return any(check(text) for check in (
        _asks_tension_series, _asks_claim_total, _asks_endpoint_tensions,
        _asks_framework_cleanup, _asks_substantive_background,
    ))


def _section_span(paper_md: str, heading: str, level: int = 2) -> tuple[int, int] | None:
    match = re.search(rf"^#{{{level}}}\s+{re.escape(heading)}[ \t]*$", paper_md, re.M | re.I)
    if not match:
        return None
    tail = paper_md[match.end():]
    next_heading = re.search(rf"^#{{1,{level}}}\s+", tail, re.M)
    return match.end(), match.end() + (next_heading.start() if next_heading else len(tail))


def _upsert_section_note(paper_md: str, heading: str, marker: str, note: str) -> tuple[str, int]:
    span = _section_span(paper_md, heading)
    if not span:
        return paper_md, 0
    start, end = span
    existing = re.search(rf"^{re.escape(marker)}.*$", paper_md[start:end], re.M)
    if existing:
        left, right = start + existing.start(), start + existing.end()
        return (
            (paper_md, 0) if existing.group(0) == note
            else (paper_md[:left] + note + paper_md[right:], 1)
        )
    return paper_md[:start] + "\n\n" + note + paper_md[start:], 1


def _repair_tension_series(paper_md: str) -> tuple[str, int]:
    span = _section_span(paper_md, "Cross-Domain Synthesis")
    if not span:
        return paper_md, 0
    start, end = span
    parts = re.split(r"(\n\s*\n)", paper_md[start:end])
    index = changed = 0
    for pos in range(0, len(parts), 2):
        if not _TENSION_LEAD_RE.match(parts[pos].strip()) or index >= len(_ORDINALS):
            continue
        lead = "The first" if index == 0 else f"A {_ORDINALS[index]}"
        fixed = _TENSION_LEAD_RE.sub(lead, parts[pos].strip(), count=1)
        if fixed != parts[pos].strip():
            parts[pos], changed = fixed, changed + 1
        index += 1
    return paper_md[:start] + "".join(parts) + paper_md[end:], changed


def _tension_series_is_stated(paper_md: str) -> bool:
    span = _section_span(paper_md, "Cross-Domain Synthesis")
    if not span:
        return False
    leads = [
        match.group(0).lower().removeprefix("the ").removeprefix("a ")
        for part in re.split(r"\n\s*\n", paper_md[span[0]:span[1]])
        if (match := _TENSION_LEAD_RE.match(part.strip()))
    ]
    return bool(leads) and leads == list(_ORDINALS[:len(leads)])


def _claim_total(rows: Sequence[dict[str, Any]]) -> int:
    return sum(int(row.get("n_claims") or 0) for row in rows)


def _claim_total_note(rows: Sequence[dict[str, Any]]) -> str:
    return (
        f"Claim-count reconciliation: The authoritative all-corpus total is {_claim_total(rows)} "
        f"high-confidence extracted claims, computed from extracted-claim counts across {len(rows)} "
        "included sources; outcome slices partition this total and are not additional claims."
    )


def _repair_claim_totals(paper_md: str, rows: Sequence[dict[str, Any]]) -> tuple[str, int]:
    total = _claim_total(rows)
    if not total:
        return paper_md, 0
    changed = 0

    def replace_total(match: re.Match[str]) -> str:
        nonlocal changed
        if int(match.group(0).replace(",", "")) != total:
            changed += 1
        return str(total)

    patched = re.sub(
        r"\b\d[\d,]*(?=\s+high-confidence extracted claims\b)", replace_total, paper_md,
    )
    patched = re.sub(
        r"(?<=retained sources, )\d[\d,]*(?=\s+extracted claims\b)", replace_total, patched,
    )
    heading = "Evidence Landscape" if _section_span(patched, "Evidence Landscape") else "Background"
    patched, n = _upsert_section_note(
        patched, heading, "Claim-count reconciliation:", _claim_total_note(rows),
    )
    return patched, changed + n


def _claim_total_is_stated(paper_md: str, rows: Sequence[dict[str, Any]]) -> bool:
    total = _claim_total(rows)
    values = {
        int(value.replace(",", ""))
        for value in re.findall(r"\b(\d[\d,]*)\s+high-confidence extracted claims\b", paper_md, re.I)
    }
    return bool(total and _claim_total_note(rows) in paper_md and (not values or values == {total}))


def _tension_summary_row(row: dict[str, Any], index: int) -> ReceiptSummary:
    directions = endpoint_direction_map(row.get("endpoint_directions"), (), None)
    return ReceiptSummary(
        receipt_id=f"{index:04d}",
        receipt_path="",
        topic="",
        thesis_text="",
        spar_verdict="accept_clean",
        n_claims=int(row.get("n_claims") or 0),
        n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier=str(row.get("evidence_tier") or ""),
        directness=effective_directness(row),
        outcome_class=cast(OutcomeClass, _normalise(str(row.get("outcome_class") or "contextual_other"))),
        effect_direction="unclear",
        p_values=(),
        population_summary=str(row.get("population_summary") or ""),
        endpoint_directions=tuple(directions.items()),
    )


def _endpoint_tension_lines(rows: Sequence[dict[str, Any]], limit: int = 8) -> list[str]:
    summaries = [_tension_summary_row(row, index) for index, row in enumerate(rows, start=1)]
    by_id = {summary.receipt_id: (index, rows[index - 1]) for index, summary in enumerate(summaries, start=1)}
    candidates: list[tuple[int, str, str]] = []
    for tension in build_tension_matrix(summaries).pairs:
        if tension.severity < 4 or not tension.endpoint:
            continue
        left_i, left = by_id[tension.receipt_a_id]
        right_i, right = by_id[tension.receipt_b_id]
        if any(derive_receipt_lane(row) == "animal_preclinical" for row in (left, right)):
            continue
        left_label = str(left.get("citation_token") or left.get("receipt_id") or "source").strip()
        right_label = str(right.get("citation_token") or right.get("receipt_id") or "source").strip()
        left_map = endpoint_direction_map(left.get("endpoint_directions"), (), None)
        right_map = endpoint_direction_map(right.get("endpoint_directions"), (), None)
        left_direction = cast(EffectDirection, left_map[tension.endpoint])
        right_direction = cast(EffectDirection, right_map[tension.endpoint])
        line = (
            f"- Severity {tension.severity} {tension.kind.replace('_', ' ')}: "
            f"{left_label} [bundle:{left_i}] vs {right_label} [bundle:{right_i}]; "
            f"{left_direction} versus {right_direction} on {tension.endpoint} - endpoint-coded conflict."
        )
        candidates.append((-tension.severity, f"{tension.endpoint}:{left_label}:{right_label}".casefold(), line))
    return [line for _rank, _key, line in sorted(candidates)[:limit]]


def _endpoint_tension_section(rows: Sequence[dict[str, Any]]) -> str:
    lines = _endpoint_tension_lines(rows)
    section = "### Load-Bearing Tensions\n\n" + _TENSION_AUDIT
    section += "\n\n" + ("\n".join(lines) if lines else "- No endpoint-coded severity-4 tension is retained.")
    return section


def _repair_endpoint_tensions(
    paper_md: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    match = re.search(
        r"^### Load-Bearing Tensions\b.*?(?=^### |^## |\Z)", paper_md, re.M | re.S | re.I,
    )
    if not match:
        return paper_md, 0
    section = _endpoint_tension_section(rows)
    return (
        (paper_md, 0) if match.group(0).strip() == section.strip()
        else (paper_md[:match.start()] + section + "\n\n" + paper_md[match.end():], 1)
    )


def _endpoint_tensions_are_stated(paper_md: str, rows: Sequence[dict[str, Any]]) -> bool:
    match = re.search(
        r"^### Load-Bearing Tensions\b.*?(?=^### |^## |\Z)", paper_md, re.M | re.S | re.I,
    )
    return bool(match and match.group(0).strip() == _endpoint_tension_section(rows).strip())


def _repair_framework(paper_md: str) -> tuple[str, int]:
    body, separator, references = paper_md.partition("\n## References")
    body, removed = _FRAMEWORK_HEADING_RE.subn("", body, count=1)
    body, rephrased = _FRAMEWORK_RE.subn(_FRAMEWORK_REPLACEMENT, body)
    body, proposals = _FRAMEWORK_PROPOSAL_RE.subn(
        f"The paper describes a {_FRAMEWORK_REPLACEMENT}",
        body,
    )
    body, claims = _FRAMEWORK_NOVELTY_RE.subn(
        r"\1 as a descriptive source-map comparison",
        body,
    )
    heading = "Discussion" if _section_span(body, "Discussion") else "Cross-Domain Synthesis"
    body, added = _upsert_section_note(body, heading, "Framework boundary:", _FRAMEWORK_NOTE)
    return (
        body + (separator + references if separator else ""),
        removed + rephrased + proposals + claims + added,
    )


def _row_endpoints(row: dict[str, Any]) -> tuple[object, ...]:
    values = row.get("endpoints")
    if isinstance(values, list):
        return tuple(value for value in values if value)
    value = row.get("endpoint")
    return (value,) if value else ()


def _background_note(paper_md: str, rows: Sequence[dict[str, Any]]) -> str:
    human = [row for row in rows if derive_receipt_lane(row) != "animal_preclinical"]
    endpoints = list(dict.fromkeys(
        _normalise(str(endpoint))
        for row in human for endpoint in _row_endpoints(row)
    ))[:5]
    populations = list(dict.fromkeys(
        str(row.get("population_summary") or "").strip()
        for row in human if str(row.get("population_summary") or "").strip()
    ))[:3]
    anchors = [
        f"{str(row.get('citation_token') or row.get('receipt_id') or 'source').strip()} [bundle:{index}]"
        for index, row in enumerate(rows, start=1)
        if derive_receipt_lane(row) != "animal_preclinical"
        and str(row.get("directness") or "").lower().startswith("direct")
    ][:3]
    return (
        "Substantive background rationale: The retained human evidence tests "
        f"{', '.join(endpoints) or 'clinical and functional endpoints'} in "
        f"{', '.join(populations) or 'the represented study populations'} "
        f"({'; '.join(anchors) or 'see the Findings Map'}). The clinical rationale is to determine "
        "whether proximal biomarker or body-composition changes translate into durable functional, safety, "
        "or hard-outcome benefit; animal and mechanistic evidence is used only to explain plausibility."
    )


def _repair_background(paper_md: str, rows: Sequence[dict[str, Any]]) -> tuple[str, int]:
    note = _background_note(paper_md, rows)
    return _upsert_section_note(paper_md, "Background", "Substantive background rationale:", note)


def proof_is_stated(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> bool:
    text = _normalise(ask)
    body = paper_md.partition("\n## References")[0]
    checks = (
        (_asks_tension_series, _tension_series_is_stated(paper_md)),
        (_asks_claim_total, _claim_total_is_stated(paper_md, rows)),
        (_asks_endpoint_tensions, _endpoint_tensions_are_stated(paper_md, rows)),
        (_asks_framework_cleanup, not _FRAMEWORK_RE.search(body)
         and not _FRAMEWORK_PROPOSAL_RE.search(body)
         and not _FRAMEWORK_NOVELTY_RE.search(body)
         and _FRAMEWORK_NOTE in body),
        (_asks_substantive_background, _background_note(paper_md, rows) in paper_md),
    )
    return all(not matches(text) or passed for matches, passed in checks)


def repair(
    paper_md: str, rows: Sequence[dict[str, Any]], feedback: str,
) -> tuple[str, list[str]]:
    lower, patched, details = _normalise(feedback), paper_md, []
    for predicate, repairer, detail in (
        (_asks_tension_series, lambda text: _repair_tension_series(text), "tension_series"),
        (_asks_claim_total, lambda text: _repair_claim_totals(text, rows), "claim_total_reconciliation"),
        (_asks_endpoint_tensions, lambda text: _repair_endpoint_tensions(text, rows), "endpoint_tension_recompute"),
        (_asks_framework_cleanup, lambda text: _repair_framework(text), "framework_cleanup"),
        (_asks_substantive_background, lambda text: _repair_background(text, rows), "substantive_background"),
    ):
        if predicate(lower):
            patched, changed = repairer(patched)
            if changed:
                details.append(detail)
    return patched, details
