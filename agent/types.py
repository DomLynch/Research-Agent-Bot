"""Core types for the research agent pipeline.

Stdlib only. Frozen dataclasses for everything that crosses a stage boundary.

The single invariant that defines the system:
    An EvidenceItem with role="published_results" must be paired with at least
    one Fact of kind="result". An EvidenceItem with role="published_protocol"
    or "registered_pending" must NOT be paired with any Fact of kind="result".

This rule structurally prevents the credibility-fatal contradiction class
(prose says "planned trial, results unavailable" while citing a paper the
bundle has typed as published RCT).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "Role",
    "Tier",
    "Design",
    "FactKind",
    "Query",
    "RawHit",
    "Source",
    "EvidenceItem",
    "Fact",
    "GateFailure",
    "QAResult",
    "Draft",
    "InvariantError",
    "assert_invariants",
]

# --- Enums (Literal aliases — mypy-friendly, zero runtime cost) -------------

Role = Literal[
    "published_results",
    "published_protocol",
    "registered_pending",
    "review",
    "mechanistic",
    "off_domain",
]

Tier = Literal["A1", "A2", "B", "C"]

Design = Literal[
    "rct",
    "observational",
    "review",
    "meta_analysis",
    "protocol",
    "preprint",
    "registry",
    "mechanistic",
    "other",
]

FactKind = Literal["result", "protocol", "context"]


# --- Inputs ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Query:
    """One search query against one source adapter."""

    text: str
    limit: int = 25


@dataclass(frozen=True, slots=True)
class RawHit:
    """Pre-normalization hit from a source adapter. Adapter-shaped."""

    source: str
    title: str
    abstract: str
    year: int | None
    url: str
    doi: str | None = None
    pmid: str | None = None
    nct: str | None = None
    venue: str | None = None
    raw: dict = field(default_factory=dict)


# --- Pipeline objects ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    """Canonical normalized source record. ref is 1-indexed for citation."""

    ref: int
    title: str
    year: int | None
    url: str
    source: str
    doi: str | None = None
    pmid: str | None = None
    nct: str | None = None
    venue: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Bundled view of a Source with deterministic role/tier classification.

    role/tier/direct/strict are pure functions of Source + abstract. They are
    materialized here so downstream stages never recompute or disagree.
    """

    source: Source
    abstract: str
    design: Design
    role: Role
    tier: Tier
    direct: bool
    strict: bool


@dataclass(frozen=True, slots=True)
class Fact:
    """Atomic claim extracted from a Source's abstract.

    Pairing rule (enforced by assert_invariants):
      - kind="result"   <=> role must be "published_results"
      - kind="protocol" <=> role in {"published_protocol", "registered_pending"}
      - kind="context"  <=> role in {"review", "mechanistic"}
    """

    ref: int
    kind: FactKind
    claim: str
    outcome: str | None = None
    estimate: str | None = None
    p_value: str | None = None
    ci: str | None = None


# --- QA outputs ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateFailure:
    code: str
    message: str
    severity: Literal["block", "warn"]


@dataclass(frozen=True, slots=True)
class QAResult:
    approved: bool
    failures: tuple[GateFailure, ...]
    score: dict[str, int]


# --- Draft (mutable during compose, treat as frozen after qa.approved) -----


@dataclass
class Draft:
    """The composed paper. Mutable during compose; treat as immutable after qa."""

    topic: str
    domain: str
    criteria: str
    title: str
    abstract: list[str]
    sections: dict[str, list[str]]
    bundle: list[EvidenceItem]
    facts: list[Fact]


# --- Invariant enforcement -------------------------------------------------


class InvariantError(AssertionError):
    """Raised when the role <-> fact-kind pairing rule is violated."""


_RESULT_ONLY = "published_results"
_PROTOCOL_ROLES = {"published_protocol", "registered_pending"}
_CONTEXT_ROLES = {"review", "mechanistic"}


def assert_invariants(bundle: list[EvidenceItem], facts: list[Fact]) -> None:
    """Raise InvariantError if the role <-> fact-kind pairing rule is violated.

    Enforces TWO directions:
      Forward (per-fact): a Fact's kind must match its EvidenceItem's role.
      Reverse (per-item completeness): an item with role='published_results'
        must carry at least one Fact of kind='result'; an item with role in
        {published_protocol, registered_pending} must carry at least one Fact
        of kind='protocol'. Otherwise the prose can either contradict the
        bundle or silently drop a key finding.

    Call this after bundle() AND after facts() in the pipeline. Calling it
    before facts() are extracted will raise on the completeness check.
    """
    by_ref: dict[int, EvidenceItem] = {item.source.ref: item for item in bundle}

    # Forward direction: every Fact must pair with the right role.
    for fact in facts:
        item = by_ref.get(fact.ref)
        if item is None:
            raise InvariantError(
                f"Fact references unknown source ref={fact.ref}"
            )
        if fact.kind == "result" and item.role != _RESULT_ONLY:
            raise InvariantError(
                f"Fact ref={fact.ref} kind='result' but EvidenceItem.role={item.role!r}; "
                f"only role='published_results' may carry result facts"
            )
        if fact.kind == "protocol" and item.role not in _PROTOCOL_ROLES:
            raise InvariantError(
                f"Fact ref={fact.ref} kind='protocol' but EvidenceItem.role={item.role!r}; "
                f"protocol facts require role in {_PROTOCOL_ROLES}"
            )
        if fact.kind == "context" and item.role not in _CONTEXT_ROLES:
            raise InvariantError(
                f"Fact ref={fact.ref} kind='context' but EvidenceItem.role={item.role!r}; "
                f"context facts require role in {_CONTEXT_ROLES}"
            )

    # Reverse direction: every result/protocol item must carry its kind of fact.
    refs_with_result = {f.ref for f in facts if f.kind == "result"}
    refs_with_protocol = {f.ref for f in facts if f.kind == "protocol"}
    for item in bundle:
        ref = item.source.ref
        if item.role == _RESULT_ONLY and ref not in refs_with_result:
            raise InvariantError(
                f"EvidenceItem ref={ref} role='published_results' has no "
                f"Fact(kind='result'); the bundle would silently drop this finding"
            )
        if item.role in _PROTOCOL_ROLES and ref not in refs_with_protocol:
            raise InvariantError(
                f"EvidenceItem ref={ref} role={item.role!r} has no "
                f"Fact(kind='protocol'); the bundle would carry a registered "
                f"trial with no protocol detail"
            )
