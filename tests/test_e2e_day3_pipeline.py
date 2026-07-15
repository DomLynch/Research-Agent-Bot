"""Day 3.4 — End-to-end Day 3 pipeline (fixture-replay, no network, no LLM).

Extends the Day 2.5 metformin E2E (fixture replay → bundle) with the Day 3
stages:

  1. retrieve.normalize_and_dedup     (Day 2.5 — already covered)
  2. evidence_cards.bundle            (Day 2.5 — already covered)
  3. fact_extractor.extract_facts_*   (Day 3.2c — LLM, SKIPPED here; use
                                       hand-curated Facts from the actual
                                       abstracts so this test stays
                                       network-free and key-free)
  4. compiler.compile_claims          (Day 3.2a — deterministic)
  5. compiler.compile_claim_graph     (Day 3.2a — deterministic)
  6. citation_trace.trace_claim_graph (Day 3.1 — fixture trace clients)

Done-when (DESIGN-001 §19 Day 3 close):
- ClaimGraph builds from the real metformin bundle (≥6 claims)
- Citation traces fire for at least one canonical NCT (MASTERS)
- Planted-failure regression: case 4 alias drift (Glufomin) flagged
  through trace_alias_match
- Performance baseline captured (deterministic stages < 1s)

The LLM extraction stage is exercised by `scripts/e2e_metformin_proof_001.py`
(opt-in, requires MIMO_API_KEY or OPENROUTER_API_KEY) — keeping it out of
pytest avoids both network dependence and CI cost.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.citation_trace import trace_claim_graph
from agent.compiler import compile_claim_graph, compile_claims
from agent.evidence_cards import bundle
from agent.retrieve import normalize_and_dedup
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Fact, RawHit

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "metformin"
TOPIC_PACK_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"

# Same adapter priority as the Day 2 E2E test; PMIDs survive cross-source
# dedup only if PubMed leads.
ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(TOPIC_PACK_PATH)


@pytest.fixture(scope="module")
def metformin_items(metformin_pack: TopicPack) -> list[EvidenceItem]:
    """Drive the Day 2 pipeline once, return the bundled items."""
    hits: list[RawHit] = []
    for adapter_name in ADAPTER_PRIORITY:
        path = FIXTURES_ROOT / f"{adapter_name}.json"
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    return bundle(
        sources, abstracts,
        topic="metformin", domain="longevity older adults",
        raw_signals=raw_signals,
        topic_pack=metformin_pack,
    )


def _hand_curated_facts(items: list[EvidenceItem]) -> list[Fact]:
    """Construct ≥6 Facts from the real metformin abstracts.

    These stand in for the Day 3.2c LLM extraction stage in this
    fixture-replay path — same shape, same downstream code path. The
    LLM stage is exercised live by `scripts/e2e_metformin_proof_001.py`
    (opt-in, requires API keys).

    MASTERS surfaces via the OpenAlex paper hit, NOT the CT.gov registry
    entry — so its `source.nct` is None even though the NCT is in the
    abstract. We search abstracts for the canonical NCT to find it.
    `trace_nct_exists` does the same thing (`registry_ids_for` extracts
    NCTs from source.nct + URL + abstract).
    """
    facts: list[Fact] = []
    used_refs: set[int] = set()

    # MASTERS (NCT02308228, role=published_results) — Walton 2019 Aging Cell.
    # Real abstract excerpts: 'lean body mass (p = .003)', 'thigh muscle
    # area (p = .005) and density (p = .020) were greater in placebo'.
    masters = next(
        (it for it in items if "NCT02308228" in (it.abstract or "")),
        None,
    )
    if masters is not None:
        facts.append(Fact(
            ref=masters.source.ref, kind="result",
            claim=(
                "Placebo gained more lean body mass than metformin during "
                "progressive resistance training in older adults."
            ),
            outcome="lean body mass", estimate=None,
            p_value="0.003", ci=None,
        ))
        used_refs.add(masters.source.ref)

    # Up to 5 more result-role claims from other published_results items.
    # Sort by (tier, ref) so we deterministically pick the strongest first.
    others = sorted(
        (it for it in items
         if it.role == "published_results" and it.source.ref not in used_refs),
        key=lambda it: (it.tier, it.source.ref),
    )
    for it in others[:5]:
        # Title-anchored claim text — survives schema (claim non-empty)
        # without needing source-trace (this isn't the LLM path).
        title_snippet = (it.source.title or "metformin trial")[:60].strip()
        facts.append(Fact(
            ref=it.source.ref, kind="result",
            claim=f"Trial '{title_snippet}' reported clinical outcomes.",
            outcome=None, estimate=None, p_value=None, ci=None,
        ))
        used_refs.add(it.source.ref)

    # One review context claim. Reviews cluster mechanistic + clinical
    # findings, so the graph isn't all efficacy.
    review = next(
        (it for it in items
         if it.role == "review" and it.source.ref not in used_refs),
        None,
    )
    if review is not None:
        facts.append(Fact(
            ref=review.source.ref, kind="context",
            claim="Reviews summarize metformin's effects on aging-related outcomes.",
            outcome=None, estimate=None, p_value=None, ci=None,
        ))
        used_refs.add(review.source.ref)

    # One mechanistic context claim — covers the indirect-evidence layer.
    mech = next(
        (it for it in items
         if it.role == "mechanistic" and it.source.ref not in used_refs),
        None,
    )
    if mech is not None:
        facts.append(Fact(
            ref=mech.source.ref, kind="context",
            claim="Metformin engages AMPK/mTOR pathways relevant to aging biology.",
            outcome=None, estimate=None, p_value=None, ci=None,
        ))
    return facts


@pytest.fixture(scope="module")
def metformin_day3_e2e(
    metformin_items: list[EvidenceItem],
    metformin_pack: TopicPack,
) -> dict:
    """Run the Day-3 deterministic stages once, return everything."""
    facts = _hand_curated_facts(metformin_items)

    items_by_ref = {it.source.ref: it for it in metformin_items}

    t_compile = time.perf_counter()
    claims = compile_claims(facts, metformin_items)
    # Day 4.1b — pass items_by_ref so the tournament uses the recency
    # dimension (real publication years from the bundle) in addition
    # to the five always-available dims.
    graph = compile_claim_graph(claims, items_by_ref=items_by_ref)
    t_compile = time.perf_counter() - t_compile

    registry = FixtureTrialRegistryClient()
    drug_client = FixtureDrugAliasClient()

    t_trace = time.perf_counter()
    all_traces = trace_claim_graph(
        graph, items_by_ref, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    t_trace = time.perf_counter() - t_trace

    return {
        "facts": facts,
        "claims": claims,
        "graph": graph,
        "traces": all_traces,
        "t_compile_sec": t_compile,
        "t_trace_sec": t_trace,
    }


# --- Day 3.4 done-when criteria ------------------------------------------


def test_claim_graph_builds_from_real_metformin_corpus(
    metformin_day3_e2e: dict,
) -> None:
    """The deterministic spine produces a structurally valid ClaimGraph
    from real metformin evidence. DESIGN-001 §19 done-when threshold:
    ≥6 claims (mix of result/context kinds, multiple refs)."""
    graph = metformin_day3_e2e["graph"]
    assert len(graph.claims) >= 6, (
        f"Day 3 done-when requires ≥6 claims, got {len(graph.claims)}. "
        f"Hand-curated facts may be too sparse for the corpus."
    )
    assert graph.thesis_claim_id is not None
    # Thesis must be one of the claims (schema invariant).
    assert graph.thesis_claim_id in {c.claim_id for c in graph.claims}
    # Mix of kinds, not all efficacy — proves the pipeline composes
    # result + context claims correctly.
    kinds = {c.claim_type for c in graph.claims}
    assert "efficacy" in kinds, "no efficacy claim — published_results path failed"
    assert "context" in kinds, "no context claim — review/mechanistic path failed"


def test_thesis_picks_direct_a1_when_available(
    metformin_day3_e2e: dict,
    metformin_items: list[EvidenceItem],
) -> None:
    """MASTERS is direct + A1 in the metformin pack. If a fact for it is
    present, the deterministic _pick_thesis must select that claim
    (direct + A1 + high beats any other shape)."""
    graph = metformin_day3_e2e["graph"]
    masters = next(
        (it for it in metformin_items if "NCT02308228" in (it.abstract or "")),
        None,
    )
    if masters is None:
        pytest.skip("MASTERS not present in fixture corpus")
    masters_claim = next(
        (c for c in graph.claims if masters.source.ref in c.supporting_refs),
        None,
    )
    assert masters_claim is not None, "no claim cites MASTERS"
    assert graph.thesis_claim_id == masters_claim.claim_id


def test_traces_fire_for_canonical_nct(metformin_day3_e2e: dict) -> None:
    """At least one trace_nct_exists trace must fire and pass for
    MASTERS (NCT02308228) — it's a real completed trial in the fixture
    registry with has_results=True."""
    traces = metformin_day3_e2e["traces"]
    nct_traces = [t for t in traces if t.trace_type == "nct_exists"]
    masters_passes = [
        t for t in nct_traces
        if t.passed and "NCT02308228" in (t.detail or "")
    ]
    assert masters_passes, (
        f"no passing nct_exists trace for MASTERS. All nct traces: "
        f"{[(t.passed, t.detail) for t in nct_traces]}"
    )


def test_no_unexpected_failed_traces(metformin_day3_e2e: dict) -> None:
    """Diagnostic: in the happy-path metformin run, traces should mostly
    pass. Failed traces are surfaced as a list — used as telemetry, not
    a hard gate. If failures appear here that weren't expected, that's
    a regression worth investigating."""
    traces = metformin_day3_e2e["traces"]
    failed = [t for t in traces if not t.passed]
    # Soft gate: print and continue. The hard gates are the positive
    # assertions above.
    if failed:
        print(f"\n{len(failed)} failed traces (diagnostic):")
        for t in failed:
            print(f"  - {t.trace_type} ref={t.ref}: {t.detail}")


def test_planted_case_4_glufomin_alias_drift_flagged(
    metformin_pack: TopicPack,
    metformin_items: list[EvidenceItem],
) -> None:
    """Adversarial regression: a synthetic claim citing the planted-case-4
    drug 'Glufomin' must trigger trace_alias_match → passed=False. This
    proves the trace_clients fixture corpus correctly omits Glufomin
    AND the trace orchestrator surfaces the drift."""
    from agent.citation_trace import trace_alias_match
    from agent.schemas import Claim

    # Construct a malicious claim with Glufomin
    claim = Claim(
        claim_id="C999", text="Glufomin demonstrated mortality benefit in older adults.",
        claim_type="efficacy", supporting_refs=(metformin_items[0].source.ref,),
        opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    drug_client = FixtureDrugAliasClient()
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    assert any("Glufomin" in (t.detail or "") for t in drift), (
        f"Glufomin drift not flagged. Traces: {[(t.passed, t.detail) for t in traces]}"
    )


def test_pipeline_performance_baseline(metformin_day3_e2e: dict) -> None:
    """Day-3 deterministic stages (compile + trace) must stay under
    sub-second budget on the fixture corpus. Real httpx-trace runtime
    will be network-bound; this baseline is for the deterministic path."""
    t_compile = metformin_day3_e2e["t_compile_sec"]
    t_trace = metformin_day3_e2e["t_trace_sec"]
    assert t_compile < 0.5, f"compile took {t_compile:.3f}s; baseline < 0.5s"
    assert t_trace < 1.0, f"trace took {t_trace:.3f}s; baseline < 1.0s"


# --- Telemetry summary ---------------------------------------------------


def test_day3_e2e_summary(metformin_day3_e2e: dict) -> None:
    """Pretty-print Day 3 E2E summary — running pytest -s shows the
    telemetry. Body is sanity assertions; print is the Day 3.4
    deliverable snapshot of what the full Day-3 pipeline produced."""
    facts = metformin_day3_e2e["facts"]
    claims = metformin_day3_e2e["claims"]
    graph = metformin_day3_e2e["graph"]
    traces = metformin_day3_e2e["traces"]

    print()
    print("=" * 60)
    print("Day 3.4 — Metformin Day-3 Pipeline E2E Summary")
    print("=" * 60)
    print(f"hand-curated facts:    {len(facts)}")
    print(f"compiled claims:       {len(claims)}")
    print(f"thesis_claim_id:       {graph.thesis_claim_id}")
    print(f"compile time:          {metformin_day3_e2e['t_compile_sec']*1000:.1f} ms")
    print(f"trace time:            {metformin_day3_e2e['t_trace_sec']*1000:.1f} ms")
    print(f"total traces:          {len(traces)}")
    by_type: dict[str, int] = {}
    for t in traces:
        by_type[t.trace_type] = by_type.get(t.trace_type, 0) + 1
    print(f"traces by type:        {by_type}")
    n_passed = sum(1 for t in traces if t.passed)
    print(f"passed:                {n_passed} / {len(traces)}")
    print("=" * 60)

    assert len(claims) == len(facts)
    assert graph.thesis_claim_id is not None
