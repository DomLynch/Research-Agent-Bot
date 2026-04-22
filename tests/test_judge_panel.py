"""Tests for agent.review.judge_panel. Uses FakeProvider, no live MiMo."""
from __future__ import annotations

from agent.review.judge_panel import (
    review_draft,
    _draft_as_review_input,
    _normalize_judge_review,
    _adjudicate,
    _aggregate_score,
)


# ---- Fake provider ----

class FakeProvider:
    """Returns pre-canned responses per system_prompt substring match."""
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.calls.append((system_prompt[:50], user_prompt[:50]))
        for needle, response in self.responses.items():
            if needle in system_prompt:
                return (response, {"raw": True})
        return ({}, {"raw": True})


# ---- Sample draft ----

_SAMPLE_DRAFT = {
    "title": "Rapid Evidence Synthesis: metformin and healthspan",
    "abstract": "This draft reviewed 12 studies...",
    "sections": {
        "Methods": "PRISMA-style flow: 100 retrieved, 80 screened, 12 included.",
        "Key Findings": "Metformin reduced mortality by 15% (HR 0.85, 95% CI 0.72-0.98, p=0.03) [1].",
        "Conclusion": "Evidence supports benefit with caveats.",
    },
    "source_bundle": [
        {"title": "A", "year": 2023, "evidence_type": "review", "directness": "direct",
         "card": {"evidence_grade": "H"}},
    ] * 12,
}


# ---- Tests ----

def test_draft_formatter_includes_all_sections():
    text = _draft_as_review_input(_SAMPLE_DRAFT)
    assert "## Methods" in text
    assert "## Key Findings" in text
    assert "HR 0.85" in text
    assert "Source Bundle (12 items)" in text


def test_normalize_judge_review_handles_full_response():
    raw = {
        "axis_scores": [
            {"axis": "search_strategy", "score": 4, "rationale": "good flow"},
            {"axis": "directness", "score": 3, "rationale": "some leakage"},
        ],
        "strengths": ["clear methods"],
        "weaknesses": ["scope drift"],
        "recommendation": "minor_revision",
        "rationale": "Mostly solid, one scope issue.",
    }
    out = _normalize_judge_review(raw, "methodology")
    assert out["role"] == "methodology"
    assert len(out["axis_scores"]) == 2
    assert out["axis_scores"][0]["score"] == 4
    assert out["recommendation"] == "minor_revision"


def test_normalize_handles_score_out_of_range():
    raw = {"axis_scores": [{"axis": "x", "score": 99, "rationale": ""}], "strengths": [],
           "weaknesses": [], "recommendation": "accept", "rationale": ""}
    out = _normalize_judge_review(raw, "evidence")
    assert out["axis_scores"][0]["score"] == 5  # clamped


def test_normalize_handles_malformed_response():
    raw = {}
    out = _normalize_judge_review(raw, "claims")
    assert out["role"] == "claims"
    assert out["recommendation"] == "minor_revision"  # default
    assert out["axis_scores"] == []


def test_normalize_rejects_invalid_verdict():
    raw = {"axis_scores": [], "strengths": [], "weaknesses": [],
           "recommendation": "approve_with_love", "rationale": ""}
    out = _normalize_judge_review(raw, "methodology")
    assert out["recommendation"] == "minor_revision"  # safe default


def test_aggregate_score_mean():
    judges = [
        {"role": "methodology", "axis_scores": [
            {"axis": "a", "score": 5, "rationale": ""},
            {"axis": "b", "score": 3, "rationale": ""}],
         "strengths": [], "weaknesses": [], "recommendation": "accept", "rationale": ""},
        {"role": "evidence", "axis_scores": [
            {"axis": "c", "score": 4, "rationale": ""}],
         "strengths": [], "weaknesses": [], "recommendation": "accept", "rationale": ""},
    ]
    assert _aggregate_score(judges) == 4.0


def test_aggregate_score_empty():
    assert _aggregate_score([]) == 0.0


def test_adjudicate_returns_verdict():
    provider = FakeProvider({
        "peer-review adjudicator": {
            "adjudicated_verdict": "minor_revision",
            "adjudicator_rationale": "Two minors and one major average to minor.",
            "required_fixes": ["fix numeric citations", "tighten scope"],
        },
    })
    judges = [{"role": "methodology", "axis_scores": [], "strengths": [], "weaknesses": [],
               "recommendation": "minor_revision", "rationale": ""}] * 3
    verdict, rationale, fixes = _adjudicate(judges, provider)
    assert verdict == "minor_revision"
    assert len(fixes) == 2


def test_review_draft_full_panel():
    """End-to-end: 4 provider calls (3 judges + 1 adjudicator)."""
    provider = FakeProvider({
        "methodology judge": {
            "axis_scores": [{"axis": "search_strategy", "score": 4, "rationale": "x"}],
            "strengths": ["clear"], "weaknesses": [],
            "recommendation": "accept", "rationale": "solid methodology",
        },
        "evidence judge": {
            "axis_scores": [{"axis": "bundle_quality", "score": 4, "rationale": "x"}],
            "strengths": ["12 sources"], "weaknesses": [],
            "recommendation": "accept", "rationale": "adequate bundle",
        },
        "claims judge": {
            "axis_scores": [{"axis": "overclaim_risk", "score": 3, "rationale": "x"}],
            "strengths": [], "weaknesses": ["some hedging issues"],
            "recommendation": "minor_revision", "rationale": "okay but hedged",
        },
        "peer-review adjudicator": {
            "adjudicated_verdict": "minor_revision",
            "adjudicator_rationale": "One minor rev triggers overall minor.",
            "required_fixes": ["recalibrate hedges"],
        },
    })
    review = review_draft(_SAMPLE_DRAFT, provider=provider)
    assert len(review["judges"]) == 3
    assert review["adjudicated_verdict"] == "minor_revision"
    assert review["aggregate_score"] > 0
    assert "recalibrate hedges" in review["required_fixes"]


def test_review_draft_reject_verdict_propagates():
    provider = FakeProvider({
        "methodology judge": {
            "axis_scores": [{"axis": "scope_discipline", "score": 1, "rationale": "scope abandoned"}],
            "strengths": [], "weaknesses": ["total scope fail"],
            "recommendation": "reject", "rationale": "scope abandoned",
        },
        "evidence judge": {
            "axis_scores": [{"axis": "bundle_quality", "score": 2, "rationale": "thin"}],
            "strengths": [], "weaknesses": ["only 3 sources"],
            "recommendation": "major_revision", "rationale": "thin bundle",
        },
        "claims judge": {
            "axis_scores": [{"axis": "overclaim_risk", "score": 2, "rationale": "big claims"}],
            "strengths": [], "weaknesses": ["unsupported claims"],
            "recommendation": "major_revision", "rationale": "overclaims",
        },
        "peer-review adjudicator": {
            "adjudicated_verdict": "reject",
            "adjudicator_rationale": "Methodology reject + two majors = reject.",
            "required_fixes": ["re-declare scope", "rebuild bundle", "remove overclaims"],
        },
    })
    review = review_draft(_SAMPLE_DRAFT, provider=provider)
    assert review["adjudicated_verdict"] == "reject"
    assert len(review["required_fixes"]) == 3


def test_fake_provider_receives_four_calls():
    provider = FakeProvider({
        "judge": {"axis_scores": [], "strengths": [], "weaknesses": [],
                  "recommendation": "accept", "rationale": ""},
        "adjudicator": {"adjudicated_verdict": "accept", "adjudicator_rationale": "",
                        "required_fixes": []},
    })
    review_draft(_SAMPLE_DRAFT, provider=provider)
    # Should be exactly 3 judge calls + 1 adjudicator call
    assert len(provider.calls) == 4


def test_review_draft_with_empty_bundle():
    """Bot can still review drafts with zero sources -- surfaces as weakness."""
    empty_draft = {"title": "Empty", "abstract": "", "sections": {}, "source_bundle": []}
    provider = FakeProvider({
        "methodology judge": {"axis_scores": [{"axis": "search_strategy", "score": 1, "rationale": "no methods"}],
                  "strengths": [], "weaknesses": ["no sources"],
                  "recommendation": "major_revision", "rationale": "insufficient"},
        "evidence judge": {"axis_scores": [{"axis": "bundle_quality", "score": 1, "rationale": "empty"}],
                  "strengths": [], "weaknesses": ["no sources"],
                  "recommendation": "reject", "rationale": ""},
        "claims judge": {"axis_scores": [{"axis": "overclaim_risk", "score": 2, "rationale": "thin"}],
                  "strengths": [], "weaknesses": ["unsupported"],
                  "recommendation": "major_revision", "rationale": "weak"},
        "adjudicator": {"adjudicated_verdict": "reject",
                        "adjudicator_rationale": "No sources, reject + two majors",
                        "required_fixes": ["add sources"]},
    })
    review = review_draft(empty_draft, provider=provider)
    assert review["adjudicated_verdict"] == "reject"


def test_strengths_and_weaknesses_truncation():
    raw = {
        "axis_scores": [],
        "strengths": ["s" * 500] * 10,
        "weaknesses": ["w" * 500] * 10,
        "recommendation": "accept", "rationale": "r" * 2000,
    }
    out = _normalize_judge_review(raw, "methodology")
    assert len(out["strengths"]) == 5   # truncated to 5
    assert len(out["strengths"][0]) == 300   # each truncated to 300
    assert len(out["rationale"]) == 800      # rationale truncated to 800
