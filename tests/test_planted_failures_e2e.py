"""Day 4.4 + 4-fix P2 — end-to-end planted-failure regression.

For each of the 5 planted-failure cases, drive a synthetic adversarial
scenario through the **real** `trace_claim_graph` against fixture
trace clients, then feed the resulting traces into `run_spar` (with
mocked-accept judges) and assert the trust-spine trace gate fires.

This closes Day 4-fix P2: the previous Day 4.4 fed synthetic
`CitationTrace` objects directly to SPAR, proving the gate worked but
NOT proving the planted scenarios actually generate failed traces
through the real citation_trace path. Now both halves are proven.

The strongest scenario: 3 LLM judges all vote ACCEPT (worst-case
"panel fooled"); the deterministic trust-spine gate must still
reject the submission via the failed traces produced by real
citation_trace logic.

Cases:
  1. TAME protocol cited as results — `trace_nct_exists` fails
     (TAME registry record has `has_results=False` while the
     EvidenceItem is classified `role=published_results`).
  2. Fabricated NCT99999999 — `trace_nct_exists` yields passed=False
     (fixture registry returns None for the unknown id).
  3. Inflated p-value — `trace_p_value_in_text` fails per-pvalue
     (claim cites `p<0.001`; abstract has `p=0.08`).
  4. Glufomin alias drift — `trace_alias_match` yields passed=False
     (fixture compound store has no Glufomin entry).
  5. Off-domain extrapolation — `trace_role_match` flags the
     directness/role contract violation.

Plus 3 defense-in-depth tests showing the same cases caught at
interior layers (writer-time validators), proving the trust spine
isn't relying on a single defense layer.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from agent.citation_trace import trace_claim_graph
from agent.llm_client import CallSpec
from agent.schemas import (
    Claim,
    CitationTrace,
    ClaimGraph,
)
from agent.spar import run_spar
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Source
from agent.validators import (
    check_alias_drift,
    check_p_value_in_source,
    check_verb_ban,
)


METFORMIN_PACK_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


# --- Fixtures (real metformin pack + fixture trace clients) --------------


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(METFORMIN_PACK_PATH)


@pytest.fixture(scope="module")
def registry() -> FixtureTrialRegistryClient:
    return FixtureTrialRegistryClient()


@pytest.fixture(scope="module")
def drug_client() -> FixtureDrugAliasClient:
    return FixtureDrugAliasClient()


# --- Helpers --------------------------------------------------------------


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
    direct: bool = True,
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design="rct",  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        tier="A1", direct=direct, strict=direct,
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


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _all_accept_handler() -> callable:
    """Mock LLM handler returning ACCEPT for all 3 judges. Simulates
    the worst-case panel-fooled scenario: only the deterministic
    trust-spine gate stands between bad evidence and accept_clean."""
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
                "rationale": f"{role} fooled — accepts despite trace failure",
                "flagged_claims": [],
            })}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
    return handler


def _run(coro):
    return asyncio.run(coro)


def _real_traces(
    graph: ClaimGraph,
    items: list[EvidenceItem],
    pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> list[CitationTrace]:
    """Run real `trace_claim_graph` against fixture trace clients.
    No synthesizing — every trace returned is what the citation_trace
    layer actually produces from the inputs."""
    items_by_ref = {it.source.ref: it for it in items}
    return list(trace_claim_graph(
        graph, items_by_ref, pack,
        registry=registry, drug_client=drug_client,
    ))


def _pipeline_to_spar(
    graph: ClaimGraph,
    items: list[EvidenceItem],
    pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
    submission_id: str,
):
    """Drive: real_traces → run_spar → return (traces, review).

    Mocked judges all vote accept; the trust-spine gate must override
    if any of the real traces failed.
    """
    traces = _real_traces(graph, items, pack, registry, drug_client)

    handler = _all_accept_handler()

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_spar(
                graph, traces,
                topic="metformin", submission_id=submission_id,
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    return traces, _run(go())


# --- Real-trace planted-failure E2E (Day 4-fix P2) -----------------------


def test_case_1_tame_protocol_as_results_real_pipeline(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """TAME (NCT04264897) registry has `has_results=False`; an item
    classified `role=published_results` citing it produces a failed
    `nct_exists` trace via the real citation_trace path."""
    item = _item(
        ref=1, role="published_results", nct="NCT04264897",
        abstract="The TAME trial (NCT04264897) is studying metformin in older adults.",
    )
    graph = _graph(_claim(refs=(1,)))
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="planted-1-real",
    )

    # Real trace produced a failure
    nct_failures = [
        t for t in traces
        if t.trace_type == "nct_exists" and not t.passed
    ]
    assert nct_failures, (
        f"expected nct_exists FAIL for TAME has_results=False; got {traces}"
    )
    assert "has_results=False" in nct_failures[0].detail

    # Trust-spine gate fired
    assert review.gate_override is not None
    assert review.verdict == "reject_critical"
    assert review.gate_override.pre_gate_verdict == "accept_clean"


def test_case_2_fabricated_nct_real_pipeline(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Fixture registry returns None for NCT99999999. Real
    `trace_nct_exists` yields passed=False."""
    item = _item(
        ref=1, role="published_results", nct="NCT99999999",
        abstract="A study (NCT99999999) reported metformin outcomes.",
    )
    graph = _graph(_claim(refs=(1,)))
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="planted-2-real",
    )
    nct_failures = [
        t for t in traces
        if t.trace_type == "nct_exists" and not t.passed
    ]
    assert nct_failures, "expected fabricated-NCT trace failure"
    assert "not found" in nct_failures[0].detail.lower()
    assert review.gate_override is not None
    assert review.verdict == "reject_critical"


def test_case_3_inflated_pvalue_real_pipeline(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Claim cites `p<0.001`; abstract only has `p=0.08`. Real
    `trace_p_value_in_text` yields passed=False."""
    item = _item(
        ref=1, role="published_results",
        abstract="A modest signal was reported (p=0.08).",
    )
    claim = _claim(text="metformin reduced X (p<0.001).", refs=(1,))
    graph = _graph(claim)
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="planted-3-real",
    )
    pval_failures = [
        t for t in traces
        if t.trace_type == "p_value_in_text" and not t.passed
    ]
    assert pval_failures, (
        f"expected p_value_in_text FAIL for inflated p<0.001 vs p=0.08; "
        f"got {[(t.trace_type, t.passed, t.detail) for t in traces]}"
    )
    assert review.gate_override is not None
    assert review.verdict == "reject_critical"


def test_case_4_glufomin_alias_drift_real_pipeline(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Claim text mentions `Glufomin`; the fixture compound corpus
    does not have a Glufomin entry, so real `trace_alias_match`
    yields passed=False on that token."""
    item = _item(ref=1, role="published_results")
    claim = _claim(text="Glufomin showed mortality benefit.", refs=(1,))
    graph = _graph(claim)
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="planted-4-real",
    )
    alias_failures = [
        t for t in traces
        if t.trace_type == "alias_match" and not t.passed
        and "Glufomin" in (t.detail or "")
    ]
    assert alias_failures, (
        f"expected alias_match FAIL for Glufomin; got "
        f"{[(t.trace_type, t.passed, t.detail) for t in traces]}"
    )
    assert review.gate_override is not None
    assert review.verdict == "reject_critical"


def test_case_5_off_domain_extrapolation_real_pipeline(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Claim with `directness=direct` but supporting ref has
    `direct=False` (off-topic / off-population) — real
    `trace_role_match` (which wraps `check_role_claim_match`) flags
    the directness contract violation as `CLAIM_DIRECTNESS_MISMATCH`."""
    item = _item(ref=1, role="mechanistic", direct=False)  # off-domain
    claim = _claim(directness="direct", refs=(1,))
    graph = _graph(claim)
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="planted-5-real",
    )
    role_failures = [
        t for t in traces
        if t.trace_type == "role_match" and not t.passed
    ]
    assert role_failures, (
        f"expected role_match FAIL for direct claim with mechanistic-only ref; "
        f"got {[(t.trace_type, t.passed, t.detail) for t in traces]}"
    )
    assert review.gate_override is not None
    assert review.verdict == "reject_critical"


# --- Defense-in-depth: validators catch interior cases at prose layer ----


def test_case_1_caught_at_validator_verb_ban_layer(
    metformin_pack: TopicPack,
) -> None:
    """`validators.check_verb_ban` catches Case 1's prose form
    (`TAME demonstrated...` against a registered_pending ref) at
    the prose layer — even before SPAR or citation_trace run."""
    item = _item(ref=1, role="registered_pending", nct="NCT04264897")
    fail = check_verb_ban(
        "TAME demonstrated cardiovascular benefit in older adults.",
        item, metformin_pack,
    )
    assert fail is not None
    assert fail.code == "VERB_BAN_PROTOCOL"


def test_case_3_caught_at_validator_p_value_layer() -> None:
    """`validators.check_p_value_in_source` catches Case 3's inflated
    p-value at the prose layer."""
    fail = check_p_value_in_source(
        "metformin lowered HbA1c (p<0.001).",
        "Some effect was observed (p=0.08).",
    )
    assert fail is not None
    assert fail.code == "P_VALUE_NOT_IN_SOURCE"


def test_case_4_caught_at_validator_alias_drift_layer(
    metformin_pack: TopicPack,
) -> None:
    """`validators.check_alias_drift` catches Case 4's apposition
    pattern at the prose layer."""
    fail = check_alias_drift(
        "Glufomin, a metformin alias, was tested in older adults.",
        metformin_pack,
    )
    assert fail is not None


# --- Sensitivity AND specificity ----------------------------------------


def test_clean_paper_passes_through_with_no_gate_trigger(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Specificity proof (reviewer's missing-test concern): a clean,
    valid scenario must NOT trigger the trust-spine gate.

    The fixture corpus has MASTERS (NCT02308228) as a real completed
    trial with `has_results=True`. A claim citing MASTERS with a
    matching p-value and clean prose should produce only PASS traces;
    the panel's accept_clean should stand un-overridden."""
    item = _item(
        ref=1,
        role="published_results",
        nct="NCT02308228",  # MASTERS, completed, has_results=True
        abstract=(
            "The MASTERS trial reported lean body mass changes "
            "(p=0.003) and thigh muscle area (p=0.005) in older adults."
        ),
    )
    claim = _claim(
        text="metformin reduced lean body mass (p=0.003).",
        refs=(1,),
    )
    graph = _graph(claim)
    traces, review = _pipeline_to_spar(
        graph, [item], metformin_pack, registry, drug_client,
        submission_id="clean-passthrough",
    )
    failed = [t for t in traces if not t.passed]
    assert not failed, (
        f"clean scenario produced unexpected failures: "
        f"{[(t.trace_type, t.detail) for t in failed]}"
    )
    # No gate fire — verdict comes from the panel
    assert review.gate_override is None
    assert review.verdict == "accept_clean"
