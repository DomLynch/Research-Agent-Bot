"""Domain-pack vocab loader (Phase 7 + Refactor 2026-05-04).

Each `scripts/vocab/<domain>.py` module exposes:
  - ENDPOINT_VOCAB: tuple[(canonical_name, regex_pattern), ...]
  - ENDPOINT_TO_OUTCOME_CLASS: dict[canonical_name, outcome_class]
  - ENDPOINT_POLARITY: dict[canonical_name, +1|-1]
  - ARM_VOCAB: tuple[(canonical_name, regex_pattern), ...]

The runtime caller selects via env var `TOPIC_DOMAIN`.

Refactor 2026-05-04: removed the _KNOWN_DOMAINS gate. When no
explicit vocab/<topic>.py exists, the loader auto-generates a
synthetic vocab module from the topic pack's active_arm_synonyms +
endpoint_polarity (defaults to metformin's ENDPOINT_VOCAB regex
patterns since cardiometabolic endpoints are highly shared across
drugs). This means new topics work via TOML alone, no Python file
needed per topic.
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _resolve_domain() -> str:
    """Return the active domain name. No allow-list — any topic
    is valid; if no vocab/<topic>.py exists, _synthesize_from_pack
    builds a generic vocab from the topic pack TOML."""
    return (
        os.environ.get("TOPIC_DOMAIN")
        or "metformin"
    ).strip().lower()


def _synthesize_from_pack(domain: str) -> Any:
    """Build a synthetic vocab module from the topic pack TOML.

    Strategy:
    - ARM_VOCAB: derived from pack.active_arm_synonyms +
      pack.placebo_arm_synonyms — no hardcoded drug names.
    - ENDPOINT_VOCAB / ENDPOINT_TO_OUTCOME_CLASS / ENDPOINT_POLARITY:
      inherit from metformin pack (cardiometabolic endpoints overlap
      across most drugs in scope: HbA1c, mortality, body weight,
      blood pressure, frailty, sarcopenia, etc.). Topics that need
      domain-specific endpoints can still override by creating
      vocab/<topic>.py.
    """
    repo = Path(__file__).resolve().parent.parent.parent
    tp_path = repo / "topic_packs" / f"{domain}.toml"
    if not tp_path.exists():
        # No pack at all — fall back to metformin
        return importlib.import_module("vocab.metformin")
    import sys
    sys.path.insert(0, str(repo))
    from agent.topic_pack import load_topic_pack
    pack = load_topic_pack(tp_path)
    # Inherit endpoint vocab from metformin (most shared across
    # cardiometabolic / aging drugs; can be overridden via per-topic
    # vocab/<topic>.py if needed).
    base = importlib.import_module("vocab.metformin")
    ENDPOINT_VOCAB = base.ENDPOINT_VOCAB
    ENDPOINT_TO_OUTCOME_CLASS = base.ENDPOINT_TO_OUTCOME_CLASS
    ENDPOINT_POLARITY = base.ENDPOINT_POLARITY
    # Build ARM_VOCAB from topic pack's active + placebo synonyms.
    # Order: longer/more-specific patterns first; bare keywords last.
    arm_patterns: list[tuple[str, str]] = []
    # Modified-noun forms for each active arm synonym
    for syn in sorted(pack.active_arm_synonyms, key=len, reverse=True):
        canon = syn  # use the synonym as canonical
        esc = re.escape(syn)
        arm_patterns.append((
            canon,
            rf"\b{esc}\s+(?:group|arm|treatment|cohort)|"
            rf"\b{esc}-?treated",
        ))
    # Placebo modified-noun forms
    for syn in sorted(pack.placebo_arm_synonyms, key=len, reverse=True):
        esc = re.escape(syn)
        arm_patterns.append((
            syn,
            rf"\b{esc}\s+(?:group|arm|cohort|control)|"
            rf"\b{esc}-?treated",
        ))
    # Generic helpers
    arm_patterns += [
        ("control", r"\bcontrol\s+(?:group|arm|cohort|subjects?)\b"),
        ("treatment", r"\btreatment\s+(?:group|arm|cohort)\b|\bactive\s+treatment\b"),
        ("pooled", r"\bpooled\b|combined\s+groups?|both\s+(?:groups|arms)|across\s+groups"),
    ]
    # Bare keyword fallbacks (lower confidence) — kept LAST.
    for syn in sorted(pack.active_arm_synonyms, key=len, reverse=True):
        arm_patterns.append((syn, rf"\b{re.escape(syn)}\b"))
    for syn in sorted(pack.placebo_arm_synonyms, key=len, reverse=True):
        arm_patterns.append((syn, rf"\b{re.escape(syn)}\b"))
    ARM_VOCAB = tuple(arm_patterns)
    # Return a SimpleNamespace that quacks like a vocab module
    return SimpleNamespace(
        ENDPOINT_VOCAB=ENDPOINT_VOCAB,
        ENDPOINT_TO_OUTCOME_CLASS=ENDPOINT_TO_OUTCOME_CLASS,
        ENDPOINT_POLARITY=ENDPOINT_POLARITY,
        ARM_VOCAB=ARM_VOCAB,
        __name__=f"vocab.<auto:{domain}>",
        __doc__=f"Auto-synthesized vocab for {domain} from topic pack.",
    )


def load_domain(domain: str | None = None) -> Any:
    """Import and return the vocab module for the given (or env-resolved)
    domain.

    - If `vocab/<domain>.py` exists, import it normally.
    - If not, auto-synthesize from the topic pack TOML. This means
      new topics work via TOML alone — no Python file needed per
      topic (the user-mandated 'no hardcoding' rule).
    """
    name = (domain or _resolve_domain()).strip().lower()
    try:
        return importlib.import_module(f"vocab.{name}")
    except ModuleNotFoundError:
        return _synthesize_from_pack(name)
