"""Typed validation gates for LLM output. Reject before render.

Five gates, in priority order:
  1. citations resolve         — every [N] in prose maps to a bundle ref
  2. role/prose consistency    — protocol/registered refs cannot 'show', 'reduce', etc.
  3. numbers traceable         — every effect-size in prose appears in cited abstract
  4. mechanistic hedging       — Tier C cannot carry definitive efficacy claims
  5. completeness              — title + abstract + 5 required sections all present

A `block` failure rejects the draft. draft.py's orchestrator retries the LLM
once with the failure list as a correction prompt; if QA still rejects, the
draft is not rendered for publication.
"""
from __future__ import annotations

import re

from agent.types import Draft, EvidenceItem, GateFailure, QAResult

REQUIRED_SECTIONS = ("introduction", "methods", "findings", "limitations", "conclusion")

_CITATION_RE = re.compile(r"\[(\d+)\]")

# Effect-size markers that must be traceable to a cited abstract.
_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*%"
    r"|p\s*[<=>]\s*0?\.\d+"
    r"|(?:hr|or|rr)\s*=?\s*\d+(?:\.\d+)?"
    r"|95\s*%\s*ci"
    r"|n\s*=\s*\d{2,})",
    re.IGNORECASE,
)

# Verbs/phrases that imply a reported outcome — banned for protocol/pending refs.
_PROTOCOL_BANNED = re.compile(
    r"\b(showed|demonstrated|reduced|improved|reversed|attenuated|"
    r"increased|decreased|lowered|raised|achieved|"
    r"resulted in (?:a|an|significant|measurable|the)|"
    r"led to (?:a|an|significant|measurable)|"
    r"the (?:trial|study) (?:showed|demonstrated|reported|found)|"
    r"reported (?:a|an|the) (?:effect|benefit|reduction|improvement|outcome))\b",
    re.IGNORECASE,
)

# Definitive-claim verbs banned for mechanistic (Tier C) refs.
_MECHANISTIC_BANNED = re.compile(
    r"\b(established|proven|definitive|conclusively (?:shows?|demonstrates?)|"
    r"clearly (?:shows?|demonstrates?))\b",
    re.IGNORECASE,
)


def _all_sentences(draft: Draft) -> list[tuple[str, str]]:
    """Yield (location_label, sentence) for every cite-able sentence."""
    out: list[tuple[str, str]] = []
    for sent in draft.abstract:
        out.append(("abstract", sent))
    for section, sentences in draft.sections.items():
        for sent in sentences:
            out.append((section, sent))
    return out


def _refs_in(sent: str) -> set[int]:
    return {int(m.group(1)) for m in _CITATION_RE.finditer(sent)}


def gate_citations_resolve(
    draft: Draft, by_ref: dict[int, EvidenceItem]
) -> list[GateFailure]:
    failures: list[GateFailure] = []
    for loc, sent in _all_sentences(draft):
        for ref in _refs_in(sent):
            if ref not in by_ref:
                failures.append(GateFailure(
                    code="citation_unresolved",
                    message=f"{loc}: [{ref}] is not in the bundle. Sentence: {sent!r}",
                    severity="block",
                ))
    return failures


def gate_role_prose_consistency(
    draft: Draft, by_ref: dict[int, EvidenceItem]
) -> list[GateFailure]:
    """The rapamycin bug class: a protocol or registered-pending ref described
    as having reported an outcome."""
    failures: list[GateFailure] = []
    for loc, sent in _all_sentences(draft):
        for ref in _refs_in(sent):
            item = by_ref.get(ref)
            if item is None:
                continue
            if item.role in {"published_protocol", "registered_pending"}:
                if _PROTOCOL_BANNED.search(sent):
                    failures.append(GateFailure(
                        code="protocol_described_as_results",
                        message=(
                            f"{loc}: ref [{ref}] is role={item.role!r} but prose "
                            f"reports an outcome: {sent!r}"
                        ),
                        severity="block",
                    ))
            if item.role == "mechanistic":
                if _MECHANISTIC_BANNED.search(sent):
                    failures.append(GateFailure(
                        code="mechanistic_definitive_claim",
                        message=(
                            f"{loc}: ref [{ref}] is mechanistic (Tier C) but prose "
                            f"makes a definitive efficacy claim: {sent!r}"
                        ),
                        severity="block",
                    ))
    return failures


def gate_numbers_traceable(
    draft: Draft, by_ref: dict[int, EvidenceItem]
) -> list[GateFailure]:
    """Every numeric effect-size claim must appear in a cited source's abstract."""
    failures: list[GateFailure] = []
    for loc, sent in _all_sentences(draft):
        numbers = _NUMBER_RE.findall(sent)
        if not numbers:
            continue
        cited = _refs_in(sent)
        if not cited:
            failures.append(GateFailure(
                code="number_uncited",
                message=f"{loc}: numeric claim with no citation: {sent!r}",
                severity="block",
            ))
            continue
        haystack = re.sub(r"\s+", "", " ".join(
            (by_ref[r].abstract or "").lower() for r in cited if r in by_ref
        ))
        for number in numbers:
            normalized = re.sub(r"\s+", "", number.lower())
            if normalized not in haystack:
                failures.append(GateFailure(
                    code="number_not_in_source",
                    message=(
                        f"{loc}: '{number}' not found in cited abstracts "
                        f"for refs {sorted(cited)}"
                    ),
                    severity="block",
                ))
    return failures


def gate_completeness(draft: Draft) -> list[GateFailure]:
    failures: list[GateFailure] = []
    if not (draft.title or "").strip():
        failures.append(GateFailure("title_empty", "title is required", "block"))
    if not draft.abstract or not any(s.strip() for s in draft.abstract):
        failures.append(GateFailure("abstract_empty", "abstract is required", "block"))
    for required in REQUIRED_SECTIONS:
        sentences = draft.sections.get(required, [])
        if not sentences or not any(s.strip() for s in sentences):
            failures.append(GateFailure(
                code="section_missing",
                message=f"required section '{required}' is missing or empty",
                severity="block",
            ))
    return failures


def qa(draft: Draft) -> QAResult:
    by_ref = {item.source.ref: item for item in draft.bundle}
    failures: list[GateFailure] = []
    failures.extend(gate_citations_resolve(draft, by_ref))
    failures.extend(gate_role_prose_consistency(draft, by_ref))
    failures.extend(gate_numbers_traceable(draft, by_ref))
    failures.extend(gate_completeness(draft))
    score = {
        "citations": 10 if not any(f.code.startswith("citation") for f in failures) else 0,
        "role_consistency": 10 if not any(
            f.code in {"protocol_described_as_results", "mechanistic_definitive_claim"}
            for f in failures
        ) else 0,
        "numeric_fidelity": 10 if not any(f.code.startswith("number_") for f in failures) else 0,
        "completeness": 10 if not any(
            f.code in {"title_empty", "abstract_empty", "section_missing"}
            for f in failures
        ) else 0,
    }
    blocks = [f for f in failures if f.severity == "block"]
    return QAResult(approved=not blocks, failures=tuple(failures), score=score)


def correction_prompt(failures: tuple[GateFailure, ...]) -> str:
    """Format gate failures into a one-shot correction prompt for write_draft."""
    return "; ".join(f"[{f.code}] {f.message}" for f in failures if f.severity == "block")
