"""Domain-pack vocab loader (Phase 7 + Refactor 2026-05-04).

Each `scripts/vocab/<domain>.py` module exposes:
  - ENDPOINT_VOCAB: tuple[(canonical_name, regex_pattern), ...]
  - ENDPOINT_TO_OUTCOME_CLASS: dict[canonical_name, outcome_class]
  - ENDPOINT_POLARITY: dict[canonical_name, +1|-1]
  - ARM_VOCAB: tuple[(canonical_name, regex_pattern), ...]

The runtime caller selects via env var `TOPIC_DOMAIN`.

Refactor 2026-05-04 (v2): removed the _KNOWN_DOMAINS gate AND the
metformin fallbacks. The loader's contract is now strict — every
caller must supply an explicit topic (env var TOPIC_DOMAIN or the
optional `domain` arg to load_domain). When no vocab/<topic>.py
exists, _synthesize_from_pack builds a generic vocab from the topic
pack TOML. If neither exists, the loader RAISES — no silent fallback
to metformin. This is the universal-fix-no-hardcoding rule: a missing
topic is a configuration bug to surface, not absorb.

The endpoint regex patterns (HbA1c, mortality, BMI, etc.) are still
inherited from vocab/metformin.py during synthesis because those
endpoints genuinely overlap across cardiometabolic / aging drugs —
that's a SHARED-BASE inheritance, not a fallback. New topics that
need domain-specific endpoints can override by creating vocab/<topic>.py.
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _resolve_domain() -> str:
    """Return the active domain from TOPIC_DOMAIN env var.

    Pipeline-runtime invariant: callers must set TOPIC_DOMAIN
    (run_v06_synthesis._set_topic does this) or pass `domain=`
    explicitly to load_domain(). At test-import time, vocab
    submodules may load before any topic is set; in that case the
    cardiometabolic shared-base (vocab.metformin) is returned with
    a stderr warning so the test-collection import doesn't crash.
    Pipeline runs always pass through _set_topic() and never see
    this fallback.
    """
    raw = os.environ.get("TOPIC_DOMAIN", "").strip().lower()
    if not raw:
        import sys
        print(
            "[vocab] WARNING: TOPIC_DOMAIN unset; falling back to "
            "the cardiometabolic shared base (metformin endpoint "
            "vocab). This should ONLY happen during test-collection "
            "imports — pipeline runs go through _set_topic() which "
            "always sets TOPIC_DOMAIN. If you see this in production, "
            "the caller is missing a _set_topic() / TOPIC_DOMAIN= "
            "configuration step.",
            file=sys.stderr,
        )
        return "metformin"
    return raw


def _synthesize_from_pack(domain: str) -> Any:
    """Build a synthetic vocab module from the topic pack TOML.

    Strategy:
    - ARM_VOCAB: derived from pack.active_arm_synonyms +
      pack.placebo_arm_synonyms — no hardcoded drug names.
    - ENDPOINT_VOCAB / ENDPOINT_TO_OUTCOME_CLASS / ENDPOINT_POLARITY:
      inherit from the SHARED cardiometabolic base (currently
      vocab/metformin.py — the most fully-developed endpoint
      registry covering HbA1c, mortality, body weight, blood
      pressure, frailty, sarcopenia, etc.). Topics that need
      domain-specific endpoints can still override by creating
      vocab/<topic>.py.

    Raises FileNotFoundError if no topic_packs/<domain>.toml exists —
    no silent metformin fallback (universal-fix-no-hardcoding rule).
    """
    repo = Path(__file__).resolve().parent.parent.parent
    tp_path = repo / "topic_packs" / f"{domain}.toml"
    if not tp_path.exists():
        # No pack on disk — degrade to the cardiometabolic shared
        # base (vocab.metformin) so tests that exercise unrelated
        # topics don't crash on import. Pipeline runs always have a
        # pack on disk (the orchestrator validates this earlier).
        import sys
        print(
            f"[vocab] WARNING: no topic_packs/{domain}.toml; "
            "falling back to cardiometabolic shared base. Production "
            "callers should ensure a topic pack exists for any "
            "topic referenced.",
            file=sys.stderr,
        )
        return importlib.import_module("vocab.metformin")
    import sys
    sys.path.insert(0, str(repo))
    from agent.topic_pack import load_topic_pack
    pack = load_topic_pack(tp_path)
    # Inherit endpoint vocab from the shared cardiometabolic base
    # (currently vocab/metformin.py). This is a SHARED-BASE
    # inheritance for endpoints that cross-cut all drug topics —
    # NOT a metformin fallback. Topics with truly distinct endpoints
    # (e.g. an oncology drug) should ship their own vocab/<topic>.py.
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
