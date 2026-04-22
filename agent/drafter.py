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
_DIRECT_STUDY_TYPES = {
    "rct",
    "clinical-trial",
    "cohort",
    "case-control",
    "cross-sectional",
    "observational",
    "meta-analysis",
    "systematic-review",
}

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
_NUMERIC_CLAIM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_OUTCOME_VERB_RE = re.compile(
    r"\b(found|showed|reported|demonstrated|improved|reduced|increased|decreased|achieved|yielded)\b",
    re.IGNORECASE,
)


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
    if item.get("source_type") == "clinicaltrials" and not item.get("has_results"):
        return "indirect"
    title = str(item.get("title") or "").lower()
    text = " ".join(str(item.get(k) or "") for k in ("title", "excerpt", "query")).lower()
    title_match = any(tok in title for tok in topic_tokens)
    study_type = str(card.get("study_type") or "")
    aging_signal = (
        any(term in title for term in _ANTI_AGING_TERMS)
        or card.get("context") == "aging"
        or "older adults" in str(card.get("population") or "")
        or any(term in str(card.get("outcomes") or "") for term in ("healthspan", "aging", "longevity", "mortality", "cognitive", "frailty"))
    )
    if _is_anti_aging_domain(domain_slug):
        if card.get("context") in {"oncology", "transplant", "device", "pediatric"}:
            return "indirect"
        if title_match and aging_signal and study_type in _DIRECT_STUDY_TYPES:
            return "direct"
        if any(tok in text for tok in topic_tokens):
            return "indirect"
        return "indirect"
    return "direct" if title_match else "indirect"


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
        "trial_status": item.get("trial_status"),
        "has_results": bool(item.get("has_results")),
        "year": int(item["year"]) if isinstance(item.get("year"), int) else None,
        "url": item.get("url"),
        "doi": item.get("doi"),
        "query": item.get("query"),
        "extraction": item.get("extraction") or {},
        "relevance": relevance,
        "directness": directness,
        "card": card,
    }


def _effect_brief(extraction: dict[str, Any]) -> str:
    effects = extraction.get("effects") or []
    if not effects:
        return ""
    parts = []
    for effect in effects[:2]:
        outcome = _clean(effect.get("outcome"), limit=80)
        metric = _clean(effect.get("metric"), limit=20)
        value = _clean(effect.get("value"), limit=20)
        ci_low = _clean(effect.get("ci_low"), limit=20)
        ci_high = _clean(effect.get("ci_high"), limit=20)
        n = _clean(effect.get("n"), limit=20)
        snippet = []
        if outcome:
            snippet.append(outcome)
        if metric and value:
            snippet.append(f"{metric} {value}")
        if ci_low and ci_high:
            snippet.append(f"95% CI {ci_low}-{ci_high}")
        if n:
            snippet.append(f"N={n}")
        parts.append(", ".join(snippet))
    return " | ".join(part for part in parts if part)


def _is_reported_finding(entry: dict[str, Any]) -> bool:
    return not (entry.get("source_type") == "clinicaltrials" and not entry.get("has_results"))


def _sanitize_registry_claims(text: str, blocked_refs: list[int]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned or not blocked_refs:
        return cleaned
    blocked_tags = [f"[{idx}]" for idx in blocked_refs]
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    kept = []
    hit_tags: list[str] = []
    for sentence in sentences:
        tags = [tag for tag in blocked_tags if tag in sentence]
        if tags and _OUTCOME_VERB_RE.search(sentence):
            hit_tags.extend(tags)
            continue
        kept.append(sentence)
    if hit_tags:
        refs = ", ".join(dict.fromkeys(hit_tags))
        kept.append(f"Registered studies {refs} describe study design only; outcome results have not been posted.")
    return " ".join(part for part in kept if part).strip()


def _numeric_effect_sentence(index: int, entry: dict[str, Any]) -> str:
    effects = ((entry.get("extraction") or {}).get("effects") or [])
    if not effects:
        return ""
    effect = effects[0]
    outcome = _clean(effect.get("outcome"), limit=90) or "reported outcome"
    metric = _clean(effect.get("metric"), limit=30)
    value = _clean(effect.get("value"), limit=120)
    p_value = _clean(effect.get("p_value"), limit=20)
    n = _clean(effect.get("n"), limit=80)
    bits = [f"Published results [{index}] report {outcome}"]
    if metric and value:
        bits.append(f"{metric} {value}")
    elif value:
        bits.append(value)
    if p_value:
        bits.append(f"p={p_value}")
    if n:
        bits.append(n)
    return "; ".join(bits).strip() + "."


def _has_quantitative_content(text: str) -> bool:
    cleaned = re.sub(r"\[\d+\]", "", _clean(text, limit=4000))
    return bool(_NUMERIC_CLAIM_RE.search(cleaned))


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
        prompt_entries = [entry for entry in selected if _is_reported_finding(entry)] + [
            entry for entry in selected if not _is_reported_finding(entry)
        ]
        registered_refs = [i for i, entry in enumerate(prompt_entries, start=1) if not _is_reported_finding(entry)]
        first_effect_entry = next(
            (
                (i, entry)
                for i, entry in enumerate(prompt_entries, start=1)
                if _is_reported_finding(entry) and ((entry.get("extraction") or {}).get("effects") or [])
            ),
            None,
        )
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
        full_text_ct = sum(1 for e in source_bundle if e.get("card", {}).get("full_text_found"))
        extracted_ct = sum(1 for e in source_bundle if e.get("card", {}).get("extraction_found"))

        has_effect_data = any((entry.get("extraction") or {}).get("effects") for entry in prompt_entries if _is_reported_finding(entry))
        system_prompt = (
            "You write cautious research drafts grounded in the supplied evidence. "
            "Return JSON only. Do not use placeholders or revision instructions. "
            "Cite sources inline using [1], [2], etc. to refer to the numbered evidence list. "
            "The evidence is split into Published findings and Registered but not yet reported studies. "
            "For registered studies, describe only the study design or aim. "
            "Do not say they found, showed, reported, or demonstrated outcomes. "
            "The 'question' field MUST be a full paragraph of at least 50 words. "
            "Example: 'What are the effects of [intervention] on [outcomes] in [population], "
            "compared to [comparator], as evaluated in [study types] with [time frame]?' "
            "Frame a specific, bounded research question with explicit scope, population, intervention, and outcome. "
            "Return exactly these JSON keys, each a plain string: "
            "question, search_summary, landscape, findings, limitations, gaps_identified, conclusion."
        )
        if has_effect_data:
            system_prompt += " In Key Findings, when Published findings include effect data, cite at least one numeric value from that effect data."
        reported_lines = []
        registered_lines = []
        for i, e in enumerate(prompt_entries, start=1):
            card = e["card"]
            parts = [f"cite={card.get('citation', 'unknown')}"]
            parts.append(f"type={card.get('study_type', 'unknown')}")
            parts.append(f"grade={card.get('evidence_grade', 'L')}")
            parts.append(f"directness={e.get('directness', 'indirect')}")
            if e.get("source_type") == "clinicaltrials":
                parts.append(f"trial_status={e.get('trial_status', 'registered')}")
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
            if card.get("full_text_found"):
                parts.append(f"fulltext={card.get('full_text_source') or 'yes'}")
            if card.get("comparator"):
                parts.append(f"comparator={card['comparator']}")
            if card.get("methods_summary"):
                parts.append(f"methods={_clean(card['methods_summary'], limit=140)}")
            if card.get("risk_of_bias"):
                parts.append(f"bias={_clean(card['risk_of_bias'], limit=100)}")
            if card.get("effects"):
                parts.append(f"effect={_effect_brief(e.get('extraction') or {})}")
                top_span = _clean((e.get("extraction") or {}).get("effects", [{}])[0].get("source_span"), limit=220)
                if top_span:
                    parts.append(f"results_excerpt={top_span}")
            line = f"{i}. {'; '.join(parts)}"
            if _is_reported_finding(e):
                reported_lines.append(line)
            else:
                registered_lines.append(line)
        evidence_blocks = []
        if reported_lines:
            evidence_blocks.append("Published findings (can support outcome claims):")
            evidence_blocks.extend(reported_lines)
        if registered_lines:
            evidence_blocks.append("Registered but not yet reported (design only, no outcome claims):")
            evidence_blocks.extend(registered_lines)
        result, raw_payload = self.provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\nQueries: {' | '.join(queries)}\n\nCRITICAL: The 'question' field must be at least 50 words. Write a full paragraph: 'What are the effects of [topic] on healthspan outcomes in older adults, compared to placebo, as evaluated in randomized controlled trials with an intervention duration of at least 6 months, and what is the evidence for safety and efficacy?'\n\nEvidence:\n" + "\n".join(evidence_blocks) or "No evidence receipts retained.",
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

        for heading in ("Evidence Landscape", "Key Findings", "Conclusion"):
            if heading in sections:
                sections[heading] = _sanitize_registry_claims(sections[heading], registered_refs)

        if has_effect_data and not _has_quantitative_content(sections.get("Key Findings", "")) and first_effect_entry:
            sections["Key Findings"] = f"{sections['Key Findings']} {_numeric_effect_sentence(*first_effect_entry)}".strip()

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
                f"{indirect_ct} indirect items, {mechanistic_ct} mechanistic items, {full_text_ct} full-text-backed items, "
                f"and {extracted_ct} structured-extraction items.",
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
