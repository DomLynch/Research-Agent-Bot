"""Risk-of-bias dataclass schema for RCT (RoB 2), observational (ROBINS-I),
and animal (SYRCLE) studies.

Phase 4 of the WORLDCLASS rapamycin sprint. Stdlib-only, no external deps,
no LLM. Strict validation at construction time: invalid domain or rating
raises ValueError; missing required domains raises ValueError.

Hard rule: LLM PROPOSES, CODE DISPOSES. The schema is the gate; the
extractor (a separate concern) populates it from source text.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DesignType",
    "Tool",
    "Rating",
    "VALID_RATINGS",
    "ROB2_DOMAINS",
    "ROBINS_I_DOMAINS",
    "SYRCLE_DOMAINS",
    "DOMAINS_BY_TOOL",
    "DEFAULT_TOOL_FOR_DESIGN",
    "DomainAssessment",
    "StudyAssessment",
]

DesignType = Literal["rct", "observational", "animal"]
Tool = Literal["rob2", "robins_i", "syrcle"]
Rating = Literal["low", "some_concerns", "high", "unclear"]

VALID_RATINGS: frozenset[str] = frozenset(("low", "some_concerns", "high", "unclear"))

# RoB 2 — five domains for RCTs (Cochrane RoB 2.0).
ROB2_DOMAINS: tuple[str, ...] = (
    "randomization",
    "deviations",
    "missing_data",
    "outcome_measurement",
    "selective_reporting",
)

# ROBINS-I — seven domains for non-randomised studies of interventions.
ROBINS_I_DOMAINS: tuple[str, ...] = (
    "confounding",
    "selection",
    "intervention_classification",
    "deviations",
    "missing_data",
    "outcome_measurement",
    "selective_reporting",
)

# SYRCLE — seven canonical risk-of-bias domains for animal studies.
SYRCLE_DOMAINS: tuple[str, ...] = (
    "sequence_generation",
    "baseline",
    "allocation_concealment",
    "random_housing",
    "blinding",
    "incomplete_data",
    "selective_reporting",
)

DOMAINS_BY_TOOL: Mapping[str, tuple[str, ...]] = {
    "rob2": ROB2_DOMAINS,
    "robins_i": ROBINS_I_DOMAINS,
    "syrcle": SYRCLE_DOMAINS,
}

DEFAULT_TOOL_FOR_DESIGN: Mapping[str, str] = {
    "rct": "rob2",
    "observational": "robins_i",
    "animal": "syrcle",
}

_VALID_DESIGNS: frozenset[str] = frozenset(("rct", "observational", "animal"))
_VALID_TOOLS: frozenset[str] = frozenset(DOMAINS_BY_TOOL.keys())


@dataclass(frozen=True, slots=True)
class DomainAssessment:
    """One domain-level RoB judgment.

    Validation: rating must be one of VALID_RATINGS. Domain is validated at
    StudyAssessment level (since allowed domains depend on tool)."""

    domain: str
    rating: Rating
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.rating not in VALID_RATINGS:
            raise ValueError(
                f"invalid rating {self.rating!r}; must be one of {sorted(VALID_RATINGS)}"
            )
        if not self.domain:
            raise ValueError("domain must be a non-empty string")


@dataclass(frozen=True, slots=True)
class StudyAssessment:
    """Per-study RoB / ROBINS-I / SYRCLE judgment.

    Validation rules (all enforced at construction):
      - design ∈ {rct, observational, animal}
      - tool   ∈ {rob2, robins_i, syrcle}
      - overall_rating ∈ VALID_RATINGS
      - domains: every required domain for the tool must be present, exactly
        once; no extra/unknown domains allowed; each domain rating valid.
    """

    study_id: str
    design: DesignType
    tool: Tool
    domains: tuple[DomainAssessment, ...]
    overall_rating: Rating
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.study_id:
            raise ValueError("study_id must be a non-empty string")
        if self.design not in _VALID_DESIGNS:
            raise ValueError(
                f"invalid design {self.design!r}; must be one of {sorted(_VALID_DESIGNS)}"
            )
        if self.tool not in _VALID_TOOLS:
            raise ValueError(
                f"invalid tool {self.tool!r}; must be one of {sorted(_VALID_TOOLS)}"
            )
        expected_tool = DEFAULT_TOOL_FOR_DESIGN[self.design]
        if self.tool != expected_tool:
            raise ValueError(
                f"incompatible design/tool pair: design={self.design!r} "
                f"requires tool={expected_tool!r}, got {self.tool!r}"
            )
        if self.overall_rating not in VALID_RATINGS:
            raise ValueError(
                f"invalid overall_rating {self.overall_rating!r}; "
                f"must be one of {sorted(VALID_RATINGS)}"
            )
        required = set(DOMAINS_BY_TOOL[self.tool])
        present = [d.domain for d in self.domains]
        present_set = set(present)
        # Duplicate domains within a study are forbidden.
        if len(present) != len(present_set):
            duplicates = sorted({d for d in present if present.count(d) > 1})
            raise ValueError(
                f"duplicate domain(s) for {self.tool}: {duplicates}"
            )
        missing = required - present_set
        if missing:
            raise ValueError(
                f"missing required domain(s) for {self.tool}: {sorted(missing)}"
            )
        unknown = present_set - required
        if unknown:
            raise ValueError(
                f"unknown domain(s) for {self.tool}: {sorted(unknown)}"
            )

    def domain_map(self) -> dict[str, Rating]:
        """Return a domain → rating dict in the canonical tool-domain order."""
        by_name = {d.domain: d.rating for d in self.domains}
        return {name: by_name[name] for name in DOMAINS_BY_TOOL[self.tool]}


def required_domains_for(tool: str) -> tuple[str, ...]:
    """Return the canonical-order required domain tuple for a tool."""
    if tool not in DOMAINS_BY_TOOL:
        raise ValueError(f"invalid tool {tool!r}")
    return DOMAINS_BY_TOOL[tool]


def assert_studies_unique(studies: Iterable[StudyAssessment]) -> None:
    """Raise ValueError if any study_id appears more than once."""
    seen: dict[str, int] = {}
    for s in studies:
        seen[s.study_id] = seen.get(s.study_id, 0) + 1
    duplicates = sorted([sid for sid, count in seen.items() if count > 1])
    if duplicates:
        raise ValueError(f"duplicate study_id(s): {duplicates}")
