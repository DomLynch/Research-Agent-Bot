"""Deterministic repair and proof for recurring reviewer-quality revisions."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from agent.outcome_class_remap import outcome_display, refine_other_outcome_class
from agent.publication_evidence import attach_bundle_references, ordered_source_rows
from agent.revision_claim_trace import asks_major_claim_trace, major_claim_trace_is_stated, repair_major_claim_trace
from agent.revision_identity import (
    direction_attribution_is_stated,
    direction_attribution_requested,
    review_role_contradiction,
)


_EFFECT_STAT_RE = re.compile(
    r"\b(?:HR|OR|RR|NNT)\s*(?:=|:)?\s*\d+(?:\.\d+)?"
    r"|\b(?:95\s*%\s*)?(?:CI|confidence interval)\s*[:=]?\s*"
    r"\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?"
    r"|\bp\s*(?:<|>|=|≤|≥)\s*(?:0?\.\d+|1(?:\.0+)?)"
    r"|\b\d+(?:\.\d+)?\s*%(?!\w)",
    re.I,
)
_STRONG_CLAIM_RE = re.compile(
    r"\bdefinitive\s+(?:evidence|proof|clinical benefit|benefit)\b"
    r"|\bproves?\b.{0,60}\b(?:benefit|causal|clinical|longer life|mortality|survival)\b"
    r"|\b(?:establish(?:es|ed)?|demonstrat(?:es|ed))\b.{0,60}\b(?:causal|clinical benefit|longer life)\b"
    r"|\b(?:caus(?:e[sd]?|ing)|led to|results? in)\b.{0,60}\b(?:benefit|longer life|live[sd]? longer|mortality|survival)\b"
    r"|\bextend(?:s|ed|ing)?\b.{0,40}\b(?:life\s*span|lifespan|survival|life expectancy)\b"
    r"|\bimprov(?:e[sd]?|ing)\b.{0,40}\b(?:longer life|mortality|survival)\b"
    r"|\bconverges? on the same directional finding\b"
    r"|\bsignificantly reduced\b.{0,40}\b(?:mortality|risk|disease|symptoms?|events?|hospitali[sz]ation)\b"
    r"|\banchors? the upper bound of the [^.]{0,50}signal\b",
    re.I,
)
_SUBSET_NOTE = (
    "Narrative coverage scope: The Findings Map enumerates every admitted source. "
    "Outcome prose discusses a representative subset to avoid repetitive source-by-source narration; "
    "mapped rows omitted from prose remain in the auditable accounting and are not treated as excluded."
)
_LEGACY_SOURCE_SIGNIFICANCE_NOTE_RE = re.compile(
    r"^\s*(?:[*_]{1,3})?Numeric (?:verification|reconciliation) note:"
    r"(?:[*_]{1,3})?\s*[A-Z][^\n]{0,400}"
    r"\b(?:statistically significant|non-significant|not significant|significance threshold)\b",
    re.I,
)


def revision_quality_ask_known(ask: str, evidence_rows: Sequence[dict[str, Any]] | None = None) -> bool:
    lower = _normalise(ask)
    return any(check(lower) for check in (
        _asks_outcome_roster, _asks_exact_stat_trace, asks_major_claim_trace,
        _asks_fragment_cleanup,
        _asks_representative_subset, _asks_evidence_role_reconciliation,
        _asks_evidence_honesty, _asks_named_direction_reconciliation,
        _asks_named_statistic_reconciliation,
    )) or _asks_named_topic_fit_boundary(lower) and _topic_fit_is_deterministic(
        ask, _ordered_rows(evidence_rows or ()),
    )


def asks_exact_stat_trace(feedback: str) -> bool:
    return _asks_exact_stat_trace(_normalise(feedback))


def revision_quality_proof_is_stated(
    paper_md: str,
    ask: str,
    evidence_rows: Sequence[dict[str, Any]] | None,
) -> bool:
    lower = _normalise(ask)
    rows = _ordered_rows(evidence_rows or ())
    checks = (
        (_asks_outcome_roster, lambda: _findings_map_is_exact(paper_md, rows)),
        (_asks_exact_stat_trace, lambda: _statistics_are_source_bound(paper_md, rows)),
        (asks_major_claim_trace, lambda: major_claim_trace_is_stated(paper_md, ask, rows)),
        (_asks_fragment_cleanup, lambda: _reviewed_fragments_are_absent(paper_md, ask)),
        (_asks_representative_subset, lambda: _subset_scope_is_stated(paper_md, rows)),
        (_asks_evidence_role_reconciliation, lambda: _evidence_roles_are_reconciled(paper_md, ask, rows)),
        (_asks_evidence_honesty, lambda: _evidence_honesty_is_stated(paper_md, ask, rows)),
        (_asks_named_direction_reconciliation, lambda: _named_revision_is_stated(paper_md, ask, rows, "direction")),
        (_asks_named_statistic_reconciliation, lambda: _named_revision_is_stated(paper_md, ask, rows, "statistic")),
        (_asks_named_topic_fit_boundary, lambda: not _topic_fit_is_deterministic(ask, rows)
         or _named_revision_is_stated(paper_md, ask, rows, "topic_fit")),
    )
    return all(not matches(lower) or satisfied() for matches, satisfied in checks)


def repair_revision_quality(
    paper_md: str,
    evidence_rows: Sequence[dict[str, Any]],
    feedback: str,
) -> tuple[str, list[str]]:
    lower = _normalise(feedback)
    rows = _ordered_rows(evidence_rows)
    patched = paper_md
    details: list[str] = []
    if _asks_exact_stat_trace(lower):
        patched, changed = _repair_untraceable_statistics(patched, rows)
        if changed:
            details.append("exact_stat_trace")
    if asks_major_claim_trace(lower):
        patched, changed = repair_major_claim_trace(patched, feedback, rows)
        if changed:
            details.append("major_claim_trace")
    for predicate, kind, detail in (
        (_asks_named_direction_reconciliation, "direction", "named_direction_reconciliation"),
        (_asks_named_statistic_reconciliation, "statistic", "named_statistic_reconciliation"),
        (_asks_named_topic_fit_boundary, "topic_fit", "named_topic_fit_boundary"),
    ):
        changed = 0
        for ask in _feedback_parts(feedback):
            if predicate(_normalise(ask)):
                patched, n = _repair_named_revision(patched, ask, rows, kind)
                changed += n
        if changed:
            details.append(detail)
    if _asks_fragment_cleanup(lower):
        patched, changed = _repair_fragmentary_prose(patched, feedback)
        if changed:
            details.append("fragmentary_prose")
    if _asks_outcome_roster(lower) or _asks_representative_subset(lower):
        patched, changed = _add_subset_scope(patched)
        if changed:
            details.append("representative_subset_scope")
    role_ask = _matching_feedback(feedback, _asks_evidence_role_reconciliation)
    if role_ask:
        patched, changed = _reconcile_evidence_roles(patched, role_ask, rows)
        if changed:
            details.append("evidence_role_reconciliation")
    honesty_ask = _matching_feedback(feedback, _asks_evidence_honesty)
    if honesty_ask:
        patched, changed = _bound_named_outcomes(patched, honesty_ask, rows)
        if changed:
            details.append("outcome_evidence_honesty")
    return patched, details


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def _ordered_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    values = list(rows)
    return ordered_source_rows(values, {
        str(row.get("receipt_id") or ""): row for row in values
    })


def receipt_direction(row: dict[str, Any]) -> str:
    raw = str(row.get("effect_direction") or "unclear").strip().lower()
    for direction in ("positive", "negative", "mixed", "null", "unclear"):
        if direction in raw:
            return direction
    return "unclear"


def manifest_row_finding(row: dict[str, Any]) -> str:
    stat = next(iter(traceable_p_values(row)), "")
    if stat:
        relation = next(iter(_p_relations(stat)), None)
        nonsignificant = bool(relation and (
            relation[0] in {">", ">="} and float(relation[1]) >= 0.05
            or relation[0] == "=" and float(relation[1]) > 0.05
        ))
        prefix = "representative non-significant statistic" if nonsignificant else "representative statistic"
        suffix = (
            "; not treated as positive or negative directional support unless source direction is coded"
            if nonsignificant else "; source-level statistic reported"
        )
        return f"{prefix} {stat}{suffix}"
    claims = row.get("n_claims")
    if isinstance(claims, int) and claims > 0:
        return f"{claims} extracted claim(s); receipt-level direction is the coded finding"
    return "qualitative receipt-level finding recorded in the manifest"


def findings_map_row(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    outcome = _findings_map_outcome(row)
    direction = resolved_effect_direction(row)
    citation = _label(row)
    title = str(row.get("source_title") or "").strip()
    source = f"{citation}: {title}" if citation and title and citation not in title else (citation or title)
    return (
        outcome, source, f"direction={direction}",
        f"directness={str(row.get('directness') or 'unknown').strip().lower()}",
        str(row.get("evidence_tier") or "unknown").strip(),
        f"outcome={_findings_map_role_outcome(row, outcome)}; direction={direction}",
        f"finding={manifest_row_finding(row)}",
    )


def _findings_map_outcome(row: dict[str, Any]) -> str:
    current = str(row.get("outcome_class") or "contextual_other").strip() or "contextual_other"
    receipt = SimpleNamespace(
        receipt_id=row.get("receipt_id"), source_title=row.get("source_title"),
        population_summary=row.get("population_summary"), directness=row.get("directness"),
    )
    return outcome_display(refine_other_outcome_class(receipt, current))


def _findings_map_role_outcome(row: dict[str, Any], outcome: str) -> str:
    directness = str(row.get("directness") or "").strip().lower()
    if directness.startswith("direct"):
        return outcome
    scope = " ".join(str(row.get(key) or "") for key in (
        "source_title", "outcome_class", "endpoint", "population_summary", "evidence_type",
    )).lower()
    model = _model_context(scope)
    if "mechanistic" in directness or "mechanism" in scope or model:
        label = outcome if outcome == "Mechanism" else f"Mechanism/{outcome}"
        return f"{label} ({model})" if model and model.lower() not in label.lower() else label
    if any(token in scope for token in (
        "biomarker", "marker", "blood-based", "serum", "plasma", "8-ohdg", "8ohdg",
        "8-hydroxy", "mtdna", "mitochondrial dna", "deletion", "heteroplasmy",
        "telomere length", "dna methylation",
    )):
        return "Biomarker/Adjacent Evidence" if outcome in {"Contextual Adjacent Evidence", "Other"} else f"Biomarker/Adjacent {outcome}"
    return outcome


def _model_context(scope: str) -> str:
    for pattern, label in (
        (r"c\. elegans|caenorhabditis", "C. elegans"),
        (r"drosophila|\bfruit fl(?:y|ies)\b", "Drosophila"),
        (r"zebrafish", "zebrafish"), (r"\b(?:mouse|mice|murine)\b", "mouse"),
        (r"\b(?:rat|rats|rodent)\b", "rodent"),
        (r"\b(?:cell|cells|in vitro|organoid|ex vivo)\b", "cell/in vitro"),
        (r"animal|preclinical|model organism|model-system|model system", "animal/preclinical"),
    ):
        if re.search(pattern, scope):
            return label
    return ""


def _matching_feedback(feedback: str, predicate: Any) -> str:
    return " ".join(
        part for part in _feedback_parts(feedback) if predicate(_normalise(part))
    )


def _feedback_parts(feedback: str) -> list[str]:
    return [part.strip() for part in re.split(r";\s+(?=[A-Z])", feedback) if part.strip()]


def _asks_outcome_roster(text: str) -> bool:
    return "findings map" in text and "source bundle" in text and any(
        token in text for token in ("table counts", "lists all", "update counts", "actual source bundle")
    )


def _asks_exact_stat_trace(text: str) -> bool:
    return any(token in text for token in (
        "every exact statistic", "every exact p value", "exact p value",
        "every exact interval", "exact confidence interval", "exact bundle token",
        "effect estimate", "percentage cited",
    )) and any(
        token in text for token in (
            "bundle", "source excerpt", "source number", "trace", "verif",
            "extraction artifact",
        )
    )


def _asks_fragment_cleanup(text: str) -> bool:
    return any(token in text for token in (
        "fragmentary prose", "fragementary prose", "opening fragment", "opening comma",
        "ending mid sentence", "orphaned prose",
    ))


def _asks_representative_subset(text: str) -> bool:
    return "representative subset" in text or ("discuss all" in text and "sources" in text and "scope" in text)


def _asks_evidence_role_reconciliation(text: str) -> bool:
    return any(token in text for token in ("evidence_type", "evidence type")) and "directness" in text and any(
        token in text for token in ("clinical rct", "randomized", "randomised")
    )


def _asks_evidence_honesty(text: str) -> bool:
    return (
        "evidence honesty" in text
        and any(token in text for token in ("consistently reflected", "throughout", "directional confidence"))
    ) or ("pooled review estimates" in text and "directional confidence" in text)


def _asks_named_direction_reconciliation(text: str) -> bool:
    request = ("direction" in text and "consistent wording" in text) or all(
        token in text for token in ("coding", "align", "refers to"))
    return _has_named_source(text) and request and any(token in text for token in ("positive", "negative", "null", "mixed", "unclear"))


def _asks_named_statistic_reconciliation(text: str) -> bool:
    return (
        _has_named_source(text)
        and any(token in text for token in ("statistic", "p value", "p <", "p =", "effect estimate"))
        and any(token in text for token in ("if it is not present", "if not present", "not present in"))
        and any(token in text for token in ("bundle", "excerpt", "source", "trace"))
    )


def _asks_named_topic_fit_boundary(text: str) -> bool:
    return (
        _has_named_source(text)
        and any(token in text for token in ("justify inclusion", "included under", "topic fit", "topic-fit"))
        and "structural corpus limitation" in text
    )


def _has_named_source(text: str) -> bool:
    return re.search(r"\b[A-Z][A-Za-z'’.\-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", text, re.I) is not None


def _label(row: dict[str, Any]) -> str:
    return str(
        row.get("citation_token") or row.get("cited_as") or row.get("body_citation")
        or row.get("receipt_id") or ""
    ).strip()


def _findings_map(paper_md: str) -> str:
    matches = re.findall(r"^### Findings Map\b.*?(?=^### |^## |\Z)", paper_md, re.M | re.S | re.I)
    return matches[0] if len(matches) == 1 else ""


def _findings_map_is_exact(paper_md: str, rows: Sequence[dict[str, Any]]) -> bool:
    scope = _findings_map(paper_md)
    if not rows or f"all {len(rows)} admitted manifest rows" not in scope.lower():
        return False
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(findings_map_row(row)[0], []).append(row)
    for display, outcome_rows in grouped.items():
        directions = _count_text(receipt_direction(row) for row in outcome_rows)
        directness = _count_text(str(row.get("directness") or "unknown").strip().lower() for row in outcome_rows)
        labels = "; ".join(sorted((_label(row) for row in outcome_rows), key=str.casefold))
        roster = (
            f"{display} n={len(outcome_rows)} (direction: {directions}; "
            f"directness: {directness}; sources: {labels})"
        )
        if scope.casefold().count(roster.casefold()) != 1:
            return False
    table_rows = [_table_cells(line) for line in scope.splitlines()]
    table_rows = [cells for cells in table_rows if len(cells) == 7 and cells[0].lower() not in {"outcome class", "evidence domain"}]
    if len(table_rows) != len(rows):
        return False
    expected = Counter(tuple(value.casefold() for value in findings_map_row(row)) for row in rows)
    actual = Counter(tuple(value.casefold() for value in cells) for cells in table_rows)
    return actual == expected


def _count_text(values: Sequence[str] | Any) -> str:
    counts = Counter(values)
    return "; ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")] if line.startswith("|") and "---" not in line else []


def _prose_paragraphs(text: str) -> list[str]:
    return [
        part.strip() for part in re.split(r"\n\s*\n", text)
        if part.strip() and not part.lstrip().startswith(("#", "|", "```")) and "\n|" not in part
    ]


def _row_evidence(row: dict[str, Any]) -> str:
    return " ".join((
        str(row.get("thesis_text") or ""), str(row.get("source_title") or ""),
    ))


def traceable_p_values(row: dict[str, Any]) -> tuple[str, ...]:
    values = row.get("p_values")
    return tuple(
        value for raw in values if (value := str(raw).strip()) and _stat_supported(value, row)
    ) if isinstance(values, list) else ()


def _traceable_effect_statistics(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        match.group(0) for match in _EFFECT_STAT_RE.finditer(_row_evidence(row))
        if _stat_supported(match.group(0), row)
    ))


def resolved_effect_direction(row: dict[str, Any]) -> str:
    """Correct only a source-traceable harmful null-code contradiction."""
    raw = receipt_direction(row)
    if raw != "null":
        return raw
    scope = " ".join((str(row.get("source_title") or ""), str(row.get("thesis_text") or ""))).lower()
    harmful_increase = re.search(
        r"\b(?:higher|increas\w*|worsen\w*|accelerat\w*)\b.{0,50}"
        r"\b(?:damage|injury|risk|mortality|inflammation|toxicity|dysfunction)\b",
        scope,
    )
    significant = any(
        operator in {"<", "<="} or operator == "=" and float(value) < 0.05
        for stat in traceable_p_values(row) for operator, value in _p_relations(stat)
    )
    return "negative" if harmful_increase and significant else raw


def _numbers(text: str) -> tuple[str, ...]:
    values = [
        f"0{value}" if value.startswith(".") else value
        for value in re.findall(r"(?<![A-Za-z])(?:\d+\.\d+|\.\d+|\d+)", text)
    ]
    return tuple(value.rstrip("0").rstrip(".") if "." in value else value for value in values)


def _stat_supported(stat: str, row: dict[str, Any]) -> bool:
    evidence = _row_evidence(row).casefold().replace("–", "-")
    evidence_numbers = set(_numbers(evidence))
    metric = next((token for token in ("nnt", "hr", "or", "rr", "ci", "p", "%") if token in stat.casefold()), "")
    metric_present = metric == "%" and "%" in evidence or bool(metric and re.search(rf"\b{re.escape(metric)}\b", evidence))
    p_relations = _p_relations(stat)
    return (not p_relations or set(p_relations) <= set(_p_relations(evidence))) and metric_present and all(
        number in evidence_numbers
        for number in _numbers(stat) if number != "95" or metric != "ci"
    )


def _p_relations(text: str) -> tuple[tuple[str, str], ...]:
    operators = {"≤": "<=", "≥": ">="}
    return tuple(
        (operators.get(operator, operator), _numbers(value)[0])
        for operator, value in re.findall(r"\bp\s*(<=|>=|<|>|=|≤|≥)\s*(0?\.\d+|1(?:\.0+)?)", text, re.I)
    )


def _nearest_row(
    paragraph: str, stat_at: int, rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], int, int] | None:
    scan = re.sub(r"\bet al\.", lambda match: match.group(0)[:-1] + " ", paragraph, flags=re.I)
    starts = [match.end() for match in re.finditer(r"[.!?]\s+", scan[:stat_at])]
    sentence_start = starts[-1] if starts else 0
    end = re.search(r"[.!?](?:\s+|$)", scan[stat_at:])
    sentence_end = stat_at + end.end() if end else len(paragraph)
    found: list[tuple[int, int, dict[str, Any], int, int]] = []
    for index, row in enumerate(rows, start=1):
        label = _label(row)
        for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", paragraph, re.I) if label else ():
            if sentence_start <= match.start() < sentence_end:
                found.append((match.start() > stat_at, abs(match.start() - stat_at), row, index, match.end()))
    return (found[0][2], found[0][3], found[0][4]) if (found := sorted(found, key=lambda item: item[:2])) else None


def _stat_is_source_bound(paragraph: str, match: re.Match[str], rows: Sequence[dict[str, Any]]) -> bool:
    nearest = _nearest_row(paragraph, match.start(), rows)
    if not nearest:
        return False
    row, index, label_end = nearest
    marker = re.match(rf"(?:\](?:\([^)]+\))?)?\s*\[bundle:{index}\]", paragraph[label_end:], re.I)
    return marker is not None and _stat_supported(match.group(0), row)


def _statistics_are_source_bound(paper_md: str, rows: Sequence[dict[str, Any]]) -> bool:
    prose_ok = all(
        _stat_is_source_bound(paragraph, match, rows)
        for paragraph in _prose_paragraphs(paper_md) for match in _EFFECT_STAT_RE.finditer(paragraph)
    )
    table_ok = all(
        (row := _table_source_row(line, rows)) is not None
        and all(_stat_supported(match.group(0), row) for match in _EFFECT_STAT_RE.finditer(line))
        for line in _findings_map(paper_md).splitlines()
        if line.startswith("|") and _EFFECT_STAT_RE.search(line)
    )
    return prose_ok and table_ok


def _table_source_row(line: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    found = _named_rows(line, rows)
    return found[0] if len(found) == 1 else None


def _repair_findings_map_statistics(
    paper_md: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    scope = _findings_map(paper_md)
    if not scope:
        return paper_md, 0
    lines = scope.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.startswith("|") or not _EFFECT_STAT_RE.search(line):
            continue
        row = _table_source_row(line, rows)
        lines[index] = _EFFECT_STAT_RE.sub(
            lambda match: match.group(0)
            if row and _stat_supported(match.group(0), row)
            else "a source-reported estimate",
            line,
        )
    fixed = "".join(lines)
    return (paper_md, 0) if fixed == scope else (paper_md.replace(scope, fixed, 1), 1)


def _soften_statistics(paragraph: str) -> str:
    paragraph = re.sub(
        r"\([^()\n]{0,220}\)",
        lambda match: "" if _EFFECT_STAT_RE.search(match.group(0)) else match.group(0),
        paragraph,
    )
    paragraph = _EFFECT_STAT_RE.sub("a source-reported estimate", paragraph)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.;:])", r"\1", paragraph))


def _repair_untraceable_statistics(
    paper_md: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    paper_md, changed = _repair_findings_map_statistics(paper_md, rows)
    parts = re.split(r"(\n\s*\n)", paper_md)
    for index in range(0, len(parts), 2):
        original = parts[index]
        if (
            original.lstrip().startswith("Source-statistic reconciliation (")
            or original.strip() not in _prose_paragraphs(original)
        ):
            continue
        paragraph = attach_bundle_references(original, rows)
        matches = list(_EFFECT_STAT_RE.finditer(paragraph))
        has_unbound = any(
            not _stat_is_source_bound(paragraph, match, rows) for match in matches
        )
        if _LEGACY_SOURCE_SIGNIFICANCE_NOTE_RE.search(original) and (
            not matches or has_unbound
        ):
            fixed = ""
        elif not matches:
            continue
        else:
            fixed = _soften_statistics(paragraph) if has_unbound else paragraph
        if fixed != original:
            parts[index], changed = fixed, changed + 1
    return "".join(parts), changed


def _fragmentary(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped or stripped.startswith(("#", "|", "-", "*", "```")):
        return False
    return bool(re.match(r"^[,;]", stripped)) or (
        len(stripped.split()) >= 8 and re.search(r"[.!?:][\"')\]]?$", stripped) is None
    )


def _target_headings(paper_md: str, ask: str) -> set[str]:
    ask_words = set(re.findall(r"[a-z]{4,}", ask.lower()))
    return {
        heading for heading in re.findall(r"^#{2,3}\s+(.+?)\s*$", paper_md, re.M)
        if set(re.findall(r"[a-z]{4,}", heading.lower())) & ask_words
    }


def _paragraphs_with_headings(paper_md: str) -> list[tuple[str, str]]:
    heading = ""
    out: list[tuple[str, str]] = []
    for part in re.split(r"\n\s*\n", paper_md):
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", part.strip()):
            heading = match.group(1)
        elif part.strip() in _prose_paragraphs(part):
            out.append((heading, part))
    return out


def _reviewed_fragments_are_absent(paper_md: str, ask: str) -> bool:
    targets = _target_headings(paper_md, ask)
    for heading, paragraph in _paragraphs_with_headings(paper_md):
        if _fragmentary(paragraph) and (re.match(r"^[,;]", paragraph.strip()) or not targets or heading in targets):
            return False
    return True


def _repair_fragmentary_prose(paper_md: str, ask: str) -> tuple[str, int]:
    targets = _target_headings(paper_md, ask)
    parts = re.split(r"(\n\s*\n)", paper_md)
    heading, changed = "", 0
    boundary = "This subsection remains bounded to the source-level findings reported in the Findings Map."
    for index in range(0, len(parts), 2):
        part, stripped = parts[index], parts[index].strip()
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", stripped):
            heading = match.group(1)
            continue
        if not _fragmentary(part):
            continue
        if re.match(r"^[,;]", stripped):
            remainder = re.sub(r"^[,;][^.!?]*[.!?]\s*", "", stripped, count=1)
            parts[index] = remainder or boundary
            changed += 1
        elif re.search(r"\]\([^)]+\)$", stripped):
            parts[index], changed = part.rstrip() + ".", changed + 1
        elif not targets or heading in targets:
            parts[index], changed = boundary, changed + 1
    return "".join(parts), changed


def _add_subset_scope(paper_md: str) -> tuple[str, int]:
    existing = re.search(r"^Narrative coverage scope:.*?(?=\n\s*\n|\Z)", paper_md, re.M | re.S | re.I)
    if existing:
        return (
            (paper_md, 0) if _normalise(existing.group(0)) == _normalise(_SUBSET_NOTE)
            else (paper_md[:existing.start()] + _SUBSET_NOTE + paper_md[existing.end():], 1)
        )
    match = re.search(r"^## (?:Scope|Results)\b", paper_md, re.M | re.I)
    if not match:
        return paper_md, 0
    return paper_md[:match.end()] + "\n\n" + _SUBSET_NOTE + paper_md[match.end():], 1


def _subset_scope_is_stated(paper_md: str, rows: Sequence[dict[str, Any]]) -> bool:
    return _normalise(_SUBSET_NOTE) in _normalise(paper_md) and _findings_map_is_exact(paper_md, rows)


def _mention_key(text: str) -> str:
    return _normalise(re.sub(r"\bet\s+al\.?", "", text, flags=re.I))


def _named_rows(ask: str, rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    lower = _mention_key(ask)
    return [row for row in rows if any(
        value and re.search(rf"(?<!\w){re.escape(_mention_key(value))}(?!\w)", lower)
        for value in (_label(row), str(row.get("source_title") or "").strip())
    )]


def _topic_fit_is_deterministic(ask: str, rows: Sequence[dict[str, Any]]) -> bool:
    named = _named_rows(ask, rows)
    return bool(named) and all(
        (directness := str(row.get("directness") or "").strip().lower())
        and directness != "unknown" and not directness.startswith("direct")
        for row in named
    )


def _section_span(paper_md: str, heading: str) -> tuple[int, int] | None:
    match = re.search(rf"^(?P<marks>#{{2,3}})\s+{re.escape(heading)}[ \t]*$", paper_md, re.M | re.I)
    if not match:
        return None
    tail = paper_md[match.end():]
    next_heading = re.search(rf"^#{{1,{len(match.group('marks'))}}}\s+", tail, re.M)
    return match.end(), match.end() + (next_heading.start() if next_heading else len(tail))


def _requested_headings(paper_md: str, ask: str) -> list[str]:
    lower = _normalise(ask)
    return [
        heading.strip()
        for heading in re.findall(r"^#{2,3}\s+(.+?)[ \t]*$", paper_md, re.M)
        if _normalise(heading) in lower
    ]


def _upsert_section_note(paper_md: str, heading: str, marker: str, note: str) -> tuple[str, int]:
    span = _section_span(paper_md, heading)
    if not span:
        return paper_md, 0
    start, end = span
    section = paper_md[start:end]
    existing = re.search(rf"^{re.escape(marker)}.*$", section, re.M)
    if existing:
        if existing.group(0) == note:
            return paper_md, 0
        left, right = start + existing.start(), start + existing.end()
        return paper_md[:left] + note + paper_md[right:], 1
    return paper_md[:start] + "\n\n" + note + paper_md[start:], 1


def _section_has_note(paper_md: str, heading: str, note: str) -> bool:
    span = _section_span(paper_md, heading)
    return bool(span and note in paper_md[span[0]:span[1]])


def _revision_headings(paper_md: str, ask: str, kind: str) -> list[str]:
    requested = _requested_headings(paper_md, ask)
    if kind == "direction" and requested:
        return requested
    defaults = {
        "direction": ("Results",),
        "statistic": ("Evidence Snapshot", "Evidence Landscape", "Results"),
        "topic_fit": ("Evidence Landscape", "Limitations", "Results"),
    }[kind]
    heading = requested[0] if requested else next(
        (name for name in defaults if _section_span(paper_md, name)), None,
    )
    return [heading] if heading else []


def _revision_note(kind: str, row: dict[str, Any], index: int, ask: str) -> tuple[str, str] | None:
    label = _label(row)
    if kind == "direction":
        marker = f"Source-direction reconciliation ({label}):"
        detail = (
            f"source-level direction={resolved_effect_direction(row)} is used consistently; "
            "endpoint-specific findings remain separately qualified."
        )
    elif kind == "statistic":
        stats = _traceable_effect_statistics(row)
        if re.search(r"\bp\s*(?:value|[<>=])", ask, re.I):
            statistic_kind = "p-value"
            stats = tuple(stat for stat in stats if stat.lower().startswith("p"))
        elif "effect estimate" in ask.lower():
            statistic_kind = "effect estimate"
            stats = tuple(stat for stat in stats if not stat.lower().startswith("p"))
        else:
            statistic_kind = "exact statistic"
        marker = f"Source-statistic reconciliation ({label}; {statistic_kind}):"
        finding = (
            f"{label} [bundle:{index}] retains {stats[0]} as bundle-traceable"
            if stats
            else f"{label} has no bundle-traceable exact statistic"
        )
        detail = f"{finding}; other exact values are excluded, and no direction is inferred from a statistic alone."
    else:
        marker = f"Source-scope boundary ({label}):"
        directness = str(row.get("directness") or "unknown").strip().lower()
        if not directness or directness == "unknown" or directness.startswith("direct"):
            return None
        detail = (
            f"{label} is retained only as directness={directness} contextual evidence and a structural corpus "
            "limitation; it is excluded from direct effect accounting for the paper topic."
        )
    return marker, f"{marker} {detail}"


def _direction_patterns(label: str) -> tuple[str, ...]:
    direction = r"(?P<direction>positive|negative|null|mixed|unclear)"
    return (
        rf"(?P<prefix>{re.escape(label)}[^\n]{{0,160}}?\bdirection\s*=\s*){direction}(?P<suffix>)",
        rf"(?P<prefix>{re.escape(label)}\s*\(){direction}(?P<suffix>\s+on\b)",
        rf"(?P<prefix>{re.escape(label)}[^\n.;]{{0,80}}?\b(?:is|was|coded(?:\s+as)?)\s+){direction}(?P<suffix>)",
        rf"(?P<prefix>{re.escape(label)}[^\n.;]{{0,100}}?\b(?:show(?:s|ed)?|support(?:s|ed)?|"
        rf"indicat(?:e|es|ed)|report(?:s|ed)?|ha(?:s|d))\s+(?:an?\s+)?){direction}"
        rf"(?P<suffix>\s+(?:direction|effect|signal|finding)\b)",
    )


def _reconcile_direction_mentions(
    paper_md: str, row: dict[str, Any], headings: Sequence[str],
) -> tuple[str, int]:
    label, resolved, changed = _label(row), resolved_effect_direction(row), 0
    patched = paper_md
    for heading in headings:
        span = _section_span(patched, heading)
        if not span:
            continue
        start, end = span
        section = patched[start:end]
        for pattern in _direction_patterns(label):
            def replace(match: re.Match[str]) -> str:
                nonlocal changed
                if match.group("direction").lower() == resolved:
                    return match.group(0)
                changed += 1
                return match.group("prefix") + resolved + match.group("suffix")
            section = re.sub(pattern, replace, section, flags=re.I)
        patched = patched[:start] + section + patched[end:]
    return patched, changed


def _direction_mentions_are_consistent(
    paper_md: str, row: dict[str, Any], headings: Sequence[str],
) -> bool:
    resolved = resolved_effect_direction(row)
    for heading in headings:
        span = _section_span(paper_md, heading)
        section = paper_md[span[0]:span[1]] if span else ""
        if any(
            match.group("direction").lower() != resolved
            for pattern in _direction_patterns(_label(row))
            for match in re.finditer(pattern, section, re.I)
        ):
            return False
    return True


def _repair_named_revision(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]], kind: str,
) -> tuple[str, int]:
    patched, changed = (
        _repair_untraceable_statistics(paper_md, rows) if kind == "statistic" else (paper_md, 0)
    )
    headings = _revision_headings(patched, ask, kind)
    named = _named_rows(ask, rows)
    if kind == "direction":
        for row in named:
            patched, n = _reconcile_direction_mentions(patched, row, headings)
            changed += n
    note_headings = ["Results"] if kind == "direction" and "Results" in headings else headings[:1]
    for row in named:
        note = _revision_note(kind, row, list(rows).index(row) + 1, ask)
        if not note:
            continue
        marker, text = note
        for heading in note_headings:
            patched, n = _upsert_section_note(patched, heading, marker, text)
            changed += n
    return patched, changed


def _named_revision_is_stated(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]], kind: str,
) -> bool:
    named, headings = _named_rows(ask, rows), _revision_headings(paper_md, ask, kind)
    notes = [(row, _revision_note(kind, row, list(rows).index(row) + 1, ask)) for row in named]
    if not named or not headings or any(note is None for _, note in notes):
        return False
    note_headings = ["Results"] if kind == "direction" and "Results" in headings else headings[:1]
    endpoint_attribution = kind == "direction" and direction_attribution_requested(ask)
    statistics_ok = kind != "statistic" or _statistics_are_source_bound(paper_md, rows)
    directions_ok = kind != "direction" or all(_direction_mentions_are_consistent(paper_md, row, headings) for row in named)
    proofs_ok = all((direction_attribution_is_stated(
        _prose_paragraphs(paper_md), _label(row), resolved_effect_direction(row), ask) if endpoint_attribution else
                     _section_has_note(paper_md, heading, note[1]))
                    for row, note in notes if note is not None for heading in note_headings)
    return statistics_ok and directions_ok and proofs_ok


def _review_level(row: dict[str, Any]) -> bool:
    return any(str(row.get(key) or "").strip().lower() == "review" for key in ("evidence_type", "directness"))


def _role_scope(heading: str, paragraph: str) -> bool:
    return not heading.lower().startswith(("references", "bibliography")) and paragraph.strip() in _prose_paragraphs(paragraph)


def _reconcile_evidence_roles(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    named = [row for row in _named_rows(ask, rows) if _review_level(row)]
    if not named:
        return paper_md, 0
    changed = 0
    parts = re.split(r"(\n\s*\n)", paper_md)
    heading = ""
    for index in range(0, len(parts), 2):
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", parts[index].strip()):
            heading = match.group(1)
            continue
        if not _role_scope(heading, parts[index]):
            continue
        sentences = re.split(r"(?<=[.!?])\s+", parts[index])
        kept = [sentence for pos, sentence in enumerate(sentences) if not any(
            review_role_contradiction(sentence, _label(row), sentences[pos - 1] if pos else "") for row in named)]
        if len(kept) != len(sentences):
            parts[index], changed = " ".join(kept), changed + 1
    patched = "".join(parts)
    notes = " ".join(
        f"{_label(row)} is retained as review-level evidence (directness=review) and is not counted as a direct clinical RCT."
        for row in named
    )
    if "evidence-type reconciliation:" not in patched.lower():
        match = re.search(r"^## Results\b", patched, re.M | re.I)
        if match:
            patched = patched[:match.end()] + "\n\nEvidence-type reconciliation: " + notes + patched[match.end():]
            changed += 1
    return patched, changed


def _evidence_roles_are_reconciled(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> bool:
    named = [row for row in _named_rows(ask, rows) if _review_level(row)]
    scope = paper_md.lower()
    return bool(named) and all(
        _label(row).lower() in scope and "evidence-type reconciliation:" in scope
        and "directness=review" in scope
        and not any(review_role_contradiction(sentence, _label(row), sentences[pos - 1] if pos else "")
            for heading, paragraph in _paragraphs_with_headings(paper_md)
            if _role_scope(heading, paragraph)
            for sentences in (re.split(r"(?<=[.!?])\s+", paragraph),)
            for pos, sentence in enumerate(sentences))
        for row in named
    )


def _named_outcomes(ask: str, rows: Sequence[dict[str, Any]]) -> set[str]:
    lower = _normalise(ask)
    return {
        outcome_display(str(row.get("outcome_class") or "other")) for row in rows
        if _normalise(outcome_display(str(row.get("outcome_class") or "other"))) in lower
        or _normalise(str(row.get("outcome_class") or "")) in lower
    }


def _outcome_section(paper_md: str, display: str) -> re.Match[str] | None:
    return re.search(rf"^###\s+{re.escape(display)}(?:\s+Outcomes?)?\b.*?(?=^### |^## |\Z)", paper_md, re.M | re.S | re.I)


def _bound_named_outcomes(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    patched, changed = paper_md, 0
    for display in _named_outcomes(ask, rows):
        match = _outcome_section(patched, display)
        if not match:
            continue
        section = match.group(0)
        parts = re.split(r"(\n\s*\n)", section)
        replacement = f"{display} evidence is interpreted as bounded and does not establish causal clinical benefit."
        for index in range(0, len(parts), 2):
            if parts[index].strip() not in _prose_paragraphs(parts[index]):
                continue
            sentences = re.split(r"(?<=[.!?])\s+", parts[index])
            bounded = [replacement if _strong_claim_present(sentence) else sentence for sentence in sentences]
            changed += sum(left != right for left, right in zip(sentences, bounded, strict=True))
            parts[index] = " ".join(bounded)
        section = "".join(parts)
        note = (
            "Outcome evidence-role boundary: pooled, review-level, or indirect estimates are bounded associations; "
            "they do not establish a uniform causal direction or direct clinical benefit."
        )
        if "outcome evidence-role boundary:" not in section.lower():
            heading_end = section.find("\n")
            section = section[:heading_end] + "\n\n" + note + section[heading_end:]
            changed += 1
        patched = patched[:match.start()] + section + patched[match.end():]
    return patched, changed


def _strong_claim_present(text: str) -> bool:
    for match in _STRONG_CLAIM_RE.finditer(text):
        prefix = text[max(0, match.start() - 45):match.start()]
        suffix = text[match.end():match.end() + 45]
        if re.search(r"\b(?:no|not|never|cannot|can't|does not|did not|can not)\b[^,.;:]{0,35}$", prefix, re.I):
            continue
        if re.search(r"\b(?:cannot|can not|is not|was not)\s+be\s+(?:inferred|established|claimed)\b", suffix, re.I):
            continue
        return True
    return False


def _evidence_honesty_is_stated(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> bool:
    outcomes = _named_outcomes(ask, rows)
    if not outcomes:
        return False
    return all(
        (match := _outcome_section(paper_md, display)) is not None
        and "outcome evidence-role boundary:" in match.group(0).lower()
        and not _strong_claim_present(match.group(0))
        for display in outcomes
    )
