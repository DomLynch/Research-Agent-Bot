"""GRADE (Grading of Recommendations Assessment, Development and Evaluation)
dataclass schema for outcome-level certainty assessment.

Phase 4 of the WORLDCLASS rapamycin sprint. Stdlib-only.

Strict validation at construction time:
  - starting_certainty must be one of VALID_CERTAINTY
  - downgrade reasons must be one of VALID_DOWNGRADE
  - upgrade reasons must be one of VALID_UPGRADE
  - downgrade levels: 1 or 2
  - upgrade levels: 1
  - final_certainty (computed) is clamped to [very_low, high]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "Certainty",
    "DowngradeReason",
    "UpgradeReason",
    "VALID_CERTAINTY",
    "VALID_DOWNGRADE",
    "VALID_UPGRADE",
    "DowngradeAdjustment",
    "UpgradeAdjustment",
    "GradeAssessment",
    "starting_certainty_for_design",
]

Certainty = Literal["high", "moderate", "low", "very_low"]
DowngradeReason = Literal[
    "rob", "inconsistency", "indirectness", "imprecision", "publication_bias"
]
UpgradeReason = Literal["large_effect", "dose_response", "plausible_confounding"]

VALID_CERTAINTY: frozenset[str] = frozenset(("high", "moderate", "low", "very_low"))
VALID_DOWNGRADE: frozenset[str] = frozenset(
    ("rob", "inconsistency", "indirectness", "imprecision", "publication_bias")
)
VALID_UPGRADE: frozenset[str] = frozenset(
    ("large_effect", "dose_response", "plausible_confounding")
)

# Numeric levels for arithmetic. Higher = stronger evidence.
_CERTAINTY_LEVEL: dict[str, int] = {
    "very_low": 1,
    "low": 2,
    "moderate": 3,
    "high": 4,
}
_LEVEL_TO_CERTAINTY: dict[int, str] = {v: k for k, v in _CERTAINTY_LEVEL.items()}
_MIN_LEVEL = 1
_MAX_LEVEL = 4


@dataclass(frozen=True, slots=True)
class DowngradeAdjustment:
    """One GRADE downgrade. levels is 1 (serious) or 2 (very serious).

    Validation: reason ∈ VALID_DOWNGRADE, levels ∈ {1, 2}."""

    reason: DowngradeReason
    levels: int
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.reason not in VALID_DOWNGRADE:
            raise ValueError(
                f"invalid downgrade reason {self.reason!r}; "
                f"must be one of {sorted(VALID_DOWNGRADE)}"
            )
        if self.levels not in (1, 2):
            raise ValueError(
                f"downgrade levels must be 1 or 2, got {self.levels}"
            )


@dataclass(frozen=True, slots=True)
class UpgradeAdjustment:
    """One GRADE upgrade. Only 1 level per upgrade per GRADE convention.

    Validation: reason ∈ VALID_UPGRADE, levels == 1."""

    reason: UpgradeReason
    levels: int
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.reason not in VALID_UPGRADE:
            raise ValueError(
                f"invalid upgrade reason {self.reason!r}; "
                f"must be one of {sorted(VALID_UPGRADE)}"
            )
        if self.levels != 1:
            raise ValueError(
                f"upgrade levels must be 1, got {self.levels}"
            )


@dataclass(frozen=True, slots=True)
class GradeAssessment:
    """Per-outcome GRADE judgment.

    starting_certainty:
      - "high" for body of evidence dominated by RCTs.
      - "low"  for body of evidence dominated by observational studies.
      - "moderate" / "very_low" allowed only if a non-standard starting
        point is justified (validated as long as it is a valid value).

    final_certainty (computed):
      starting_level - sum(downgrades.levels) + sum(upgrades.levels),
      clamped to [very_low (1), high (4)].
    """

    outcome: str
    starting_certainty: Certainty
    downgrades: tuple[DowngradeAdjustment, ...] = ()
    upgrades: tuple[UpgradeAdjustment, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.outcome:
            raise ValueError("outcome must be a non-empty string")
        if self.starting_certainty not in VALID_CERTAINTY:
            raise ValueError(
                f"invalid starting_certainty {self.starting_certainty!r}; "
                f"must be one of {sorted(VALID_CERTAINTY)}"
            )

    @property
    def downgrade_total(self) -> int:
        return sum(d.levels for d in self.downgrades)

    @property
    def upgrade_total(self) -> int:
        return sum(u.levels for u in self.upgrades)

    @property
    def final_certainty(self) -> Certainty:
        start = _CERTAINTY_LEVEL[self.starting_certainty]
        delta = self.downgrade_total - self.upgrade_total
        final_level = start - delta
        final_level = max(_MIN_LEVEL, min(_MAX_LEVEL, final_level))
        return _LEVEL_TO_CERTAINTY[final_level]  # type: ignore[return-value]

    @property
    def downgrade_reasons(self) -> tuple[DowngradeReason, ...]:
        return tuple(d.reason for d in self.downgrades)

    @property
    def upgrade_reasons(self) -> tuple[UpgradeReason, ...]:
        return tuple(u.reason for u in self.upgrades)


def starting_certainty_for_design(design: str) -> Certainty:
    """Convenience: standard GRADE starting points by design."""
    if design == "rct":
        return "high"
    if design == "observational":
        return "low"
    if design == "animal":
        return "low"  # animal evidence treated as observational-tier for human inference
    raise ValueError(f"unknown design {design!r}")
