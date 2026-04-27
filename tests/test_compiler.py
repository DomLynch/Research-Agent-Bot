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
    _pick_thesis,
    _thesis_score,
    compile_claim_graph,
    compile_claims,
)
from agent.schemas import Claim
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


# --- Thesis-score determinism --------------------------------------------


def test_thesis_score_orders_by_directness_then_tier_then_confidence() -> None:
    """Verify the score tuple's ordering produces sensible results."""
    direct_a1_high = Claim(
        claim_id="C100", text="x", claim_type="efficacy",
        supporting_refs=(1,), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    direct_a2_high = Claim(
        claim_id="C200", text="x", claim_type="efficacy",
        supporting_refs=(1,), opposing_refs=(),
        directness="direct", evidence_tier="A2", confidence="high",
        attack_surface=(),
    )
    indirect_a1_high = Claim(
        claim_id="C300", text="x", claim_type="indirect",
        supporting_refs=(1,), opposing_refs=(),
        directness="indirect", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    # direct A1 < direct A2 < indirect A1 (directness dominates over tier)
    assert _thesis_score(direct_a1_high) < _thesis_score(direct_a2_high)
    assert _thesis_score(direct_a2_high) < _thesis_score(indirect_a1_high)


def test_pick_thesis_breaks_ties_lexically_by_claim_id() -> None:
    """Two identical-quality claims → lower claim_id wins."""
    c_a = Claim(
        claim_id="C001", text="a", claim_type="efficacy",
        supporting_refs=(1,), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    c_b = Claim(
        claim_id="C002", text="b", claim_type="efficacy",
        supporting_refs=(1,), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    assert _pick_thesis([c_a, c_b]) == "C001"
    assert _pick_thesis([c_b, c_a]) == "C001"  # order-independent
