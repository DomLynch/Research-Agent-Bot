"""Deterministic manuscript-consistency repairs requested by reviewers."""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from agent import reviewer_consistency_repairs as _reviewer_repairs
from agent.endpoint_evidence import endpoint_direction_map
from agent.evidence_lanes import derive_receipt_lane, effective_directness
from agent.outcome_class_remap import outcome_display
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
_P_VALUE_RE = re.compile(r"\bp\s*(<=|>=|<|>|=|≤|≥)\s*(0?\.\d+|1(?:\.0+)?)", re.I)
_REPLACEMENT_CUE_RE = re.compile(
    r"\b(?:(?:bundled?|source(?:\s+bundle)?)\s+)?excerpt\s+(?:shows?|reports?|contains?|lists?|states?|gives?)\b",
    re.I,
)
_FRAMEWORK_NOVELTY_RE = re.compile(
    rf"({re.escape(_FRAMEWORK_REPLACEMENT)})\s+as\s+(?:a\s+)?"
    r"(?:(?:novel|new|original)\s+)?(?:organizing\s+claim|model|framework|construct)",
    re.I,
)
_DECISION_GRADE_MARKER = "Decision-grade answer:"
_DIRECTNESS_FLOW_MARKER = "Directness-flow clarification:"
_GENERIC_OUTCOME_TOKENS = frozenset({"and", "evidence", "other", "outcome", "slice"})
_DIRECTION_ORDER = ("positive", "negative", "null", "mixed", "unclear")


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def _p_key(text: str) -> tuple[str, float] | None:
    match = _P_VALUE_RE.search(text)
    return ({"≤": "<=", "≥": ">="}.get(match.group(1), match.group(1)), float(match.group(2))) if match else None


def _replacement_parts(ask: str) -> tuple[str, str]:
    match = _REPLACEMENT_CUE_RE.search(ask)
    return (ask[:match.start()], ask[match.end():]) if match else ("", "")


def preferred_replacement_statistics(ask: str, supported: Sequence[str]) -> tuple[str, ...]:
    before, after = _replacement_parts(ask)
    disputed = {_p_key(match.group()) for match in _P_VALUE_RE.finditer(before)} if after else set()
    by_key = {_p_key(stat): stat for stat in supported if _p_key(stat)}
    preferred = [by_key[key] for match in _P_VALUE_RE.finditer(after)
                 if (key := _p_key(match.group())) in by_key]
    return tuple(dict.fromkeys(preferred + [
        stat for stat in supported if _p_key(stat) not in disputed
    ]))


def _nearest_source(text: str, at: int, labels: Sequence[str]) -> str:
    start = max(text.rfind(token, 0, at) for token in ("\n", ". ", "! ", "? ")) + 1
    ends = [pos for token in ("\n", ". ", "! ", "? ") if (pos := text.find(token, at)) >= 0]
    scope, local_at = text[start:min(ends, default=len(text))], at - start
    found = [
        (abs(match.start() - local_at), match.start() > local_at, label.lower())
        for label in labels for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", scope, re.I)
    ]
    return min(found)[2] if found else ""


def disputed_p_value_near_sources(
    ask: str, paper_md: str, labels: Sequence[str], all_labels: Sequence[str],
) -> bool:
    before, after = _replacement_parts(ask)
    disputed = {_p_key(match.group()) for match in _P_VALUE_RE.finditer(before)} if after else set()
    targets = {label.lower() for label in labels}
    return bool(disputed) and any(
        _p_key(match.group()) in disputed
        and _nearest_source(paper_md, match.start(), all_labels) in targets
        for match in _P_VALUE_RE.finditer(paper_md)
    )


def remove_disputed_p_values_near_sources(
    ask: str, paper_md: str, labels: Sequence[str], all_labels: Sequence[str],
) -> str:
    before, after = _replacement_parts(ask)
    disputed = {_p_key(match.group()) for match in _P_VALUE_RE.finditer(before)} if after else set()
    targets = {label.lower() for label in labels}
    return _P_VALUE_RE.sub(
        lambda match: "a source-reported estimate"
        if _p_key(match.group()) in disputed
        and _nearest_source(paper_md, match.start(), all_labels) in targets else match.group(),
        paper_md,
    )


def repair_structured_evidence_revision_p_values(
    out_dir: Path, manifest: dict[str, Any],
) -> int:
    path = out_dir / "structured_evidence_tables.md"
    request_path = out_dir / "researka_revision_request.json"
    if not path.is_file() or not request_path.is_file():
        return 0
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(request, dict):
        return 0
    required = request.get("required_revisions")
    asks = (
        [str(item) for item in required if str(item).strip()]
        if isinstance(required, list)
        else re.split(r";\s+(?=[A-Z])", str(request.get("feedback") or ""))
    )
    sources = tuple(
        (row, label)
        for row in manifest.get("receipts", ()) if isinstance(row, dict)
        if (label := str(row.get("citation_token") or row.get("cited_as")
            or row.get("body_citation") or row.get("receipt_id") or "").strip())
    )
    labels = tuple(label for _, label in sources)
    text, changed = path.read_text(encoding="utf-8"), 0
    for ask in asks:
        ask_key = _normalise(re.sub(r"\bet\s+al\.?", "", ask, flags=re.I))
        targets = tuple(
            label for row, label in sources
            if label and any(
                value and _normalise(re.sub(r"\bet\s+al\.?", "", value, flags=re.I)) in ask_key
                for value in (label, str(row.get("source_title") or "").strip())
            )
        )
        repaired = remove_disputed_p_values_near_sources(
            ask, text, targets, labels,
        )
        if repaired != text:
            text, changed = repaired, changed + 1
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


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


def _asks_decision_grade_answer(text: str) -> bool:
    return (
        "decision grade" in text
        and "direct evidence" in text
        and ("research question" in text or "direct answer" in text)
        and any(token in text for token in ("condition", "state explicitly", "whether"))
    )


def _asks_exclusion_directness_reconciliation(text: str) -> bool:
    return (
        "exclusion" in text
        and any(token in text for token in ("indirect", "adjacent", "directness"))
        and any(token in text for token in ("reconcile", "classification", "rephrase", "down weighting"))
    )


def ask_known(ask: str, _rows: Sequence[dict[str, Any]] | None = None) -> bool:
    text = _normalise(ask)
    return any(check(text) for check in (
        _asks_tension_series, _asks_claim_total, _asks_endpoint_tensions,
        _asks_framework_cleanup, _asks_substantive_background, _asks_decision_grade_answer,
        _asks_exclusion_directness_reconciliation,
    )) or _reviewer_repairs.ask_known(ask, _rows)


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
    body, separator, references = paper_md.partition("\n## References")
    parts = re.split(r"(\n\s*\n)", body)
    index = changed = 0
    for pos in range(0, len(parts), 2):
        if not _TENSION_LEAD_RE.match(parts[pos].strip()) or index >= len(_ORDINALS):
            continue
        lead = "The first" if index == 0 else f"A {_ORDINALS[index]}"
        fixed = _TENSION_LEAD_RE.sub(lead, parts[pos].strip(), count=1)
        if fixed != parts[pos].strip():
            parts[pos], changed = fixed, changed + 1
        index += 1
    return "".join(parts) + separator + references, changed


def _tension_series_is_stated(paper_md: str) -> bool:
    body = paper_md.partition("\n## References")[0]
    leads = [
        match.group(0).lower().removeprefix("the ").removeprefix("a ")
        for part in re.split(r"\n\s*\n", body)
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


def _decision_grade_rows(
    ask: str, rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    ask_tokens = set(_normalise(ask).split())
    scoped = [
        row for row in rows
        if (
            set(_normalise(str(row.get("outcome_class") or "").replace("_", " ")).split())
            - _GENERIC_OUTCOME_TOKENS
        ) & ask_tokens
    ]
    return scoped or list(rows)


def _decision_grade_note(ask: str, rows: Sequence[dict[str, Any]]) -> str:
    scoped = _decision_grade_rows(ask, rows)
    direct = [row for row in scoped if effective_directness(row) == "direct"]
    directions = Counter(
        value if value in _DIRECTION_ORDER else "unclear"
        for row in direct
        for value in (_normalise(str(row.get("effect_direction") or "unclear")),)
    )
    ordered_directions = [
        f"{name}={directions[name]}"
        for name in _DIRECTION_ORDER
        if directions[name]
    ]
    outcomes = list(dict.fromkeys(
        re.sub(
            r"\s+evidence$", "",
            outcome_display(str(row.get("outcome_class") or "contextual_other")),
            flags=re.I,
        )
        for row in scoped
    ))
    populations = [
        value for value, _count in Counter(
            " ".join(str(row.get("population_summary") or "").split())[:100]
            for row in direct if str(row.get("population_summary") or "").strip()
        ).most_common(3)
    ]
    scope = " and ".join(outcomes[:3]).lower() or "reviewed"
    clear_directions = [name for name in ("positive", "negative", "null") if directions[name]]
    convergence = (
        f"The direct sources converge on a source-bounded {clear_directions[0]} direction"
        if len(clear_directions) == 1 and not directions["mixed"] and not directions["unclear"]
        else "The direct sources do not converge on one decision-grade direction"
    )
    return (
        f"{_DECISION_GRADE_MARKER} No broad decision-grade conclusion is supported for the "
        f"{scope} evidence slice. The retained slice contains "
        f"{len(direct)}/{len(scoped)} direct sources; direct-source direction codes are "
        f"{', '.join(ordered_directions) or 'none'}. {convergence}. Interpretation is conditional on "
        f"the represented populations ({', '.join(populations) or 'not consistently reported'}), "
        "study designs, measured endpoints, and follow-up windows. Indirect, review-level, "
        "mechanistic, and contextual sources bound interpretation and do not upgrade clinical actionability."
    )


def _repair_decision_grade_answer(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    heading = "Conclusion" if _section_span(paper_md, "Conclusion") else "Research Question"
    return _upsert_section_note(
        paper_md, heading, _DECISION_GRADE_MARKER, _decision_grade_note(ask, rows),
    )


def _directness_flow_note(paper_md: str, rows: Sequence[dict[str, Any]]) -> str:
    excluded = re.search(r"\b(\d+)\s+were excluded at full-text review\b", paper_md, re.I)
    non_direct = sum(effective_directness(row) != "direct" for row in rows)
    exclusion_text = f"{excluded.group(1)} full-text exclusions" if excluded else "the reported full-text exclusions"
    return (
        f"{_DIRECTNESS_FLOW_MARKER} All {len(rows)} retained sources remain in the descriptive "
        f"map; {non_direct}/{len(rows)} are classified as indirect, review-level, adjacent, "
        "mechanistic, or contextual and are down-weighted for causal interpretation, not excluded "
        f"from source admission. {exclusion_text} and the {non_direct}/{len(rows)} non-direct "
        "classification describe different stages and are not contradictory."
    )


def _repair_directness_flow(
    paper_md: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    return _upsert_section_note(
        paper_md, "Methods", _DIRECTNESS_FLOW_MARKER, _directness_flow_note(paper_md, rows),
    )


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
        (_asks_decision_grade_answer, _decision_grade_note(ask, rows) in paper_md),
        (_asks_exclusion_directness_reconciliation, _directness_flow_note(paper_md, rows) in paper_md),
    )
    return (
        all(not matches(text) or passed for matches, passed in checks)
        and _reviewer_repairs.proof_is_stated(paper_md, ask, rows)
    )


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
        (_asks_exclusion_directness_reconciliation,
         lambda text: _repair_directness_flow(text, rows), "directness_flow_reconciliation"),
    ):
        if predicate(lower):
            patched, changed = repairer(patched)
            if changed:
                details.append(detail)
    decision_ask = next((
        part.strip() for part in re.split(r";\s+", feedback)
        if _asks_decision_grade_answer(_normalise(part))
    ), "")
    if decision_ask:
        patched, changed = _repair_decision_grade_answer(patched, decision_ask, rows)
        if changed:
            details.append("decision_grade_answer")
    patched, reviewer_details = _reviewer_repairs.repair(patched, rows, feedback)
    details.extend(detail for detail in reviewer_details if detail not in details)
    return patched, details
