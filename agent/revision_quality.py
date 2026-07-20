"""Deterministic repair and proof for recurring reviewer-quality revisions."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from agent.outcome_class_remap import outcome_display, refine_other_outcome_class
from agent.publication_evidence import attach_bundle_references, ordered_source_rows


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


def revision_quality_ask_known(ask: str) -> bool:
    lower = _normalise(ask)
    return any(check(lower) for check in (
        _asks_outcome_roster, _asks_exact_stat_trace, _asks_fragment_cleanup,
        _asks_representative_subset, _asks_evidence_role_reconciliation,
        _asks_evidence_honesty,
    ))


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
        (_asks_fragment_cleanup, lambda: _reviewed_fragments_are_absent(paper_md, ask)),
        (_asks_representative_subset, lambda: _subset_scope_is_stated(paper_md, rows)),
        (_asks_evidence_role_reconciliation, lambda: _evidence_roles_are_reconciled(paper_md, ask, rows)),
        (_asks_evidence_honesty, lambda: _evidence_honesty_is_stated(paper_md, ask, rows)),
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
    p_values = row.get("p_values")
    stat = next((str(value).strip() for value in p_values if str(value).strip()), "") if isinstance(p_values, list) else ""
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
    direction = receipt_direction(row)
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
        part for part in re.split(r";\s+(?=[A-Z])", feedback) if predicate(_normalise(part))
    )


def _asks_outcome_roster(text: str) -> bool:
    return "findings map" in text and "source bundle" in text and any(
        token in text for token in ("table counts", "lists all", "update counts", "actual source bundle")
    )


def _asks_exact_stat_trace(text: str) -> bool:
    return "every exact statistic" in text and any(
        token in text for token in ("bundle token", "source excerpt", "directional language")
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
    p_values = row.get("p_values")
    return " ".join((
        str(row.get("thesis_text") or ""), str(row.get("source_title") or ""),
        " ".join(map(str, p_values)) if isinstance(p_values, list) else "",
    ))


def _numbers(text: str) -> tuple[str, ...]:
    values = [
        f"0{value}" if value.startswith(".") else value
        for value in re.findall(r"(?<![A-Za-z])(?:\d+\.\d+|\.\d+|\d+)", text)
    ]
    return tuple(value.rstrip("0").rstrip(".") if "." in value else value for value in values)


def _stat_supported(stat: str, row: dict[str, Any]) -> bool:
    evidence = _row_evidence(row).casefold().replace("–", "-")
    metric = next((token for token in ("nnt", "hr", "or", "rr", "ci", "p", "%") if token in stat.casefold()), "")
    metric_present = metric == "%" and "%" in evidence or bool(metric and re.search(rf"\b{re.escape(metric)}\b", evidence))
    p_relations = _p_relations(stat)
    return (not p_relations or set(p_relations) <= set(_p_relations(evidence))) and metric_present and all(
        re.search(rf"(?<![\d.])0*{re.escape(number)}(?!\d|\.\d)", evidence) is not None
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
    return all(
        _stat_is_source_bound(paragraph, match, rows)
        for paragraph in _prose_paragraphs(paper_md) for match in _EFFECT_STAT_RE.finditer(paragraph)
    )


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
    parts = re.split(r"(\n\s*\n)", paper_md)
    changed = 0
    for index in range(0, len(parts), 2):
        original = parts[index]
        if original.strip() not in _prose_paragraphs(original) or not _EFFECT_STAT_RE.search(original):
            continue
        paragraph = attach_bundle_references(original, rows)
        matches = list(_EFFECT_STAT_RE.finditer(paragraph))
        fixed = _soften_statistics(paragraph) if any(
            not _stat_is_source_bound(paragraph, match, rows) for match in matches
        ) else paragraph
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


def _named_rows(ask: str, rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    lower = ask.casefold()
    return [row for row in rows if any(
        value and value.casefold() in lower
        for value in (_label(row), str(row.get("source_title") or "").strip())
    )]


def _review_level(row: dict[str, Any]) -> bool:
    return any(str(row.get(key) or "").strip().lower() == "review" for key in ("evidence_type", "directness"))


def _role_contradiction(sentence: str, row: dict[str, Any]) -> bool:
    lower = sentence.lower()
    if _label(row).lower() not in lower:
        return False
    trials = re.finditer(r"\b(?:clinical\s+)?(?:rct|randomi[sz]ed[^.]{0,35}trial|trial)\b", lower)
    for trial in trials:
        prefix = lower[max(0, trial.start() - 90):trial.start()]
        bounded = re.search(
            r"(?:(?:is|was|are|were)\s+not\s+(?:counted\s+as\s+)?(?:a\s+)?(?:direct\s+|clinical\s+)*"
            r"|(?:does\s+not|cannot)\s+(?:make|constitute|represent|support)[^.]{0,35})$",
            prefix,
        )
        if bounded is None:
            return True
    return False


def _reconcile_evidence_roles(
    paper_md: str, ask: str, rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    named = [row for row in _named_rows(ask, rows) if _review_level(row)]
    if not named:
        return paper_md, 0
    changed = 0
    parts = re.split(r"(\n\s*\n)", paper_md)
    for index in range(0, len(parts), 2):
        if parts[index].strip() not in _prose_paragraphs(parts[index]):
            continue
        sentences = re.split(r"(?<=[.!?])\s+", parts[index])
        kept = [sentence for sentence in sentences if not any(_role_contradiction(sentence, row) for row in named)]
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
        and not any(_role_contradiction(sentence, row) for sentence in _prose_paragraphs(paper_md))
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
