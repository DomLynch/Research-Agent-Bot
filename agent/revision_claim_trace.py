"""Deterministic source binding for reviewer-requested major-claim traces."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agent.endpoint_evidence import endpoint_key
from agent.publication_evidence import attach_bundle_references, ordered_source_rows

_TRACE_LINE_RE = re.compile(
    r"^- \*\*Manuscript claim (?P<number>\d+)\.\*\* (?P<claim>.*?) "
    r"\*\*Supporting source:\*\* "
    r"(?P<support>.*?\[bundle:(?P<bundle>\d+)\].*?) "
    r"\*\*Evidence span:\*\* (?P<span>.+)$",
    re.I,
)
_ABBREVIATION_RE = re.compile(r"\b(?:vs|e\.g|i\.e|et al)\.", re.I)
_RESULT_SIGNAL_RE = re.compile(r"\b(?:decreas(?:e|ed|ing)|improv(?:e|ed|ement|ements)|increas(?:e|ed|ing)|reduc(?:e|ed|ing|tion|tions)|unchanged|differ(?:ed|ence|ences)|associated|association)\b|\b(?:no|not|statistically)\s+significant\b|\bdid not (?:change|decrease|improve|increase|reduce)\b", re.I)
_STATISTIC_RE = re.compile(r"(?i:\bp\s*[<=>]\s*\.?\d|\b(?:confidence interval|ci|md|smd|wmd|rr|hr)\s*(?::|=)?\s*-?\.?\d|\d+(?:\.\d+)?\s*%)|\b(?:OR|(?i:odds ratio))\s*(?::|=)?\s*-?\.?\d")
_PROCEDURAL_RE = re.compile(r"\b(?:at baseline|baseline characteristics?|candidate (?:coverage|pool)|enrollment|index selection|literature search|records? (?:identified|screened)|search (?:increased|strategy))\b", re.I)
_PROTECTED_PERIOD = "\ue000"
_NON_CLAIM_PREFIXES = (
    "Evidence-type reconciliation:",
    "Source-direction reconciliation (",
    "Source-statistic reconciliation (",
    "Source-scope boundary (",
)


def asks_major_claim_trace(text: str) -> bool:
    tokens = ("exact source token", "doi/pmid", "doi or pmid", "evidence span", "exactly traceable")
    return "major claim" in text and any(token in text for token in tokens)


def major_claim_trace_is_stated(
    paper_md: str,
    ask: str,
    rows: Sequence[dict[str, Any]],
) -> bool:
    rows = _ordered_rows(rows)
    claims = _source_bound_claims(_without_trace(paper_md), rows)
    return len({claim for claim, _number, _row in claims if _claim_is_fully_traced(claim, rows)}) >= _requested_count(ask, len(claims))


def strip_validated_trace_support(
    paper_md: str,
    rows: Sequence[dict[str, Any]],
) -> str:
    """Hide only manifest-verified support metadata from numeric prose audit."""
    rows = _ordered_rows(rows)
    scope = _scope(paper_md)
    if not scope:
        return paper_md
    source_bound_claims = {(claim, number) for claim, number, _row in _source_bound_claims(paper_md, rows)}
    lines = []
    for line in scope.splitlines():
        match = _TRACE_LINE_RE.match(line)
        if match and _trace_line_is_valid(match, source_bound_claims, rows):
            line = (
                f"- **Manuscript claim {match.group('number')}.** "
                f"{match.group('claim').strip()} "
                "**Supporting source:** validated manifest source."
            )
        lines.append(line)
    return paper_md.replace(scope, "\n".join(lines), 1)


def _trace_line_is_valid(
    match: re.Match[str],
    source_bound_claims: set[tuple[str, int]],
    rows: Sequence[dict[str, Any]],
) -> bool:
    claim, bundle_number = match.group("claim").strip(), int(match.group("bundle"))
    if not 1 <= bundle_number <= len(rows):
        return False
    row = rows[bundle_number - 1]
    support = f"{_label(row)} [bundle:{bundle_number}]" + (f" {_stable_locator(row)}" if _stable_locator(row) else "")
    return bool(
        _evidence_span(row) and (claim, bundle_number) in source_bound_claims
        and f"[bundle:{bundle_number}]" in claim and match.group("support").strip() == support
        and match.group("span").strip() == _evidence_span(row)
    )


def repair_major_claim_trace(
    paper_md: str,
    ask: str,
    rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    rows = _ordered_rows(rows)
    patched = attach_bundle_references(re.sub(r"\s*\(evidence anchor:\s*.*?\s+\[bundle:\d+\]\)(?:\s*\[exact source:\s*https?://[^\]]+\])?", "", re.sub(r"(?ms)^### Source-Traced Findings\b.*?(?=^## |\Z)", "", _without_trace(paper_md)), flags=re.I), rows)
    claims = _source_bound_claims(patched, rows)
    for claim, _bundle_number, _row in claims:
        traced = claim
        for number in _bundle_numbers(claim, len(rows)):
            locator = _stable_locator(rows[number - 1])
            if locator and not _locator_is_stated(traced, locator):
                traced = _append_inline_locator(traced, locator)
        if traced != claim:
            patched = patched.replace(claim, traced, 1)
    patched = _add_source_trace_findings(patched, rows, ask)
    return patched, int(patched != paper_md)


def _add_source_trace_findings(
    paper_md: str, rows: Sequence[dict[str, Any]], ask: str,
) -> str:
    valid = [(claim, number) for claim, number, _row in _source_bound_claims(paper_md, rows) if _claim_is_fully_traced(claim, rows)]
    missing = _requested_count(ask, len(rows)) - len(valid)
    if missing <= 0:
        return paper_md
    used = {number for _claim, number in valid}
    findings = {_claim_key(claim, rows): "" for claim, _number in valid}
    for number, row in sorted(enumerate(rows, 1), key=lambda item: (item[0] in used, str(item[1].get("directness") or "").lower() != "direct", not str(item[1].get("evidence_tier") or "").upper().startswith("A"), item[0])):
        label, locator, span = _label(row), _stable_locator(row), _result_span(row)
        if label and locator and row.get("thesis_text") and _RESULT_SIGNAL_RE.search(span) and len(span) >= 20 and (key := _claim_key(span)) not in findings:
            findings[key] = f"{label} [bundle:{number}] reports: {span} [exact source: {locator}]."
        if sum(bool(value) for value in findings.values()) >= missing:
            break
    block = "### Source-Traced Findings\n\n" + "\n\n".join(value for value in findings.values() if value)
    return re.sub(r"(?ms)(^## Results\b.*?)(?=^## |\Z)", lambda match: match.group(1).rstrip() + "\n\n" + block + "\n\n", paper_md, count=1) if any(findings.values()) else paper_md


def _append_inline_locator(claim: str, locator: str) -> str:
    terminal = re.search(r"""[.!?](?:["')\]]|\*{1,2}|_{1,2})*$""", claim)
    return f"{claim} [exact source: {locator}]" if not terminal else f"{claim[:terminal.start()]} [exact source: {locator}]{claim[terminal.start():]}"


def _requested_count(ask: str, available: int) -> int:
    return max(1, int(match.group(1)) if (match := re.search(r"\brequired\s+(\d+)\b", ask, re.I)) else min(16, available))


def _claim_key(claim: str, rows: Sequence[dict[str, Any]] = ()) -> str:
    claim = re.sub(labels, "", claim, flags=re.I) if (labels := "|".join(sorted((re.escape(_label(row)) for row in rows if _label(row)), key=len, reverse=True))) else claim
    text = re.sub(r"^.*?\[bundle:\d+\]\s+reports:\s*|\[exact source:\s*https?://[^\]]+\]|\[bundle:\d+\]", "", claim, flags=re.I)
    return " ".join(re.sub(r"\W+", " ", text.casefold()).split())


def _result_span(row: dict[str, Any]) -> str:
    endpoints = {(key, "".join(word[0] for word in key.split())) for value in row.get("endpoints") or () if (key := endpoint_key(value))}
    for part in re.split(r"source excerpts:\s*", str(row.get("thesis_text") or ""), maxsplit=1, flags=re.I)[-1].split("|"):
        for sentence in _sentences(part.strip()):
            for clause in re.split(r";\s*|,\s*(?=(?:while|whereas|but)\b)", sentence, flags=re.I):
                normalized = endpoint_key(clause)
                if _RESULT_SIGNAL_RE.search(clause) and not _PROCEDURAL_RE.search(clause) and _STATISTIC_RE.search(clause) and any(re.search(rf"\b{re.escape(value)}\b", normalized) or len(initials) >= 3 and re.search(rf"\b{'[^A-Za-z0-9]*'.join(initials)}\b", clause, re.I) for value, initials in endpoints):
                    return _evidence_span({"thesis_text": clause}).strip().rstrip(" .!?")
    return ""


def _without_trace(paper_md: str) -> str:
    return paper_md.replace(scope, "", 1) if (scope := _scope(paper_md)) else paper_md


def _scope(paper_md: str) -> str:
    return match.group(0) if (match := re.search(r"^## Major Claim Trace\b.*?(?=^## |\Z)", paper_md, re.M | re.S | re.I)) else ""


def _sentences(text: str) -> list[str]:
    protected = _ABBREVIATION_RE.sub(lambda match: match.group(0)[:-1] + _PROTECTED_PERIOD, text)
    boundary = r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+(?=(?:[\"'(\[]|\*{1,2}|_{1,2})?[A-Z0-9])"
    return [claim.replace(_PROTECTED_PERIOD, ".") for claim in re.split(boundary, protected)]


def _bundle_numbers(claim: str, row_count: int) -> list[int]:
    values = (int(value) for value in re.findall(r"\[bundle:(\d+)\]", claim, re.I))
    return list(dict.fromkeys(value for value in values if 1 <= value <= row_count))


def _claim_is_fully_traced(claim: str, rows: Sequence[dict[str, Any]]) -> bool:
    numbers = _bundle_numbers(claim, len(rows))
    return bool(numbers and all(
        (locator := _stable_locator(rows[number - 1])) and _locator_is_stated(claim, locator)
        for number in numbers
    ))


def _locator_is_stated(claim: str, locator: str) -> bool:
    return f"[exact source: {locator}]" in claim or f"]({locator})" in claim or bool(
        re.search(rf"(?<!\S){re.escape(locator)}(?=\s|$)", claim)
    )


def _source_bound_claims(
    paper_md: str,
    rows: Sequence[dict[str, Any]],
) -> list[tuple[str, int, dict[str, Any]]]:
    claims: list[tuple[int, int, str, int, dict[str, Any]]] = []
    section = ""
    seen: set[str] = set()
    for order, line in enumerate(_without_trace(paper_md).splitlines()):
        if heading := re.match(r"^##+\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
            continue
        stripped = " ".join(line.split())
        if (
            section == "references"
            or len(stripped) < 40
            or stripped.startswith(("#", "|", "```", "- "))
            or stripped.startswith(_NON_CLAIM_PREFIXES)
        ):
            continue
        for claim in _sentences(stripped):
            claim = _drop_unmatched_parentheses(claim)
            candidates = _bundle_numbers(claim, len(rows))
            if not candidates:
                continue
            bundle_number = min(candidates, key=lambda number: (
                str(rows[number - 1].get("directness") or "").lower() != "direct",
                not str(rows[number - 1].get("evidence_tier") or "").upper().startswith("A"),
                number,
            ))
            key = _claim_key(claim, [rows[number - 1] for number in candidates])
            if key in seen:
                continue
            seen.add(key)
            priority = 0 if any(token in section for token in (
                "result", "outcome", "synthesis", "conclusion", "what this synthesis adds",
            )) else 1
            claims.append((priority, order, claim, bundle_number, rows[bundle_number - 1]))
    ordered = [(claim, number, row) for _, _, claim, number, row in sorted(claims)]
    first: dict[int, tuple[str, int, dict[str, Any]]] = {}
    for item in ordered:
        first.setdefault(item[1], item)
    return list(first.values()) + [item for item in ordered if item is not first[item[1]]]


def _ordered_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return ordered_source_rows(list(rows), {str(row.get("receipt_id") or ""): row for row in rows})


def _label(row: dict[str, Any]) -> str:
    return str(row.get("citation_token") or row.get("cited_as") or row.get("body_citation") or row.get("receipt_id") or "").strip()


def _evidence_span(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get("thesis_text") or row.get("source_title") or "").split())
    if "source excerpts:" in text.lower():
        text = re.split(r"source excerpts:\s*", text, maxsplit=1, flags=re.I)[1]
    text = text.split(" | ", 1)[0].replace("|", " ").strip()
    upstream_truncated = text.endswith(("...", "\u2026"))
    if upstream_truncated:
        text = text.removesuffix("\u2026").removesuffix("...").rstrip()
    if upstream_truncated or len(text) > 320:
        suffix = " [excerpt truncated]."
        limit = 320 - len(suffix)
        prefix = text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]
        text = (prefix or text[:limit]).rstrip(" ,;:") + suffix
    return _drop_unmatched_parentheses(text)


def _drop_unmatched_parentheses(text: str) -> str:
    open_positions: list[int] = []
    remove: set[int] = set()
    for index, character in enumerate(text):
        if character == "(":
            open_positions.append(index)
        elif character == ")":
            if open_positions:
                open_positions.pop()
            else:
                remove.add(index)
    remove.update(open_positions)
    return "".join(character for index, character in enumerate(text) if index not in remove)


def _stable_locator(row: dict[str, Any]) -> str:
    doi = str(row.get("source_doi") or row.get("doi") or "").strip()
    if doi:
        doi = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", doi, flags=re.I)
        return f"https://doi.org/{doi}"
    pmid = str(row.get("source_pmid") or row.get("pmid") or "").strip()
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
