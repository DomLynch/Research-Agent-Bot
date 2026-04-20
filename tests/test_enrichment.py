from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment import enrich_evidence, enrich_batch, _safe_fallback, _validate, SCHEMA_FIELDS


def test_schema_fields_present():
    card = _validate({}, {})
    for field in SCHEMA_FIELDS:
        assert field in card, f"missing field: {field}"


def test_safe_fallback_has_error():
    raw = {"title": "Test", "year": 2020}
    result = _safe_fallback(raw, "parse failed")
    assert result["error"] == "parse failed"
    assert result["title"] == "Test"
    assert result["is_generic_or_off_topic"] is True


def test_batch_writes_output(tmp_path):
    evidence = [
        {"title": "Study A", "excerpt": "A study about X", "year": 2020, "url": "http://a.com", "source_type": "pubmed", "evidence_type": "primary", "query": "X"},
        {"title": "Study B", "excerpt": "B study about Y", "year": 2021, "url": "http://b.com", "source_type": "openalex", "evidence_type": "review", "query": "Y"},
    ]
    output_path = tmp_path / "test.evidence.json"
    result = enrich_batch(evidence, output_path)
    assert "cards" in result
    assert "metadata" in result
    assert len(result["cards"]) == 2
    assert output_path.exists()
    stored = json.loads(output_path.read_text())
    assert "cards" in stored
    assert "metadata" in stored
    assert "total_cost_usd" in result["metadata"]
    assert result["metadata"]["total_cost_usd"] >= 0


def test_batch_writes_raw_output(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({
                    "title": "Study A", "year": 2020, "doi": None, "url": "http://a.com",
                    "source_type": "pubmed", "evidence_type": "primary", "study_type": "unknown",
                    "population": None, "intervention_or_exposure": None, "outcomes": None,
                    "summary_bullets": ["point 1"], "relevance_score": 0.8,
                    "human_evidence_score": 0.7, "safety_signal_score": 0.1,
                    "novelty_score": 0.3, "is_generic_or_off_topic": False,
                    "reasoning_notes": "test",
                })}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    from agent.provider import ChatClient
    client = ChatClient(transport=httpx.MockTransport(handler))

    evidence = [
        {"title": "Study A", "excerpt": "A study about X", "year": 2020, "url": "http://a.com", "source_type": "pubmed", "evidence_type": "primary", "query": "X"},
    ]
    output_path = tmp_path / "test.evidence.json"
    result = enrich_batch(evidence, output_path, client=client)
    raw_path = tmp_path / "test.evidence.raw.json"
    assert raw_path.exists()
    raw_stored = json.loads(raw_path.read_text())
    assert "responses" in raw_stored
    assert "metadata" in raw_stored


def test_enrich_with_mocked_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({
                    "title": "Mocked Study",
                    "year": 2021,
                    "doi": "10.1234/test",
                    "url": "http://test.com",
                    "source_type": "pubmed",
                    "evidence_type": "primary",
                    "study_type": "RCT",
                    "population": "Adults with condition X",
                    "intervention_or_exposure": "Drug A vs placebo",
                    "outcomes": "Response rate at 12 weeks",
                    "summary_bullets": ["Primary outcome positive", "Safety profile acceptable", "No serious adverse events"],
                    "relevance_score": 0.85,
                    "human_evidence_score": 0.9,
                    "safety_signal_score": 0.2,
                    "novelty_score": 0.4,
                    "is_generic_or_off_topic": False,
                    "reasoning_notes": "Directly relevant to query",
                })}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    from agent.provider import ChatClient
    minimax_client = ChatClient(transport=httpx.MockTransport(handler))

    raw = {"title": "Test", "excerpt": "Test excerpt", "year": 2021, "url": "http://test.com", "source_type": "pubmed", "evidence_type": "primary", "query": "test"}
    card, raw_resp = enrich_evidence(raw, minimax_client)

    assert card["title"] == "Mocked Study"  # model title used by _validate
    assert card["year"] == 2021
    assert card["study_type"] == "RCT"
    assert card["relevance_score"] == 0.85
    assert card["is_generic_or_off_topic"] is False
    assert "error" not in card
    assert raw_resp is not None
    assert card["cost_usd"] > 0


def test_enrich_fallback_on_invalid_response(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})

    from agent.provider import ChatClient
    minimax_client = ChatClient(transport=httpx.MockTransport(handler))

    raw = {"title": "Test", "excerpt": "Test", "year": 2021, "url": "http://test.com", "source_type": "pubmed", "evidence_type": "primary", "query": "test"}
    card, raw_resp = enrich_evidence(raw, minimax_client)

    assert "error" in card
    assert card["title"] == "Test"
    assert raw_resp is None


def test_enriched_cards_enable_filtering():
    cards = [
        {"title": "A", "relevance_score": 0.9, "is_generic_or_off_topic": False, "safety_signal_score": 0.1},
        {"title": "B", "relevance_score": 0.3, "is_generic_or_off_topic": True, "safety_signal_score": 0.8},
        {"title": "C", "relevance_score": 0.7, "is_generic_or_off_topic": False, "safety_signal_score": 0.2},
    ]
    filtered = [c for c in cards if c["relevance_score"] >= 0.7 and not c["is_generic_or_off_topic"]]
    assert len(filtered) == 2
    assert all(c["relevance_score"] >= 0.7 for c in filtered)
    assert all(not c["is_generic_or_off_topic"] for c in filtered)
    high_safety = [c for c in cards if c["safety_signal_score"] > 0.5]
    assert len(high_safety) == 1
    assert high_safety[0]["title"] == "B"
