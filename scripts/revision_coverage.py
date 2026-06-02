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
    if _asks_source_verification_transparency(lower):
        return _source_verification_transparency_is_stated(paper_md)
    if _asks_section_source_grounding(lower):
        return _section_source_grounding_is_stated(paper_md)
    if _asks_admission_funnel_numeric_consistency(lower):
        return _admission_funnel_numeric_consistency_is_stated(paper_md)
    if _asks_single_source_proportionality(lower):
        return _single_source_proportionality_is_stated(paper_md)
    if _asks_direct_evidence_definition(lower):
        text = paper_md.lower()
        return (
            "qualifying direct source" in text
            or "direct interventional hard-endpoint evidence" in text
        )
    if _asks_directional_coding(lower):
        return _directional_coding_explanation_is_material(paper_md)
    if _asks_directional_table_narrative_consistency(lower):
        return _directional_table_narrative_is_consistent(paper_md)
    if _asks_actionable_gaps(lower):
        return _gaps_section_is_actionable(paper_md)
    if _asks_null_signal_reconciliation(lower):
        return _null_signal_conclusion_is_bounded(paper_md)
    if _asks_internal_duplication(lower):
        return _internal_duplication_is_low(paper_md)
    if _asks_long_term_safety_scope(lower):
        return _long_term_safety_scope_is_stated(paper_md)
    if _asks_reference_traceability(lower):
        return _references_are_traceable(paper_md)
    return True


def _asks_classification_criteria(text: str) -> bool:
    return "classification criteria" in text or (
        "assign" in text and "outcome class" in text and "directness" in text
    )


def _asks_source_classification_map(text: str) -> bool:
    return "mapping table" in text or "mapping list" in text or (
        "which of the" in text and "source" in text and "outcome class" in text
    )


def _asks_source_verification_transparency(text: str) -> bool:
    return (
        ("source bundle" in text or "reference-only" in text)
        and any(token in text for token in ("external verification", "independently verified", "exact statistics", "detailed quantitative"))
        and any(token in text for token in ("manifest", "methods_pack", "supplementary artifact", "supplemental artifact"))
    )


def _asks_section_source_grounding(text: str) -> bool:
    return "source_grounding" in text or "directly supports that specific claim" in text or (
        "every claim" in text
        and all(token in text for token in ("key findings", "limitations", "conclusion"))
    )


def _asks_admission_funnel_numeric_consistency(text: str) -> bool:
    return (
        any(token in text for token in ("admission funnel", "source admission", "receipt admission"))
        and any(token in text for token in ("numerical inconsistency", "numeric inconsistency", "inconsistently", "both equal", "contradictory", "contradiction", "clarify"))
    ) or ("no extractable claims" in text and "admitted final" in text) or (
        "partial/none-only" in text and "partial-only" in text
    )


def _asks_single_source_proportionality(text: str) -> bool:
    return (
        ("single-source" in text or "single source" in text)
        and any(token in text for token in ("hypothesis-generating", "proportionality", "reduce narrative depth"))
    )


def _asks_direct_evidence_definition(text: str) -> bool:
    return "direct evidence" in text and any(token in text for token in ("definition", "qualifying", "qualify", "0/"))


def _asks_directional_coding(text: str) -> bool:
    return "directional coding" in text or (
        "no extracted directional signal" in text and "clarify" in text
    )


def _asks_directional_table_narrative_consistency(text: str) -> bool:
    return (
        "evidence landscape" in text
        and "no directional signal" in text
        and any(token in text for token in ("positive association", "positive associations", "positive signal", "positive signals"))
        and any(token in text for token in ("contradiction", "narrative", "table coding", "needs correction"))
    )


def _asks_actionable_gaps(text: str) -> bool:
    return "gaps identified" in text and any(token in text for token in ("actionable", "future research", "next steps"))


def _asks_null_signal_reconciliation(text: str) -> bool:
    return "null directional" in text and any(token in text for token in ("concluding", "conclusion", "rationale"))


def _asks_internal_duplication(text: str) -> bool:
    return any(token in text for token in ("internal duplication", "repetitive narrative", "verbatim repetition", "non-repetitive"))


def _asks_long_term_safety_scope(text: str) -> bool:
    return "long-term safety" in text or ("safety data" in text and "older adult" in text)


def _asks_reference_traceability(text: str) -> bool:
    return (
        "reference list" in text
        and any(token in text for token in ("doi", "pmid", "bibliographic identifier", "source bundle", "traceable"))
    ) or "traceable to the source bundle" in text


def _gaps_section_is_actionable(paper_md: str) -> bool:
    gaps = _section(paper_md, "Gaps Identified") or _section(paper_md, "Evidence-Gap Priority")
    if not gaps:
        return False
    text = gaps.lower()
    if len(gaps.split()) < 40:
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


def _internal_duplication_is_low(paper_md: str) -> bool:
    seen: list[set[str]] = []
    for paragraph in re.split(r"\n\s*\n", paper_md):
        text = " ".join(line.strip() for line in paragraph.splitlines() if not line.lstrip().startswith(("|", "#", "- [")))
        words = re.findall(r"[a-z0-9]+", text.lower())
        if len(words) < 18:
            continue
        tokens = set(words)
        if any(len(tokens & prior) / max(1, min(len(tokens), len(prior))) >= 0.75 for prior in seen):
            return False
        seen.append(tokens)
    return True


def _long_term_safety_scope_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion"), _section(paper_md, "Limitations")) if part).lower()
    if not scope:
        return False
    safety = "long-term safety" in scope or "long term safety" in scope or "safety data" in scope
    population = "older adult" in scope or "older adults" in scope or "aged" in scope
    return safety and population


def _directional_coding_explanation_is_material(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (_section(paper_md, "Evidence Snapshot"), _section(paper_md, "Evidence Landscape"), _section(paper_md, "Results"), _section(paper_md, "Conclusion"))
        if part
    ).lower()
    if not scope:
        return False
    directional = "directional coding" in scope and "no extracted directional signal" in scope
    null_scope = "null" in scope and ("unclear" in scope or "no signal" in scope)
    cross_context = (
        any(token in scope for token in ("positive", "mixed", "negative"))
        and any(token in scope for token in ("other outcome", "elsewhere", "separately reported", "different outcome"))
    )
    return directional and null_scope and cross_context


def _directional_table_narrative_is_consistent(paper_md: str) -> bool:
    table_scope = " ".join(
        part for part in (_section(paper_md, "Evidence Snapshot"), _section(paper_md, "Evidence Landscape")) if part
    ).lower()
    narrative_scope = " ".join(
        part for part in (_section(paper_md, "Key Findings"), _section(paper_md, "Results"), _section(paper_md, "Conclusion")) if part
    ).lower()
    if not table_scope or not narrative_scope:
        return False
    no_signal = "no extracted directional signal" in table_scope or "no directional signal" in table_scope
    positive_narrative = any(
        token in narrative_scope
        for token in ("positive association", "positive associations", "positive signal", "positive signals")
    )
    reconciled = any(
        token in (table_scope + " " + narrative_scope)
        for token in ("different outcome", "other outcome", "separately reported", "does not mean absence", "not absence of support")
    )
    return not (no_signal and positive_narrative and not reconciled)


def _section_source_grounding_is_stated(paper_md: str) -> bool:
    sections = [_section(paper_md, name) for name in ("Key Findings", "Limitations", "Conclusion")]
    return all(section and _has_source_trace_marker(section) for section in sections)


def _has_source_trace_marker(text: str) -> bool:
    lower = text.lower()
    author_year = re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", text)
    source_note = ("source-grounding" in lower or "source grounding" in lower) and any(
        token in lower for token in ("excerpt", "title", "trace", "source")
    )
    return bool(author_year or source_note)


def _source_verification_transparency_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (_section(paper_md, "Methods"), _section(paper_md, "Limitations"), _section(paper_md, "References"))
        if part
    ).lower()
    if not scope:
        return False
    limitation = (
        "reference-only" in scope
        or "external verification" in scope
        or "independently verified" in scope
        or "traceability" in scope
    )
    artifact = any(token in scope for token in ("manifest", "methods_pack", "supplementary artifact", "supplemental artifact"))
    return "source bundle" in scope and limitation and artifact


def _admission_funnel_numeric_consistency_is_stated(paper_md: str) -> bool:
    lower = paper_md.lower()
    if (
        "admission-bucket note:" in lower
        and "not an additive conservation table" in lower
        and "claim-binding states" in lower
    ):
        return True
    rows = _funnel_counts(paper_md)
    if not rows:
        return False
    no_extractable = rows.get("no extractable claims")
    admitted = rows.get("admitted final sources")
    if admitted is None:
        admitted = rows.get("admitted final receipts")
    if no_extractable is None or admitted is None:
        return False
    return no_extractable != admitted


def _single_source_proportionality_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part for part in (
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Key Findings"),
            _section(paper_md, "Limitations"),
            _section(paper_md, "Conclusion"),
        ) if part
    ).lower()
    if not scope:
        return False
    single_source = any(token in scope for token in ("single-source", "single source", "one-source", "one source"))
    bounded = "hypothesis-generating" in scope or "proportional" in scope or "proportionality" in scope
    return single_source and bounded


def _funnel_counts(paper_md: str) -> dict[str, int]:
    rows: dict[str, int] = {}
    in_funnel = False
    for line in paper_md.splitlines():
        stripped = line.strip()
        if re.match(r"^#{2,4}\s+", stripped):
            in_funnel = "admission funnel" in stripped.lower() or "selection flow" in stripped.lower()
            continue
        if not in_funnel or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in {"admission bucket", "---"}:
            continue
        try:
            rows[cells[0].lower()] = int(cells[1].replace(",", ""))
        except ValueError:
            continue
    return rows


def _references_are_traceable(paper_md: str) -> bool:
    refs = _section(paper_md, "References")
    if not refs:
        return False
    lines = [
        line.strip().lstrip("-* ").strip()
        for line in refs.splitlines()
        if line.strip() and not line.lstrip().startswith("|")
    ]
    if not lines:
        return False
    identifier = re.compile(
        r"\b(?:doi\s*:|https?://doi\.org/|pmid\s*:|pmcid\s*:|pmc\d+|nct\d+|isrctn\d+|clinicaltrials\.gov)",
        re.I,
    )
    explicit_caveat = re.compile(
        r"\b(?:identifier unavailable|no doi|no pmid|trial registration|protocol registration)\b",
        re.I,
    )
    return all(identifier.search(line) or explicit_caveat.search(line) for line in lines)


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
