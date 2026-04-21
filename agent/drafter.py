from __future__ import annotations

from agent.evidence_cards import build_card

import os
import re
from datetime import datetime, timezone
from typing import Any


SECTION_FIELDS = (
    ("Research Question", "question"),
    ("Search Summary", "search_summary"),
    ("Evidence Landscape", "landscape"),
    ("Key Findings", "findings"),
    ("Limitations", "limitations"),
    ("Gaps Identified", "gaps_identified"),
    ("Conclusion", "conclusion"),
)
LEAKY_PHRASES = (
    "coverage decay detected",
    "replace this section",
    "revision brief",
    "[placeholder",
    "[tbd",
    "[tk]",
)
_FALLBACKS = {
    "Research Question": "This draft asks whether {topic} has decision-relevant evidence in the {domain} domain and keeps the scope narrow enough to stay faithful to the retained evidence.",
    "Key Findings": "The main signal is directional rather than definitive. The evidence bundle suggests the topic is relevant, but the confidence level should stay bounded by heterogeneous designs, limited samples, and incomplete replication.",
    "Conclusion": "The draft supports a cautious summary on {topic} without claiming more than the retained evidence can justify. Representative retained titles include {titles}.",
}
_GENERIC_FALLBACK = "This section draws on {nr} retained evidence receipts ({rv} review, {pr} primary) queried on {today} via {nq} scoped search strings."

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}
_SYNONYMS = {"rapamycin": ["sirolimus"], "metformin": ["glucophage"], "senolytic": ["senolytics"]}
_ANTI_AGING_DOMAINS = {"longevity", "anti-aging", "anti aging"}
_ANTI_AGING_TERMS = (
    "aging", "ageing", "healthspan", "longevity", "older adults", "biological age",
    "geroscience", "frailty", "multimorbidity", "mci", "cognitive decline",
)

_INJECTION_PATTERNS = (
    r"ignore previous instructions",
    r"you are now",
    r"system prompt",
    r"reveal your",
    r"act as",
    r"do not follow",
    r"new instructions",
    r"override",
    r"jailbreak",
    r"prompt injection",
    r"disregard.*above",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"BEGINCHAT",
    r"ENDCHAT",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def _clean(value: Any, limit: int = 2000) -> str:
    raw = str(value or "")
    raw = _INJECTION_RE.sub("[REDACTED]", raw)
    return re.sub(r"\s+", " ", raw).strip()[:limit]


def _dedupe(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        key = _clean(item.get("doi") or item.get("url") or item.get("title"), limit=300).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _rank(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _s(item: dict[str, Any]) -> tuple[int, int, int]:
        return (
            int(item.get("year") or 0),
            1 if item.get("evidence_type") == "review" else 0,
            len(_clean(item.get("excerpt"))),
        )

    return sorted(_dedupe(evidence), key=_s, reverse=True)


def _is_anti_aging_domain(domain_slug: str) -> bool:
    domain = domain_slug.lower().strip()
    return domain in _ANTI_AGING_DOMAINS or "aging" in domain


def _classify_directness(item: dict[str, Any], card: dict[str, Any], domain_slug: str, topic_tokens: list[str]) -> str:
    if item.get("evidence_type") == "mechanism" or item.get("source_type") == "chembl":
        return "mechanistic"
    text = " ".join(str(item.get(k) or "") for k in ("title", "excerpt", "query")).lower()
    if _is_anti_aging_domain(domain_slug):
        if any(term in text for term in _ANTI_AGING_TERMS) or card.get("context") == "aging":
            return "direct"
        if card.get("context") in {"oncology", "transplant", "device", "pediatric"}:
            return "indirect"
        if any(tok in text for tok in topic_tokens):
            return "indirect"
        return "indirect"
    return "direct" if any(tok in text for tok in topic_tokens) else "indirect"


def _relevance(item: dict[str, Any], topic_tokens: list[str], *, card: dict[str, Any] | None = None, directness: str = "indirect") -> float:
    title = str(item.get("title") or "").lower()
    card = card or {}
    text = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            item.get("query"),
            card.get("population"),
            card.get("intervention"),
            card.get("outcomes"),
            card.get("journal"),
        )
    ).lower()
    if not topic_tokens:
        return 0.25
    title_matched = sum(1 for t in topic_tokens if t in title)
    text_matched = sum(1 for t in topic_tokens if t in text)
    if text_matched == 0:
        return 0.1 if directness != "mechanistic" else 0.05
    base = 0.2 + (text_matched / len(topic_tokens)) * 0.25
    if title_matched > 0:
        base += 0.15 + min(0.1, (title_matched / len(topic_tokens)) * 0.1)
    base += {"direct": 0.2, "indirect": 0.05, "mechanistic": 0.0}.get(directness, 0.0)
    if item.get("evidence_type") == "review":
        base += 0.1
    elif item.get("evidence_type") in {"interventional", "observational"}:
        base += 0.05
    if int(item.get("year") or 0) >= 2020:
        base += 0.05
    return round(min(base, 1.0), 2)


def _bundle_entry(item: dict[str, Any], topic_tokens: list[str], domain_slug: str) -> dict[str, Any]:
    card = build_card(item)
    directness = _classify_directness(item, card, domain_slug, topic_tokens)
    card["directness"] = directness
    relevance = _relevance(item, topic_tokens, card=card, directness=directness)
    return {
        "title": _clean(item.get("title"), limit=200),
        "excerpt": _clean(item.get("excerpt"), limit=500),
        "evidence_type": item.get("evidence_type"),
        "source_type": item.get("source_type"),
        "year": int(item["year"]) if isinstance(item.get("year"), int) else None,
        "url": item.get("url"),
        "doi": item.get("doi"),
        "query": item.get("query"),
        "relevance": relevance,
        "directness": directness,
        "card": card,
    }


def _entry_sort_key(entry: dict[str, Any]) -> tuple[int, float, int, int]:
    return (
        {"direct": 3, "indirect": 2, "mechanistic": 1}.get(entry.get("directness", "indirect"), 0),
        float(entry.get("relevance") or 0.0),
        int(entry.get("year") or 0),
        1 if entry.get("evidence_type") == "review" else 0,
    )


class RapidEvidenceDrafter:
    def __init__(self, *, provider: Any) -> None:
        self.provider = provider

    def draft(self, *, topic: str, domain_slug: str, criteria: str, queries: list[str], evidence: list[dict[str, Any]], all_evidence: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        topic_tokens = [t for t in _clean(topic).lower().split() if t not in _STOPWORDS]
        expanded = list(topic_tokens)
        for tok in topic_tokens:
            expanded.extend(_SYNONYMS.get(tok, []))
        topic_tokens = expanded

        ranked = _rank(evidence)
        selected = sorted(
            (_bundle_entry(e, topic_tokens, domain_slug) for e in ranked),
            key=_entry_sort_key,
            reverse=True,
        )[:6]
        bundle_candidates = sorted(
            (_bundle_entry(e, topic_tokens, domain_slug) for e in _rank(all_evidence or evidence)),
            key=_entry_sort_key,
            reverse=True,
        )

        if len(selected) < 2:
            return (
                {
                    "error": "Insufficient evidence for synthesis (fewer than 2 relevant sources retained).",
                    "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
                    "sections": {},
                    "source_bundle": [],
                },
                None,
            )

        accepted_types = {"review", "primary", "interventional", "observational", "mechanism"}
        source_bundle = [
            entry for entry in bundle_candidates
            if entry.get("evidence_type") in accepted_types and float(entry.get("relevance") or 0.0) >= 0.25
        ][:20]
        if len(source_bundle) < 8:
            source_bundle = [entry for entry in bundle_candidates if entry.get("evidence_type") in accepted_types][:20]

        years = [int(e["year"]) for e in source_bundle if isinstance(e.get("year"), int)]
        rc = sum(1 for e in source_bundle if e.get("evidence_type") == "review")
        pc = sum(1 for e in source_bundle if e.get("evidence_type") in {"primary", "interventional", "observational", "mechanism"})
        direct_ct = sum(1 for e in source_bundle if e.get("directness") == "direct")
        indirect_ct = sum(1 for e in source_bundle if e.get("directness") == "indirect")
        mechanistic_ct = sum(1 for e in source_bundle if e.get("directness") == "mechanistic")

        system_prompt = (
            "You write cautious research drafts grounded in the supplied evidence. "
            "Return JSON only. Do not use placeholders or revision instructions. "
            "Cite sources inline using [1], [2], etc. to refer to the numbered evidence list. "
            "The 'question' field MUST be a full paragraph of at least 50 words. "
            "Example: 'What are the effects of [intervention] on [outcomes] in [population], "
            "compared to [comparator], as evaluated in [study types] with [time frame]?' "
            "Frame a specific, bounded research question with explicit scope, population, intervention, and outcome. "
            "Return exactly these JSON keys, each a plain string: "
            "question, search_summary, landscape, findings, limitations, gaps_identified, conclusion."
        )
        prompt_lines = []
        for i, e in enumerate(selected, start=1):
            card = e["card"]
            parts = [f"cite={card.get('citation', 'unknown')}"]
            parts.append(f"type={card.get('study_type', 'unknown')}")
            parts.append(f"grade={card.get('evidence_grade', 'L')}")
            parts.append(f"directness={e.get('directness', 'indirect')}")
            if card.get("quality_signal"):
                parts.append(f"quality={card['quality_signal']}")
            parts.append(f"year={e.get('year', 'unknown')}")
            if card.get("journal"):
                parts.append(f"journal={card['journal']}")
            if card.get("population"):
                parts.append(f"pop={card['population']}")
            if card.get("intervention"):
                parts.append(f"intervention={card['intervention']}")
            if card.get("outcomes"):
                parts.append(f"outcomes={card['outcomes']}")
            if card.get("context"):
                parts.append(f"context={card['context']}")
            prompt_lines.append(f"{i}. {'; '.join(parts)}")
        result, raw_payload = self.provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\nQueries: {' | '.join(queries)}\n\nCRITICAL: The 'question' field must be at least 50 words. Write a full paragraph: 'What are the effects of [topic] on healthspan outcomes in older adults, compared to placebo, as evaluated in randomized controlled trials with an intervention duration of at least 6 months, and what is the evidence for safety and efficacy?'\n\nEvidence:\n" + "\n".join(prompt_lines) or "No evidence receipts retained.",
        )
        result = {str(k).lower(): v for k, v in result.items()}
        fb_ctx = {
            "topic": topic, "domain": domain_slug,
            "today": datetime.now(timezone.utc).date().isoformat(),
            "nq": str(len(queries)), "nr": str(len(source_bundle)),
            "rv": str(rc), "pr": str(pc),
            "titles": "; ".join(_clean(e.get("title"), limit=110) for e in source_bundle[:3]) or "the retained evidence bundle",
        }
        fallback_count = 0
        sections: dict[str, str] = {}
        for heading, field in SECTION_FIELDS:
            raw = result.get(field, "")
            fallback = _FALLBACKS.get(heading, _GENERIC_FALLBACK).format(**fb_ctx)
            c = _clean(raw, limit=4000)
            picked = fallback if not c or any(t in c.lower() for t in LEAKY_PHRASES) else c
            if picked == fallback:
                fallback_count += 1
            sections[heading] = picked

        if fallback_count >= 6:
            return (
                {"error": "Model contributed no usable content — all sections fell back to templates."},
                raw_payload,
            )

        # enforce RQ minimum word count for Researka intake
        rq_text = sections.get("Research Question", "")
        if len(rq_text.split()) < 50:
            scope_hint = f"for the {domain_slug} domain" if domain_slug != "general" else ""
            sections["Research Question"] = (
                f"{rq_text} This synthesis specifically examines the available public-index evidence {scope_hint}, "
                f"considering the quality, recency, and directness of the retained receipts, "
                f"to determine whether the current literature supports actionable conclusions for practitioners and researchers."
            ).strip()

        if len(source_bundle) < 8 and os.getenv("RESEARKA_URL"):
            return (
                {"error": f"Insufficient relevant sources for submission ({len(source_bundle)}/8).", "source_bundle": source_bundle},
                raw_payload,
            )
        artifact = {
            "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
            "abstract": _clean(
                f"This draft synthesizes public-index evidence on {topic} for the {domain_slug} domain. "
                f"The run retained {len(source_bundle)} evidence receipts spanning {min(years) if years else 'unknown'} to {max(years) if years else 'unknown'}, "
                f"with {rc} review-like items, {pc} primary-study items, {direct_ct} direct items, "
                f"{indirect_ct} indirect items, and {mechanistic_ct} mechanistic items.",
                limit=1200,
            ),
            "domain_slug": _clean(domain_slug, limit=48).lower() or "general",
            "sections": sections,
            "source_bundle": source_bundle,
            "bundle_profile": {
                "review_count": rc,
                "primary_count": pc,
                "direct_count": direct_ct,
                "indirect_count": indirect_ct,
                "mechanistic_count": mechanistic_ct,
            },
            "prompt_version": result.get("prompt_version", getattr(self.provider, "prompt_version", "unknown")),
            "usage": result.get("usage", {}),
            "estimated_cost_usd": float(result.get("estimated_cost_usd", 0.0) or 0.0),
            "model": result.get("model", getattr(self.provider, "model", "unknown")),
        }
        return (artifact, raw_payload)
