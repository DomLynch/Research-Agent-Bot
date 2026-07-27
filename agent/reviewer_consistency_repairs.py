"""Fail-closed repairs for reviewer-requested manuscript consistency issues."""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from agent.evidence_lanes import LANE_DISPLAY, derive_receipt_lane, effective_directness
from agent.outcome_class_remap import outcome_display

Rows = Sequence[dict[str, Any]]
_DENOMINATOR_MARKER = "Decision-grade denominator clarification:"
_CROSS_DOMAIN_MARKER = "Cross-domain tension reconciliation:"
_MECHANISTIC_MARKER = "Mechanistic-content clarification:"
_NO_POOLING_NOTE = (
    "Quantitative synthesis boundary: No quantitative pooling was performed because the retained sources "
    "did not provide a sufficiently comparable endpoint-and-effect-estimate set; synthesis is narrative and source-level."
)
_AUTHOR_YEAR_RE = re.compile(r"\b[A-Z][A-Za-z'’.-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b")
_DECISION_COUNT_RE = re.compile(
    r"(?P<prefix>Decision-grade answer:\s*No broad decision-grade conclusion is supported for the\s+)"
    r"(?P<scope>[^.]+?)\s+evidence slice\.\s*"
    r"(?P<count_prefix>The retained slice contains\s+)"
    r"(?P<direct>\d+)\s*/\s*(?P<total>\d+)(?P<suffix>\s+direct sources)",
    re.I,
)
_MIXED_CONFLICT_RE = re.compile(
    r"agreement rather than disagreement|directionally concordant|directionally consistent|"
    r"both [^.]{0,300}\b(?:are coded as reporting a negative effect|trend in the direction of "
    r"(?:reduced|increased) inflammation)\b|"
    r"directionally heterogeneous\s*[-\u2010-\u2015]+\s*(?:anti|pro)[- ]inflammatory",
    re.I,
)
_MECHANISTIC_ABSENCE_RE = re.compile(
    r"\b(?:no (?:retained )?sources? (?:is|are )?(?:classified )?primarily as mechanistic|"
    r"no mechanistic sources?|absence of mechanistic evidence)\b",
    re.I,
)
_POOLING_POSITIVE_RES = (
    re.compile(r"\bquantitative pooling (?:was )?(?:applied|performed|conducted|used)\b", re.I),
    re.compile(
        r"\b(?:performed|conducted|used|fit|ran)\s+(?:a\s+)?"
        r"(?:(?:random|fixed)[- ]effects?\s+)?(?:meta-analysis|quantitative pooling)\b",
        re.I,
    ),
    re.compile(r"\bpooled\s+(?:all|the|these|effect|risk|odds|hazard|results?|estimates?)\b", re.I),
    re.compile(r"\bmeta-analy[sz]ed\b", re.I),
)
_POOLING_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|without)\b[^.!?]{0,40}\b(?:pool|meta-analy)|"
    r"\b(?:pool|meta-analy)[^.!?]{0,40}\b(?:not|never)\b",
    re.I,
)
_GENERIC_SCOPE_TOKENS = frozenset({
    "adjacent", "and", "evidence", "other", "outcome", "reviewed", "slice",
})


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def _has_any(text: str, *tokens: str) -> bool:
    return any(token in text for token in tokens)


def _asks_denominator(text: str) -> bool:
    return "denominator" in text and "direct source" in text and _has_any(
        text, "all corpus", "total direct sources", "outcome slice", "reconcile", "applies",
    )


def _asks_unbundled(text: str) -> bool:
    return (_has_any(
        text, "external reference citation", "external citations", "bundle provenance",
        "not present in the source bundle", "not in the source bundle",
    ) or "missing in text citations" in text and "references list" in text) and _has_any(
        text, "remove", "add them to the source bundle", "verification token", "bundle provenance",
        "add the missing",
    )


def _asks_pooling(text: str) -> bool:
    return "pooling" in text and _has_any(
        text, "no quantitative pooling", "no pooling", "not presented", "does not occur",
        "remove the implication", "remove implication", "pooling artifact",
    )


def _asks_cross_domain(text: str) -> bool:
    return "cross domain synthesis" in text and "tension" in text and _has_any(
        text, "template prose", "generic", "source specific", "direction code", "load bearing",
    )


def _asks_mechanistic(text: str) -> bool:
    return "mechanistic" in text and _has_any(
        text, "no mechanistic source", "no sources classified primarily as mechanistic",
        "absence of mechanistic", "mechanistic content",
    ) and _has_any(
        text, "clarify", "correct", "decide consistently", "recode", "adjust", "resolve",
        "reconcile", "framing",
    )


def _asks_mixed(text: str) -> bool:
    return "mixed" in text and "concordant" in text and _has_any(
        text, "reconcile", "do not both label", "internally",
    )


_ASK_CHECKS = (
    _asks_denominator, _asks_unbundled, _asks_pooling,
    _asks_cross_domain, _asks_mechanistic, _asks_mixed,
)


def ask_known(ask: str, _rows: Rows | None = None) -> bool:
    text = _normalise(ask)
    return any(check(text) for check in _ASK_CHECKS)


def _section_span(paper_md: str, heading: str) -> tuple[int, int] | None:
    match = re.search(rf"^##\s+{re.escape(heading)}[ \t]*$", paper_md, re.M | re.I)
    if not match:
        return None
    tail = paper_md[match.end():]
    next_heading = re.search(r"^#{1,2}\s+", tail, re.M)
    return match.end(), match.end() + (next_heading.start() if next_heading else len(tail))


def _upsert_note(paper_md: str, heading: str, marker: str, note: str) -> tuple[str, int]:
    span = _section_span(paper_md, heading)
    if not span:
        return paper_md, 0
    start, end = span
    existing = re.search(rf"^{re.escape(marker)}.*$", paper_md[start:end], re.M)
    if existing:
        left, right = start + existing.start(), start + existing.end()
        return (paper_md, 0) if existing.group() == note else (paper_md[:left] + note + paper_md[right:], 1)
    return paper_md[:start] + "\n\n" + note + paper_md[start:], 1


def _row_label(row: dict[str, Any]) -> str:
    return str(
        row.get("citation_token") or row.get("cited_as")
        or row.get("body_citation") or row.get("receipt_id") or "source"
    ).strip()


def _author_year_key(text: str) -> str:
    return _normalise(re.sub(r"\bet\s+al\.?", "", text, flags=re.I))


def _named_rows(ask: str, rows: Rows) -> list[dict[str, Any]]:
    ask_key = _author_year_key(ask)
    return [
        row for row in rows
        if any(
            value and _author_year_key(str(value)) in ask_key
            for value in (
                row.get("citation_token"), row.get("cited_as"),
                row.get("body_citation"), row.get("source_title"),
            )
        )
    ]


def _resolved_direction(row: dict[str, Any]) -> str:
    # Local import avoids revision_quality -> revision_consistency -> this module cycle.
    from agent.revision_quality import resolved_effect_direction

    return _normalise(resolved_effect_direction(row) or "unclear")


def _scope_rows(scope: str, rows: Rows) -> list[dict[str, Any]]:
    scope_tokens = set(_normalise(scope).split()) - _GENERIC_SCOPE_TOKENS
    if not scope_tokens:
        return []
    return [
        row for row in rows
        if scope_tokens & (
            set(_normalise(str(row.get("outcome_class") or "").replace("_", " ")).split())
            | set(_normalise(outcome_display(str(row.get("outcome_class") or ""))).split())
        )
    ]


def _denominator_state(
    paper_md: str, rows: Rows,
) -> tuple[re.Match[str], str, int, int, int, int] | None:
    match = _DECISION_COUNT_RE.search(paper_md)
    if not match:
        return None
    scope = " ".join(match.group("scope").split())
    scoped = _scope_rows(scope, rows)
    if not scoped:
        return None
    return (
        match, scope,
        sum(effective_directness(row) == "direct" for row in scoped), len(scoped),
        sum(effective_directness(row) == "direct" for row in rows), len(rows),
    )


def _denominator_note(state: tuple[re.Match[str], str, int, int, int, int]) -> str:
    _match, scope, direct, total, all_direct, all_total = state
    return (
        f"{_DENOMINATOR_MARKER} The {direct}/{total} direct-source fraction applies only to the "
        f"{scope} evidence slice; the all-corpus direct-source denominator is "
        f"{all_direct}/{all_total}. The slice and all-corpus counts are separate and are not combined."
    )


def direct_ceiling_note(rows: Rows) -> str:
    direct = [row for row in rows if effective_directness(row) == "direct"]
    noun = "source" if len(direct) == 1 else "sources"
    shown = "; ".join(_row_label(row) for row in direct[:5]) or "none"
    extra = f"; {len(direct) - 5} additional direct sources are listed in the Findings Map" if len(direct) > 5 else ""
    return (
        f"**Direct-source ceiling:** The corpus contains {len(direct)} direct clinical {noun}. "
        f"Representative direct sources are {shown}{extra}. The remaining {len(rows) - len(direct)} "
        "sources are indirect, review, protocol, mechanistic, or contextual evidence."
    )


def _repair_denominator(paper_md: str, rows: Rows) -> tuple[str, int]:
    state = _denominator_state(paper_md, rows)
    if not state:
        return paper_md, 0
    match, _scope, direct, total, _all_direct, _all_total = state
    replacement = (
        f"{match.group('prefix')}{match.group('scope')} evidence slice. "
        f"{match.group('count_prefix')}{direct}/{total}{match.group('suffix')}"
    )
    patched = paper_md[:match.start()] + replacement + paper_md[match.end():]
    refreshed = _denominator_state(patched, rows)
    if not refreshed:
        return paper_md, 0
    heading = "Conclusion" if _section_span(patched, "Conclusion") else "Research Question"
    patched, inserted = _upsert_note(patched, heading, _DENOMINATOR_MARKER, _denominator_note(refreshed))
    patched = re.sub(
        r"^\*\*Direct-source ceiling:\*\*.*$",
        direct_ceiling_note(rows),
        patched,
        flags=re.M,
    )
    return patched, int(patched != paper_md or inserted)


def _denominator_is_stated(paper_md: str, rows: Rows) -> bool:
    state = _denominator_state(paper_md, rows)
    if not state:
        return False
    match, _scope, direct, total, _all_direct, _all_total = state
    ceiling_ok = "**Direct-source ceiling:**" not in paper_md or direct_ceiling_note(rows) in paper_md
    return (
        int(match.group("direct")) == direct
        and int(match.group("total")) == total
        and _denominator_note(state) in paper_md
        and ceiling_ok
    )


def _bundled_author_years(rows: Rows) -> set[str]:
    return {
        _author_year_key(match.group())
        for row in rows
        for value in (
            row.get("citation_token"), row.get("cited_as"), row.get("body_citation"),
            row.get("source_label"), row.get("source_title"),
        )
        if value
        for match in _AUTHOR_YEAR_RE.finditer(str(value))
    }


def _unbundled_targets(ask: str, rows: Rows) -> tuple[str, ...]:
    bundled = _bundled_author_years(rows)
    return tuple(dict.fromkeys(
        match.group() for match in _AUTHOR_YEAR_RE.finditer(ask)
        if _author_year_key(match.group()) not in bundled
    ))


def _mentions(text: str, targets: Sequence[str]) -> bool:
    return any(re.search(re.escape(target), text, re.I) for target in targets)


def _has_bundle_anchor(sentence: str, rows: Rows) -> bool:
    lower = sentence.lower()
    return "[bundle:" in lower or any(
        label and label.lower() in lower for label in map(_row_label, rows)
    )


def _strip_external_group(group: str, targets: Sequence[str], rows: Rows) -> str:
    if not _mentions(group, targets):
        return group
    if not _has_bundle_anchor(group, rows):
        return ""
    parts = [part.strip() for part in group[1:-1].split(";")]
    if len(parts) < 2 or any(_mentions(part, targets) and _has_bundle_anchor(part, rows) for part in parts):
        return group
    kept = [part for part in parts if not _mentions(part, targets)]
    return f"{group[0]}{'; '.join(kept)}{group[-1]}" if kept else ""


def _strip_external_clause(sentence: str, targets: Sequence[str], rows: Rows) -> str:
    if not _mentions(sentence, targets):
        return sentence
    candidate = re.sub(
        r"\([^)\n]*\)|\[[^\]\n]*\]",
        lambda match: _strip_external_group(match.group(), targets, rows),
        sentence,
    )
    for target in targets:
        candidate = re.sub(
            rf"\s*[,;]\s*(?:(?:which\s+)?{re.escape(target)}|"
            rf"(?:(?:according|consistent)\s+(?:to|with)|"
            rf"as\s+(?:defined|described|reported)\s+by)\s+{re.escape(target)})"
            rf"(?:(?!\s+\[(?:exact source|bundle):).)*?"
            rf"(?P<suffix>\s+\[(?:exact source|bundle):|[.!?]$|$)",
            lambda match: match.group("suffix"),
            candidate,
            flags=re.I,
        )
    candidate = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", candidate)).strip()
    if not _mentions(candidate, targets):
        return candidate
    return sentence if _has_bundle_anchor(sentence, rows) else ""


def _repair_unbundled(paper_md: str, ask: str, rows: Rows) -> tuple[str, int]:
    targets = _unbundled_targets(ask, rows)
    if not targets or not _mentions(paper_md, targets):
        return paper_md, 0
    body, separator, references = paper_md.partition("\n## References")
    body_lines = []
    for line in body.splitlines():
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*_(])", line)
        body_lines.append(" ".join(
            kept for sentence in sentences
            if (kept := _strip_external_clause(sentence, targets, rows))
        ))
    reference_lines = [
        line for line in references.splitlines() if not _mentions(line, targets)
    ]
    patched = "\n".join(body_lines)
    if separator:
        patched += separator + "\n".join(reference_lines)
    patched = re.sub(r"\n{3,}", "\n\n", patched)
    return patched, int(patched != paper_md)


def _unbundled_is_resolved(paper_md: str, ask: str, rows: Rows) -> bool:
    named = tuple(match.group() for match in _AUTHOR_YEAR_RE.finditer(ask))
    if not named:
        return False
    bundled = _bundled_author_years(rows)
    return all(
        _author_year_key(target) in bundled
        or not re.search(re.escape(target), paper_md, re.I)
        for target in named
    )


def _positive_pooling_claim(sentence: str) -> bool:
    return not _POOLING_NEGATION_RE.search(sentence) and any(
        pattern.search(sentence) for pattern in _POOLING_POSITIVE_RES
    )


def _repair_pooling(paper_md: str) -> tuple[str, int]:
    lines = []
    for line in paper_md.splitlines():
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*_(])", line)
        lines.append(" ".join(sentence for sentence in sentences if not _positive_pooling_claim(sentence)))
    patched = "\n".join(lines)
    patched, inserted = _upsert_note(
        patched, "Methods", "Quantitative synthesis boundary:", _NO_POOLING_NOTE,
    )
    return patched, int(patched != paper_md or inserted)


def _pooling_is_stated(paper_md: str) -> bool:
    return _NO_POOLING_NOTE in paper_md and not any(
        _positive_pooling_claim(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", paper_md)
    )


def _cross_domain_note(ask: str, rows: Rows) -> str:
    named = _named_rows(ask, rows)
    labels = [
        (_row_label(row), _resolved_direction(row), outcome_display(str(row.get("outcome_class") or "contextual_other")))
        for row in named
    ]
    coded = "; ".join(
        f"{label}: direction={direction}, outcome={outcome}"
        for label, direction, outcome in labels
    ) or "the named sources retain their resolved Findings Map codes"
    return (
        f"{_CROSS_DOMAIN_MARKER} {coded}. These are source-specific contrasts, not load-bearing "
        "tensions, unless shared endpoint-level evidence supports one explicit explanation."
    )


def _source_pattern(row: dict[str, Any]) -> str:
    return rf"{re.escape(_row_label(row))}(?:\s+\[[^\]\n]+\])*"


def _pair_item_pattern(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_pattern, right_pattern = _source_pattern(left), _source_pattern(right)
    return (
        rf"^[ \t]*[-*][^\n]*?(?:{left_pattern}\s+(?:vs\.?|versus)\s+{right_pattern}|"
        rf"{right_pattern}\s+(?:vs\.?|versus)\s+{left_pattern})[^\n]*\n?"
    )


def _repair_cross_domain(paper_md: str, ask: str, rows: Rows) -> tuple[str, int]:
    span = _section_span(paper_md, "Cross-Domain Synthesis")
    named = _named_rows(ask, rows)
    if not span or len(named) < 2:
        return paper_md, 0
    start, end = span
    section, removed = re.subn(
        r"\s+Leading explanations:.*?(?=\n(?:\s*[-*] |\s*\n|## )|\Z)",
        "",
        paper_md[start:end],
        flags=re.S,
    )
    patched = paper_md[:start] + section + paper_md[end:]
    pair_changes = 0
    for left, right in zip(named[::2], named[1::2]):
        patched, changed = re.subn(
            _pair_item_pattern(left, right), "", patched, flags=re.I | re.M,
        )
        pair_changes += changed
    patched, inserted = _upsert_note(
        patched, "Cross-Domain Synthesis", _CROSS_DOMAIN_MARKER, _cross_domain_note(ask, rows),
    )
    return patched, removed + pair_changes + inserted


def _cross_domain_is_stated(paper_md: str, ask: str, rows: Rows) -> bool:
    span = _section_span(paper_md, "Cross-Domain Synthesis")
    named = _named_rows(ask, rows)
    if not span or len(named) < 2:
        return False
    pairs_match = all(
        not re.search(_pair_item_pattern(left, right), paper_md, re.I | re.M)
        for left, right in zip(named[::2], named[1::2])
    )
    section = paper_md[span[0]:span[1]]
    return _cross_domain_note(ask, rows) in section and "Leading explanations:" not in section and pairs_match


def _mechanistic_rows(rows: Rows) -> list[dict[str, Any]]:
    fields = ("directness", "evidence_type", "source_type", "role", "study_design")
    return [
        row for row in rows
        if derive_receipt_lane(row) in {"human_mechanistic", "animal_preclinical"}
        or any(
            re.search(r"\b(?:mechanistic|model[- ]system|preclinical)\b", str(row.get(field) or ""), re.I)
            for field in fields
        )
    ]


def _mechanistic_note(ask: str, rows: Rows) -> str:
    classified = _mechanistic_rows(rows)
    if classified:
        roster = ", ".join(
            f"{_row_label(row)} ({LANE_DISPLAY.get(derive_receipt_lane(row), derive_receipt_lane(row))})"
            for row in classified
        )
        return (
            f"{_MECHANISTIC_MARKER} Source-level classification separates {roster} as "
            "mechanistic or model-system evidence; these sources do not upgrade clinical effect evidence."
        )
    named = _named_rows(ask, rows)
    roles = ", ".join(
        f"{_row_label(row)} ({LANE_DISPLAY.get(derive_receipt_lane(row), derive_receipt_lane(row))})"
        for row in named
    )
    named_clause = f" The named retained sources are classified by primary study role as {roles}." if roles else ""
    return (
        f"{_MECHANISTIC_MARKER} No retained source is classified primarily as mechanistic or model-system "
        f"evidence under the source-level schema.{named_clause} Mechanistic or biomarker content can still "
        "occur within those sources, so this is not evidence that mechanistic content is absent."
    )


def _repair_mechanistic(paper_md: str, ask: str, rows: Rows) -> tuple[str, int]:
    note = _mechanistic_note(ask, rows)
    lines = []
    for line in paper_md.splitlines():
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*_(])", line)
        lines.append(" ".join(
            sentence for sentence in sentences
            if not _MECHANISTIC_ABSENCE_RE.search(sentence) or _has_bundle_anchor(sentence, rows)
        ))
    patched = "\n".join(lines)
    heading = "Evidence Landscape" if _section_span(patched, "Evidence Landscape") else "Limitations"
    patched, inserted = _upsert_note(patched, heading, _MECHANISTIC_MARKER, note)
    return patched, int(patched != paper_md or inserted)


def _mechanistic_is_stated(paper_md: str, ask: str, rows: Rows) -> bool:
    if not rows:
        lower = paper_md.lower()
        return all(token in lower for token in (
            "classified primarily as mechanistic",
            "mechanistic or biomarker content",
            "not evidence that mechanistic content is absent",
        ))
    note = _mechanistic_note(ask, rows)
    remainder = paper_md.replace(note, "")
    return note in paper_md and not _MECHANISTIC_ABSENCE_RE.search(remainder)


def _mixed_note(row: dict[str, Any]) -> str:
    return (
        f"Source-direction reconciliation ({_row_label(row)}): reviewer-reconciled direction=mixed is "
        "used consistently; within-source endpoints are heterogeneous, so this source is not counted as "
        "unidirectionally positive or negative and no cross-source agreement is inferred from it."
    )


def _repair_mixed(paper_md: str, ask: str, rows: Rows) -> tuple[str, int]:
    patched, changed = paper_md, 0
    for row in _named_rows(ask, rows):
        if _resolved_direction(row) != "mixed":
            continue
        label = _row_label(row)
        parts = re.split(r"(\n\s*\n)", patched)
        for index in range(0, len(parts), 2):
            paragraph = parts[index]
            if label.lower() not in paragraph.lower() or not _MIXED_CONFLICT_RE.search(paragraph):
                continue
            replacements = (
                (r"agreement rather than disagreement", "heterogeneity rather than agreement"),
                (
                    r"both [^.]{0,120}\bare coded as reporting a negative effect\b",
                    "the named within-source endpoints are not assigned one shared source-level direction",
                ),
                (
                    r"meaning both [^.]{0,300}\btrend in the direction of "
                    r"(?:reduced|increased) inflammation against their respective controls",
                    "meaning endpoint-specific signals do not establish one shared source-level direction "
                    "across the two sources",
                ),
                (r"directionally concordant", "directionally heterogeneous"),
                (r"directionally consistent", "directionally heterogeneous"),
            )
            for pattern, replacement in replacements:
                paragraph, count = re.subn(pattern, replacement, paragraph, flags=re.I)
                changed += count
            paragraph, count = re.subn(
                r"directionally heterogeneous(?:\s+and|\s*[-\u2010-\u2015]+)\s*anti[- ]inflammatory"
                r"(?:\s*[-\u2010-\u2015]+)?",
                "heterogeneous across inflammatory endpoints",
                paragraph,
                flags=re.I,
            )
            parts[index], changed = paragraph, changed + count
        patched = "".join(parts)
        patched, inserted = _upsert_note(
            patched, "Results", f"Source-direction reconciliation ({label}):", _mixed_note(row),
        )
        changed += inserted
    return patched, changed


def _mixed_is_stated(paper_md: str, ask: str, rows: Rows) -> bool:
    targets = [row for row in _named_rows(ask, rows) if _resolved_direction(row) == "mixed"]
    return bool(targets) and all(
        _mixed_note(row) in paper_md
        and not any(
            _row_label(row).lower() in paragraph.lower() and _MIXED_CONFLICT_RE.search(paragraph)
            for paragraph in re.split(r"\n\s*\n", paper_md)
        )
        for row in targets
    )


def proof_is_stated(paper_md: str, ask: str, rows: Rows) -> bool:
    text = _normalise(ask)
    checks = (
        (_asks_denominator, _denominator_is_stated(paper_md, rows)),
        (_asks_unbundled, _unbundled_is_resolved(paper_md, ask, rows)),
        (_asks_pooling, _pooling_is_stated(paper_md)),
        (_asks_cross_domain, _cross_domain_is_stated(paper_md, ask, rows)),
        (_asks_mechanistic, _mechanistic_is_stated(paper_md, ask, rows)),
        (_asks_mixed, _mixed_is_stated(paper_md, ask, rows)),
    )
    return all(not matches(text) or passed for matches, passed in checks)


def repair(paper_md: str, rows: Rows, feedback: str) -> tuple[str, list[str]]:
    patched, details = paper_md, []
    repairers: tuple[
        tuple[Callable[[str], bool], Callable[[str, str], tuple[str, int]], str], ...
    ] = (
        (_asks_denominator, lambda text, _ask: _repair_denominator(text, rows), "decision_denominator_reconciliation"),
        (_asks_unbundled, lambda text, ask: _repair_unbundled(text, ask, rows), "unbundled_citation_cleanup"),
        (_asks_pooling, lambda text, _ask: _repair_pooling(text), "pooling_claim_cleanup"),
        (_asks_cross_domain, lambda text, ask: _repair_cross_domain(text, ask, rows), "cross_domain_tension_specificity"),
        (_asks_mechanistic, lambda text, ask: _repair_mechanistic(text, ask, rows), "mechanistic_content_framing"),
        (_asks_mixed, lambda text, ask: _repair_mixed(text, ask, rows), "named_direction_reconciliation"),
    )
    for ask in (part.strip() for part in re.split(r";\s+(?=[A-Z])", feedback) if part.strip()):
        lower = _normalise(ask)
        for predicate, repairer, detail in repairers:
            if predicate(lower):
                patched, changed = repairer(patched, ask)
                if changed and detail not in details:
                    details.append(detail)
    if details:
        patched = re.sub(r"\n{3,}", "\n\n", patched)
    return patched, details
