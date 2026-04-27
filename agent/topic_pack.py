"""Topic pack loader — TOML + stdlib `tomllib`. No third-party YAML libs.

Loads a topic pack file (`topic_packs/<topic>.toml`) into a frozen TopicPack
dataclass and exposes the lookups that downstream stages need:
- alias whitelist (case-insensitive)
- canonical-trial expectations (used by qa_report surface check)
- known_role_overrides — the registry-pinned roles that evidence_cards.py
  consults BEFORE running the deterministic abstract classifier
- forbidden-verb sets for role-claim mismatch checks (consumed by validators.py)

This module owns NO classification logic — it's a pure loader + lookup layer.
Code disposes; this file is the table the code reads.
"""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

__all__ = [
    "OverrideRecord",
    "CanonicalTrial",
    "TopicPack",
    "TopicPackError",
    "load_topic_pack",
]

# Type aliases match agent/types.py Role/Tier/Design literals so a hit in the
# override table is directly assignable to an EvidenceItem field.
_Role = Literal[
    "published_results",
    "published_protocol",
    "registered_pending",
    "review",
    "mechanistic",
    "off_domain",
]
_Tier = Literal["A1", "A2", "B", "C"]
_Design = Literal[
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


class TopicPackError(ValueError):
    """Raised when a topic pack file is malformed."""


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    """One row of `known_role_overrides`. Pins role/design/tier for a registry id."""

    role: _Role
    design: _Design
    tier: _Tier


@dataclass(frozen=True, slots=True)
class CanonicalTrial:
    """One canonical-trial expectation. Used by qa_report surface check."""

    id: str
    name: str
    expected_role: _Role
    design: _Design


@dataclass(frozen=True, slots=True)
class TopicPack:
    """Frozen topic pack. All collections are tuples / frozensets / mappingproxies.

    Aliases are stored lowercase for case-insensitive match. The original
    presentation casings live in `aliases_display` for prompt rendering.
    """

    topic: str
    drug_class: str
    aliases: frozenset[str]                  # lowercase, for matching
    aliases_display: tuple[str, ...]         # original case, for prompts
    expected_evidence_slots: tuple[str, ...]
    special_rules: tuple[str, ...]
    forbidden_verbs_for_protocol_role: frozenset[str]
    forbidden_verbs_for_results_role_with_protocol_keywords: frozenset[str]
    canonical_trials: tuple[CanonicalTrial, ...]
    # MappingProxyType — read-only view; mutation raises TypeError. The
    # frozen dataclass alone does NOT make the dict immutable; we need a
    # proxy wrapper so the registry-pinned roles cannot be overwritten at
    # runtime by any caller (defensive against accidental writes from
    # downstream stages — the table is sacred).
    known_role_overrides: Mapping[str, OverrideRecord]

    # --- Lookups (intentionally explicit, not __contains__-style) ----------

    def has_alias(self, candidate: str) -> bool:
        """Case-insensitive alias whitelist check. Defends planted-failure case 4."""
        return candidate.strip().lower() in self.aliases

    def lookup_role_override(self, registry_id: str | None) -> OverrideRecord | None:
        """Return the pinned override for an NCT/ISRCTN, or None if not in pack.

        Case-insensitive: input is uppercased before the dict lookup, and
        the dict itself is built with uppercase keys at TOML load time
        (see _build_overrides). Both layers must agree on the canonical
        form so misformatted TOML or adapter output cannot silently miss.
        """
        if not registry_id:
            return None
        return self.known_role_overrides.get(registry_id.strip().upper())

    def is_protocol_verb_forbidden(self, verb: str) -> bool:
        return verb.strip().lower() in self.forbidden_verbs_for_protocol_role

    def is_results_protocol_keyword(self, keyword: str) -> bool:
        return (
            keyword.strip().lower()
            in self.forbidden_verbs_for_results_role_with_protocol_keywords
        )


# --- Loader -----------------------------------------------------------------

_REQUIRED_TOP_LEVEL = (
    "topic",
    "class_",
    "aliases",
    "expected_evidence_slots",
    "special_rules",
    "forbidden_verbs_for_protocol_role",
    "forbidden_verbs_for_results_role_with_protocol_keywords",
    "canonical_trials",
    "known_role_overrides",
)

_VALID_ROLES: frozenset[str] = frozenset({
    "published_results", "published_protocol", "registered_pending",
    "review", "mechanistic", "off_domain",
})
_VALID_DESIGNS: frozenset[str] = frozenset({
    "rct", "observational", "review", "meta_analysis",
    "protocol", "preprint", "registry", "mechanistic", "other",
})
_VALID_TIERS: frozenset[str] = frozenset({"A1", "A2", "B", "C"})


def _validate_top_level_keys(data: dict, path: Path) -> None:
    missing = [k for k in _REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise TopicPackError(
            f"{path}: missing top-level keys {missing}. "
            f"TOML scoping bug suspect — top-level keys must be declared "
            f"BEFORE any [section] or [[array]] marker."
        )


def _build_canonical_trials(rows: list[dict], path: Path) -> tuple[CanonicalTrial, ...]:
    out: list[CanonicalTrial] = []
    for i, row in enumerate(rows):
        for key in ("id", "name", "expected_role", "design"):
            if key not in row:
                raise TopicPackError(
                    f"{path}: canonical_trials[{i}] missing key {key!r}"
                )
        if row["expected_role"] not in _VALID_ROLES:
            raise TopicPackError(
                f"{path}: canonical_trials[{i}] invalid role {row['expected_role']!r}"
            )
        if row["design"] not in _VALID_DESIGNS:
            raise TopicPackError(
                f"{path}: canonical_trials[{i}] invalid design {row['design']!r}"
            )
        out.append(CanonicalTrial(
            id=row["id"], name=row["name"],
            expected_role=row["expected_role"], design=row["design"],
        ))
    return tuple(out)


def _build_overrides(raw: dict, path: Path) -> Mapping[str, OverrideRecord]:
    """Build the override map with UPPERCASE keys.

    Canonicalizing the keys at load time means lookup_role_override only
    needs to upper-case its input — both layers agree on the canonical
    form. Without this, a TOML file with lowercase `nctXXX` keys would
    silently fail every lookup. Detecting duplicate keys after
    upper-casing also catches accidental case-only duplicates.
    """
    out: dict[str, OverrideRecord] = {}
    for registry_id, row in raw.items():
        canonical_id = registry_id.strip().upper()
        if canonical_id in out:
            raise TopicPackError(
                f"{path}: duplicate override id {canonical_id!r} "
                f"(after case normalization). Original keys produced this clash."
            )
        registry_id = canonical_id  # use canonical form going forward in this iter
        for key in ("role", "design", "tier"):
            if key not in row:
                raise TopicPackError(
                    f"{path}: known_role_overrides[{registry_id}] missing {key!r}"
                )
        if row["role"] not in _VALID_ROLES:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid role {row['role']!r}"
            )
        if row["design"] not in _VALID_DESIGNS:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid design {row['design']!r}"
            )
        if row["tier"] not in _VALID_TIERS:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid tier {row['tier']!r}"
            )
        out[registry_id] = OverrideRecord(
            role=row["role"], design=row["design"], tier=row["tier"],
        )
    # Wrap in MappingProxyType so the registry-pinned roles are read-only.
    # Any attempt to mutate raises TypeError at runtime.
    return MappingProxyType(out)


def load_topic_pack(path: str | Path) -> TopicPack:
    """Load a topic pack TOML file into a frozen TopicPack.

    Raises TopicPackError on malformed input — preferable to silent
    misclassification later in the pipeline.
    """
    p = Path(path)
    if not p.exists():
        raise TopicPackError(f"topic pack not found: {p}")
    with p.open("rb") as fh:
        data = tomllib.load(fh)

    _validate_top_level_keys(data, p)

    aliases_raw = data["aliases"]
    if not aliases_raw:
        raise TopicPackError(f"{p}: aliases must be non-empty")
    aliases_lower = frozenset(a.strip().lower() for a in aliases_raw)
    aliases_display = tuple(aliases_raw)

    canonical = _build_canonical_trials(data["canonical_trials"], p)
    overrides = _build_overrides(data["known_role_overrides"], p)

    return TopicPack(
        topic=data["topic"],
        drug_class=data["class_"],
        aliases=aliases_lower,
        aliases_display=aliases_display,
        expected_evidence_slots=tuple(data["expected_evidence_slots"]),
        special_rules=tuple(data["special_rules"]),
        forbidden_verbs_for_protocol_role=frozenset(
            v.strip().lower() for v in data["forbidden_verbs_for_protocol_role"]
        ),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(
            v.strip().lower()
            for v in data["forbidden_verbs_for_results_role_with_protocol_keywords"]
        ),
        canonical_trials=canonical,
        known_role_overrides=overrides,
    )
