from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


SECTION_FIELDS = (
    ("Research Question", "question"),
    ("Search Summary", "search_summary"),
    ("Evidence Landscape", "landscape"),
    ("Methods", "methods"),
    ("Key Findings", "findings"),
    ("Limitations", "limitations"),
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
    def _s(item: dict[str, Any]) -> tuple[int, int, int, int]:
        return (
            1 if item.get("evidence_type") == "review" else 0,
            int(item.get("year") or 0),
            1 if item.get("doi") else 0,
            len(_clean(item.get("excerpt"))),
        )

    return sorted(_dedupe(evidence), key=_s, reverse=True)


class RapidEvidenceDrafter:
    def __init__(self, *, provider: Any) -> None:
        self.provider = provider

    def draft(self, *, topic: str, domain_slug: str, criteria: str, queries: list[str], evidence: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        selected = _rank(evidence)[:6]

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

        years = [int(e["year"]) for e in selected if isinstance(e.get("year"), int)]
        rc = sum(1 for e in selected if e.get("evidence_type") == "review")
        pc = sum(1 for e in selected if e.get("evidence_type") == "primary")

        system_prompt = (
            "You write cautious research drafts grounded in the supplied evidence. "
            "Return JSON only. Do not use placeholders or revision instructions. "
            "Cite sources inline using [1], [2], etc. to refer to the numbered evidence list. "
            "Return exactly these JSON keys, each a plain string: "
            "question, search_summary, landscape, methods, findings, limitations, conclusion."
        )
        prompt_lines = [
            f"{i}. type={e.get('evidence_type', 'unknown')}; year={e.get('year', 'unknown')}; "
            f"title={_clean(e.get('title'), limit=220)}; excerpt={_clean(e.get('excerpt'), limit=320)}"
            for i, e in enumerate(selected, start=1)
        ]
        result, raw_payload = self.provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\nQueries: {' | '.join(queries)}\nEvidence:\n" + "\n".join(prompt_lines) or "No evidence receipts retained.",
        )
        result = {str(k).lower(): v for k, v in result.items()}
        fb_ctx = {
            "topic": topic, "domain": domain_slug,
            "today": datetime.now(timezone.utc).date().isoformat(),
            "nq": str(len(queries)), "nr": str(len(selected)),
            "rv": str(rc), "pr": str(pc),
            "titles": "; ".join(_clean(e.get("title"), limit=110) for e in selected[:3]) or "the retained evidence bundle",
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

        source_bundle = [
            {
                "evidence_type": e["evidence_type"],
                "year": int(e["year"]),
                "title": _clean(e.get("title"), limit=200),
                "url": e.get("url"),
                "source_type": e.get("source_type"),
                "doi": e.get("doi"),
            }
            for e in selected
            if e.get("evidence_type") in {"review", "primary"} and isinstance(e.get("year"), int)
        ]
        artifact = {
            "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
            "abstract": _clean(
                f"This draft synthesizes public-index evidence on {topic} for the {domain_slug} domain. "
                f"The run retained {len(selected)} evidence receipts spanning {min(years) if years else 'unknown'} to {max(years) if years else 'unknown'}, "
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
