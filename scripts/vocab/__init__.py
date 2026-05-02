"""Domain-pack vocab loader (Phase 7 refactor).

Each `scripts/vocab/<domain>.py` module exposes:
  - ENDPOINT_VOCAB: tuple[(canonical_name, regex_pattern), ...]
  - ENDPOINT_TO_OUTCOME_CLASS: dict[canonical_name, outcome_class]
  - ENDPOINT_POLARITY: dict[canonical_name, +1|-1]

Add a new drug pack by creating a new module here. The runtime
caller selects via env var `TOPIC_DOMAIN` (default: "metformin").

Domain-AGNOSTIC vocab (ARM_VOCAB, DIRECTION_VOCAB) lives in
scripts/quant_endpoints.py since it's the same across drug packs:
metformin/placebo/control structure + universal English direction
verbs apply to any clinical RCT or animal study.
"""
from __future__ import annotations

import importlib
import os
from typing import Any


_KNOWN_DOMAINS = ("metformin", "rapamycin")  # extend as needed


def _resolve_domain() -> str:
    domain = (os.environ.get("TOPIC_DOMAIN") or "metformin").strip().lower()
    if domain not in _KNOWN_DOMAINS:
        raise ValueError(
            f"Unknown TOPIC_DOMAIN={domain!r}; "
            f"add scripts/vocab/{domain}.py and register in __init__._KNOWN_DOMAINS"
        )
    return domain


def load_domain(domain: str | None = None) -> Any:
    """Import and return the vocab module for the given (or env-resolved)
    domain. The returned module exposes ENDPOINT_VOCAB +
    ENDPOINT_TO_OUTCOME_CLASS + ENDPOINT_POLARITY."""
    name = domain or _resolve_domain()
    return importlib.import_module(f"vocab.{name}")
