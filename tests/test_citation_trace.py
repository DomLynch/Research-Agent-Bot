"""Tests for agent/citation_trace.py — the moat orchestrator.

Each per-check trace function gets:
- A positive test (real evidence → passed=True)
- A negative test (planted failure shape → passed=False)

Plus orchestrator tests that compose multiple checks and end-to-end tests
that load the planted-failure fixtures and assert the right TraceType
catches each case.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.citation_trace import (
    summary,
    trace_alias_match,
    trace_claim,
    trace_claim_graph,
    trace_nct_exists,
    trace_p_value_in_text,
    trace_percentage_in_text,
    trace_role_match,
)
from agent.schemas import Claim, ClaimGraph
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Source

METFORMIN_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(METFORMIN_PATH)


@pytest.fixture(scope="module")
def registry() -> FixtureTrialRegistryClient:
    return FixtureTrialRegistryClient()


@pytest.fixture(scope="module")
def drug_client() -> FixtureDrugAliasClient:
    return FixtureDrugAliasClient()


def _src(ref: int = 1, nct: str | None = None) -> Source:
    return Source(ref=ref, title="", year=2024, url="", source="pubmed", nct=nct)


def _item(
    *,
    ref: int = 1,
    role: str = "published_results",
    design: str = "rct",
    tier: str = "A1",
    direct: bool = True,
    nct: str | None = None,
    abstract: str = "",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design=design, role=role, tier=tier,  # type: ignore[arg-type]
        direct=direct, strict=True,
    )


def _claim(
    *,
    cid: str = "C01",
    text: str = "metformin blunts hypertrophy.",
    refs: tuple[int, ...] = (1,),
    directness: str = "direct",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier="A1", confidence="high", attack_surface=(),
    )


# --- trace_nct_exists -----------------------------------------------------


def test_trace_nct_exists_pass_for_real_nct(
    registry: FixtureTrialRegistryClient,
) -> None:
    """MASTERS NCT02308228 is in the fixture registry."""
    claim = _claim()
    item = _item(nct="NCT02308228")
    rec = trace_nct_exists(claim, item, registry)
    assert rec is not None
    assert rec.passed is True
    assert rec.trace_type == "nct_exists"
    assert "NCT02308228" in rec.detail


def test_trace_nct_exists_planted_case_2(
    registry: FixtureTrialRegistryClient,
) -> None:
    """Planted case 2: fabricated NCT99999999."""
    claim = _claim()
    item = _item(nct="NCT99999999")
    rec = trace_nct_exists(claim, item, registry)
    assert rec is not None and rec.passed is False
    assert "not found" in rec.detail.lower() or "fabricated" in rec.detail.lower()


def test_trace_nct_exists_returns_none_when_no_nct(
    registry: FixtureTrialRegistryClient,
) -> None:
    """Source has no NCT — nothing to trace; returns None (not a failure)."""
    claim = _claim()
    item = _item(nct=None)
    assert trace_nct_exists(claim, item, registry) is None


# --- trace_role_match -----------------------------------------------------


def test_trace_role_match_pass_for_aligned_claim() -> None:
    """Direct claim with at least one direct evidence item."""
    claim = _claim(directness="direct")
    items = {1: _item(role="published_results", direct=True)}
    rec = trace_role_match(claim, items)
    assert rec.passed is True
    assert rec.trace_type == "role_match"


def test_trace_role_match_fails_when_direct_claim_has_no_direct_evidence() -> None:
    claim = _claim(directness="direct")
    items = {1: _item(role="mechanistic", direct=False)}
    rec = trace_role_match(claim, items)
    assert rec.passed is False
    assert "DIRECTNESS_MISMATCH" in rec.detail or "directness" in rec.detail.lower()


def test_trace_role_match_passes_for_non_direct_claims() -> None:
    """Non-direct claims have no analogous constraint."""
    claim = _claim(directness="indirect")
    items = {1: _item(role="review", direct=False)}
    rec = trace_role_match(claim, items)
    assert rec.passed is True


# --- trace_p_value_in_text ------------------------------------------------


def test_trace_p_value_pass_for_matching_pvalue() -> None:
    claim = _claim(text="Reduced muscle mass (p=0.003).")
    item = _item(abstract="Placebo gained more lean mass (p=0.003).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is True


def test_trace_p_value_planted_case_3_inflated() -> None:
    """Claim cites p<0.001 but source has p=0.08."""
    claim = _claim(text="Reported significant attenuation of VO2max (p<0.001).")
    item = _item(abstract="Metformin attenuated VO2max (p=0.08).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is False
    assert "p<0.001" in traces[0].detail
    assert traces[0].source_excerpt is not None  # excerpt populated on fail


def test_trace_p_value_emits_one_per_pvalue() -> None:
    """A claim with two p-values → two traces."""
    claim = _claim(text="VO2max (p=0.08) and insulin (p=0.02).")
    item = _item(abstract="VO2max (p=0.08) and insulin (p=0.02).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 2
    assert all(t.passed for t in traces)


def test_trace_p_value_no_pvalues_yields_nothing() -> None:
    claim = _claim(text="No statistical reporting in this claim.")
    item = _item(abstract="Some abstract.")
    traces = list(trace_p_value_in_text(claim, item))
    assert traces == []


# --- trace_percentage_in_text --------------------------------------------


def test_trace_percentage_pass_for_matching_percentage() -> None:
    claim = _claim(text="Mortality decreased by 30%.")
    item = _item(abstract="30% reduction in mortality observed.")
    traces = list(trace_percentage_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is True


def test_trace_percentage_fails_when_not_in_source() -> None:
    """Claim cites 30%, source says 22%."""
    claim = _claim(text="Mortality decreased by 30%.")
    item = _item(abstract="22% reduction in mortality.")
    traces = list(trace_percentage_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is False
    assert "30%" in traces[0].detail


def test_trace_percentage_handles_decimals() -> None:
    claim = _claim(text="Improved by 1.5%.")
    item = _item(abstract="Treatment yielded 1.5% improvement.")
    traces = list(trace_percentage_in_text(claim, item))
    assert traces and traces[0].passed is True


# --- trace_alias_match ----------------------------------------------------


def test_trace_alias_match_planted_case_4_glufomin(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Glufomin is not in compounds/ fixture → drift caught."""
    claim = _claim(text="Glufomin reduced incident frailty by 20%.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    assert drift, "Glufomin should fail alias_match"
    assert "Glufomin" in drift[0].detail


def test_trace_alias_match_passes_for_known_canonical(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """A non-topic drug name that IS in the alias registry should pass."""
    claim = _claim(text="In a comparison with Glucophage, the trial enrolled adults.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    # Glucophage is in the metformin pack alias list, so alias_match skips it
    # entirely (already validated). Test passes by emitting no failed alias trace.
    assert all(t.passed for t in traces), traces


def test_trace_alias_match_skips_pack_aliases(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Topic-pack aliases are pre-validated and skipped to avoid noise."""
    claim = _claim(text="Glucophage and metformin were compared.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    candidates = {t.detail.split("'")[1] for t in traces if "'" in t.detail}
    # Glucophage is a pack alias (case-insensitive); should be skipped
    assert "Glucophage" not in candidates


def test_trace_alias_match_filters_stopwords(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Common false positives (Trial, Study, Older) don't fire."""
    claim = _claim(text="The Trial in Older Adults found Reduced mortality.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    # All these words are in the stopword list — no alias_match traces should
    # emerge for them.
    candidates = [t for t in traces if t.trace_type == "alias_match"]
    for t in candidates:
        for noise in ("Trial", "Older", "Study", "Reduced"):
            assert noise not in t.detail, (
                f"stopword {noise!r} should not appear in alias_match trace"
            )


# --- trace_claim orchestrator --------------------------------------------


def test_trace_claim_emits_role_match_first(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    claim = _claim()
    items = {1: _item(role="published_results", abstract="(p=0.04)")}
    traces = trace_claim(
        claim, items, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    assert traces[0].trace_type == "role_match"


def test_trace_claim_records_unresolvable_ref(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """A claim referencing a missing ref should emit a failed trace."""
    claim = _claim(refs=(99,))
    items: dict[int, EvidenceItem] = {}  # ref 99 not present
    traces = trace_claim(
        claim, items, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    failures = [t for t in traces if not t.passed]
    assert any("not present" in t.detail for t in failures)


def test_trace_claim_e2e_planted_case_2(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted fabricated NCT shows up as a failed nct_exists trace."""
    claim = _claim(text="The trial showed 30% reduction (p=0.04).")
    items = {1: _item(nct="NCT99999999",
                       abstract="30% reduction observed (p=0.04).")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    nct_traces = [t for t in traces if t.trace_type == "nct_exists"]
    assert nct_traces and not nct_traces[0].passed


def test_trace_claim_e2e_planted_case_3(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted inflated p-value shows up as failed p_value_in_text."""
    claim = _claim(text="Konopka reported VO2max attenuation (p<0.001).")
    items = {1: _item(abstract="Metformin attenuated VO2max (p=0.08).")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    pv = [t for t in traces if t.trace_type == "p_value_in_text"]
    assert pv and not pv[0].passed


def test_trace_claim_e2e_planted_case_4(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted alias drift shows up as failed alias_match."""
    claim = _claim(text="Glufomin reduced frailty.")
    items = {1: _item(abstract="Some study.")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    drift = [t for t in traces if t.trace_type == "alias_match" and not t.passed]
    assert drift and "Glufomin" in drift[0].detail


# --- trace_claim_graph orchestrator --------------------------------------


def test_trace_claim_graph_runs_per_claim(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    c1 = _claim(cid="C01", text="(p=0.04)", refs=(1,))
    c2 = _claim(cid="C02", text="(p=0.10)", refs=(1,))
    graph = ClaimGraph(claims=(c1, c2), edges=(), thesis_claim_id="C01")
    items = {1: _item(abstract="results (p=0.04) and (p=0.10).")}
    traces = trace_claim_graph(graph, items, metformin_pack,
                                registry=registry, drug_client=drug_client)
    claim_ids = {t.claim_id for t in traces}
    assert claim_ids == {"C01", "C02"}


# --- summary helper -------------------------------------------------------


def test_summary_groups_by_type_and_outcome() -> None:
    from agent.schemas import CitationTrace
    traces = [
        CitationTrace(claim_id="C1", ref=1, trace_type="nct_exists",
                      passed=True, detail="x"),
        CitationTrace(claim_id="C1", ref=1, trace_type="nct_exists",
                      passed=False, detail="x"),
        CitationTrace(claim_id="C1", ref=1, trace_type="p_value_in_text",
                      passed=True, detail="x"),
    ]
    s = summary(traces)
    assert s == {
        "nct_exists:pass": 1, "nct_exists:fail": 1, "p_value_in_text:pass": 1,
    }


# --- regression: ClaimEdge isn't being used here, but import stays valid --


def test_imports_clean() -> None:
    """If this test runs, the module imports without circular issues."""
    # Re-import everything in one shot
    import agent.citation_trace  # noqa: F401
    assert True
