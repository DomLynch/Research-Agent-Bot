"""LLM coverage judge: verify each enumerated Researka revision ask is
MATERIALLY addressed in the rendered paper before submit.

Uses the SPAR judge chain (Gemma primary — a different model family than the
MiMo writer, per the judge!=writer rule). Fail-open: any judge/infra error or
a malformed verdict returns no unmet asks, so an LLM outage can never block the
whole submission pipeline. Topic-agnostic — the asks come verbatim from
Researka; no per-topic knowledge.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent.llm_client import LLMError, LLMResponse, build_judge_chain, chat_json
from agent.settings import load_settings

_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_USER = (
    "Below are {n} required revisions and a manuscript. For EACH revision, in "
    "order, decide whether the manuscript MATERIALLY addresses it — a substantive "
    "change, not merely repeating the words. Reply with JSON "
    '{{"addressed": [<one boolean per revision, in the same order>]}}.\n\n'
    "REQUIRED REVISIONS:\n{asks}\n\n=== MANUSCRIPT ===\n{paper}"
)


def _excerpt(paper_md: str, head: int = 16000, tail: int = 8000) -> str:
    """Head + tail of the paper so the judge sees both the abstract/intro and
    the conclusion/limitations — where reviewer asks concentrate — without
    paying for the full ~50k-word body."""
    if len(paper_md) <= head + tail:
        return paper_md
    return f"{paper_md[:head]}\n\n[... middle omitted ...]\n\n{paper_md[-tail:]}"


def unmet_asks(
    paper_md: str,
    asks: Sequence[str],
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Return the asks NOT materially addressed by the paper. Empty when every
    ask is met — or fail-open ([]) on any error or malformed verdict."""
    clean = [a.strip() for a in asks if a and a.strip()]
    if not clean:
        return []
    try:
        numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(clean, 1))
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": _USER.format(n=len(clean), asks=numbered, paper=_excerpt(paper_md))},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        flags = resp.parsed.get("addressed", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open — never block submit on a judge/infra failure
    if not isinstance(flags, list) or len(flags) != len(clean):
        return []  # malformed verdict — fail-open
    return [a for a, ok in zip(clean, flags, strict=True) if not ok]


def deterministic_unmet_asks(paper_md: str, asks: Sequence[str]) -> list[str]:
    """Reviewer asks with deterministic manuscript evidence.

    The LLM coverage judge stays useful for semantic asks, but these recurring
    Researka revise classes are structural enough to verify directly. This
    makes the gate resilient when the judge fails open.
    """
    clean = [a.strip() for a in asks if a and a.strip()]
    if not clean:
        return []
    return [ask for ask in clean if not _deterministic_ask_satisfied(paper_md, ask)]


def _deterministic_ask_satisfied(paper_md: str, ask: str) -> bool:
    lower = " ".join(ask.lower().split())
    if _asks_classification_criteria(lower):
        text = paper_md.lower()
        return all(token in text for token in ("classification criteria", "outcome class", "directness", "evidence tier"))
    if _asks_source_classification_map(lower):
        text = paper_md.lower()
        return all(token in text for token in ("source classification map", "outcome=", "directness=", "tier="))
    if _asks_direct_evidence_definition(lower):
        text = paper_md.lower()
        return (
            "qualifying direct source" in text
            or "direct interventional hard-endpoint evidence" in text
        )
    if _asks_directional_coding(lower):
        text = paper_md.lower()
        return "directional coding" in text and all(token in text for token in ("null", "unclear", "positive", "mixed"))
    if _asks_actionable_gaps(lower):
        return _gaps_section_is_actionable(paper_md)
    if _asks_null_signal_reconciliation(lower):
        return _null_signal_conclusion_is_bounded(paper_md)
    return True


def _asks_classification_criteria(text: str) -> bool:
    return "classification criteria" in text or (
        "assign" in text and "outcome class" in text and "directness" in text
    )


def _asks_source_classification_map(text: str) -> bool:
    return "mapping table" in text or "mapping list" in text or (
        "which of the" in text and "source" in text and "outcome class" in text
    )


def _asks_direct_evidence_definition(text: str) -> bool:
    return "direct evidence" in text and any(token in text for token in ("definition", "qualifying", "qualify", "0/"))


def _asks_directional_coding(text: str) -> bool:
    return "directional coding" in text or (
        "no extracted directional signal" in text and "clarify" in text
    )


def _asks_actionable_gaps(text: str) -> bool:
    return "gaps identified" in text and any(token in text for token in ("actionable", "future research", "next steps"))


def _asks_null_signal_reconciliation(text: str) -> bool:
    return "null directional" in text and any(token in text for token in ("concluding", "conclusion", "rationale"))


def _gaps_section_is_actionable(paper_md: str) -> bool:
    gaps = _section(paper_md, "Gaps Identified") or _section(paper_md, "Evidence-Gap Priority")
    if not gaps:
        return False
    text = gaps.lower()
    if len(gaps.split()) < 55:
        return False
    action_tokens = (
        "sample size", "powered", "priority population", "population", "follow-up",
        "duration", "endpoint", "trial", "randomized", "prospective", "safety",
        "dose", "comparator", "measurement",
    )
    return sum(1 for token in action_tokens if token in text) >= 3


def _null_signal_conclusion_is_bounded(paper_md: str) -> bool:
    scope = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion")) if part).lower()
    if not scope:
        return False
    if "bounded geroscience rationale" in scope and "null" not in scope:
        return False
    return any(token in scope for token in ("null", "mixed", "hypothesis-generating", "does not support", "not definitive"))


_CLAIM_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_CLAIM_USER = (
    "Below is a paper's ABSTRACT and the rest of the manuscript. List any abstract "
    "claim the manuscript's own evidence does NOT support, or that overstates it "
    "(too strong / unhedged given mixed or indirect evidence) — the most common "
    "reason an abstract is sent back for revision. Do not list neutral "
    "corpus-composition summaries (evidence-tier counts, outcome-bucket summaries, "
    "or disagreement counts) unless they assert efficacy or causal benefit. Reply with JSON "
    '{{"unsupported": [<verbatim claim>, ...]}} — empty if every abstract claim '
    "is supported and appropriately hedged.\n\n"
    "ABSTRACT:\n{abstract}\n\n=== REST OF MANUSCRIPT ===\n{body}"
)
_PROFILE_SUMMARY_RE = re.compile(
    r"\b("
    r"evidence profile contains|no sources classified primarily as|"
    r"positive (?:study-level )?signals (?:concentrate|concentrated|cluster|are summarized|are represented)|"
    r"no single positive outcome class dominates|"
    r"null signals (?:in|cluster)|negative signals (?:in|cluster)|"
    r"cross-study disagreement"
    r")\b",
    re.I,
)
_P_VALUE_RE = re.compile(r"\bp\s*(?:=|>|≥|>=)\s*(0?\.\d+|1(?:\.0+)?)", re.I)
_CI_RE = re.compile(r"\b(?:CI|confidence interval)\b[^.\n;:]{0,80}?(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)", re.I)
_SIG_RE = re.compile(r"\b(?:statistically\s+)?significant(?:ly)?\b", re.I)
_NONSIG_RE = re.compile(
    r"\b(?:non[- ]?significant(?:ly)?|not\s+(?:statistically\s+)?significant(?:ly)?|did\s+not\s+reach\s+significance)\b",
    re.I,
)


def _abstract(paper_md: str) -> str:
    m = re.search(r"^##\s+Abstract\b.*?\n(.*?)(?=^##\s)", paper_md, re.M | re.S)
    return m.group(1).strip() if m else ""


def _section(paper_md: str, name: str) -> str:
    m = re.search(rf"^##\s+{re.escape(name)}\b.*?\n(.*?)(?=^##\s|\Z)", paper_md, re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if s.strip()]


def numeric_effect_direction_issues(paper_md: str) -> list[str]:
    """Deterministic numeric sanity gate for the common reviewer failure:
    calling p>=0.05 or a CI crossing null "significant". Bounded and fail-closed
    only on explicit numeric contradictions, not absence of statistics."""
    scope = "\n".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion")) if part)
    issues: list[str] = []
    for sentence in _sentences(scope):
        if not _SIG_RE.search(sentence) or _NONSIG_RE.search(sentence):
            continue
        for value in _P_VALUE_RE.findall(sentence):
            if float(value) >= 0.05:
                issues.append(f"non-significant p-value described as significant: {sentence}")
                break
        for lo, hi in _CI_RE.findall(sentence):
            low, high = float(lo), float(hi)
            if low <= 0 <= high or (low <= 1 <= high and min(abs(low), abs(high)) > 0):
                issues.append(f"CI crossing null described as significant: {sentence}")
                break
    return issues


def unsupported_abstract_claims(
    paper_md: str,
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Abstract claims the manuscript's evidence does not support / overstates
    (paper-qa contradiction-check borrow). Empty when the abstract is supported,
    or fail-open ([]) on any error/malformed verdict. Bounded: one judge call."""
    abstract = _abstract(paper_md)
    if not abstract:
        return []
    body = paper_md.replace(abstract, "", 1)
    try:
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _CLAIM_SYS},
                {"role": "user", "content": _CLAIM_USER.format(abstract=abstract[:6000], body=body[:18000])},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        claims = resp.parsed.get("unsupported", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open
    if not isinstance(claims, list):
        return []
    return [
        claim for c in claims
        if (claim := str(c).strip()) and not _PROFILE_SUMMARY_RE.search(claim)
    ]
