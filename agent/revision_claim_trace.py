"""Deterministic source binding for reviewer-requested major-claim traces."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agent.publication_evidence import attach_bundle_references


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
    required = _requested_count(ask, len(rows))
    manuscript = _without_trace(paper_md)
    source_bound_claims = {
        (claim, bundle_number)
        for claim, bundle_number, _row in _source_bound_claims(manuscript, rows)
    }
    valid: set[str] = set()
    for line in _scope(paper_md).splitlines():
        match = re.match(
            r"^- \*\*Manuscript claim \d+\.\*\* (.*?) "
            r"\*\*Supporting source:\*\* .*?\[bundle:(\d+)\] .*?"
            r"\*\*Evidence span:\*\* (.+)$",
            line,
            re.I,
        )
        if not match:
            continue
        claim = match.group(1).strip()
        bundle_number = int(match.group(2))
        if not 1 <= bundle_number <= len(rows):
            continue
        row = rows[bundle_number - 1]
        support = f"{_label(row)} [bundle:{bundle_number}]"
        locator = _stable_locator(row)
        if locator:
            support += f" {locator}"
        if (
            _evidence_span(row)
            and (claim, bundle_number) in source_bound_claims
            and f"[bundle:{bundle_number}]" in claim
            and f"**Supporting source:** {support}" in line
            and match.group(3).strip() == _evidence_span(row)
        ):
            valid.add(claim)
    return bool(required and len(valid) >= required)


def repair_major_claim_trace(
    paper_md: str,
    ask: str,
    rows: Sequence[dict[str, Any]],
) -> tuple[str, int]:
    if major_claim_trace_is_stated(paper_md, ask, rows):
        return paper_md, 0
    patched = attach_bundle_references(paper_md, rows)
    claims = _source_bound_claims(patched, rows)
    if not claims:
        return patched, int(patched != paper_md)
    lines = ["## Major Claim Trace", ""]
    for claim_number, (claim, bundle_number, row) in enumerate(
        claims[:_requested_count(ask, len(claims))],
        start=1,
    ):
        support = f"{_label(row)} [bundle:{bundle_number}]"
        if locator := _stable_locator(row):
            support += f" {locator}"
        lines.append(
            f"- **Manuscript claim {claim_number}.** {claim} "
            f"**Supporting source:** {support} "
            f"**Evidence span:** {_evidence_span(row)}"
        )
    section = "\n".join(lines).rstrip() + "\n\n"
    existing = _scope(patched)
    if existing:
        patched = patched.replace(existing, section, 1)
    elif references := re.search(r"^## References\b", patched, re.M | re.I):
        patched = patched[:references.start()] + section + patched[references.start():]
    else:
        patched = patched.rstrip() + "\n\n" + section
    return patched, 1


def _requested_count(ask: str, available: int) -> int:
    match = re.search(r"\brequired\s+(\d+)\b", ask, re.I)
    requested = int(match.group(1)) if match else min(16, available)
    return max(1, requested)


def _scope(paper_md: str) -> str:
    match = re.search(
        r"^## Major Claim Trace\b.*?(?=^## |\Z)",
        paper_md,
        re.M | re.S | re.I,
    )
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
        ):
            continue
        for claim in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", stripped):
            bundle_numbers = [
                int(value) for value in re.findall(r"\[bundle:(\d+)\]", claim, re.I)
            ]
            candidates = [
                number for number in bundle_numbers if 1 <= number <= len(rows)
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
    return [
        (claim, bundle_number, row)
        for _priority, _order, claim, bundle_number, row in sorted(claims)
    ]


def _label(row: dict[str, Any]) -> str:
    return str(
        row.get("citation_token") or row.get("cited_as") or row.get("body_citation")
        or row.get("receipt_id") or ""
    ).strip()


def _evidence_span(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get("thesis_text") or row.get("source_title") or "").split())
    if "source excerpts:" in text.lower():
        text = re.split(r"source excerpts:\s*", text, maxsplit=1, flags=re.I)[1]
    text = text.split(" | ", 1)[0].replace("|", " ").strip()
    text = text if len(text) <= 320 else text[:317].rstrip() + "..."
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
        return f"[DOI](https://doi.org/{doi})"
    pmid = str(row.get("source_pmid") or row.get("pmid") or "").strip()
    return f"[PMID](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)" if pmid else ""
