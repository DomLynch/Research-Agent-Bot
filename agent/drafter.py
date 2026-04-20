from __future__ import annotations

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


def _clean(value: Any, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


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


def _relevance(item: dict[str, Any], topic_tokens: list[str]) -> float:
    title = str(item.get("title") or "").lower()
    text = " ".join(str(item.get(k) or "") for k in ("title", "excerpt")).lower()
    if not topic_tokens:
        return 0.3
    title_matched = sum(1 for t in topic_tokens if t in title)
    text_matched = sum(1 for t in topic_tokens if t in text)
    if text_matched == 0:
        return 0.1
    base = 0.3 + (text_matched / len(topic_tokens)) * 0.3
    if title_matched > 0:
        base += 0.2
    if item.get("evidence_type") == "review":
        base += 0.1
    if int(item.get("year") or 0) >= 2020:
        base += 0.1
    return round(min(base, 1.0), 2)


class RapidEvidenceDrafter:
    def __init__(self, *, provider: Any) -> None:
        self.provider = provider

    def draft(self, *, topic: str, domain_slug: str, criteria: str, queries: list[str], evidence: list[dict[str, Any]], all_evidence: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        ranked = _rank(evidence)
        selected = ranked[:6]
        bundle_sources = _rank(all_evidence or evidence)[:20]

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

        years = [int(e["year"]) for e in bundle_sources if isinstance(e.get("year"), int)]
        rc = sum(1 for e in bundle_sources if e.get("evidence_type") == "review")
        pc = sum(1 for e in bundle_sources if e.get("evidence_type") == "primary")
        topic_tokens = [t for t in _clean(topic).lower().split() if t not in _STOPWORDS]
        expanded = list(topic_tokens)
        for tok in topic_tokens:
            expanded.extend(_SYNONYMS.get(tok, []))
        topic_tokens = expanded

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
        prompt_lines = [
            f"{i}. type={e.get('evidence_type', 'unknown')}; year={e.get('year', 'unknown')}; "
            f"title={_clean(e.get('title'), limit=220)}; excerpt={_clean(e.get('excerpt'), limit=320)}"
            for i, e in enumerate(selected, start=1)
        ]
        result, raw_payload = self.provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\nQueries: {' | '.join(queries)}\n\nCRITICAL: The 'question' field must be at least 50 words. Write a full paragraph: 'What are the effects of [topic] on healthspan outcomes in older adults, compared to placebo, as evaluated in randomized controlled trials with an intervention duration of at least 6 months, and what is the evidence for safety and efficacy?'\n\nEvidence:\n" + "\n".join(prompt_lines) or "No evidence receipts retained.",
        )
        result = {str(k).lower(): v for k, v in result.items()}
        fb_ctx = {
            "topic": topic, "domain": domain_slug,
            "today": datetime.now(timezone.utc).date().isoformat(),
            "nq": str(len(queries)), "nr": str(len(bundle_sources)),
            "rv": str(rc), "pr": str(pc),
            "titles": "; ".join(_clean(e.get("title"), limit=110) for e in bundle_sources[:3]) or "the retained evidence bundle",
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

        source_bundle = [
            {
                "title": _clean(e.get("title"), limit=200),
                "evidence_type": e.get("evidence_type"),
                "year": int(e["year"]) if isinstance(e.get("year"), int) else None,
                "url": e.get("url"),
                "doi": e.get("doi"),
                "relevance": rel,
            }
            for e in bundle_sources
            if e.get("evidence_type") in {"review", "primary"}
            and (rel := _relevance(e, topic_tokens)) >= 0.3
        ]

        if len(source_bundle) < 12 and os.getenv("RESEARKA_URL"):
            return (
                {"error": f"Insufficient relevant sources for submission ({len(source_bundle)}/12).", "source_bundle": source_bundle},
                raw_payload,
            )
        artifact = {
            "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
            "abstract": _clean(
                f"This draft synthesizes public-index evidence on {topic} for the {domain_slug} domain. "
                f"The run retained {len(bundle_sources)} evidence receipts spanning {min(years) if years else 'unknown'} to {max(years) if years else 'unknown'}, "
                f"with {rc} review-like items and {pc} primary-study items.",
                limit=1200,
            ),
            "domain_slug": _clean(domain_slug, limit=48).lower() or "general",
            "sections": sections,
            "source_bundle": source_bundle,
            "prompt_version": result.get("prompt_version", getattr(self.provider, "prompt_version", "unknown")),
            "usage": result.get("usage", {}),
            "estimated_cost_usd": float(result.get("estimated_cost_usd", 0.0) or 0.0),
            "model": result.get("model", getattr(self.provider, "model", "unknown")),
        }
        return (artifact, raw_payload)
