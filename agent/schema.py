from __future__ import annotations

from typing import Mapping, NotRequired, TypedDict


class EffectDict(TypedDict):
    outcome: str
    metric: str
    value: str
    ci_low: str
    ci_high: str
    p_value: str
    n: str
    source_span: str


class ExtractionDict(TypedDict):
    primary_outcome: str
    population: str
    intervention: str
    comparator: str
    methods_summary: str
    risk_of_bias: str
    effects: list[EffectDict]
    extractor_version: str
    source_doi: str
    found: bool


class EvidenceCardDict(TypedDict):
    citation: str
    journal: str
    quality_signal: str
    evidence_grade: str
    study_type: str
    context: str
    population: str
    intervention: str
    outcomes: str
    comparator: str
    methods_summary: str
    risk_of_bias: str
    effects: list[EffectDict]
    full_text_source: str
    full_text_found: bool
    extraction_found: bool
    extractor_version: str


class SourceEntryDict(TypedDict):
    id: str
    title: str
    excerpt: str
    url: str
    source_type: str
    evidence_type: str
    doi: NotRequired[str | None]
    year: NotRequired[int | None]
    journal: NotRequired[str | None]
    authors: NotRequired[list[str]]
    query: NotRequired[str]
    full_text: NotRequired[str]
    full_text_source: NotRequired[str]
    full_text_sections: NotRequired[Mapping[str, str]]
    extraction: NotRequired[ExtractionDict]
    has_results: NotRequired[bool]


class SourceReviewEntry(TypedDict):
    doi: str
    title: str
    year: int
    journal: str
    url: NotRequired[str]


class QuantitativeClaim(TypedDict):
    claim: str
    source_doi: str


class VerificationNotes(TypedDict):
    dropped_dois: NotRequired[list[str]]


class GoldTopicDict(TypedDict):
    topic: str
    domain: str
    criteria: str
    source_review: SourceReviewEntry
    conclusion_direction: str
    limitations: list[str]
    last_validated: str
    curator: str
    included_dois: NotRequired[list[str]]
    conclusion_summary: NotRequired[str]
    quantitative_claims: NotRequired[list[QuantitativeClaim]]
    doi_verified: NotRequired[bool]
    doi_verified_at: NotRequired[str]
    verification_notes: NotRequired[VerificationNotes]
