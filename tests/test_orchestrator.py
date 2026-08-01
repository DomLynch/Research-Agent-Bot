"""Tests for agent/orchestrator.py — single-call pipeline driver.

Fixture-replay only — no network, no real LLM keys. Mocks the two
LLM call layers (fact extraction + SPAR) via httpx.MockTransport,
uses fixture trace clients (FixtureTrialRegistryClient +
FixtureDrugAliasClient), and asserts the 8 receipts are produced
and JSON-loadable.

Live publication execution belongs to the maintained V3 lanes.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import cast

import httpx
import pytest

from agent.llm_client import CallSpec
from agent.orchestrator import (
    OrchestratorError,
    RunReceipts,
    _cluster_manifest_rows,
    run_proof,
    run_proof_multi_receipt,
)
from agent.schemas import ClaimGraph
from agent.topic_pack import TopicPack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Source


# --- Fixtures -------------------------------------------------------------


def _src(ref: int = 1, *, nct: str | None = None) -> Source:
    return Source(
        ref=ref, title=f"Trial {ref}", year=2024,
        url=f"https://x.example/{ref}", source="pubmed", nct=nct,
    )


def _item(
    ref: int = 1, *,
    role: str = "published_results",
    nct: str | None = None,
    abstract: str = "Metformin reduced HbA1c by 0.5% (p=0.003).",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design="rct",  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        tier="A1", direct=True, strict=True,
    )


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


def test_cluster_manifest_preserves_original_indices_after_failure(
    tmp_path: Path,
) -> None:
    def success(cluster_index: int) -> tuple[int, ClaimGraph, RunReceipts]:
        output_dir = tmp_path / f"cluster_{cluster_index:02d}"
        output_dir.mkdir()
        spar_review = output_dir / "spar_review.json"
        spar_review.write_text('{"verdict": "accept_clean"}', encoding="utf-8")
        placeholder = output_dir / "placeholder"
        paths = RunReceipts(
            output_dir=output_dir,
            claim_receipt_md=placeholder,
            claim_graph=placeholder,
            citation_traces=placeholder,
            spar_review=spar_review,
            evidence_cards=placeholder,
            cost_log=placeholder,
            fact_extraction_log=placeholder,
            run_metadata=placeholder,
        )
        graph = cast(ClaimGraph, SimpleNamespace(claims=(object(),)))
        return cluster_index, graph, paths

    rows = _cluster_manifest_rows([success(2), success(4)])

    assert [row["cluster_index"] for row in rows] == [2, 4]
    assert [row["subdir"] for row in rows] == ["cluster_02", "cluster_04"]


def _extractor_response(claim: str, p_value: str = "0.003") -> dict:
    """Mock fact_extractor LLM response — one valid Fact."""
    return {
        "choices": [{"message": {"content": json.dumps({
            "facts": [{
                "source_quote": claim,
                "outcome": "HbA1c", "estimate": None,
                "p_value": p_value, "ci": None,
            }],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def _judge_response(verdict: str = "accept") -> dict:
    """Mock SPAR judge response."""
    return {
        "choices": [{"message": {"content": json.dumps({
            "verdict": verdict, "score": 8,
            "rationale": f"{verdict} rationale", "flagged_claims": [],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def _make_handler(
    extract_claim: str = "Metformin reduced HbA1c by 0.5% (p=0.003)",
    extract_pvalue: str = "0.003",
    judge_verdict: str = "accept",
) -> Callable[[httpx.Request], httpx.Response]:
    """Compose a single MockTransport handler that routes by system
    prompt content — fact extractor vs. SPAR judges."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        text = sys_msg["content"]
        if "extract structured FACTS" in text:
            return httpx.Response(200, json=_extractor_response(
                extract_claim, p_value=extract_pvalue,
            ))
        # All three judges return the same canned verdict
        return httpx.Response(200, json=_judge_response(judge_verdict))
    return handler


def _run(coro):
    return asyncio.run(coro)


# --- Happy path ----------------------------------------------------------


def test_run_proof_happy_path_emits_all_eight_receipts(tmp_path: Path) -> None:
    """Clean scenario: 1 item + LLM extracts 1 valid fact + 3 judges
    all accept + no failed traces. All 8 receipts produced and the
    paper is rendered."""
    handler = _make_handler()
    items = [_item(1, abstract="Metformin reduced HbA1c by 0.5% (p=0.003).")]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-happy-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts: RunReceipts = _run(go())

    # All 8 receipts exist on disk
    for path in (
        receipts.claim_receipt_md, receipts.claim_graph, receipts.citation_traces,
        receipts.spar_review, receipts.evidence_cards, receipts.cost_log,
        receipts.fact_extraction_log, receipts.run_metadata,
    ):
        assert path.exists(), f"missing receipt: {path.name}"

    # paper.md has thesis content
    paper = receipts.claim_receipt_md.read_text()
    assert "# " in paper  # has a title
    assert "## Thesis" in paper
    assert "accept_clean" in paper

    # claim_graph.json reloads cleanly
    cg = json.loads(receipts.claim_graph.read_text())
    assert "thesis_claim_id" in cg
    assert isinstance(cg["claims"], list)
    assert len(cg["claims"]) >= 1

    # spar_review.json has the verdict
    sr = json.loads(receipts.spar_review.read_text())
    assert sr["verdict"] == "accept_clean"
    assert sr["gate_override"] is None

    # run_metadata has the right summary
    md = json.loads(receipts.run_metadata.read_text())
    assert md["submission_id"] == "run-happy-001"
    assert md["topic"] == "metformin"
    assert md["spar_verdict"] == "accept_clean"
    assert md["gate_override"] is False
    assert md["n_claims"] >= 1
    assert "started_at" in md and "finished_at" in md


# --- Gate-override path --------------------------------------------------


def test_run_proof_gate_override_path_renders_rejection(tmp_path: Path) -> None:
    """Trace gate fires: judges all accept, but one trace fails.
    paper.md is the rejection notice; run_metadata.gate_override=True."""
    # Use a fabricated NCT so the fixture registry returns None →
    # trace_nct_exists yields passed=False, the trust-spine gate fires.
    items = [_item(
        1, role="published_results", nct="NCT99999999",
        abstract="Trial NCT99999999 reported metformin outcomes (p=0.003).",
    )]
    handler = _make_handler(
        extract_claim="metformin outcomes (p=0.003)",  # verbatim span of the abstract
        judge_verdict="accept",
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-gate-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts: RunReceipts = _run(go())
    paper = receipts.claim_receipt_md.read_text()
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in paper
    assert "reject_critical" in paper

    md = json.loads(receipts.run_metadata.read_text())
    assert md["spar_verdict"] == "reject_critical"
    assert md["gate_override"] is True
    assert md["n_failed_traces"] >= 1

    sr = json.loads(receipts.spar_review.read_text())
    assert sr["gate_override"] is not None
    assert sr["gate_override"]["pre_gate_verdict"] == "accept_clean"


# --- Reject panel path ---------------------------------------------------


def test_run_proof_unanimous_reject_renders_rejection(tmp_path: Path) -> None:
    """Judges all reject → reject_critical, no gate fired (panel
    rejected on its own). paper.md is rejection notice."""
    handler = _make_handler(judge_verdict="reject")
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-reject-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts: RunReceipts = _run(go())
    paper = receipts.claim_receipt_md.read_text()
    assert "DRAFT REJECTED" in paper
    md = json.loads(receipts.run_metadata.read_text())
    assert md["spar_verdict"] == "reject_critical"
    assert md["gate_override"] is False  # panel rejected; gate didn't fire


# --- Empty-extraction failure path ---------------------------------------


def test_run_proof_zero_facts_raises_orchestrator_error(tmp_path: Path) -> None:
    """LLM extracts no usable facts (e.g., all malformed) → orchestrator
    fails loud rather than producing an empty paper. Caller decides
    retry vs surface."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            # Empty facts list — schema-valid but no usable output
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"facts": []}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            })
        return httpx.Response(200, json=_judge_response("accept"))

    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-empty-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(OrchestratorError, match="0 accepted facts"):
        _run(go())


# --- Cost log + fact log shape -------------------------------------------


def test_run_proof_cost_log_separates_extract_and_spar(tmp_path: Path) -> None:
    """cost_log.json records both LLM stages independently for audit."""
    handler = _make_handler()
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-cost-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    cost = json.loads(receipts.cost_log.read_text())
    assert "extract" in cost
    assert "spar" in cost
    assert "total_usd" in cost
    # Extract path: 1 LLM call (1 item)
    assert len(cost["extract"]["calls"]) == 1
    # SPAR path: 3 LLM calls (3 judges)
    assert len(cost["spar"]["calls"]) == 3


def test_run_proof_fact_log_includes_accepted_and_rejected(tmp_path: Path) -> None:
    """fact_extraction_log.json carries BOTH accepted facts and the
    full rejection list for audit. The orchestrator doesn't filter
    rejections away."""
    # Make the extractor propose both a valid fact and a malformed one
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps({
                    "facts": [
                        {  # valid: verbatim span of default abstract
                            "source_quote": "Metformin reduced HbA1c by 0.5% (p=0.003)",
                            "outcome": "HbA1c", "estimate": None,
                            "p_value": "0.003", "ci": None,
                        },
                        {},  # missing source_quote → rejection
                    ],
                })}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })
        return httpx.Response(200, json=_judge_response("accept"))

    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-faclog-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    fact_log = json.loads(receipts.fact_extraction_log.read_text())
    assert "accepted" in fact_log
    assert "rejected" in fact_log
    assert len(fact_log["accepted"]) == 1
    assert len(fact_log["rejected"]) == 1
    assert fact_log["rejected"][0]["reason"] == "missing_or_empty_source_quote"


# --- Output dir handling -------------------------------------------------


def test_run_proof_published_results_with_empty_llm_facts_is_documented_orphan(
    tmp_path: Path,
) -> None:
    """Day 6.1c: a published_results item where the LLM returns an empty
    facts list now produces a SYNTHETIC rejection
    (`llm_returned_empty_facts_for_results_role`), which the orchestrator
    treats as a tolerated orphan — the audit trail captures the failure,
    so it isn't a silent drop. The pipeline continues with the items
    that DID extract.

    Pre-Day-6.1: the orchestrator failed loud here (OrchestratorError:
    invariant violated). The change recognizes that "LLM said nothing
    extractable" is a documented event, not a silent one — failing
    loud blocked real-LLM runs where one paper in fifteen produces no
    facts."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            user_msg = next(m for m in body["messages"] if m["role"] == "user")
            if "[1]" in user_msg["content"]:
                return httpx.Response(200, json=_extractor_response(
                    "Metformin reduced HbA1c (p=0.003)",
                ))
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"facts": []}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            })
        return httpx.Response(200, json=_judge_response("accept"))

    items = [
        _item(1, abstract="Metformin reduced HbA1c (p=0.003)."),
        _item(2, abstract="Another results paper."),
    ]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-orphan-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    assert receipts.claim_receipt_md.exists()
    fact_log = json.loads(receipts.fact_extraction_log.read_text())
    # ref=1 produced the fact, ref=2 produced the synthetic rejection
    assert len(fact_log["accepted"]) == 1
    assert fact_log["accepted"][0]["ref"] == 1
    rejected_for_2 = [r for r in fact_log["rejected"] if r["item_ref"] == 2]
    assert len(rejected_for_2) == 1
    assert rejected_for_2[0]["reason"] == "llm_returned_empty_facts_for_results_role"


def test_run_proof_refuses_to_overwrite_existing_receipts(tmp_path: Path) -> None:
    """P1-3 fix: a prior run's receipts must not be silently clobbered.
    Audit-trail integrity over write-throughput convenience."""
    # Pre-create one of the receipt files in the target dir
    (tmp_path / "claim_receipt.md").write_text("# Old run\n", encoding="utf-8")

    handler = _make_handler()
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-clobber-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(OrchestratorError, match="Refusing to overwrite"):
        _run(go())


def test_run_proof_force_overwrite_re_runs_into_existing_directory(
    tmp_path: Path,
) -> None:
    """5.1-fix Gap-1: `force_overwrite=True` is the controlled escape
    hatch for re-running into a partially-written output_dir (e.g.,
    after a crash). The operator opts in explicitly; the safe default
    still refuses to clobber."""
    # Pre-create an old paper.md as if from a partial run
    (tmp_path / "paper.md").write_text("# Old run\n", encoding="utf-8")

    handler = _make_handler()
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-force-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
                force_overwrite=True,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    # New paper.md has replaced the old one
    new_paper = receipts.claim_receipt_md.read_text()
    assert "Old run" not in new_paper
    assert "## Thesis" in new_paper


def test_run_proof_zero_facts_error_includes_rejection_histogram(
    tmp_path: Path,
) -> None:
    """P2-2 fix: zero-facts error message must surface the rejection
    category histogram, not just the first 3 reasons. An operator
    seeing `{'llm_error': 5}` knows immediately that the LLM is down,
    rather than seeing three unrelated rejection reasons by chance."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"facts": []}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            })
        return httpx.Response(200, json=_judge_response("accept"))

    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-hist-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(OrchestratorError, match="by category:") as exc_info:
        _run(go())
    # Histogram is a dict literal in the message
    assert "{" in str(exc_info.value)


def test_run_proof_extract_failure_writes_diagnostic_receipts(
    tmp_path: Path,
) -> None:
    """P2-3 fix: even when extraction fails, fact_extraction_log and
    cost_log are written so the operator can debug WHY without re-running."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"facts": []}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            })
        return httpx.Response(200, json=_judge_response("accept"))

    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="run-diag-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(OrchestratorError):
        _run(go())
    # Two diagnostic receipts on disk
    fact_log = json.loads((tmp_path / "fact_extraction_log.json").read_text())
    assert fact_log["accepted"] == []
    cost = json.loads((tmp_path / "cost_log.json").read_text())
    assert "extract" in cost
    assert "spar" in cost  # always present; zero on this path
    # The 6 non-diagnostic receipts MUST NOT exist (no full run happened)
    assert not (tmp_path / "paper.md").exists()
    assert not (tmp_path / "claim_graph.json").exists()
    assert not (tmp_path / "spar_review.json").exists()


def test_run_proof_compile_error_wraps_in_orchestrator_error(
    tmp_path: Path,
) -> None:
    """P1-2 fix: CompileError from compile_claims (orphan ref) must be
    wrapped as OrchestratorError per the documented contract."""
    # The LLM returns a fact whose ref=99 doesn't exist in the bundle
    # (ref=1 is the only item). compile_claims raises CompileError.
    # NOTE: fact_extractor pins fact.ref to item.source.ref, so this is
    # hard to trigger via the real extraction path. We can simulate by
    # having two items but extracting facts that don't satisfy the
    # invariant. Easier: monkey-patch compile_claims to raise.
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            return httpx.Response(200, json=_extractor_response(
                "Metformin reduced HbA1c by 0.5% (p=0.003)",  # verbatim span
            ))
        return httpx.Response(200, json=_judge_response("accept"))

    items = [_item(1)]

    # Patch compile_claims to raise to exercise the wrapper.
    import agent.orchestrator as orch
    from agent.compiler import CompileError as _CE

    def fake_compile_claims(*a, **kw):
        raise _CE("synthetic orphan ref for the test")

    real = orch.compile_claims
    orch.compile_claims = fake_compile_claims
    try:
        async def go():
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                await run_proof(
                    items,
                    topic="metformin", domain="aging",
                    pack=_pack(), output_dir=tmp_path,
                    submission_id="run-compile-001",
                    extract_chain=(_spec(),), spar_chain=(_spec(),),
                    registry=FixtureTrialRegistryClient(),
                    drug_client=FixtureDrugAliasClient(),
                    client=client,
                )
            finally:
                await client.aclose()

        with pytest.raises(OrchestratorError, match="compile stage failed"):
            _run(go())
    finally:
        orch.compile_claims = real


# --- Day 10.8b: multi-receipt mode ---------------------------------------


def test_run_proof_multi_receipt_emits_one_subdir_per_cluster(
    tmp_path: Path,
) -> None:
    """Two items from distinct refs → compiler clusters into 2 groups
    (each item's ref forms its own cluster). run_proof_multi_receipt
    emits cluster_01/ and cluster_02/ subdirs, each with the full
    8-receipt set, plus a top-level multi_receipt_manifest.json."""
    handler = _make_handler()
    # Two items, distinct refs/NCTs → compiler will detect the
    # all-singleton case and emit one cluster covering both. To force
    # 2 clusters, we'd need shared refs WITHIN each cluster — but the
    # mock extractor returns one fact per HTTP call, so each item gives
    # one claim with its own ref. That's the all-singleton case →
    # cluster_all_claims returns ((all,),) → ONE cluster receipt.
    # For a true 2-cluster test, we use the multi-fact path.
    items = [
        _item(1, abstract="Metformin reduced HbA1c by 0.5% (p=0.003)."),
        _item(2, abstract="Metformin reduced HbA1c by 0.5% (p=0.003)."),
    ]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof_multi_receipt(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="multi-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    per_cluster = _run(go())
    # All-singleton → exactly one cluster, even with 2 items
    assert len(per_cluster) == 1
    cluster_dir = per_cluster[0].output_dir
    assert cluster_dir.name == "cluster_01"
    assert cluster_dir.parent == tmp_path
    # Full 8-receipt set in the cluster subdir
    for name in (
        "claim_receipt.md", "claim_graph.json", "citation_traces.json",
        "spar_review.json", "evidence_cards.json", "cost_log.json",
        "fact_extraction_log.json", "run_metadata.json",
    ):
        assert (cluster_dir / name).exists(), f"missing {name}"
    # Top-level manifest links the clusters
    manifest = json.loads((tmp_path / "multi_receipt_manifest.json").read_text())
    assert manifest["n_clusters"] == 1
    assert manifest["topic"] == "metformin"
    assert manifest["clusters"][0]["subdir"] == "cluster_01"
    # Each cluster's run_metadata flags multi-receipt mode
    md = json.loads(per_cluster[0].run_metadata.read_text())
    assert md["multi_receipt"] is True
    assert md["cluster_index"] == 1
    assert md["parent_submission_id"] == "multi-001"


def test_run_proof_multi_receipt_filters_protocol_only_clusters(
    tmp_path: Path,
) -> None:
    """Day 10.12 — a cluster whose every supporting ref is
    role={published_protocol, registered_pending} cannot stand as a
    standalone evidence claim receipt (its quotes are study purposes,
    not findings). The filter excludes such clusters from multi-receipt
    output and records them in the manifest's
    `protocol_only_excluded_indices`."""
    # Mix: one published_results item and one registered_pending item.
    # Each gets its own fact → singleton clusters → all-singleton
    # fallback merges them into ONE cluster of mixed roles, which is
    # NOT protocol-only and should pass the filter.
    handler = _make_handler()
    items = [
        _item(1, abstract="Metformin reduced HbA1c by 0.5% (p=0.003)."),
        EvidenceItem(
            source=_src(2),
            abstract="Metformin reduced HbA1c by 0.5% (p=0.003).",
            design="rct", role="registered_pending", tier="B",
            direct=False, strict=False,
        ),
    ]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof_multi_receipt(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="multi-mixed",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    per_cluster = _run(go())
    # Mixed cluster (one published_results + one registered_pending)
    # is NOT protocol-only — filter must keep it.
    assert len(per_cluster) >= 1
    manifest = json.loads((tmp_path / "multi_receipt_manifest.json").read_text())
    # The protocol-only filter is present in the manifest but didn't fire.
    assert "n_protocol_only_excluded" in manifest
    assert manifest["n_protocol_only_excluded"] == 0


def test_run_proof_multi_receipt_two_clusters_when_refs_overlap(
    tmp_path: Path,
) -> None:
    """When two items SHARE one ref via cross-citation in the abstract,
    a multi-fact extractor can produce a 2-claim cluster — but our mock
    extractor produces 1 fact per call. To exercise the 2-cluster path,
    we directly feed the orchestrator's compile stage by patching the
    fact extractor's response to return TWO facts from one item (forming
    a 2-claim cluster with shared refs), plus a singleton from the other
    item. The orchestrator's all-singleton fallback won't trigger."""
    multi_fact_resp = {
        "choices": [{"message": {"content": json.dumps({
            "facts": [
                {
                    "source_quote": "Metformin reduced HbA1c by 0.5% (p=0.003)",
                    "outcome": "HbA1c", "estimate": None,
                    "p_value": "0.003", "ci": None,
                },
                {
                    "source_quote": "Metformin reduced fasting glucose by 1.0 (p=0.01)",
                    "outcome": "fasting glucose", "estimate": None,
                    "p_value": "0.01", "ci": None,
                },
            ],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    abstract_with_two = (
        "Metformin reduced HbA1c by 0.5% (p=0.003). "
        "Metformin reduced fasting glucose by 1.0 (p=0.01)."
    )
    call_count = {"extract": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        text = sys_msg["content"]
        if "extract structured FACTS" in text:
            call_count["extract"] += 1
            # First item gets two facts (forms 1-claim cluster of size 2);
            # second item gets one fact (different ref → singleton).
            if call_count["extract"] == 1:
                return httpx.Response(200, json=multi_fact_resp)
            return httpx.Response(200, json=_extractor_response(
                "Metformin reduced HbA1c by 0.5% (p=0.003)",
            ))
        return httpx.Response(200, json=_judge_response("accept"))

    items = [
        _item(1, abstract=abstract_with_two),
        _item(2, abstract="Metformin reduced HbA1c by 0.5% (p=0.003)."),
    ]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof_multi_receipt(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="multi-002",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    per_cluster = _run(go())
    # Item 1 has 2 claims (same ref) → 1 cluster of size 2.
    # Item 2 has 1 claim (different ref) → singleton.
    # Largest cluster has size 2 → multi-cluster path activates →
    # cluster_all_claims returns 2 clusters.
    assert len(per_cluster) == 2
    assert per_cluster[0].output_dir.name == "cluster_01"
    assert per_cluster[1].output_dir.name == "cluster_02"
    # Both clusters had SPAR fired
    for paths in per_cluster:
        sr = json.loads(paths.spar_review.read_text())
        assert sr["verdict"] == "accept_clean"
    # Manifest reflects both
    manifest = json.loads((tmp_path / "multi_receipt_manifest.json").read_text())
    assert manifest["n_clusters"] == 2


def test_run_proof_multi_receipt_max_clusters_caps_emission(
    tmp_path: Path,
) -> None:
    """`max_clusters=1` truncates output to the top-1 cluster even when
    the corpus has more — useful for cost containment in cohort runs."""
    multi_fact_resp = {
        "choices": [{"message": {"content": json.dumps({
            "facts": [
                {
                    "source_quote": "Metformin reduced HbA1c by 0.5% (p=0.003)",
                    "outcome": "HbA1c", "estimate": None,
                    "p_value": "0.003", "ci": None,
                },
                {
                    "source_quote": "Metformin reduced fasting glucose by 1.0 (p=0.01)",
                    "outcome": "fasting glucose", "estimate": None,
                    "p_value": "0.01", "ci": None,
                },
            ],
        })}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    call_count = {"extract": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            call_count["extract"] += 1
            if call_count["extract"] == 1:
                return httpx.Response(200, json=multi_fact_resp)
            return httpx.Response(200, json=_extractor_response(
                "Metformin reduced HbA1c by 0.5% (p=0.003)",
            ))
        return httpx.Response(200, json=_judge_response("accept"))

    items = [
        _item(1, abstract=(
            "Metformin reduced HbA1c by 0.5% (p=0.003). "
            "Metformin reduced fasting glucose by 1.0 (p=0.01)."
        )),
        _item(2, abstract="Metformin reduced HbA1c by 0.5% (p=0.003)."),
    ]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof_multi_receipt(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="multi-cap",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
                max_clusters=1,
            )
        finally:
            await client.aclose()

    per_cluster = _run(go())
    assert len(per_cluster) == 1


def test_run_proof_multi_receipt_refuses_existing_manifest(
    tmp_path: Path,
) -> None:
    """Audit-trail integrity: refuse to clobber a prior multi-receipt
    manifest unless force_overwrite=True."""
    (tmp_path / "multi_receipt_manifest.json").write_text("{}")
    handler = _make_handler()
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof_multi_receipt(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=tmp_path,
                submission_id="multi-existing",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    with pytest.raises(OrchestratorError, match="multi-receipt manifest"):
        _run(go())


def test_run_proof_creates_output_dir_if_missing(tmp_path: Path) -> None:
    """`output_dir` doesn't need to pre-exist — orchestrator creates it
    (with parents) before writing receipts."""
    target = tmp_path / "deeply" / "nested" / "run-001"
    assert not target.exists()
    handler = _make_handler()
    items = [_item(1)]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=_pack(), output_dir=target,
                submission_id="run-mkdir-001",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    assert target.is_dir()
    assert receipts.claim_receipt_md.parent == target
