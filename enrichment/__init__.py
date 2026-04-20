from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.provider import ChatClient

MINIMAX_COST_PER_1K_INPUT_TOKENS = 0.001
MINIMAX_COST_PER_1K_OUTPUT_TOKENS = 0.005

SCHEMA_FIELDS = [
    "title",
    "year",
    "doi",
    "url",
    "source_type",
    "evidence_type",
    "study_type",
    "population",
    "intervention_or_exposure",
    "outcomes",
    "summary_bullets",
    "relevance_score",
    "human_evidence_score",
    "safety_signal_score",
    "novelty_score",
    "is_generic_or_off_topic",
    "reasoning_notes",
    "raw_model",
    "prompt_version",
]


SYSTEM_PROMPT = """You are an evidence enrichment worker. Given a raw evidence receipt, produce a structured evidence_card JSON object.

Return ONLY valid JSON. No prose, no markdown fences, no commentary.

Schema:
- title: string (from source)
- year: integer or null
- doi: string or null
- url: string or null
- source_type: string (e.g. pubmed, openalex)
- evidence_type: string (e.g. primary, review)
- study_type: string or null (e.g. RCT, cohort, case-control, systematic-review, unknown)
- population: string or null (brief description of study population)
- intervention_or_exposure: string or null
- outcomes: string or null (primary outcomes measured)
- summary_bullets: array of 3-5 neutral factual strings
- relevance_score: float 0-1 (how relevant to the query)
- human_evidence_score: float 0-1 (quality of human-generated evidence)
- safety_signal_score: float 0-1 (potential safety concerns or signals)
- novelty_score: float 0-1 (how novel or surprising the findings are)
- is_generic_or_off_topic: boolean
- reasoning_notes: string (brief factual notes on scoring)
- raw_model: string (always "MiniMax-M2.7-highspeed")
- prompt_version: string (always "enrichment/v0")

If a field cannot be determined from the input, use null for nullable fields, empty array for summary_bullets, and "unknown" for study_type."""


USER_PROMPT_TEMPLATE = """Raw evidence receipt:
- title: {title}
- excerpt: {excerpt}
- year: {year}
- url: {url}
- doi: {doi}
- source_type: {source_type}
- evidence_type: {evidence_type}
- query: {query}

Produce the evidence_card JSON."""


def _validate(card: dict, raw: dict) -> dict:
    for field in SCHEMA_FIELDS:
        if field not in card:
            card[field] = None
    if not isinstance(card.get("summary_bullets"), list):
        card["summary_bullets"] = []
    for num_field in ("relevance_score", "human_evidence_score", "safety_signal_score", "novelty_score"):
        if isinstance(card.get(num_field), (int, float)):
            card[num_field] = max(0.0, min(1.0, float(card[num_field])))
        else:
            card[num_field] = 0.0
    card["is_generic_or_off_topic"] = bool(card.get("is_generic_or_off_topic", True))
    card["raw_model"] = "MiniMax-M2.7-highspeed"
    card["prompt_version"] = "enrichment/v0"
    return card


def _safe_fallback(raw: dict, error: str) -> dict:
    return {
        "title": raw.get("title", "unknown"),
        "year": raw.get("year"),
        "doi": raw.get("doi"),
        "url": raw.get("url"),
        "source_type": raw.get("source_type", "unknown"),
        "evidence_type": raw.get("evidence_type", "unknown"),
        "study_type": None,
        "population": None,
        "intervention_or_exposure": None,
        "outcomes": None,
        "summary_bullets": [],
        "relevance_score": 0.0,
        "human_evidence_score": 0.0,
        "safety_signal_score": 0.0,
        "novelty_score": 0.0,
        "is_generic_or_off_topic": True,
        "reasoning_notes": f"fallback: {error}",
        "raw_model": "MiniMax-M2.7-highspeed",
        "prompt_version": "enrichment/v0",
        "error": error,
    }


def enrich_evidence(raw: dict, client: ChatClient | None = None) -> tuple[dict, dict | None]:
    if client is None:
        client = ChatClient.minimax()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=raw.get("title", ""),
        excerpt=raw.get("excerpt", "")[:1000],
        year=raw.get("year", ""),
        url=raw.get("url", ""),
        doi=raw.get("doi", ""),
        source_type=raw.get("source_type", ""),
        evidence_type=raw.get("evidence_type", ""),
        query=raw.get("query", ""),
    )
    try:
        result, raw_response = client.complete_json(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        if "error" in result or not any(k in result for k in ("title", "study_type", "summary_bullets", "relevance_score")):
            raise ValueError(result.get("error", "parse failure"))
        card = _validate(result, raw)
        usage = result.get("usage", {})
        input_toks = usage.get("input_tokens", 0)
        output_toks = usage.get("output_tokens", 0)
        card["cost_usd"] = (input_toks / 1000) * MINIMAX_COST_PER_1K_INPUT_TOKENS + (output_toks / 1000) * MINIMAX_COST_PER_1K_OUTPUT_TOKENS
        return card, raw_response
    except Exception as exc:
        return _safe_fallback(raw, str(exc)), None


def enrich_batch(evidence_list: list[dict], output_path: Path | str | None = None, client: ChatClient | None = None) -> dict:
    if client is None:
        client = ChatClient.minimax()
    cards = []
    raw_responses = []
    total_cost = 0.0
    total_tokens = 0

    for raw in evidence_list:
        card, raw_resp = enrich_evidence(raw, client)
        cards.append(card)
        if raw_resp:
            raw_responses.append(raw_resp)
        total_cost += card.get("cost_usd", 0.0)
        total_tokens += card.get("usage", {}).get("total_tokens", 0)

    run_metadata = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(cards),
        "success_count": sum(1 for c in cards if "error" not in c),
        "fallback_count": sum(1 for c in cards if "error" in c),
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        "prompt_version": "enrichment/v0",
        "model": "MiniMax-M2.7-highspeed",
    }

    if output_path:
        output_path = Path(output_path)
        output_path.write_text(json.dumps({"cards": cards, "metadata": run_metadata}, indent=2, default=str))
        if raw_responses:
            raw_path = output_path.with_suffix(".raw.json")
            raw_path.write_text(json.dumps({"responses": raw_responses, "metadata": run_metadata}, indent=2, default=str))

    return {"cards": cards, "metadata": run_metadata}
