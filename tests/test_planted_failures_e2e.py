"""Day 4.4 — end-to-end planted-failure regression.

For each of the 5 planted-failure cases, drive a synthetic adversarial
scenario through the full Day-4 trust spine and assert it's caught at
the expected gate. The strongest test: the LLM judges (mocked) all
vote ACCEPT — a "panel was fooled" scenario — and the deterministic
trust-spine trace gate (`bc5e080`) must still reject the submission.

Cases:
  1. TAME protocol cited as results — trace_nct_exists fails
     (has_results=False under role=published_results).
  2. Fabricated NCT99999999 — trace_nct_exists yields passed=False
     (registry returns None).
  3. Inflated p<0.001 against an abstract that says p=0.08 —
     trace_p_value_in_text fails per-pvalue.
  4. Glufomin alias drift — trace_alias_match yields passed=False
     (ChEMBL fixture has no Glufomin).
  5. Off-domain extrapolation — trace_role_match flags
     directness='direct' against indirect/mechanistic refs.

Each test assembles the failing trace(s) directly and runs them through
`run_spar` with mocked-accept judges, asserting:
  - SPARReview.gate_override is populated (gate fired)
  - SPARReview.verdict == 'reject_critical' (gate forces this)
  - The panel's pre_gate_verdict was accept_clean (LLM was fooled)
  - write_paper renders the rejection notice with TRUST-SPINE TRACE
    GATE TRIGGERED prominently, and the failed-trace detail is
    visible in the markdown.

Plus 3 interior-layer tests showing defense-in-depth: writer's gates
ALSO catch cases 1, 3, 4 at the prose level (verb-ban / p-value
mismatch / alias-drift), even before the trust-spine gate runs.

No new runtime modules — pure integration tests against existing
trust-spine code paths.
"""
from __future__ import annotations

import asyncio
import json
from types import MappingProxyType

import httpx
import pytest

from agent.llm_client import CallSpec
from agent.schemas import (
    Claim,
    CitationTrace,
    ClaimGraph,
    JudgeReview,
)
from agent.spar import run_spar
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, Source
from agent.writer import write_paper


# --- Shared fixtures ------------------------------------------------------


def _src(ref: int = 1, *, nct: str | None = None, year: int = 2024) -> Source:
    return Source(
        ref=ref, title="Trial paper", year=year,
        url="https://x", source="pubmed", nct=nct,
    )


def _item(
    ref: int = 1, *,
    role: str = "published_results",
    nct: str | None = None,
    abstract: str = "Metformin reduced HbA1c (p=0.003).",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design="rct",  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        tier="A1", direct=True, strict=True,
    )


def _claim(
    cid: str = "C001", *,
    text: str = "metformin reduced HbA1c.",
    refs: tuple[int, ...] = (1,),
    directness: str = "direct",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier="A1", confidence="high",
        attack_surface=(),
    )


def _graph(*claims: Claim) -> ClaimGraph:
    cs = claims or (_claim(),)
    return ClaimGraph(claims=cs, edges=(), thesis_claim_id=cs[0].claim_id)


def _pack() -> TopicPack:
    return TopicPack(
        topic="metformin",
        drug_class="biguanide",
        aliases=frozenset({"metformin", "biguanide", "glucophage"}),
        aliases_display=("metformin", "biguanide", "Glucophage"),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(
            {"demonstrated", "showed", "reduced", "improved"}
        ),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(
            {"planned", "pending", "will assess"}
        ),
        canonical_trials=(),
        known_role_overrides=MappingProxyType({}),
    )


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _all_accept_handler() -> callable:
    """A judge handler that returns ACCEPT for all three judges. Used
    to simulate the worst-case "panel fooled" scenario where only the
    deterministic trust-spine gate stands between bad evidence and an
    accept_clean verdict."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "EVIDENCE AUDITOR" in sys_msg["content"]:
            role = "evidence_auditor"
        elif "DOMAIN SKEPTIC" in sys_msg["content"]:
            role = "domain_skeptic"
        else:
            role = "final_judge"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "verdict": "accept",
                "score": 8,
                "rationale": f"{role} fooled — accepts despite failed trace",
                "flagged_claims": [],
            })}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
    return handler


def _writer_handler(payload: dict) -> callable:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        })
    return handler


def _run(coro):
    return asyncio.run(coro)


# --- Trust-spine gate catches all 5 cases (panel-fooled scenario) ---------


def _trace(
    claim_id: str = "C001",
    trace_type: str = "nct_exists",
    *,
    passed: bool = False,
    detail: str = "trace failed",
    ref: int = 1,
) -> CitationTrace:
    return CitationTrace(
        claim_id=claim_id, ref=ref,
        trace_type=trace_type,  # type: ignore[arg-type]
        passed=passed, detail=detail,
    )


@pytest.mark.parametrize("case_name,failed_trace", [
    (
        "case_1_tame_protocol_as_results",
        _trace(
            trace_type="nct_exists",
            detail=(
                "NCT04264897 role='published_results' but registry says "
                "has_results=False (status=recruiting). Protocol-as-results "
                "contradiction."
            ),
        ),
    ),
    (
        "case_2_fabricated_nct",
        _trace(
            trace_type="nct_exists",
            detail="NCT 'NCT99999999' not found in registry (fabricated)",
        ),
    ),
    (
        "case_3_inflated_pvalue",
        _trace(
            trace_type="p_value_in_text",
            detail="claim cites p<0.001; abstract has p=0.08",
        ),
    ),
    (
        "case_4_glufomin_alias_drift",
        _trace(
            trace_type="alias_match",
            detail="alias 'Glufomin' NOT resolved in ChEMBL (drift)",
        ),
    ),
    (
        "case_5_off_domain_extrapolation",
        _trace(
            trace_type="role_match",
            detail=(
                "claim directness='direct' but supporting_refs are all "
                "role='mechanistic' (off-domain extrapolation)"
            ),
        ),
    ),
])
def test_planted_failure_caught_by_trust_spine_gate(
    case_name: str,
    failed_trace: CitationTrace,
) -> None:
    """The strongest end-to-end test: 3 LLM judges all vote ACCEPT
    (panel fooled), but the deterministic trust-spine trace gate
    (`bc5e080`) overrides to reject_critical. This proves the gate
    is type-agnostic — it fires for any trace_type that the citation
    layer reports as failed (nct_exists / p_value / alias_match /
    role_match)."""
    handler = _all_accept_handler()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                _graph(), [failed_trace],
                topic="metformin",
                submission_id=f"planted-{case_name}",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    review = _run(go())

    # Gate fired
    assert review.gate_override is not None, (
        f"{case_name}: trust-spine gate did NOT fire despite failed trace"
    )
    assert review.gate_override.failed_trace_count == 1
    assert review.gate_override.pre_gate_verdict == "accept_clean"

    # Verdict overridden
    assert review.verdict == "reject_critical"

    # Panel votes preserved verbatim — audit trail intact
    assert all(r.verdict == "accept" for r in review.reviews)

    # Dissent suppressed on gate path
    assert review.dissent is None


def test_planted_failure_writer_renders_rejection_with_gate_banner() -> None:
    """End-to-end with the writer in the loop: gate-overridden SPAR
    produces a rejection markdown with the TRUST-SPINE TRACE GATE
    TRIGGERED banner prominent, the panel's accept_clean preserved
    for audit, and the failed trace detail visible."""
    spar_handler = _all_accept_handler()

    failed = _trace(
        trace_type="nct_exists",
        detail="NCT99999999 not found in registry (fabricated)",
    )

    async def go():
        # Run SPAR first (gate triggers here)
        client_spar = httpx.AsyncClient(transport=httpx.MockTransport(spar_handler))
        try:
            review = await run_spar(
                _graph(), [failed],
                topic="metformin", submission_id="planted-e2e",
                chain=(_spec(),), client=client_spar,
            )
        finally:
            await client_spar.aclose()

        # Then write — should NOT call the LLM (verdict is reject)
        writer_calls = {"n": 0}

        def writer_handler_local(request):
            writer_calls["n"] += 1
            pytest.fail("writer should NOT call LLM on gate-override path")
            return httpx.Response(500)  # unreachable

        client_w = httpx.AsyncClient(transport=httpx.MockTransport(writer_handler_local))
        try:
            md, rejections = await write_paper(
                _graph(), [_item(1)], [failed], review,
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client_w,
            )
        finally:
            await client_w.aclose()
        return md, rejections, writer_calls["n"]

    md, rejections, n_calls = _run(go())
    assert n_calls == 0  # writer skipped LLM
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in md
    assert "accept_clean" in md  # panel's original verdict visible
    assert "reject_critical" in md  # canonical verdict
    assert "NCT99999999 not found" in md
    assert rejections == []


# --- Defense-in-depth: writer-layer gates also catch some cases ----------


def test_case_1_caught_at_writer_verb_ban_layer() -> None:
    """Writer's verb-ban gate catches Case 1's prose form (`TAME
    demonstrated...` against a registered_pending ref) even when SPAR
    is bypassed entirely. Defense-in-depth: the spine doesn't depend
    on a single layer."""
    handler = _writer_handler({
        "title": "T",
        "abstract": [
            {"claim_ids": ["C001"], "text": "TAME demonstrated benefit [1]."},
        ],
        "sections": {},
    })

    # Set up: ref 1 is a registered_pending TAME entry
    g = _graph(_claim("C001", refs=(1,)))
    items = [_item(1, role="registered_pending", nct="NCT04264897")]
    spar_accept = _make_accept_clean_spar()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                g, items, [], spar_accept,
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert "TAME demonstrated" not in md  # prose dropped
    assert any(r.reason.startswith("verb_ban:") for r in rejections), (
        f"verb-ban should have fired; rejections: {[r.reason for r in rejections]}"
    )


def test_case_3_caught_at_writer_p_value_layer() -> None:
    """Writer's p-value source-trace catches Case 3's inflated p-value
    in prose even when upstream layers (validator + citation_trace)
    might miss a particular phrasing."""
    handler = _writer_handler({
        "title": "T",
        "abstract": [
            {
                "claim_ids": ["C001"],
                "text": "metformin reduced X (p<0.001) [1].",
            },
        ],
        "sections": {},
    })

    g = _graph(_claim("C001", refs=(1,)))
    items = [_item(1, abstract="A modest signal was reported (p=0.08).")]
    spar_accept = _make_accept_clean_spar()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                g, items, [], spar_accept,
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert "p<0.001" not in md
    assert any(r.reason.startswith("p_value_not_in_source:") for r in rejections), (
        f"p-value gate should have fired; rejections: {[r.reason for r in rejections]}"
    )


def test_case_4_caught_at_writer_alias_drift_layer() -> None:
    """Writer's alias-drift gate catches Case 4's apposition pattern
    ('Glufomin, a metformin alias, ...') even on the prose layer."""
    handler = _writer_handler({
        "title": "T",
        "abstract": [
            {
                "claim_ids": ["C001"],
                "text": "Glufomin, a metformin alias, was tested [1].",
            },
        ],
        "sections": {},
    })

    g = _graph(_claim("C001", refs=(1,)))
    items = [_item(1)]
    spar_accept = _make_accept_clean_spar()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                g, items, [], spar_accept,
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert "Glufomin" not in md
    assert any(r.reason.startswith("alias_drift:") for r in rejections), (
        f"alias-drift should have fired; rejections: {[r.reason for r in rejections]}"
    )


# --- Helpers --------------------------------------------------------------


def _make_accept_clean_spar():
    """Synthesize a clean accept_clean SPARReview for tests that bypass
    the SPAR call (i.e., focus on the writer's gates)."""
    from agent.schemas import SPARReview

    def _r(role: str) -> JudgeReview:
        return JudgeReview(
            judge_role=role,  # type: ignore[arg-type]
            model="m", verdict="accept",
            score=8, rationale="ok", flagged_claims=(),
        )

    return SPARReview(
        submission_id="x",
        reviews=(
            _r("evidence_auditor"),
            _r("domain_skeptic"),
            _r("final_judge"),
        ),
        verdict="accept_clean",
        dissent=None,
        final_judge_resolution="ok",
        gate_override=None,
    )
