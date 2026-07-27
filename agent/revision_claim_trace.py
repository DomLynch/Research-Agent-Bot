"""Deterministic source binding for reviewer-requested major-claim traces."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agent.publication_evidence import attach_bundle_references, ordered_source_rows

_TRACE_LINE_RE = re.compile(
    r"^- \*\*Manuscript claim (?P<number>\d+)\.\*\* (?P<claim>.*?) "
    r"\*\*Supporting source:\*\* "
    r"(?P<support>.*?\[bundle:(?P<bundle>\d+)\].*?) "
    r"\*\*Evidence span:\*\* (?P<span>.+)$",
    re.I,
)
_ABBREVIATION_RE = re.compile(r"\b(?:vs|e\.g|i\.e|et al)\.", re.I)
_PROTECTED_PERIOD = "\ue000"
_NON_CLAIM_PREFIXES = (
    "Evidence-type reconciliation:",
    "Source-direction reconciliation (",
    "Source-statistic reconciliation (",
    "Source-scope boundary (",
)
def asks_major_claim_trace(text: str) -> bool:
    return "major claim" in text and any(token in text for token in (
        "exact source token",
        "doi/pmid",
        "doi or pmid",
        "evidence span",
        "exactly traceable",
    ))


def major_claim_trace_is_stated(
    paper_md: str,
    ask: str,
    rows: Sequence[dict[str, Any]],
) -> bool:
    rows = _ordered_rows(rows)
    manuscript = _without_trace(paper_md)
    claims = _source_bound_claims(manuscript, rows)
    required = _requested_count(ask, len(claims))
    valid = {
        claim
        for claim, bundle_number, row in claims
        if _stable_locator(row) and _stable_locator(row) in claim
        and f"[bundle:{bundle_number}]" in claim
    }
    return bool(required and len(valid) >= required)


def strip_validated_trace_support(
    paper_md: str,
    rows: Sequence[dict[str, Any]],
) -> str:
    """Hide only manifest-verified support metadata from numeric prose audit."""
    rows = _ordered_rows(rows)
    scope = _scope(paper_md)
    if not scope:
        return paper_md
    source_bound_claims = {
        (claim, bundle_number)
        for claim, bundle_number, _row in _source_bound_claims(paper_md, rows)
    }
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
    support = f"{_label(row)} [bundle:{bundle_number}]"
    if locator := _stable_locator(row):
        support += f" {locator}"
    return bool(
        _evidence_span(row)
        and (claim, bundle_number) in source_bound_claims
        and f"[bundle:{bundle_number}]" in claim
        and match.group("support").strip() == support
        and match.group("span").strip() == _evidence_span(row)
    )


def repair_major_claim_trace(
    paper_md: str,
    ask: str,
    rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    rows = _ordered_rows(rows)
    patched = attach_bundle_references(_without_trace(paper_md), rows)
    eligible = [(number, row) for number, row in enumerate(rows, 1) if _stable_locator(row)]
    section = ""
    for line in patched.splitlines():
        if heading := re.match(r"^##+\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
        text = line.strip()
        words = set(re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()))
        matches = [item for item in eligible if words & set(re.findall(
            r"[a-z][a-z0-9-]{3,}", str(item[1].get("outcome_class") or "").lower(),
        ))]
        if (
            (matches or "conclusion" in section) and re.search(r"(abstract|result|synthesis|conclusion)", section)
            and len(text) >= 60 and text.endswith((".", "!", "?"))
            and "[bundle:" not in text.lower()
            and not re.search(r"\([A-Z][^)]*\b20\d{2}\)", text)
            and not text.startswith(("#", "-", "|", "```", *_NON_CLAIM_PREFIXES))
        ):
            number, row = min(matches or eligible, key=lambda item: (
                str(item[1].get("directness") or "").lower() != "direct", item[0],
            ))
            anchor = f"{text[:-1]} (evidence anchor: {_label(row)} [bundle:{number}]){text[-1]}"
            patched = patched.replace(line, anchor, 1)
    claims = _source_bound_claims(patched, rows)
    for claim, _bundle_number, row in claims:
        locator = _stable_locator(row)
        if locator and (locator not in claim or f"[bundle:{_bundle_number}]" not in claim):
            traced = _append_inline_locator(claim, locator) if locator not in claim else claim
            patched = patched.replace(claim, traced if f"[bundle:{_bundle_number}]" in traced else f"{traced[:-1]} [bundle:{_bundle_number}]{traced[-1]}", 1)
    return patched, int(patched != paper_md)


def _append_inline_locator(claim: str, locator: str) -> str:
    suffix = ""
    if claim.endswith((".", "!", "?")):
        claim, suffix = claim[:-1], claim[-1]
    return f"{claim} [exact source: {locator}]{suffix}"


def _requested_count(ask: str, available: int) -> int:
    requested = int(match.group(1)) if (match := re.search(r"\brequired\s+(\d+)\b", ask, re.I)) else min(16, available)
    return max(1, requested)


def _scope(paper_md: str) -> str:
    match = re.search(r"^## Major Claim Trace\b.*?(?=^## |\Z)", paper_md, re.M | re.S | re.I)
    return match.group(0) if match else ""


def _without_trace(paper_md: str) -> str:
    scope = _scope(paper_md)
    return paper_md.replace(scope, "", 1) if scope else paper_md


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
        protected = _ABBREVIATION_RE.sub(
            lambda match: match.group(0)[:-1] + _PROTECTED_PERIOD,
            stripped,
        )
        for claim in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", protected):
            claim = _drop_unmatched_parentheses(claim.replace(_PROTECTED_PERIOD, "."))
            source = claim if "[bundle:" in claim or not re.search(r"(abstract|result|synthesis|conclusion)", section) else stripped
            candidates = [
                int(value) for value in re.findall(r"\[bundle:(\d+)\]", source, re.I)
                if 1 <= int(value) <= len(rows)
            ]
            key = " ".join(claim.casefold().split())
            if not candidates or key in seen:
                continue
            seen.add(key)
            bundle_number = min(candidates, key=lambda number: (
                str(rows[number - 1].get("directness") or "").lower() != "direct",
                not str(rows[number - 1].get("evidence_tier") or "").upper().startswith("A"),
                number,
            ))
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
    values = list(rows)
    return ordered_source_rows(values, {str(row.get("receipt_id") or ""): row for row in values})


def _label(row: dict[str, Any]) -> str:
    value = row.get("citation_token") or row.get("cited_as") or row.get("body_citation")
    return str(value or row.get("receipt_id") or "").strip()


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
