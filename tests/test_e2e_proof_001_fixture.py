"""Day 5.2 — fixture-replay full-pipeline E2E through the orchestrator.

Two scenarios, both end-to-end through `run_proof`:

  1. **Clean path** (specificity proof — closes the Day 4 reviewer gap):
     Real metformin corpus, mocked LLM extracts valid facts that pass
     every trust-spine layer (claim-text overlap, verb-ban, p-value
     trace, alias drift, etc.), 3 SPAR judges all vote accept, no
     citation traces fail. Asserts `accept_clean` verdict, gate does
     NOT fire, all 8 receipts produced + JSON-loadable, paper renders
     the thesis.

  2. **Gate-fired path** (sensitivity reaffirmation): Same corpus
     plus one fabricated NCT injected. The real `trace_claim_graph`
     calls `FixtureTrialRegistryClient` which returns None for the
     fabricated id; the trust-spine gate fires and overrides
     `accept_clean` to `reject_critical`. paper.md is the rejection
     notice with `gate_override` prominent.

The clean scenario is the new test the reviewer asked for. The
gate-fired scenario is the orchestrator-level integration of the
trust-spine gate already proven at the SPAR level (4.2-fix tests)
and at the citation_trace level (4-fix planted-failure E2E).

Test-only — no new runtime modules. The live counterpart is
`scripts/e2e_metformin_proof_001.py` (Day 5.3).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from agent.llm_client import CallSpec
from agent.orchestrator import RunReceipts, run_proof
from agent.topic_pack import load_topic_pack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Source


def _all_receipt_paths(receipts: RunReceipts) -> list[Path]:
    """Return every receipt path on the RunReceipts dataclass except
    `output_dir`. Iterating dataclass fields means a future receipt
    addition automatically widens any assertion that uses this helper —
    no hardcoded list to drift out of sync."""
    return [
        getattr(receipts, f.name)
        for f in dataclasses.fields(receipts)
        if f.name != "output_dir"
    ]


METFORMIN_PACK_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"

# A mocked claim derived from MASTERS' real abstract. Overlap > 50%
# with the abstract; cites the real p-value verbatim; uses
# "metformin reduced" which doesn't trip any verb-ban.
_MASTERS_CLAIM = "metformin reduced lean body mass (p=0.003) in older adults"
_MASTERS_ABSTRACT = (
    "In a randomized trial, metformin reduced lean body mass (p=0.003) "
    "and thigh muscle area in older adults during progressive resistance "
    "training. NCT02308228 was registered in the MASTERS protocol."
)

_MECHANISM_CLAIM = "metformin engages AMPK signaling in skeletal muscle"
_MECHANISM_ABSTRACT = (
    "Mechanistic studies show that metformin engages AMPK signaling "
    "in skeletal muscle and other tissues, with implications for "
    "aging biology."
)


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(scope="module")
def metformin_pack():
    return load_topic_pack(METFORMIN_PACK_PATH)


def _src(ref: int = 1, *, nct: str | None = None) -> Source:
    return Source(
        ref=ref, title=f"Trial {ref}", year=2024,
        url=f"https://x.example/{ref}",
        source="pubmed", nct=nct,
    )


def _item(
    ref: int, *,
    role: str,
    abstract: str,
    nct: str | None = None,
    direct: bool = True,
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design="rct" if role == "published_results" else "mechanistic",  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        tier="A1" if role == "published_results" else "C",  # type: ignore[arg-type]
        direct=direct, strict=direct,
    )


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _make_proof_handler(
    extract_claims_by_ref: dict[int, str],
    *,
    extract_pvalues_by_ref: dict[int, str | None] | None = None,
    judge_verdict: str = "accept",
) -> Callable[[httpx.Request], httpx.Response]:
    """Compose a single MockTransport handler that routes by system
    prompt content. For fact extraction, parse the user prompt to
    extract `[N]` ref number, then look up the canned claim for that
    ref. SPAR judges all return the same verdict."""
    pvalues = extract_pvalues_by_ref or {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sys_msg = next(m for m in body["messages"] if m["role"] == "system")
        if "extract structured FACTS" in sys_msg["content"]:
            user_msg = next(m for m in body["messages"] if m["role"] == "user")
            # User prompt has `Source [N] (...)` for the item being extracted.
            m = re.search(r"Source \[(\d+)\]", user_msg["content"])
            ref = int(m.group(1)) if m else -1
            claim = extract_claims_by_ref.get(ref)
            if claim is None:
                # No claim configured → return zero facts (the item
                # contributes nothing). This will trip assert_invariants
                # if the item is published_results — caller must
                # configure a claim per such item.
                return httpx.Response(200, json={
                    "choices": [{"message": {"content": '{"facts": []}'}}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10},
                })
            p_value = pvalues.get(ref)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps({
                    "facts": [{
                        "claim": claim,
                        "outcome": None,
                        "estimate": None,
                        "p_value": p_value,
                        "ci": None,
                    }],
                })}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 80},
            })
        # SPAR judge response
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "verdict": judge_verdict, "score": 8,
                "rationale": f"{judge_verdict} rationale",
                "flagged_claims": [],
            })}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
    return handler


def _run(coro):
    return asyncio.run(coro)


# --- Clean path: specificity proof ---------------------------------------


def test_proof_001_clean_run_emits_all_receipts_and_renders_paper(
    tmp_path: Path,
    metformin_pack,
) -> None:
    """The reviewer's specificity test: a clean run with valid evidence,
    LLM extraction passing every gate, SPAR all-accept, and no failed
    traces must produce `accept_clean` WITHOUT triggering the
    trust-spine gate. All 8 receipts produced. Paper renders the thesis.

    Single MASTERS published_results item — simplest case that proves
    specificity. The claim text uses lowercase metformin + clinical
    endpoint vocabulary so no drug-candidate token in the claim trips
    `alias_match` against the fixture compound store.
    """
    items = [
        _item(
            ref=1, role="published_results", nct="NCT02308228",
            abstract=_MASTERS_ABSTRACT,
        ),
    ]
    handler = _make_proof_handler(
        extract_claims_by_ref={1: _MASTERS_CLAIM},
        extract_pvalues_by_ref={1: "0.003"},
        judge_verdict="accept",
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=metformin_pack,
                output_dir=tmp_path / "clean-001",
                submission_id="proof-001-clean",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts: RunReceipts = _run(go())

    # All receipts produced (iterating fields → widens automatically
    # if a future receipt is added to RunReceipts)
    for path in _all_receipt_paths(receipts):
        assert path.exists(), f"missing receipt: {path.name}"

    # Specificity: clean scenario must NOT trigger the gate
    md = json.loads(receipts.run_metadata.read_text())
    assert md["spar_verdict"] == "accept_clean", (
        f"clean scenario produced {md['spar_verdict']!r}; gate may have "
        f"fired. Receipts: {receipts.output_dir}"
    )
    assert md["gate_override"] is False, (
        "gate must NOT fire on a clean run — this is the specificity proof"
    )
    assert md["n_failed_traces"] == 0, (
        f"clean scenario produced failed traces: see "
        f"{receipts.citation_traces}"
    )

    # Direct inspection of citation_traces.json — defense in depth
    # against a metadata-counter regression (P3 in 5.2 review).
    traces_data = json.loads(receipts.citation_traces.read_text())
    assert all(t["passed"] for t in traces_data), (
        f"citation_traces.json carries failed traces despite "
        f"n_failed_traces=0 in metadata: "
        f"{[t for t in traces_data if not t['passed']]}"
    )

    # Paper renders the thesis (deterministic writer — no banner phrases
    # from the rejection path)
    paper = receipts.paper_md.read_text()
    assert "## Thesis" in paper
    assert "DRAFT REJECTED" not in paper
    assert "TRUST-SPINE TRACE GATE TRIGGERED" not in paper
    assert "metformin" in paper.lower()

    # claim_graph has the single MASTERS claim as thesis
    cg = json.loads(receipts.claim_graph.read_text())
    assert len(cg["claims"]) == 1
    thesis_claim = next(
        c for c in cg["claims"] if c["claim_id"] == cg["thesis_claim_id"]
    )
    assert 1 in thesis_claim["supporting_refs"]

    # SPAR accept_clean, no gate, no dissent
    sr = json.loads(receipts.spar_review.read_text())
    assert sr["verdict"] == "accept_clean"
    assert sr["gate_override"] is None
    assert sr["dissent"] is None

    # Cost log records both LLM stages
    cost = json.loads(receipts.cost_log.read_text())
    assert len(cost["extract"]["calls"]) == 1  # 1 item
    assert len(cost["spar"]["calls"]) == 3      # 3 judges


# --- Gate-fired path: sensitivity reaffirmation --------------------------


def test_proof_001_gate_fires_on_fabricated_nct(
    tmp_path: Path,
    metformin_pack,
) -> None:
    """Sensitivity at the orchestrator level: an item citing a
    fabricated NCT (not in the fixture registry) produces a failed
    `nct_exists` trace through the real citation_trace path, which
    triggers the trust-spine gate, which overrides the panel's
    accept_clean verdict to reject_critical."""
    items = [
        _item(
            ref=1, role="published_results", nct="NCT99999999",
            abstract=(
                "Trial NCT99999999 evaluated metformin and reduced "
                "HbA1c (p=0.003) in adults at risk."
            ),
        ),
    ]
    handler = _make_proof_handler(
        extract_claims_by_ref={
            1: "metformin reduced HbA1c (p=0.003) in adults at risk",
        },
        extract_pvalues_by_ref={1: "0.003"},
        judge_verdict="accept",  # judges fooled; gate must catch
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=metformin_pack,
                output_dir=tmp_path / "gate-001",
                submission_id="proof-001-gate",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())

    md = json.loads(receipts.run_metadata.read_text())
    assert md["spar_verdict"] == "reject_critical"
    assert md["gate_override"] is True
    assert md["n_failed_traces"] >= 1

    # Paper is the rejection notice with gate banner prominent
    paper = receipts.paper_md.read_text()
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in paper
    assert "accept_clean" in paper  # panel's original verdict preserved
    assert "reject_critical" in paper  # canonical verdict
    assert "NCT99999999" in paper  # the fabricated id surfaces in the audit

    # SPAR review preserves the panel votes verbatim for audit. Verbatim
    # means verdict, score, AND rationale — a serialization bug that
    # mutated rationale/score on the gate path would corrupt the audit
    # trail invisibly. Strengthened per the 5.2 reviewer pass.
    sr = json.loads(receipts.spar_review.read_text())
    assert sr["gate_override"] is not None
    assert sr["gate_override"]["pre_gate_verdict"] == "accept_clean"
    for r in sr["reviews"]:
        assert r["verdict"] == "accept"
        assert r["score"] == 8
        assert r["rationale"] == "accept rationale"


# --- All 8 receipts JSON-loadable ----------------------------------------


def test_proof_001_all_receipts_are_json_loadable(
    tmp_path: Path,
    metformin_pack,
) -> None:
    """Audit-trail health: all JSON receipts must parse cleanly via
    `json.loads`. paper.md is plain markdown (skipped here)."""
    items = [
        _item(ref=1, role="published_results", nct="NCT02308228",
              abstract=_MASTERS_ABSTRACT),
    ]
    handler = _make_proof_handler(
        extract_claims_by_ref={1: _MASTERS_CLAIM},
        extract_pvalues_by_ref={1: "0.003"},
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await run_proof(
                items,
                topic="metformin", domain="aging",
                pack=metformin_pack,
                output_dir=tmp_path / "json-loadable-001",
                submission_id="proof-001-json",
                extract_chain=(_spec(),), spar_chain=(_spec(),),
                registry=FixtureTrialRegistryClient(),
                drug_client=FixtureDrugAliasClient(),
                client=client,
            )
        finally:
            await client.aclose()

    receipts = _run(go())
    # Iterate every JSON receipt by field-introspection (skips paper.md
    # which is markdown). Any future JSON receipt added to RunReceipts
    # is automatically validated.
    for path in _all_receipt_paths(receipts):
        if path.suffix != ".json":
            continue
        data = json.loads(path.read_text())
        assert data is not None, f"{path.name} parsed but is empty"
