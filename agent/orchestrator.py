"""Orchestrator — single-call Proof 001 pipeline driver.

Wires the trust-spine modules into one async call and emits the 8
mandatory JSON receipts (DESIGN-001 §6.1) to `output_dir`:

  claim_receipt.md           — writer.write_paper output (deterministic)
  claim_graph.json           — full ClaimGraph (source of truth)
  citation_traces.json       — every per-claim trace + pass/fail
  spar_review.json           — 3-judge verdict + dissent + gate_override
  evidence_cards.json        — bundled corpus the spine ran against
  cost_log.json              — extract + judge LLM cost breakdown
  fact_extraction_log.json   — LLM-proposed facts + rejection reasons
  run_metadata.json          — timestamps, prompt versions, settings

The orchestrator is integration glue ONLY (v4 Rule 49 — one module,
one reason). It does not classify, gate, or judge — that's all upstream.
It just wires call-order, threads errors, and serializes receipts.

Flow:
  bundled_items
    → fact_extractor.extract_facts_from_bundle    (LLM #1)
    → compiler.compile_claims
    → compiler.compile_claim_graph
    → citation_trace.trace_claim_graph
    → spar.run_spar                               (LLM #2 — 3 judges)
    → writer.write_paper                          (deterministic; was LLM #3 pre-Day-4-fix)

Caller responsibilities (kept outside this module to preserve test seams):
  - retrieve + bundle (live or fixture-replay)
  - choosing the LLM call chains (mock vs real)
  - choosing the trace clients (fixture vs httpx)

Day 5.1 ships the orchestrator + tests. Day 5.3's
`scripts/e2e_metformin_proof_001.py` is the live entry point that
calls retrieve + bundle, then run_proof.
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from collections import Counter

from agent.citation_trace import registry_ids_for, trace_claim_graph
from agent.compiler import CompileError, compile_claim_graph, compile_claims
from agent.fact_extractor import (
    PROMPT_VERSION as EXTRACT_PROMPT_VERSION,
    extract_facts_from_bundle,
)
from agent.llm_client import CallSpec, CostLedger
from agent.schemas import ClaimGraph, ClaimGraphInvariantError
from agent.spar import (
    PROMPT_VERSION as SPAR_PROMPT_VERSION,
    reviews_to_dict,
    run_spar,
)
from agent.topic_pack import TopicPack
from agent.trace_clients import DrugAliasClient, TrialRegistryClient
from agent.types import EvidenceItem, InvariantError, assert_invariants
from agent.writer import RENDER_VERSION, write_paper

__all__ = [
    "RunReceipts",
    "OrchestratorError",
    "run_proof",
]


class OrchestratorError(RuntimeError):
    """Raised when the pipeline cannot produce a valid receipt set —
    e.g., LLM extraction yielded zero facts, or SPAR raised."""


@dataclass(frozen=True, slots=True)
class RunReceipts:
    """Paths to the 8 mandatory artifacts for one Proof 001 run.
    Returned so callers can read / verify / post-process.

    Day 9.5 rename: `paper_md` → `claim_receipt_md` and the corresponding
    file output `paper.md` → `claim_receipt.md`. The output of the
    current pipeline is a CLAIM RECEIPT (atomic verified evidence
    bundle anchored on one source-paper cluster), not a synthesis
    paper. The Day 10 synthesis layer aggregates many receipts into a
    `paper_synthesis.md` artifact — that's the "paper" in the
    Researka product framing. Mislabeling these as "paper.md" pre-9.5
    made every reviewer conversation about quality miss the actual
    architectural truth."""
    output_dir: Path
    claim_receipt_md: Path
    claim_graph: Path
    citation_traces: Path
    spar_review: Path
    evidence_cards: Path
    cost_log: Path
    fact_extraction_log: Path
    run_metadata: Path


# --- JSON serialization helpers ------------------------------------------


def _json_default(obj: object) -> object:
    if isinstance(obj, frozenset):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (write to .tmp, then rename).
    A partial-write on disk-full / permission revoke leaves the OLD
    receipt untouched rather than a half-written one — audit-trail
    integrity matters more than write-throughput here."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, data: object) -> None:
    _atomic_write_text(
        path,
        json.dumps(data, indent=2, default=_json_default, ensure_ascii=False),
    )


def _claim_graph_to_dict(graph: ClaimGraph) -> dict:
    """Serialize a ClaimGraph via dataclasses.asdict — recurses through
    Claim / ClaimEdge dataclasses; tuples are encoded as JSON arrays
    by `json.dumps` natively."""
    return dataclasses.asdict(graph)


def _evidence_to_dict(item: EvidenceItem) -> dict:
    return dataclasses.asdict(item)


_RECEIPT_NAMES: tuple[str, ...] = (
    "claim_receipt.md",
    "claim_graph.json",
    "citation_traces.json",
    "spar_review.json",
    "evidence_cards.json",
    "cost_log.json",
    "fact_extraction_log.json",
    "run_metadata.json",
)


def _check_no_existing_receipts(output_dir: Path) -> None:
    """Audit-trail integrity: refuse to overwrite a prior run's receipts.
    A clobbered receipt set silently destroys the audit record.
    Callers either use a fresh output_dir per submission OR pass
    `force_overwrite=True` to `run_proof` for explicit re-runs."""
    existing = [
        name for name in _RECEIPT_NAMES if (output_dir / name).exists()
    ]
    if existing:
        raise OrchestratorError(
            f"output_dir={output_dir} already contains receipts {existing}. "
            f"Refusing to overwrite. Use a per-submission directory or pass "
            f"force_overwrite=True to retry (e.g., after a partial-write crash)."
        )


def _emit_partial_diagnostics(
    output_dir: Path,
    extract_ledger: CostLedger,
    rejections: list,
    accepted_facts: list | None = None,
) -> None:
    """Write the two diagnostic receipts (fact_extraction_log,
    cost_log) even on extraction failure — they're independent of
    the rest of the pipeline and the operator needs them to debug.

    Day 6.1c: include any accepted facts too. Pre-fix the receipt
    always wrote `accepted: []` even when invariant-failure happened
    AFTER some facts had been validated — masking real progress and
    making the audit trail misleading.
    """
    _write_json(output_dir / "fact_extraction_log.json", {
        "accepted": (
            [dataclasses.asdict(f) for f in accepted_facts]
            if accepted_facts else []
        ),
        "rejected": [dataclasses.asdict(r) for r in rejections],
    })
    _write_json(output_dir / "cost_log.json", {
        "extract": extract_ledger.to_dict(),
        "spar": {"total_usd": 0.0, "by_model": {}, "calls": []},
        "total_usd": round(extract_ledger.total_usd(), 6),
    })


# --- Orchestrator ---------------------------------------------------------


async def run_proof(
    items: Sequence[EvidenceItem],
    *,
    topic: str,
    domain: str,
    pack: TopicPack,
    output_dir: Path,
    submission_id: str,
    extract_chain: Sequence[CallSpec],
    spar_chain: Sequence[CallSpec],
    registry: TrialRegistryClient,
    drug_client: DrugAliasClient,
    client: httpx.AsyncClient | None = None,
    force_overwrite: bool = False,
    seed: int | None = None,
) -> RunReceipts:
    """Run the full Proof 001 pipeline; emit 8 receipts to output_dir.

    Caller has already done retrieve + bundle and passes the
    `EvidenceItem` corpus directly. This keeps the orchestrator
    focused on the trust spine, leaves the retrieval contract free
    to evolve, and lets fixture-replay tests inject items without
    network or schema overhead.

    `force_overwrite=False` (default) refuses to start when
    `output_dir` already contains any receipt — the safe audit-trail
    default. Pass True for controlled re-runs (e.g., after a
    partial-write crash); the operator opts in explicitly.

    Idempotency / crash recovery: a crash mid-pipeline leaves the
    receipts written so far on disk. Re-running into the same
    `output_dir` requires `force_overwrite=True`. The orchestrator
    does NOT itself attempt resume — each call is a fresh end-to-end
    pipeline run.

    Raises OrchestratorError when the pipeline can't produce a valid
    receipt set (zero accepted facts, invariant violation, compile
    error, writer regression). SPARError, LLMError, and httpx errors
    propagate uncaught per their own contracts.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # P1-3 + Gap-1 escape hatch: refuse to clobber a prior run's audit
    # receipts unless the caller explicitly opts in via force_overwrite.
    if not force_overwrite:
        _check_no_existing_receipts(output_dir)
    started_at = datetime.now(timezone.utc).isoformat()

    extract_ledger = CostLedger()
    spar_ledger = CostLedger()

    own_client = client is None
    c = client or httpx.AsyncClient()
    try:
        # Stage 1: LLM fact extraction (CODE DISPOSES via 7 layers in
        # fact_extractor; here we just call it).
        accepted_facts, rejections = await extract_facts_from_bundle(
            items, pack=pack, chain=extract_chain,
            client=c, ledger=extract_ledger,
            seed=seed,
        )
        if not accepted_facts:
            # P2-2 + P2-3: emit diagnostic receipts so the operator can
            # debug WHY extraction failed; surface a histogram, not just
            # the first 3 rejection reasons.
            _emit_partial_diagnostics(output_dir, extract_ledger, rejections, list(accepted_facts) if accepted_facts else None)
            histogram = Counter(
                r.reason.split(":", 1)[0] for r in rejections
            )
            raise OrchestratorError(
                f"fact extraction produced 0 accepted facts; "
                f"{len(rejections)} rejections by category: {dict(histogram)}. "
                f"Diagnostic receipts written: fact_extraction_log.json, "
                f"cost_log.json."
            )

        # P1-1: invariants must hold between bundle items and accepted
        # facts. A published_results item with no extracted result-fact
        # is a silent audit-trail break — fail loud.
        # Day 6.1b: an item with no fact AND ≥1 LOGGED REJECTION is a
        # DOCUMENTED extraction failure (auditable in fact_extraction_log),
        # not a silent drop — tolerate those orphans so a real-LLM run
        # with a few rejected items can still produce an artifact.
        rejected_refs = frozenset(r.item_ref for r in rejections)
        try:
            assert_invariants(
                list(items), list(accepted_facts),
                tolerated_orphans=rejected_refs,
            )
        except InvariantError as exc:
            _emit_partial_diagnostics(output_dir, extract_ledger, rejections, list(accepted_facts) if accepted_facts else None)
            raise OrchestratorError(
                f"role/fact-kind invariant violated post-extraction: {exc}. "
                f"This usually means an LLM-extractable item produced no "
                f"facts — its findings would be silently dropped from the "
                f"paper. Diagnostic receipts written for inspection."
            ) from exc

        # Stage 2: deterministic compile (P1-2: wrap so contract holds)
        try:
            claims = compile_claims(accepted_facts, items)
            items_by_ref = {it.source.ref: it for it in items}
            # Day 8.1: refs whose source paper has a canonical NCT
            # (per topic_pack). The compiler uses this to break ties
            # between equally-strong clusters in favor of the canonical
            # trial cluster — fixes Proof 001 regression where a
            # non-canonical metformin paper out-tied MASTERS by ref index.
            canonical_ids = {trial.id.upper() for trial in pack.canonical_trials}
            canonical_refs = frozenset(
                ref for ref, item in items_by_ref.items()
                if any(rid in canonical_ids for rid in registry_ids_for(item))
            )
            graph = compile_claim_graph(
                claims, items_by_ref=items_by_ref,
                canonical_refs=canonical_refs,
            )
        except (CompileError, ClaimGraphInvariantError) as exc:
            raise OrchestratorError(
                f"compile stage failed: {type(exc).__name__}: {exc}"
            ) from exc

        # Stage 3: citation traces
        traces = list(trace_claim_graph(
            graph, items_by_ref, pack,
            registry=registry, drug_client=drug_client,
        ))

        # Stage 4: 3-judge SPAR (with trust-spine trace gate). SPARError
        # is a real trust-spine failure and propagates uncaught.
        spar_review = await run_spar(
            graph, traces,
            topic=topic, submission_id=submission_id,
            chain=spar_chain, client=c, ledger=spar_ledger,
            seed=seed,
        )

        # Stage 5: deterministic write. P2-4 — the writer is documented
        # as "always [] on the deterministic path"; if it ever regresses
        # and produces rejections, those are audit-trail signals that
        # must surface, not be discarded silently.
        claim_receipt_md, writer_rejections = write_paper(
            graph, items, traces, spar_review,
            pack=pack, topic=topic,
        )
        if writer_rejections:
            raise OrchestratorError(
                f"deterministic writer produced {len(writer_rejections)} "
                f"rejection(s) — should be impossible per writer.py contract. "
                f"Possible regression in writer.py. First: {writer_rejections[0]!r}"
            )
    finally:
        if own_client:
            await c.aclose()

    # --- Emit receipts ---
    finished_at = datetime.now(timezone.utc).isoformat()
    paths = RunReceipts(
        output_dir=output_dir,
        claim_receipt_md=output_dir / "claim_receipt.md",
        claim_graph=output_dir / "claim_graph.json",
        citation_traces=output_dir / "citation_traces.json",
        spar_review=output_dir / "spar_review.json",
        evidence_cards=output_dir / "evidence_cards.json",
        cost_log=output_dir / "cost_log.json",
        fact_extraction_log=output_dir / "fact_extraction_log.json",
        run_metadata=output_dir / "run_metadata.json",
    )

    # P2: claim_receipt.md must be atomic too — same audit-trail integrity
    # rule as the JSON receipts. A partial-paper write can strand the
    # output directory and a re-run then refuses to clobber.
    _atomic_write_text(paths.claim_receipt_md, claim_receipt_md)
    _write_json(paths.claim_graph, _claim_graph_to_dict(graph))
    _write_json(paths.citation_traces, [dataclasses.asdict(t) for t in traces])
    _write_json(paths.spar_review, reviews_to_dict(spar_review))
    _write_json(paths.evidence_cards, [_evidence_to_dict(it) for it in items])

    combined_cost = {
        "extract": extract_ledger.to_dict(),
        "spar": spar_ledger.to_dict(),
        "total_usd": round(
            extract_ledger.total_usd() + spar_ledger.total_usd(), 6,
        ),
    }
    _write_json(paths.cost_log, combined_cost)

    _write_json(paths.fact_extraction_log, {
        "accepted": [dataclasses.asdict(f) for f in accepted_facts],
        "rejected": [dataclasses.asdict(r) for r in rejections],
    })

    _write_json(paths.run_metadata, {
        "submission_id": submission_id,
        "topic": topic,
        "domain": domain,
        "started_at": started_at,
        "finished_at": finished_at,
        "n_items": len(items),
        "n_accepted_facts": len(accepted_facts),
        "n_rejections": len(rejections),
        "n_claims": len(graph.claims),
        "n_traces": len(traces),
        "n_failed_traces": sum(1 for t in traces if not t.passed),
        "spar_verdict": spar_review.verdict,
        "gate_override": spar_review.gate_override is not None,
        "extract_prompt_version": EXTRACT_PROMPT_VERSION,
        "spar_prompt_version": SPAR_PROMPT_VERSION,
        "render_version": RENDER_VERSION,
    })

    return paths
