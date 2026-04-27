"""Evidence cards — high-level builder that turns retrieved sources into
deterministically classified `EvidenceItem`s.

This module owns the public `bundle()` entry point used by retrieve→bundle→
compile callers. The classifier truth tables live in role_classifier.py;
the regex/marker constants live in text_signals.py; this file owns the
tier/direct/strict logic, topic-anchor extraction, risk-of-bias labelling,
the writer-priority ranking, and the confidence verdict.

Renamed from bundle.py during the Day 2 4-file split (DESIGN-001 §16). The
module's public surface (function names + signatures) is preserved; callers
update imports from `agent.bundle` to `agent.evidence_cards`. No behavior
change in this commit — registry-override layer integration follows.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from agent.registry_overrides import lookup_override
from agent.role_classifier import classify_design, classify_role
from agent.text_signals import (
    ADULT_DOMAIN_MARKERS,
    AGING_DOMAIN_MARKERS,
    AGING_RELEVANCE_RE,
    ANIMAL_RE,
    CELL_RE,
    DEFAULT_WRITER_BUDGET,
    HIGH_IMPACT_VENUES,
    HUMAN_DOMAIN_MARKERS,
    HUMAN_TRIAL_SIGNAL_RE,
    PEDIATRIC_RE,
    ROLE_WRITER_PRIORITY,
    TIER_WRITER_PRIORITY,
    TOPIC_STOPWORDS,
    TOPIC_TOKEN_RE,
)
from agent.topic_pack import TopicPack
from agent.types import Design, EvidenceItem, Role, Source, Tier

__all__ = [
    "bundle",
    "risk_of_bias",
    "confidence_verdict",
    "rank_for_writer",
    "DEFAULT_WRITER_BUDGET",
]


# --- Public entry point ----------------------------------------------------


def bundle(
    sources: list[Source],
    abstracts: Mapping[int, str],
    *,
    topic: str = "",
    domain: str = "",
    criteria_min_year: int | None = None,
    raw_signals: Mapping[int, Mapping[str, object]] | None = None,
    topic_pack: TopicPack | None = None,
) -> list[EvidenceItem]:
    """Map (Source, abstract) -> EvidenceItem with role/tier/design/direct/strict.

    `topic`   anchors topic-relevance — items whose title+abstract contains no
              topic anchor are marked direct=False (and therefore strict=False).
              Empty topic disables the gate.
    `domain`  anchors population/setting fit (human, adult, etc.).
    `raw_signals` is the per-ref `RawHit.raw` dict from the adapter (e.g.
              clinicaltrials passes `has_results`).
    `topic_pack` (NEW Day 2): when provided, registry-pinned role overrides
              are checked BEFORE the deterministic abstract classifier.
              Hits pin role/design/tier irrevocably (the moat). When None,
              behavior is identical to V1.1 bundle.py — no overrides apply.

    Pure function; deterministic.
    """
    items: list[EvidenceItem] = []
    domain_lower = (domain or "").lower()
    topic_anchors = _topic_anchors(topic)
    signals = raw_signals or {}
    for src in sources:
        abstract = abstracts.get(src.ref, "")
        sig = signals.get(src.ref, {}) or {}
        # Registry-override gate (Day 2 + Day 3.0). When the pack pins this
        # NCT/ISRCTN, role/design/tier come from the override and the
        # abstract classifier is bypassed entirely. The abstract still
        # flows through for storage on EvidenceItem and for the
        # direct/strict checks below — a registry hit pins the categorical
        # decision but does not bypass topic-anchor or population-fit
        # gates.
        #
        # Day 3.0 added the `abstract` arg so the override fires when a
        # canonical NCT/ISRCTN is in the abstract text only (e.g., live
        # OpenAlex returns MASTERS with NCT02308228 in abstract but no
        # source.nct because the dedup-merge with CT.gov didn't fire).
        override = lookup_override(src, topic_pack, abstract=abstract)
        if override is not None:
            role: Role = override.role
            design: Design = override.design
            tier: Tier = override.tier
        else:
            role = classify_role(src, abstract, sig)
            design = classify_design(role, abstract)
            tier = _classify_tier(role, design, src.venue)
        direct = _is_direct(src.title, abstract, domain_lower, topic_anchors)
        # Mechanistic role = preclinical / animal / cell / pathway. Such
        # papers cannot be 'direct human evidence' regardless of how
        # 'aging'-flavored their title is ('Metformin improves healthspan
        # in mice' has 'healthspan' but is not direct human evidence).
        # This forces the eligibility counts and evidence tables to stay
        # honest — strict count is direct HUMAN evidence only.
        if role == "mechanistic":
            direct = False
        strict = _is_strict(direct, src.year, criteria_min_year)
        items.append(
            EvidenceItem(
                source=src,
                abstract=abstract,
                design=design,
                role=role,
                tier=tier,
                direct=direct,
                strict=strict,
            )
        )
    return items


def risk_of_bias(item: EvidenceItem) -> str:
    """Deterministic risk-of-bias label from (role, design, tier).

    Conservative: uses only structural signals (no per-paper RoB scoring).
    'low' is reserved for A1 RCTs / well-conducted meta-analyses.
    'n/a' marks items without reported human outcomes.
    """
    if item.role == "published_results":
        if item.design == "rct":
            return "low" if item.tier == "A1" else "moderate"
        return "moderate-high"  # observational
    if item.role == "review":
        return "moderate" if item.design == "meta_analysis" else "moderate-high"
    if item.role in {"registered_pending", "published_protocol"}:
        return "n/a (no results)"
    return "n/a (preclinical)"


def confidence_verdict(items: list[EvidenceItem]) -> tuple[str, str]:
    """Overall evidence confidence label + one-line rationale.

    Returns (label, rationale) where label is one of:
      high     — multiple A1/A2 direct RCTs converge
      moderate — at least one direct A1/A2 published RCT or recent meta-analysis
      low      — only registered trials / observational / single small pilot
      very low — only mechanistic / preclinical / off-topic
    """
    direct_a_results_rcts = [
        it for it in items
        if it.direct and it.role == "published_results"
        and it.design == "rct" and it.tier in {"A1", "A2"}
    ]
    direct_a_meta = [
        it for it in items
        if it.direct and it.role == "review" and it.design == "meta_analysis"
    ]
    direct_results_any = [
        it for it in items
        if it.direct and it.role == "published_results"
    ]
    direct_pending = [
        it for it in items
        if it.direct and it.role in {"registered_pending", "published_protocol"}
    ]
    if len(direct_a_results_rcts) >= 3:
        return "high", (
            f"{len(direct_a_results_rcts)} direct A-tier RCTs converge in the bundle."
        )
    if direct_a_results_rcts or direct_a_meta:
        return "moderate", (
            f"{len(direct_a_results_rcts)} direct A-tier RCT(s) and "
            f"{len(direct_a_meta)} meta-analysis/-es support the verdict."
        )
    if direct_results_any:
        return "low", (
            f"only {len(direct_results_any)} direct human-results paper(s) "
            f"(observational or small/pilot)."
        )
    if direct_pending:
        return "low", (
            f"{len(direct_pending)} registered trial(s) pending; no published "
            "human results in the eligible bundle."
        )
    return "very low", (
        "no direct human evidence; only mechanistic / off-topic sources."
    )


def rank_for_writer(
    items: list[EvidenceItem], n: int = DEFAULT_WRITER_BUDGET,
) -> list[EvidenceItem]:
    """Sort items by writer priority and return the top N.

    Priority key (smaller = higher rank):
      direct=True before direct=False
      tier   A1 < A2 < B < C
      role   published_results < review < registered_pending < protocol < mechanistic
      year   newer first
      ref    ascending (stable tie-break)

    The LLM sees only this top-N slice; the full bundle still flows to render
    so the evidence table and bibliography stay complete.
    """

    def key(it: EvidenceItem) -> tuple:
        return (
            not it.direct,
            TIER_WRITER_PRIORITY.get(it.tier, 9),
            ROLE_WRITER_PRIORITY.get(it.role, 9),
            -(it.source.year or 0),
            it.source.ref,
        )

    return sorted(items, key=key)[:n]


def _topic_anchors(topic: str) -> tuple[str, ...]:
    """Extract content-bearing topic phrases for the relevance gate.

    Rules:
      0 content tokens   -> () (gate disabled)
      1 content token    -> single unigram   ("rapamycin",)
      2 content tokens   -> single BIGRAM    ("vitamin d",) — keeps the
                            compound entity intact so "Vitamin K" doesn't
                            falsely match a Vitamin D topic.
      3+ content tokens  -> individual unigrams (>=3 chars)
                            ("senolytics", "dasatinib", "quercetin"). The
                            user is naming alternatives, not a single
                            multi-word entity.

    All matches against title+abstract use \\b word boundaries (in
    _is_direct) so "vitamin" in "multivitamin" does not match.
    """
    if not topic:
        return ()
    tokens = TOPIC_TOKEN_RE.findall(topic.lower())
    content = [t for t in tokens if t not in TOPIC_STOPWORDS]
    if not content:
        return ()
    if len(content) == 2:
        return (f"{content[0]} {content[1]}",)
    return tuple(t for t in content[:3] if len(t) >= 3)


# --- Tier classifier -------------------------------------------------------


def _classify_tier(role: Role, design: Design, venue: str | None) -> Tier:
    is_high_impact = bool(venue) and any(
        marker in venue.lower() for marker in HIGH_IMPACT_VENUES
    )
    if design in {"rct", "meta_analysis"}:
        return "A1" if is_high_impact else "A2"
    if role == "published_results":
        return "A2"
    if role == "review":
        return "A2"
    if role in {"published_protocol", "registered_pending"}:
        return "B"
    return "C"


# --- Direct (topic + population fit) ---------------------------------------


def _is_direct(
    title: str,
    abstract: str,
    domain: str,
    topic_anchors: tuple[str, ...],
) -> bool:
    """Direct = on-topic AND on-population. Off either axis -> indirect.

    Topic anchors are matched with word boundaries so 'vitamin' as an anchor
    does not match 'multivitamin', and a 'vitamin d' bigram anchor does not
    match 'Vitamin K' (the K isn't part of the bigram).

    Animal/cell match is OVERRIDDEN when the abstract carries an explicit
    human-trial signal ('we randomized N patients', 'older adults',
    'placebo-controlled', etc.). Real human RCTs routinely cite preclinical
    mouse work in their introduction; the override prevents a real human
    trial from being marked indirect just because its background mentions
    'mice'.
    """
    domain_human = any(marker in domain for marker in HUMAN_DOMAIN_MARKERS)
    domain_adult = any(marker in domain for marker in ADULT_DOMAIN_MARKERS)
    has_human_signal = bool(HUMAN_TRIAL_SIGNAL_RE.search(abstract))
    if domain_human and not has_human_signal and (
        ANIMAL_RE.search(abstract) or CELL_RE.search(abstract)
    ):
        return False
    if domain_adult and PEDIATRIC_RE.search(abstract):
        return False
    if topic_anchors:
        haystack = f"{title} {abstract}".lower()
        anchor_re = re.compile(
            r"\b(?:" + "|".join(re.escape(a) for a in topic_anchors) + r")\b",
        )
        if not anchor_re.search(haystack):
            return False
    # Aging-domain relevance: when the user asks about longevity/aging, a
    # paper that mentions the topic IN A DIFFERENT CLINICAL CONTEXT (PCOS,
    # ACS, cancer, pediatric, pharmacokinetics) carries the topic anchor
    # but tangentially mentions 'age-related' once in the abstract — that's
    # not aging-focused. Require the aging marker in the TITLE so subject
    # matter is explicit. Non-aging domains skip this gate.
    if any(m in domain for m in AGING_DOMAIN_MARKERS):
        if not AGING_RELEVANCE_RE.search(title):
            return False
    return True


# --- Strict (eligibility filter) -------------------------------------------


def _is_strict(direct: bool, year: int | None, min_year: int | None) -> bool:
    if not direct:
        return False
    if min_year is not None and year is not None and year < min_year:
        return False
    return True
