"""Deterministic role + design classifier.

Pure functions. No LLM. Same input -> same output.

Step 1 - role  (the most load-bearing decision)
| Signal                                                 | role                  |
|--------------------------------------------------------|-----------------------|
| source=clinicaltrials AND has_results=True             | published_results     |
| source=clinicaltrials AND has_results=False            | registered_pending    |
| title or abstract has REVIEW marker                    | review                |
| abstract has PROTOCOL marker but no REPORTED_OUTCOME   | published_protocol    |
| abstract has REPORTED_OUTCOME (effect, p, CI, %, ...)  | published_results     |
| trial-design phrasing + qualitative outcome verb       | published_results     |
| abstract has only MECHANISTIC markers                  | mechanistic           |
| anything else                                          | mechanistic (default) |

Step 2 - design (derived from role + abstract markers)
| role + signal                            | design          |
|------------------------------------------|-----------------|
| published_results + RANDOMIZED marker    | rct             |
| published_results without randomized     | observational   |
| review + META_ANALYSIS marker            | meta_analysis   |
| review (other)                           | review          |
| published_protocol                       | protocol        |
| registered_pending                       | registry        |
| mechanistic                              | mechanistic     |

Hard rule: the protocol branch DOMINATES — a paper saying 'this study
evaluates' or 'we will assess' is a protocol regardless of trial-design
phrasing (protocols always describe their planned design). Only a hard
numeric outcome marker overrides this.

If the truth table changes, update this docstring AND the corresponding
text_signals constant in lockstep. Tests in test_evidence_cards.py drive
every row.
"""
from __future__ import annotations

from collections.abc import Mapping

from agent.text_signals import (
    META_ANALYSIS_MARKERS,
    MECHANISTIC_RE,
    PROTOCOL_MARKERS,
    QUALITATIVE_OUTCOME_RE,
    RANDOMIZED_RE,
    REPORTED_OUTCOME_RE,
    REVIEW_MARKERS,
    TRIAL_DESIGN_RE,
)
from agent.types import Design, Role, Source

__all__ = ["classify_role", "classify_design"]


def classify_role(src: Source, abstract: str, sig: Mapping[str, object]) -> Role:
    """Return the deterministic role for a (source, abstract, raw_signals) tuple.

    The clinicaltrials fast-path uses adapter-supplied `has_results`. All
    other roles are derived from text markers; ordering matters because the
    protocol branch dominates trial-design phrasing.
    """
    haystack = f"{src.title} {abstract}".lower()
    if src.source == "clinicaltrials":
        return "published_results" if sig.get("has_results") else "registered_pending"
    if any(token in haystack for token in REVIEW_MARKERS):
        return "review"
    has_protocol = any(token in haystack for token in PROTOCOL_MARKERS)
    has_outcome = bool(REPORTED_OUTCOME_RE.search(abstract))
    # Protocol markers DOMINATE — a paper saying 'this study evaluates' or
    # 'we will assess' is a protocol regardless of trial-design phrasing
    # (protocols always describe their planned design). Only a hard numeric
    # outcome marker overrides this. Without that, protocol -> protocol.
    if has_protocol and not has_outcome:
        return "published_protocol"
    if has_outcome:
        return "published_results"
    # Trial-design fast path: a paper with explicit trial-design markers
    # (Phase I/II/III, open-label, randomized double-blind, placebo-controlled,
    # 'we randomized/administered') plus a qualitative outcome verb is a
    # results paper even when the abstract uses only qualitative effect
    # language. Catches the Hickson IPF senolytics pilot and similar real
    # RCTs whose abstracts don't carry p-values. Runs ONLY when no protocol
    # markers are present (otherwise the protocol branch above already won).
    if TRIAL_DESIGN_RE.search(abstract) and QUALITATIVE_OUTCOME_RE.search(abstract):
        return "published_results"
    if MECHANISTIC_RE.search(haystack):
        return "mechanistic"
    return "mechanistic"


def classify_design(role: Role, abstract: str) -> Design:
    """Return the deterministic design label for a (role, abstract) pair.

    Pure function of role + text markers. Never sees the source object —
    that contract was preserved from the V1.1 bundle.py implementation
    because the test suite locks the role-only-then-design ordering.
    """
    haystack = abstract.lower()
    if role == "published_results":
        return "rct" if RANDOMIZED_RE.search(haystack) else "observational"
    if role == "review":
        if any(t in haystack for t in META_ANALYSIS_MARKERS):
            return "meta_analysis"
        return "review"
    if role == "published_protocol":
        return "protocol"
    if role == "registered_pending":
        return "registry"
    if role == "mechanistic":
        return "mechanistic"
    return "other"
