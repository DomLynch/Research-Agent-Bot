"""Typed validation gates for LLM output. Reject before render.

Six gates, in priority order:
  1. citations resolve         — every [N] in prose maps to a bundle ref
  2. role/prose consistency    — both directions:
        protocol/registered refs cannot 'show'/'reduce' (V0 rapamycin bug)
        published_results refs cannot be 'pending'/'awaited' (inverse class)
  3. numbers traceable         — every effect-size in prose appears in cited abstract
  4. mechanistic hedging       — Tier C cannot carry definitive efficacy claims
  5. completeness              — title + abstract + 5 required sections all present
  6. invariants hold           — extract Facts from prose (kind inferred from
                                 sentence markers, NOT bundle role), then
                                 enforce types.assert_invariants. This makes
                                 the type-level spine load-bearing instead
                                 of dormant.

A `block` failure rejects the draft. draft.py's orchestrator retries the LLM
once with the failure list as a correction prompt; if QA still rejects, the
draft is not rendered for publication.
"""
from __future__ import annotations

import re

from agent.types import (
    Draft,
    EvidenceItem,
    Fact,
    FactKind,
    GateFailure,
    InvariantError,
    QAResult,
    assert_invariants,
)

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

# Definitive-claim phrasings banned for mechanistic (Tier C) refs.
# Tightened to require pairing with an efficacy noun — bare 'definitive'
# in 'definitive human trials are needed' (a legitimate limitation
# statement) used to false-fire. The banned form is e.g. 'established
# efficacy', 'proven benefit', 'conclusively demonstrated reduction'.
_MECHANISTIC_BANNED = re.compile(
    r"(?:established|proven|definitive)\s+(?:that\s+|the\s+|a\s+|an\s+)?"
    r"(?:efficacy|benefit|effect|reduction|improvement|outcome|treatment\s+option)"
    r"|conclusively\s+(?:shows?|showed|demonstrates?|demonstrated|proves?|proved|reduces?|reduced|improves?|improved)"
    r"|clearly\s+(?:shows?|showed|demonstrates?|demonstrated|proves?|proved)",
    re.IGNORECASE,
)

# Pending/awaited language banned for published_results refs.
# Inverse direction of the V0 rapamycin bug class: a published trial
# described as if it were a registered protocol with no outcomes.
_RESULTS_PENDING_BANNED = re.compile(
    r"\b(results?\s+(?:are\s+|is\s+)?(?:pending|awaited|forthcoming|"
    r"unavailable|not\s+yet\s+(?:reported|available|published)|"
    r"to\s+be\s+(?:reported|published|determined))"
    r"|outcomes?\s+(?:are\s+|is\s+)?(?:pending|awaited|not\s+yet|forthcoming)"
    r"|trial\s+(?:is\s+)?(?:planned|registered|underway|ongoing|currently\s+enrolling)"
    r"|study\s+(?:is\s+)?(?:planned|underway|ongoing|currently\s+enrolling|investigating)"
    r"|will\s+(?:report|examine|evaluate|investigate|assess|determine|test)"
    r"|upcoming\s+(?:trial|study|publication))\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences. Conservative — only splits on
    sentence-terminator + whitespace, so phrases like '6MWD decline by 22%'
    stay intact inside their sentence even if the LLM packed several
    sentences into one section-list element."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _all_sentences(draft: Draft) -> list[tuple[str, str]]:
    """Yield (location_label, sentence) for every cite-able sentence.

    Each draft.abstract entry and each draft.sections[k] entry can hold one
    or more sentences as a single string (the LLM sometimes packs them).
    We split into individual sentences before gating so a multi-cite
    paragraph isn't falsely flagged as having both 'reduced' and 'pending'
    semantics on every ref it contains.
    """
    out: list[tuple[str, str]] = []
    for entry in draft.abstract:
        for s in _split_sentences(entry):
            out.append(("abstract", s))
    for section, entries in draft.sections.items():
        for entry in entries:
            for s in _split_sentences(entry):
                out.append((section, s))
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
    """Both directions of the V0 rapamycin bug class:
      - protocol/registered_pending described as if it has results
      - published_results described as if it's still pending
    Plus mechanistic Tier C carrying definitive efficacy claims.
    """
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
            elif item.role == "published_results":
                if _RESULTS_PENDING_BANNED.search(sent):
                    failures.append(GateFailure(
                        code="results_described_as_pending",
                        message=(
                            f"{loc}: ref [{ref}] is role='published_results' but "
                            f"prose treats it as pending/awaited/upcoming: {sent!r}"
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


def _infer_fact_kind(sent: str, item: EvidenceItem) -> FactKind:
    """Infer Fact.kind from PROSE markers (not bundle role).

    This is what makes assert_invariants load-bearing: when the prose-derived
    kind disagrees with the bundle role, the type system raises. Examples:
      "trial showed 22% [1]" + ref[1]=published_protocol   -> kind=result vs
                                                              role=protocol
                                                              -> InvariantError
      "results pending [1]"  + ref[1]=published_results    -> kind=protocol vs
                                                              role=results
                                                              -> InvariantError
    """
    is_outcome_lang = bool(_PROTOCOL_BANNED.search(sent)) or bool(_NUMBER_RE.search(sent))
    is_pending_lang = bool(_RESULTS_PENDING_BANNED.search(sent))
    if is_outcome_lang and not is_pending_lang:
        return "result"
    if is_pending_lang and not is_outcome_lang:
        # Pending language is appropriate for protocol/registered refs and
        # is the INVERSE BUG class for published_results (must surface as
        # protocol kind so assert_invariants raises). For mechanistic/review
        # pending lang is just legitimate hedging of an unfinished study —
        # treat as context citation (no violation).
        if item.role in {"published_protocol", "registered_pending", "published_results"}:
            return "protocol"
        return "context"
    # Sentence has neither marker (or both, ambiguous): fall back to bundle
    # role so we don't manufacture spurious invariant violations.
    if item.role == "published_results":
        return "result"
    if item.role in {"published_protocol", "registered_pending"}:
        return "protocol"
    return "context"


def extract_facts(draft: Draft, by_ref: dict[int, EvidenceItem]) -> list[Fact]:
    """Extract Facts from the draft's cited sentences. Kind is prose-derived."""
    facts: list[Fact] = []
    for _loc, sent in _all_sentences(draft):
        for ref in _refs_in(sent):
            item = by_ref.get(ref)
            if item is None:
                continue
            facts.append(
                Fact(ref=ref, kind=_infer_fact_kind(sent, item), claim=sent[:240])
            )
    return facts


def gate_invariants_hold(
    draft: Draft, by_ref: dict[int, EvidenceItem]
) -> list[GateFailure]:
    """Type-level spine: prose-inferred Fact kinds must pair with bundle roles.

    Scoped to the cited subset of the bundle (the LLM is not required to cite
    every available source). Mutates draft.facts so downstream stages and
    run-logs can see what was extracted.
    """
    facts = extract_facts(draft, by_ref)
    draft.facts = facts
    if not facts:
        return []
    cited_refs = {f.ref for f in facts}
    cited_bundle = [it for ref, it in by_ref.items() if ref in cited_refs]
    try:
        assert_invariants(cited_bundle, facts)
    except InvariantError as exc:
        return [GateFailure(
            code="invariant_violation",
            message=str(exc),
            severity="block",
        )]
    return []


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
    failures.extend(gate_invariants_hold(draft, by_ref))
    score = {
        "citations": 10 if not any(f.code.startswith("citation") for f in failures) else 0,
        "role_consistency": 10 if not any(
            f.code in {
                "protocol_described_as_results",
                "results_described_as_pending",
                "mechanistic_definitive_claim",
            }
            for f in failures
        ) else 0,
        "numeric_fidelity": 10 if not any(f.code.startswith("number_") for f in failures) else 0,
        "completeness": 10 if not any(
            f.code in {"title_empty", "abstract_empty", "section_missing"}
            for f in failures
        ) else 0,
        "invariants": 10 if not any(f.code == "invariant_violation" for f in failures) else 0,
    }
    blocks = [f for f in failures if f.severity == "block"]
    return QAResult(approved=not blocks, failures=tuple(failures), score=score)


def correction_prompt(failures: tuple[GateFailure, ...]) -> str:
    """Format gate failures into a one-shot correction prompt for write_draft."""
    return "; ".join(f"[{f.code}] {f.message}" for f in failures if f.severity == "block")
