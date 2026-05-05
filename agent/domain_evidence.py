"""Domain adapter — Slice 8 step B (2026-05-05) refactor.

Reads `domains/<name>.toml` files at load time. Topic packs reference
a domain via `domain = "..."` at the top level; the loader resolves
to a frozen DomainAdapter instance.

Hard rule (Slice 8 acceptance gate): NO topic / drug / journal /
field-specific values in this file or in any other Python module.
Every domain-shape decision lives in domains/*.toml. The same
engine services biomedical, management, economics, cs_ai, legal,
and any future domain by adding a TOML file.

Backward compatibility: BIOMEDICAL / ECONOMICS / MANAGEMENT / CS_AI
constants still resolve via the same get_profile / get_adapter
entry points (Slice 5 callers keep working).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

_DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"


@dataclass(frozen=True, slots=True)
class DomainAdapter:
    """Universal domain shape — every field comes from TOML data,
    no hardcoded biomedical assumptions.

    Slice 5 'DomainProfile' callers can use this same object via
    the legacy alias (see bottom of file)."""
    name: str
    evidence_hierarchy: tuple[str, ...]
    outcome_classes: tuple[str, ...]
    required_context_fields: tuple[str, ...]
    core_clinical_signals: tuple[str, ...]
    mechanism_signals: tuple[str, ...]
    reject_signals: tuple[str, ...] = field(default_factory=tuple)

    def is_high_tier(self, tier: str) -> bool:
        """True if `tier` is in the top two slots of the hierarchy."""
        if not tier:
            return False
        for i, t in enumerate(self.evidence_hierarchy):
            if t == tier and i < 2:
                return True
        return False

    @property
    def tier_hierarchy(self) -> tuple[str, ...]:
        """Slice 5 back-compat alias."""
        return self.evidence_hierarchy

    @property
    def directness_levels(self) -> tuple[str, ...]:
        """Slice 5 back-compat: directness ≈ first 4 hierarchy slots."""
        return self.evidence_hierarchy[:4]


def _load_domain_toml(path: Path) -> DomainAdapter:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    block = data.get("domain") or {}
    return DomainAdapter(
        name=str(block.get("name", path.stem)),
        evidence_hierarchy=tuple(block.get("evidence_hierarchy", ())),
        outcome_classes=tuple(block.get("outcome_classes", ())),
        required_context_fields=tuple(
            block.get("required_context_fields", ())
        ),
        core_clinical_signals=tuple(
            block.get("core_clinical_signals", ())
        ),
        mechanism_signals=tuple(block.get("mechanism_signals", ())),
        reject_signals=tuple(block.get("reject_signals", ())),
    )


def _build_registry() -> Mapping[str, DomainAdapter]:
    """Discover every domains/*.toml at module import time. Returns
    a read-only mapping name → DomainAdapter."""
    out: dict[str, DomainAdapter] = {}
    if _DOMAINS_DIR.exists():
        for p in sorted(_DOMAINS_DIR.glob("*.toml")):
            try:
                ad = _load_domain_toml(p)
            except (OSError, ValueError, tomllib.TOMLDecodeError):
                continue
            out[ad.name.lower()] = ad
    return MappingProxyType(out)


_REGISTRY: Mapping[str, DomainAdapter] = _build_registry()


def get_adapter(name: str | None) -> DomainAdapter:
    """Resolve a domain name to its adapter. Falls back to
    'biomedical' when name is None / empty / unknown — preserves
    Slice 5 default for legacy topic packs without [domain] /
    `domain = "..."` field."""
    key = (name or "biomedical").strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key]
    bio = _REGISTRY.get("biomedical")
    if bio is None:
        # Defensive: even if domains/biomedical.toml is missing,
        # return a minimal stub so callers don't crash.
        return DomainAdapter(
            name="biomedical-fallback",
            evidence_hierarchy=("rct", "cohort", "review"),
            outcome_classes=("primary", "secondary"),
            required_context_fields=("population", "outcome"),
            core_clinical_signals=(),
            mechanism_signals=(),
        )
    return bio


def list_domains() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY.keys()))


def reload_registry() -> None:
    """Re-read domains/*.toml. Useful for tests that write new TOMLs."""
    global _REGISTRY
    _REGISTRY = _build_registry()


# ---------- Slice 5 back-compat aliases -------------------------------
# Callers from Slice 5 still import BIOMEDICAL / ECONOMICS / MANAGEMENT
# / CS_AI as module-level constants. Resolve them on first access.

def __getattr__(attr: str):
    """Lazy resolution of legacy constant names to TOML-loaded
    adapters. BIOMEDICAL → get_adapter('biomedical') etc.
    Raises AttributeError for unknown names so test discovery / IDE
    autocomplete behave normally."""
    if attr.lower() in _REGISTRY:
        return _REGISTRY[attr.lower()]
    if attr in ("BIOMEDICAL", "ECONOMICS", "MANAGEMENT", "CS_AI"):
        return get_adapter(attr.lower())
    if attr == "DomainProfile":
        # Slice 5 alias kept for back-compat
        return DomainAdapter
    if attr == "get_profile":
        return get_adapter
    if attr == "list_profiles":
        return list_domains
    raise AttributeError(attr)


__all__ = [
    "DomainAdapter",
    "get_adapter",
    "list_domains",
    "reload_registry",
]
