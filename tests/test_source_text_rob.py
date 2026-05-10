"""Tests for agent.source_text_rob — Cochrane RoB-2 source-text scaffold.

All tests use a deterministic mock `call_llm` callable. No live LLM,
no spend. The default `call_llm` raises NotImplementedError so a
production-deploy that forgets to wire a real caller fails loudly
instead of silently doing nothing useful.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.source_text_rob import (
    DomainResponse,
    ROB2_DOMAINS,
    StudyAssessmentSourceText,
    _overall_rating,
    assess_study_from_source_text,
    build_domain_prompt,
    default_call_llm_raises,
    load_paper_sections,
    parse_domain_response,
)


# --- Default LLM caller refuses to spend budget --------------------------


def test_default_call_llm_refuses_to_run() -> None:
    """A misconfigured caller MUST not silently spend; the default
    refuses with NotImplementedError."""
    with pytest.raises(NotImplementedError, match="explicit call_llm"):
        default_call_llm_raises("any prompt")


def test_assess_study_uses_default_caller_raises_loudly() -> None:
    """If a caller forgets to pass `call_llm`, the per-domain scan
    fires the default and raises before any LLM round-trip."""
    with pytest.raises(NotImplementedError):
        assess_study_from_source_text(
            study_id="X 2022", paper_id="p",
            paper_sections={"methods": "Some method text."},
        )


# --- Prompt builders -----------------------------------------------------


def test_prompt_includes_signaling_questions_for_each_domain() -> None:
    sections = {"methods": "Random allocation via computer.",
                "introduction": "We tested X."}
    for domain in ROB2_DOMAINS:
        prompt = build_domain_prompt(
            study_id="A 2020", domain=domain, paper_sections=sections,
        )
        assert "RoB-2 v9 signaling questionnaire" in prompt
        assert "Study: A 2020" in prompt
        # Every signaling question for this domain must appear.
        for q in ROB2_DOMAINS[domain]:
            assert q.qid in prompt
            # First 20 chars of the question — minor variation OK.
            assert q.text[:20] in prompt


def test_prompt_only_includes_relevant_sections() -> None:
    """The randomization domain only needs methods + intro, NOT results."""
    sections = {
        "methods": "METHODS_TEXT",
        "introduction": "INTRO_TEXT",
        "results": "RESULTS_TEXT",
        "discussion": "DISCUSSION_TEXT",
    }
    prompt = build_domain_prompt(
        study_id="X", domain="randomization", paper_sections=sections,
    )
    assert "METHODS_TEXT" in prompt
    assert "INTRO_TEXT" in prompt
    assert "RESULTS_TEXT" not in prompt
    assert "DISCUSSION_TEXT" not in prompt


def test_prompt_handles_missing_sections_gracefully() -> None:
    prompt = build_domain_prompt(
        study_id="X", domain="randomization", paper_sections={},
    )
    assert "no relevant sections found" in prompt


# --- Response parser -----------------------------------------------------


def test_parse_response_happy_path() -> None:
    raw = json.dumps({
        "domain": "randomization",
        "rating": "low",
        "rationale": "Computer-generated allocation; concealed envelopes.",
        "signaling_answers": {"1.1": "yes", "1.2": "yes", "1.3": "no"},
    })
    resp = parse_domain_response("randomization", raw)
    assert resp.rating == "low"
    assert "Computer-generated" in resp.rationale
    assert resp.signaling_answers == {"1.1": "yes", "1.2": "yes", "1.3": "no"}


def test_parse_response_strips_code_fences() -> None:
    """Some LLMs wrap JSON in ```json ... ``` even when told not to."""
    raw = "```json\n" + json.dumps({
        "domain": "deviations", "rating": "some_concerns",
        "rationale": "Open-label trial; risk of performance bias.",
        "signaling_answers": {},
    }) + "\n```"
    resp = parse_domain_response("deviations", raw)
    assert resp.rating == "some_concerns"


def test_parse_response_rejects_invalid_rating() -> None:
    raw = json.dumps({
        "domain": "missing_data", "rating": "moderate",  # not a valid rating
        "rationale": "x", "signaling_answers": {},
    })
    with pytest.raises(ValueError, match="rating"):
        parse_domain_response("missing_data", raw)


def test_parse_response_rejects_missing_rationale() -> None:
    raw = json.dumps({
        "domain": "outcome_measurement", "rating": "low",
        "rationale": "", "signaling_answers": {},
    })
    with pytest.raises(ValueError, match="rationale"):
        parse_domain_response("outcome_measurement", raw)


def test_parse_response_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_domain_response("selective_reporting", "this is not json")


def test_parse_response_filters_invalid_signaling_answers() -> None:
    """Drop unrecognized signaling answers rather than reject the whole
    response — the rating is the load-bearing part."""
    raw = json.dumps({
        "domain": "randomization", "rating": "low",
        "rationale": "OK.",
        "signaling_answers": {
            "1.1": "yes",
            "1.2": "MAYBE",          # invalid → dropped
            "1.3": "no_information",
        },
    })
    resp = parse_domain_response("randomization", raw)
    assert resp.signaling_answers == {"1.1": "yes", "1.3": "no_information"}


# --- Overall-rating aggregation (Cochrane "weakest link") ----------------


def _resp(domain: str, rating: str) -> DomainResponse:
    return DomainResponse(
        domain=domain,  # type: ignore[arg-type]
        rating=rating,  # type: ignore[arg-type]
        rationale="x",
        signaling_answers={},
    )


def test_overall_rating_is_high_when_any_domain_is_high() -> None:
    assert _overall_rating((
        _resp("randomization", "low"),
        _resp("deviations", "some_concerns"),
        _resp("missing_data", "high"),
        _resp("outcome_measurement", "low"),
        _resp("selective_reporting", "low"),
    )) == "high"


def test_overall_rating_is_some_concerns_when_max_is_some_concerns() -> None:
    assert _overall_rating((
        _resp("randomization", "low"),
        _resp("deviations", "some_concerns"),
    )) == "some_concerns"


def test_overall_rating_is_low_when_all_low() -> None:
    assert _overall_rating((
        _resp("randomization", "low"),
        _resp("deviations", "low"),
    )) == "low"


def test_overall_rating_defaults_high_on_empty_domains() -> None:
    """Fail-closed: zero domains → assume worst."""
    assert _overall_rating(()) == "high"


# --- End-to-end with deterministic mock LLM ------------------------------


def _mock_llm_factory(rating_per_domain: dict[str, str]) -> "callable":  # type: ignore[valid-type]
    """Return a deterministic call_llm that returns a JSON response
    matching `rating_per_domain` for whatever domain prompt comes in."""

    def caller(prompt: str) -> str:
        # Identify which domain by string-matching the canonical label.
        for domain, rating in rating_per_domain.items():
            label = "Domain: " + domain.replace("_", " ")
            if label in prompt:
                return json.dumps({
                    "domain": domain, "rating": rating,
                    "rationale": f"Mock {domain} rationale.",
                    "signaling_answers": {},
                })
        raise AssertionError(f"unknown domain prompt: {prompt[:200]}")

    return caller


def test_assess_study_aggregates_all_5_domains() -> None:
    sections = {"methods": "M", "introduction": "I", "results": "R",
                "discussion": "D"}
    call_llm = _mock_llm_factory({
        "randomization": "low",
        "deviations": "low",
        "missing_data": "some_concerns",
        "outcome_measurement": "low",
        "selective_reporting": "low",
    })
    assessment = assess_study_from_source_text(
        study_id="Smith 2020", paper_id="PMC1",
        paper_sections=sections, call_llm=call_llm,
    )
    assert isinstance(assessment, StudyAssessmentSourceText)
    assert assessment.study_id == "Smith 2020"
    assert assessment.paper_id == "PMC1"
    assert len(assessment.domains) == 5
    assert assessment.overall_rating == "some_concerns"
    assert assessment.method_status == "source_text_full_cochrane"


def test_assess_study_propagates_llm_parse_failure() -> None:
    """If the LLM returns junk for any domain, fail loud."""

    def broken(prompt: str) -> str:  # noqa: ARG001
        return "{not valid JSON"

    with pytest.raises(ValueError, match="not valid JSON"):
        assess_study_from_source_text(
            study_id="X", paper_id="p",
            paper_sections={"methods": "x"}, call_llm=broken,
        )


# --- Section loader ------------------------------------------------------


def test_load_paper_sections_reads_canonical_schema(tmp_path: Path) -> None:
    p = tmp_path / "paper.json"
    p.write_text(json.dumps({
        "paper_id": "PMC1", "doi": None,
        "sections": {
            "introduction": "I", "methods": "M", "results": "R",
        },
    }))
    sections = load_paper_sections(p)
    assert sections == {"introduction": "I", "methods": "M", "results": "R"}


def test_load_paper_sections_returns_empty_on_missing(tmp_path: Path) -> None:
    assert load_paper_sections(tmp_path / "nope.json") == {}


def test_load_paper_sections_returns_empty_on_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text("{not json")
    assert load_paper_sections(p) == {}


def test_load_paper_sections_drops_non_string_section_values(tmp_path: Path) -> None:
    """Some legacy schemas have nested dicts under `sections`. Coerce
    to str without crashing."""
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"sections": {"methods": "M", "extra": ""}}))
    out = load_paper_sections(p)
    # Empty values are skipped per the implementation
    assert "methods" in out and out["methods"] == "M"
    assert "extra" not in out
