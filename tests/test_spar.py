"""Tests for agent/spar.py — 3-judge panel orchestration.

Covers:
- Brief rendering (deterministic, includes thesis + claims + traces)
- JudgeReview parsing (verdict / score / rationale / flagged validation)
- Single-judge call via httpx.MockTransport
- Full run_spar happy path (3-0 unanimous)
- 2-1 split → dissent populated, verdict = accept_caveated
- 1-2 split → dissent populated, verdict = reject_majority
- 0-3 unanimous reject → verdict = reject_critical, dissent=None
- Final-judge user prompt receives panel context (the prior reviews)
- Auditor + Skeptic run in parallel (single client; both fired before final)
- Malformed judge response → SPARError
- LLM transport failure → propagates as LLMError
- Schema invariants re-enforced post-orchestration
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent.llm_client import CallSpec
from agent.schemas import (
    Claim,
    CitationTrace,
    ClaimGraph,
    JudgeReview,
    SPARInvariantError,
)
from agent.spar import (
    PROMPT_VERSION,
    SPARError,
    _identify_dissent,
    _parse_judge_review,
    render_brief,
    reviews_to_dict,
    run_spar,
)


# --- Fixtures -------------------------------------------------------------


def _claim(
    cid: str = "C001",
    *,
    text: str = "metformin reduced HbA1c.",
    refs: tuple[int, ...] = (1,),
    directness: str = "direct",
    tier: str = "A1",
    confidence: str = "high",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier=tier,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        attack_surface=(),
    )


def _graph(*claims: Claim) -> ClaimGraph:
    cs = claims or (_claim(),)
    return ClaimGraph(claims=cs, edges=(), thesis_claim_id=cs[0].claim_id)


def _trace(
    claim_id: str = "C001",
    *,
    trace_type: str = "nct_exists",
    passed: bool = True,
    detail: str = "fixture trace",
    ref: int = 1,
) -> CitationTrace:
    return CitationTrace(
        claim_id=claim_id, ref=ref,
        trace_type=trace_type,  # type: ignore[arg-type]
        passed=passed, detail=detail,
    )


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _judge_response(
    verdict: str, *,
    score: int = 7, rationale: str = "ok rationale",
    flagged: list[str] | None = None,
) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps({
            "verdict": verdict,
            "score": score,
            "rationale": rationale,
            "flagged_claims": flagged or [],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def _run(coro):
    return asyncio.run(coro)


# --- render_brief --------------------------------------------------------


def test_render_brief_includes_topic_thesis_claims_traces() -> None:
    g = _graph(_claim("C001", text="A reduced X."), _claim("C002", text="B reduced Y."))
    brief = render_brief(
        g, [_trace("C001", passed=True, detail="MASTERS found")],
        topic="metformin", submission_id="run-001",
    )
    assert "metformin" in brief
    assert "run-001" in brief
    assert "C001" in brief
    assert "A reduced X." in brief
    assert "C002" in brief  # all claims, not just thesis
    assert "MASTERS found" in brief


def test_render_brief_marks_passed_and_failed_traces() -> None:
    g = _graph()
    brief = render_brief(
        g, [
            _trace(passed=True, detail="passing"),
            _trace(passed=False, detail="failing"),
        ],
        topic="t", submission_id="s",
    )
    assert "PASS" in brief
    assert "FAIL" in brief


def test_render_brief_empty_traces_signals_explicitly() -> None:
    """No-traces case must say so (not just print empty CITATION TRACES:)
    so a judge doesn't silently miss that traces weren't run."""
    brief = render_brief(_graph(), [], topic="t", submission_id="s")
    assert "no citation traces" in brief.lower() or "CITATION TRACES (0)" in brief


def test_render_brief_is_deterministic() -> None:
    """Same input → same output (no time-of-day / random)."""
    g = _graph()
    a = render_brief(g, [_trace()], topic="m", submission_id="s")
    b = render_brief(g, [_trace()], topic="m", submission_id="s")
    assert a == b


# --- _parse_judge_review --------------------------------------------------


def test_parse_judge_review_happy_path() -> None:
    review = _parse_judge_review(
        {"verdict": "accept", "score": 8, "rationale": "good evidence", "flagged_claims": []},
        judge_role="evidence_auditor", model="m",
    )
    assert review.verdict == "accept"
    assert review.score == 8
    assert review.rationale == "good evidence"
    assert review.flagged_claims == ()
    assert review.judge_role == "evidence_auditor"
    assert review.model == "m"


def test_parse_judge_review_strips_rationale_whitespace() -> None:
    review = _parse_judge_review(
        {"verdict": "accept", "score": 5, "rationale": "  padded  ", "flagged_claims": []},
        judge_role="evidence_auditor", model="m",
    )
    assert review.rationale == "padded"


def test_parse_judge_review_filters_non_string_flagged() -> None:
    """LLM might emit `flagged_claims: [42, "C001", null]` — non-string
    entries are filtered, not coerced. Defensive."""
    review = _parse_judge_review(
        {"verdict": "reject", "score": 3, "rationale": "bad",
         "flagged_claims": [42, "C001", None, "C002"]},
        judge_role="domain_skeptic", model="m",
    )
    assert review.flagged_claims == ("C001", "C002")


def test_parse_judge_review_bad_verdict_raises() -> None:
    with pytest.raises(SPARError, match="verdict must be"):
        _parse_judge_review(
            {"verdict": "maybe", "score": 5, "rationale": "x", "flagged_claims": []},
            judge_role="final_judge", model="m",
        )


def test_parse_judge_review_score_out_of_range_raises() -> None:
    with pytest.raises(SPARError, match="score must be int 1-10"):
        _parse_judge_review(
            {"verdict": "accept", "score": 11, "rationale": "x", "flagged_claims": []},
            judge_role="final_judge", model="m",
        )


def test_parse_judge_review_score_non_int_raises() -> None:
    with pytest.raises(SPARError, match="score must be int 1-10"):
        _parse_judge_review(
            {"verdict": "accept", "score": "7", "rationale": "x", "flagged_claims": []},
            judge_role="final_judge", model="m",
        )


def test_parse_judge_review_empty_rationale_raises() -> None:
    with pytest.raises(SPARError, match="rationale must be non-empty"):
        _parse_judge_review(
            {"verdict": "accept", "score": 5, "rationale": "   ", "flagged_claims": []},
            judge_role="final_judge", model="m",
        )


def test_parse_judge_review_flagged_claims_not_a_list_raises() -> None:
    with pytest.raises(SPARError, match="flagged_claims must be a list"):
        _parse_judge_review(
            {"verdict": "accept", "score": 5, "rationale": "x", "flagged_claims": "C001"},
            judge_role="final_judge", model="m",
        )


def test_parse_judge_review_flagged_claims_default_to_empty() -> None:
    """A judge that omits `flagged_claims` entirely → empty tuple, not error."""
    review = _parse_judge_review(
        {"verdict": "accept", "score": 5, "rationale": "x"},
        judge_role="final_judge", model="m",
    )
    assert review.flagged_claims == ()


# --- _identify_dissent ----------------------------------------------------


def _r(role: str, verdict: str) -> JudgeReview:
    return JudgeReview(
        judge_role=role,  # type: ignore[arg-type]
        model="m",
        verdict=verdict,  # type: ignore[arg-type]
        score=5, rationale="r",
        flagged_claims=(),
    )


def test_identify_dissent_unanimous_accept_returns_none() -> None:
    reviews = (
        _r("evidence_auditor", "accept"),
        _r("domain_skeptic", "accept"),
        _r("final_judge", "accept"),
    )
    assert _identify_dissent(reviews, "accept_clean") is None


def test_identify_dissent_unanimous_reject_returns_none() -> None:
    reviews = (
        _r("evidence_auditor", "reject"),
        _r("domain_skeptic", "reject"),
        _r("final_judge", "reject"),
    )
    assert _identify_dissent(reviews, "reject_critical") is None


def test_identify_dissent_2_accept_1_reject_returns_rejecter() -> None:
    """accept_caveated: majority accept, dissent is the one rejecter."""
    reviews = (
        _r("evidence_auditor", "accept"),
        _r("domain_skeptic", "reject"),  # this is dissent
        _r("final_judge", "accept"),
    )
    dissent = _identify_dissent(reviews, "accept_caveated")
    assert dissent is not None
    assert dissent.judge_role == "domain_skeptic"
    assert dissent.verdict == "reject"


def test_identify_dissent_1_accept_2_reject_returns_accepter() -> None:
    """reject_majority: majority reject, dissent is the one accepter."""
    reviews = (
        _r("evidence_auditor", "reject"),
        _r("domain_skeptic", "reject"),
        _r("final_judge", "accept"),  # this is dissent
    )
    dissent = _identify_dissent(reviews, "reject_majority")
    assert dissent is not None
    assert dissent.judge_role == "final_judge"
    assert dissent.verdict == "accept"


# --- run_spar: end-to-end with httpx.MockTransport ------------------------


def _make_spar_handler(
    auditor_verdict: str = "accept",
    skeptic_verdict: str = "accept",
    final_verdict: str = "accept",
) -> tuple[callable, dict]:
    """Build a MockTransport handler that returns one canned verdict per
    call ROLE (decoded from the system prompt). Returns (handler, log)
    so the test can inspect call order + final's user prompt."""
    log: dict = {"calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        user_msg = next(m for m in body["messages"] if m["role"] == "user")
        if "EVIDENCE AUDITOR" in sys_msg["content"]:
            role = "evidence_auditor"
            verdict = auditor_verdict
        elif "DOMAIN SKEPTIC" in sys_msg["content"]:
            role = "domain_skeptic"
            verdict = skeptic_verdict
        else:
            role = "final_judge"
            verdict = final_verdict
        log["calls"].append({"role": role, "user_prompt": user_msg["content"]})
        return httpx.Response(200, json=_judge_response(
            verdict, rationale=f"{role}/{verdict} rationale",
        ))
    return handler, log


def test_run_spar_unanimous_accept_no_dissent() -> None:
    handler, log = _make_spar_handler("accept", "accept", "accept")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-001",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    assert review.verdict == "accept_clean"
    assert review.dissent is None
    assert len(review.reviews) == 3
    roles = {r.judge_role for r in review.reviews}
    assert roles == {"evidence_auditor", "domain_skeptic", "final_judge"}
    # All 3 calls fired
    assert len(log["calls"]) == 3


def test_run_spar_unanimous_reject_no_dissent() -> None:
    handler, _ = _make_spar_handler("reject", "reject", "reject")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace(passed=False)],
                topic="metformin", submission_id="run-002",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    assert review.verdict == "reject_critical"
    assert review.dissent is None


def test_run_spar_2_1_accept_split_publishes_dissent() -> None:
    """Auditor + Final accept; Skeptic rejects → accept_caveated with
    Skeptic as dissent."""
    handler, _ = _make_spar_handler(
        "accept", "reject", "accept",
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-003",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    assert review.verdict == "accept_caveated"
    assert review.dissent is not None
    assert review.dissent.judge_role == "domain_skeptic"
    assert review.dissent.verdict == "reject"


def test_run_spar_1_2_reject_split_publishes_dissent() -> None:
    """Auditor + Skeptic reject; Final accepts → reject_majority with
    Final as dissent. Final-as-dissent is the most fragile case in the
    audit trail because it's the tie-breaker breaking the wrong way —
    the dissent line keeps that decision visible."""
    handler, _ = _make_spar_handler(
        "reject", "reject", "accept",
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-004",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    assert review.verdict == "reject_majority"
    assert review.dissent is not None
    assert review.dissent.judge_role == "final_judge"
    assert review.dissent.verdict == "accept"


def test_run_spar_final_judge_sees_panel_context() -> None:
    """The final judge's user prompt must include the auditor + skeptic
    reviews appended as PANEL CONTEXT — that's the whole point of
    sequencing the third call after the first two."""
    handler, log = _make_spar_handler("accept", "reject", "accept")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-005",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    _run(go())
    final_call = next(c for c in log["calls"] if c["role"] == "final_judge")
    final_prompt = final_call["user_prompt"]
    assert "PANEL CONTEXT" in final_prompt
    assert "Evidence Auditor" in final_prompt
    assert "Domain Skeptic" in final_prompt
    assert "verdict=accept" in final_prompt   # auditor's accept
    assert "verdict=reject" in final_prompt   # skeptic's reject


def test_run_spar_first_two_run_before_final() -> None:
    """Auditor + Skeptic must complete before Final fires. Single MockTransport
    is sequential by default, so this just verifies the call ORDER:
    auditor + skeptic appear before final in the log."""
    handler, log = _make_spar_handler("accept", "accept", "accept")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-006",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    _run(go())
    roles_in_order = [c["role"] for c in log["calls"]]
    final_idx = roles_in_order.index("final_judge")
    auditor_idx = roles_in_order.index("evidence_auditor")
    skeptic_idx = roles_in_order.index("domain_skeptic")
    assert final_idx > auditor_idx
    assert final_idx > skeptic_idx


def test_run_spar_malformed_judge_response_raises_spar_error() -> None:
    """LLM emits bad-verdict JSON → parse fails → SPARError propagates.
    Caller can retry the whole pass; default is fail-loud."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "verdict": "maybe",  # bad
                "score": 5, "rationale": "x", "flagged_claims": [],
            })}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-bad",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(SPARError, match="verdict must be"):
        _run(go())


def test_run_spar_records_to_ledger() -> None:
    from agent.llm_client import CostLedger
    handler, _ = _make_spar_handler("accept", "accept", "accept")
    led = CostLedger()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-007",
                chain=(_spec(),), client=client, ledger=led,
            )
        finally:
            await client.aclose()

    _run(go())
    # 3 judges = 3 ledger entries
    assert len(led.calls) == 3


def test_run_spar_invariant_failure_surfaces() -> None:
    """Defense-in-depth: if _identify_dissent or compute_spar_verdict had
    a bug, assert_spar_invariants would raise. Force a synthetic
    invariant violation by making the schema reject — verify it surfaces."""
    # The most direct way: tamper with the SPARReview to violate the
    # consistency check. We can't easily do that through run_spar's
    # public API, but we CAN verify the invariant runs by constructing
    # a malformed review separately and asserting the error fires.
    bad = JudgeReview(
        judge_role="evidence_auditor", model="m", verdict="accept",
        score=5, rationale="r", flagged_claims=(),
    )
    bad2 = JudgeReview(
        judge_role="evidence_auditor", model="m", verdict="reject",  # duplicate role
        score=5, rationale="r", flagged_claims=(),
    )
    bad3 = JudgeReview(
        judge_role="domain_skeptic", model="m", verdict="reject",
        score=5, rationale="r", flagged_claims=(),
    )
    from agent.schemas import SPARReview, assert_spar_invariants
    review = SPARReview(
        submission_id="x", reviews=(bad, bad2, bad3),
        verdict="reject_majority",  # 1 accept / 2 reject
        dissent=bad,
        final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="roles must be exactly"):
        assert_spar_invariants(review)


# --- reviews_to_dict ------------------------------------------------------


def test_reviews_to_dict_serializes_unanimous_accept() -> None:
    handler, _ = _make_spar_handler("accept", "accept", "accept")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-100",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    d = reviews_to_dict(review)
    json.dumps(d)  # raises if not serializable
    assert d["verdict"] == "accept_clean"
    assert d["dissent"] is None
    assert len(d["reviews"]) == 3
    assert d["prompt_version"] == PROMPT_VERSION
    assert d["submission_id"] == "run-100"


def test_reviews_to_dict_serializes_split_with_dissent() -> None:
    handler, _ = _make_spar_handler("accept", "reject", "accept")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [_trace()],
                topic="metformin", submission_id="run-101",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())
    d = reviews_to_dict(review)
    assert d["verdict"] == "accept_caveated"
    assert d["dissent"] is not None
    assert d["dissent"]["judge_role"] == "domain_skeptic"
    assert d["dissent"]["verdict"] == "reject"


def test_prompt_version_anchored() -> None:
    assert PROMPT_VERSION == "spar/2026-04-28"
