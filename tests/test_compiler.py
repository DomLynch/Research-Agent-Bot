"""Tests for agent/compiler.py — deterministic facts → Claims → ClaimGraph.

Day 3.2a covers only the deterministic half of the compiler. Day 3.2c
will add an LLM fact-extraction stage with separate tests.
"""
from __future__ import annotations

import pytest

from agent.compiler import (
    CompileError,
    _claim_id_for,
    _derive_claim_type,
    _derive_confidence,
    _derive_directness,
    cluster_all_claims,
    compile_claim_graph,
    compile_claims,
    compile_per_cluster_claim_graphs,
)
from agent.types import EvidenceItem, Fact, Source


def _src(ref: int = 1, *, nct: str | None = None) -> Source:
    return Source(ref=ref, title="", year=2024, url="", source="pubmed", nct=nct)


def _item(
    *,
    ref: int = 1,
    role: str = "published_results",
    design: str = "rct",
    tier: str = "A1",
    direct: bool = True,
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref), abstract="", design=design,  # type: ignore[arg-type]
        role=role, tier=tier,  # type: ignore[arg-type]
        direct=direct, strict=direct,
    )


def _fact(
    *, ref: int = 1, kind: str = "result", claim: str = "metformin reduced X.",
) -> Fact:
    return Fact(
        ref=ref, kind=kind, claim=claim,  # type: ignore[arg-type]
        outcome=None, estimate=None, p_value=None, ci=None,
    )


# --- Helper derivations ---------------------------------------------------


def test_claim_id_for_uses_three_digit_padding() -> None:
    assert _claim_id_for(1) == "C001"
    assert _claim_id_for(42) == "C042"
    assert _claim_id_for(999) == "C999"


def test_derive_claim_type_maps_result_to_efficacy() -> None:
    assert _derive_claim_type(_fact(kind="result")) == "efficacy"


def test_derive_claim_type_protocol_and_context_become_context() -> None:
    assert _derive_claim_type(_fact(kind="protocol")) == "context"
    assert _derive_claim_type(_fact(kind="context")) == "context"


def test_derive_directness_direct_wins() -> None:
    assert _derive_directness(_item(direct=True)) == "direct"


def test_derive_directness_mechanistic_role_when_not_direct() -> None:
    item = _item(role="mechanistic", direct=False)
    assert _derive_directness(item) == "mechanistic"


def test_derive_directness_indirect_for_other_non_direct() -> None:
    item = _item(role="review", design="review", direct=False)
    assert _derive_directness(item) == "indirect"


def test_derive_confidence_a1_rct_results_is_high() -> None:
    assert _derive_confidence(_item(role="published_results", design="rct", tier="A1")) == "high"


def test_derive_confidence_a2_rct_results_is_moderate() -> None:
    assert _derive_confidence(_item(role="published_results", design="rct", tier="A2")) == "moderate"


def test_derive_confidence_observational_results_is_low() -> None:
    assert _derive_confidence(_item(role="published_results", design="observational", tier="A2")) == "low"


def test_derive_confidence_meta_analysis_is_moderate() -> None:
    assert _derive_confidence(_item(role="review", design="meta_analysis", tier="A2")) == "moderate"


def test_derive_confidence_review_other_design_is_low() -> None:
    assert _derive_confidence(_item(role="review", design="review", tier="A2")) == "low"


def test_derive_confidence_mechanistic_is_low() -> None:
    assert _derive_confidence(_item(role="mechanistic", design="mechanistic", tier="C")) == "low"


# --- compile_claims --------------------------------------------------------


def test_compile_claims_one_fact_to_one_claim() -> None:
    fact = _fact(ref=1, kind="result", claim="reduced lean mass.")
    item = _item(ref=1, role="published_results", design="rct", tier="A1", direct=True)
    claims = compile_claims([fact], [item])
    assert len(claims) == 1
    c = claims[0]
    assert c.claim_id == "C001"
    assert c.text == "reduced lean mass."
    assert c.claim_type == "efficacy"
    assert c.directness == "direct"
    assert c.evidence_tier == "A1"
    assert c.confidence == "high"
    assert c.supporting_refs == (1,)


def test_compile_claims_preserves_fact_order() -> None:
    facts = [
        _fact(ref=1, kind="result", claim="first"),
        _fact(ref=2, kind="result", claim="second"),
        _fact(ref=3, kind="context", claim="third"),
    ]
    items = [_item(ref=i) for i in (1, 2, 3)]
    claims = compile_claims(facts, items)
    assert [c.claim_id for c in claims] == ["C001", "C002", "C003"]
    assert [c.text for c in claims] == ["first", "second", "third"]


def test_compile_claims_orphan_ref_raises_compile_error() -> None:
    """A Fact pointing at a ref with no matching EvidenceItem is a
    structural error — surface it loud, don't silently drop the fact."""
    fact = _fact(ref=99, claim="orphan")
    item = _item(ref=1)
    with pytest.raises(CompileError, match="ref=99"):
        compile_claims([fact], [item])


def test_compile_claims_empty_input_returns_empty_list() -> None:
    """Empty fact list is a valid input — no claims, no error. The
    error case is upstream (compile_claim_graph rejects empty)."""
    assert compile_claims([], []) == []


def test_compile_claims_handles_multiple_facts_same_ref() -> None:
    """Two Facts citing the same EvidenceItem each become separate
    Claims (1:1 by Fact). Day 4 may merge near-duplicates."""
    facts = [
        _fact(ref=1, kind="result", claim="effect on mass."),
        _fact(ref=1, kind="result", claim="effect on strength."),
    ]
    items = [_item(ref=1)]
    claims = compile_claims(facts, items)
    assert len(claims) == 2
    assert claims[0].supporting_refs == (1,)
    assert claims[1].supporting_refs == (1,)
    assert claims[0].claim_id != claims[1].claim_id


# --- compile_claim_graph + thesis-picking ---------------------------------


def test_compile_claim_graph_picks_direct_a1_thesis() -> None:
    facts = [
        _fact(ref=1, kind="result", claim="direct a1 result"),
        _fact(ref=2, kind="context", claim="mechanistic context"),
    ]
    items = [
        _item(ref=1, role="published_results", design="rct", tier="A1", direct=True),
        _item(ref=2, role="mechanistic", design="mechanistic", tier="C", direct=False),
    ]
    claims = compile_claims(facts, items)
    graph = compile_claim_graph(claims)
    assert graph.thesis_claim_id == "C001"  # direct A1 wins


def test_compile_claim_graph_picks_a1_over_a2_when_both_direct() -> None:
    facts = [
        _fact(ref=1, kind="result", claim="direct a2"),
        _fact(ref=2, kind="result", claim="direct a1"),
    ]
    items = [
        _item(ref=1, tier="A2"),
        _item(ref=2, tier="A1"),
    ]
    claims = compile_claims(facts, items)
    graph = compile_claim_graph(claims)
    # A1 (C002) wins despite later position
    assert graph.thesis_claim_id == "C002"


def test_compile_claim_graph_picks_indirect_when_no_direct() -> None:
    facts = [
        _fact(ref=1, kind="result", claim="mechanistic"),
        _fact(ref=2, kind="context", claim="review"),
    ]
    items = [
        _item(ref=1, role="mechanistic", design="mechanistic", tier="C", direct=False),
        _item(ref=2, role="review", design="review", tier="B", direct=False),
    ]
    claims = compile_claims(facts, items)
    graph = compile_claim_graph(claims)
    # No direct claims; review tier B (indirect) beats mechanistic C
    assert graph.thesis_claim_id == "C002"


def test_compile_claim_graph_explicit_thesis_id_honored() -> None:
    facts = [
        _fact(ref=1, kind="result", claim="default thesis would be this"),
        _fact(ref=2, kind="result", claim="we pick this instead"),
    ]
    items = [_item(ref=1), _item(ref=2)]
    claims = compile_claims(facts, items)
    graph = compile_claim_graph(claims, thesis_claim_id="C002")
    assert graph.thesis_claim_id == "C002"


def test_compile_claim_graph_explicit_thesis_id_rejected_if_invalid() -> None:
    """Bad explicit thesis_claim_id surfaces via the schema invariant."""
    from agent.schemas import ClaimGraphInvariantError
    facts = [_fact()]
    items = [_item()]
    claims = compile_claims(facts, items)
    with pytest.raises(ClaimGraphInvariantError, match="thesis_claim_id"):
        compile_claim_graph(claims, thesis_claim_id="C999")


def test_compile_claim_graph_empty_claims_raises() -> None:
    with pytest.raises(CompileError, match="at least one claim"):
        compile_claim_graph([])


def test_compile_claim_graph_edges_default_empty() -> None:
    """Day 3.2a leaves edges empty — Day 4 SPAR populates them."""
    facts = [_fact()]
    items = [_item()]
    graph = compile_claim_graph(compile_claims(facts, items))
    assert graph.edges == ()


# --- Day 6.3: cohesive cluster filter -------------------------------------


def test_cohesive_cluster_keeps_largest_when_one_paper_dominates() -> None:
    """3 claims from paper [3] + 2 claims from paper [5], all direct/A2.
    The cluster filter must keep the 3-claim cluster (size wins among
    same-tier clusters), so the writer renders a coherent artifact
    rather than mixing two unrelated A2 papers."""
    items = [
        _item(ref=3, role="published_results", tier="A2", direct=True),
        _item(ref=5, role="published_results", tier="A2", direct=True),
    ]
    facts = [
        _fact(ref=3, claim="ref-3 claim 1"),
        _fact(ref=3, claim="ref-3 claim 2"),
        _fact(ref=3, claim="ref-3 claim 3"),
        _fact(ref=5, claim="ref-5 claim 1"),
        _fact(ref=5, claim="ref-5 claim 2"),
    ]
    graph = compile_claim_graph(compile_claims(facts, items))
    refs_in_graph = {r for c in graph.claims for r in c.supporting_refs}
    assert refs_in_graph == {3}
    assert len(graph.claims) == 3


def test_cohesive_cluster_prefers_a1_singleton_over_b_multi_cluster() -> None:
    """Day 8: directness + tier dominate cluster size. A solo direct-A1
    RCT (e.g., PROTECTOR / Mannick aging trial in everolimus pack) must
    win over a 5-claim indirect-B oncology cluster, even though the
    oncology cluster is bigger. Without this rule, the everolimus
    cluster filter picked the renal-cell-carcinoma trial cluster over
    PROTECTOR — a mechanism-inflated-to-clinic failure at the cluster
    level."""
    items = [
        _item(ref=1, role="published_results", tier="B", direct=False),  # oncology indirect
        _item(ref=7, role="published_results", tier="A1", direct=True),  # aging direct
    ]
    facts = [
        _fact(ref=1, claim="oncology claim 1"),
        _fact(ref=1, claim="oncology claim 2"),
        _fact(ref=1, claim="oncology claim 3"),
        _fact(ref=1, claim="oncology claim 4"),
        _fact(ref=1, claim="oncology claim 5"),
        _fact(ref=7, claim="aging claim 1"),
    ]
    graph = compile_claim_graph(compile_claims(facts, items))
    refs_in_graph = {r for c in graph.claims for r in c.supporting_refs}
    assert refs_in_graph == {7}, (
        f"direct-A1 singleton must beat indirect-B 5-cluster, kept {refs_in_graph}"
    )


def test_cohesive_cluster_no_filter_when_all_singletons() -> None:
    """When every claim has its own paper (no shared supporting_refs),
    the filter would arbitrarily keep one and drop the rest. Activation
    rule: only kicks in when at least one cluster has ≥2 members."""
    items = [
        _item(ref=1, role="published_results", tier="A1", direct=True),
        _item(ref=2, role="published_results", tier="A2", direct=True),
        _item(ref=3, role="published_results", tier="A2", direct=True),
    ]
    facts = [_fact(ref=1), _fact(ref=2), _fact(ref=3)]
    graph = compile_claim_graph(compile_claims(facts, items))
    assert len(graph.claims) == 3, "all 3 singletons must remain"


def test_cohesive_cluster_can_be_disabled() -> None:
    """`cohesive_cluster_only=False` preserves the legacy 'render every
    claim' behavior — useful for tests that assemble synthetic
    cross-paper graphs and want them all to surface."""
    items = [
        _item(ref=3, role="published_results", tier="A2", direct=True),
        _item(ref=3, role="published_results", tier="A2", direct=True),
        _item(ref=8, role="published_results", tier="A1", direct=True),
    ]
    facts = [
        _fact(ref=3, claim="a"), _fact(ref=3, claim="b"),
        _fact(ref=8, claim="c"),
    ]
    graph = compile_claim_graph(
        compile_claims(facts, items),
        cohesive_cluster_only=False,
    )
    refs_in_graph = {r for c in graph.claims for r in c.supporting_refs}
    assert refs_in_graph == {3, 8}


# Thesis-score determinism + tiebreak tests moved to
# tests/test_thesis_tournament.py after Day 4.1b wired pick_thesis into
# compile_claim_graph and dropped the in-module _thesis_score/_pick_thesis
# helpers. The integration-level guarantees (compile_claim_graph delegates
# to the tournament correctly) are covered by the tests above.


# --- Day 10.8b: multi-cluster output --------------------------------------


def test_cluster_all_claims_returns_every_cluster_best_first() -> None:
    """Two distinct paper-clusters: A1 direct (ref=3, 3 claims) and
    A2 direct (ref=5, 2 claims). Best-first ranking puts A1 cluster
    first, A2 cluster second. Multi-receipt mode iterates both."""
    items = [
        _item(ref=3, role="published_results", tier="A1", direct=True),
        _item(ref=5, role="published_results", tier="A2", direct=True),
    ]
    facts = [
        _fact(ref=3, claim="ref-3 c1"),
        _fact(ref=3, claim="ref-3 c2"),
        _fact(ref=3, claim="ref-3 c3"),
        _fact(ref=5, claim="ref-5 c1"),
        _fact(ref=5, claim="ref-5 c2"),
    ]
    claims = compile_claims(facts, items)
    clusters = cluster_all_claims(claims)
    assert len(clusters) == 2
    refs0 = {r for c in clusters[0] for r in c.supporting_refs}
    refs1 = {r for c in clusters[1] for r in c.supporting_refs}
    assert refs0 == {3}, "A1 cluster must rank first"
    assert refs1 == {5}, "A2 cluster must rank second"


def test_cluster_all_claims_singleton_corpus_returns_one_cluster() -> None:
    """When every claim has its own paper, no multi-member cluster
    exists — return one tuple with all claims so multi-receipt mode
    doesn't lose data."""
    items = [
        _item(ref=1, role="published_results", tier="A1", direct=True),
        _item(ref=2, role="published_results", tier="A2", direct=True),
        _item(ref=3, role="published_results", tier="A2", direct=True),
    ]
    facts = [_fact(ref=1), _fact(ref=2), _fact(ref=3)]
    clusters = cluster_all_claims(compile_claims(facts, items))
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_cluster_all_claims_empty_input_returns_empty() -> None:
    """Caller decides how to handle empty — cluster_all_claims is pure."""
    assert cluster_all_claims(()) == ()


def test_cluster_all_claims_canonical_cluster_outranks_non_canonical() -> None:
    """Canonical-trial bonus is the first sort dim. A non-canonical A1
    direct cluster must NOT outrank a canonical A1 direct cluster of the
    same size."""
    items = [
        _item(ref=1, role="published_results", tier="A1", direct=True),
        _item(ref=2, role="published_results", tier="A1", direct=True),
        _item(ref=3, role="published_results", tier="A1", direct=True),
        _item(ref=4, role="published_results", tier="A1", direct=True),
    ]
    facts = [
        _fact(ref=1, claim="non-canon a"),
        _fact(ref=1, claim="non-canon b"),
        _fact(ref=3, claim="canon a"),
        _fact(ref=3, claim="canon b"),
    ]
    claims = compile_claims(facts, items)
    clusters = cluster_all_claims(claims, canonical_refs=frozenset({3}))
    refs0 = {r for c in clusters[0] for r in c.supporting_refs}
    assert refs0 == {3}, "canonical cluster must rank first"


def test_compile_per_cluster_claim_graphs_emits_one_graph_per_cluster() -> None:
    """Each cluster produces its own ClaimGraph with its own thesis pick.
    Together the graphs cover the SAME claims as the input (no dropping)."""
    items = [
        _item(ref=3, role="published_results", tier="A1", direct=True),
        _item(ref=5, role="published_results", tier="A2", direct=True),
    ]
    facts = [
        _fact(ref=3, claim="alpha"),
        _fact(ref=3, claim="beta"),
        _fact(ref=5, claim="gamma"),
    ]
    claims = compile_claims(facts, items)
    items_by_ref = {it.source.ref: it for it in items}
    graphs = compile_per_cluster_claim_graphs(claims, items_by_ref=items_by_ref)
    assert len(graphs) == 2
    all_claim_ids = {c.claim_id for g in graphs for c in g.claims}
    assert all_claim_ids == {c.claim_id for c in claims}, (
        "every claim must land in some cluster graph"
    )
    for g in graphs:
        assert g.thesis_claim_id in {c.claim_id for c in g.claims}, (
            "thesis pick must reference a claim in its own graph"
        )


def test_compile_per_cluster_claim_graphs_empty_input_raises() -> None:
    with pytest.raises(CompileError):
        compile_per_cluster_claim_graphs([])


def test_largest_cohesive_cluster_still_picks_first_cluster_after_refactor() -> None:
    """Regression guard: after the Day 10.8b refactor, the existing
    cohesive_cluster_only=True path on compile_claim_graph must keep
    picking the same cluster (the highest-ranked one)."""
    items = [
        _item(ref=3, role="published_results", tier="A1", direct=True),
        _item(ref=5, role="published_results", tier="A2", direct=True),
    ]
    facts = [
        _fact(ref=3, claim="a"), _fact(ref=3, claim="b"),
        _fact(ref=5, claim="c"), _fact(ref=5, claim="d"),
    ]
    graph = compile_claim_graph(compile_claims(facts, items))
    refs = {r for c in graph.claims for r in c.supporting_refs}
    assert refs == {3}, "compile_claim_graph must still pick the A1 cluster"
