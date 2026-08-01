"""Build deterministically classified evidence items from retrieved sources."""
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
    """Deterministically map sources and abstracts to classified evidence items."""
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
    """Return only risk-of-bias states supported by this structural layer."""
    if item.role in {"published_results", "review"}:
        return "not assessed"
    if item.role in {"registered_pending", "published_protocol"}:
        return "n/a (no results)"
    return "n/a (preclinical)"


def confidence_verdict(items: list[EvidenceItem]) -> tuple[str, str]:
    """Return a bounded evidence-confidence label and rationale."""
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
    if direct_a_results_rcts or direct_a_meta:
        return "moderate", (
            f"{len(direct_a_results_rcts)} direct A-tier RCT(s) and "
            f"{len(direct_a_meta)} meta-analysis/-es are present; "
            "direction convergence was not assessed here."
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
    """Return the top writer items under the deterministic priority key."""

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
    """Extract bounded content phrases for the topic-relevance gate."""
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
    venue_text = venue or ""
    is_high_impact = bool(venue_text) and any(
        marker in venue_text.lower() for marker in HIGH_IMPACT_VENUES
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
    """Require topic and population fit, with explicit human signals authoritative."""
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
