"""Tests for agent/evidence_clusters.py — Slice 8 step D.

Verifies clusterer logic + scoring + cluster summary rendering.
Universal: every test uses dict-shaped receipts (not tied to any
specific dataclass) so the clusterer is provably domain-agnostic.
"""
from __future__ import annotations

from agent.evidence_clusters import (
    DEFAULT_TOP_N_PER_CLUSTER, EvidenceCluster,
    cluster_funnel_summary, cluster_receipts,
    format_cluster_summary, receipt_score,
)


def _r(**kw):
    """Receipt-shaped dict for tests."""
    base = dict(
        receipt_id="R", outcome_class="primary", design="rct",
        evidence_tier="rct", directness="direct",
        year=2024, n_claims=10,
    )
    base.update(kw)
    return base


# ---------- receipt_score ---------------------------------------------

def test_score_high_for_recent_direct_rct_with_claims():
    """Top-of-hierarchy + recent + direct + many claims → high score."""
    r = _r(
        evidence_tier="rct", directness="direct",
        year=2024, n_claims=20,
    )
    s = receipt_score(r, evidence_hierarchy=("rct", "cohort", "review"))
    assert 0.8 <= s <= 1.0


def test_score_low_for_old_indirect_review_no_claims():
    """When BOTH tier and design indicate the lowest hierarchy
    slot, score is materially below the strong-RCT baseline.
    The scorer takes the FIRST match in the hierarchy so a
    receipt mistakenly tagged design='rct' / tier='review' would
    get the rct rank (lenient) — that's fine; the test pins
    properly-tagged-as-weak vs properly-tagged-as-strong."""
    r = _r(
        design="review", evidence_tier="review",
        directness="review", year=2005, n_claims=0,
    )
    s = receipt_score(r, evidence_hierarchy=("rct", "cohort", "review"))
    assert s < 0.4


def test_score_universal_across_domains():
    """Same scorer works for non-biomedical domains. Economics
    receipt with natural_experiment design + recent year → high."""
    r = _r(
        evidence_tier="natural_experiment",
        design="natural_experiment", directness="direct",
        year=2024, n_claims=15,
    )
    econ_hierarchy = (
        "natural_experiment", "rct", "diff_in_diff", "panel_data",
    )
    s = receipt_score(r, evidence_hierarchy=econ_hierarchy)
    assert s >= 0.7


# ---------- cluster_receipts ------------------------------------------

def test_groups_by_outcome_and_design():
    rs = [
        _r(receipt_id="A", outcome_class="mortality", design="rct"),
        _r(receipt_id="B", outcome_class="mortality", design="rct"),
        _r(receipt_id="C", outcome_class="mortality", design="cohort"),
        _r(receipt_id="D", outcome_class="function", design="rct"),
    ]
    clusters = cluster_receipts(rs)
    keys = {(c.outcome_class, c.design) for c in clusters}
    assert keys == {
        ("mortality", "rct"),
        ("mortality", "cohort"),
        ("function", "rct"),
    }
    mort_rct = next(
        c for c in clusters
        if c.outcome_class == "mortality" and c.design == "rct"
    )
    assert mort_rct.n_total == 2


def test_top_n_per_cluster_caps_kept():
    """5 receipts in one cluster, top_n=3 → only 3 kept."""
    rs = [
        _r(receipt_id=f"R{i}", outcome_class="primary", design="rct",
           n_claims=20 - i)  # decreasing claim count
        for i in range(5)
    ]
    clusters = cluster_receipts(rs, top_n_per_cluster=3)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.n_total == 5
    assert c.n_kept == 3
    # Top 3 should be R0/R1/R2 (highest claim counts)
    kept_ids = [r["receipt_id"] for r in c.top_receipts]
    assert kept_ids == ["R0", "R1", "R2"]


def test_clusters_sorted_by_top_score_desc():
    """The strongest cluster (highest top-receipt score) ranks first."""
    rs = [
        # Weak cluster: review of cohort, old, no claims
        _r(receipt_id="weak", outcome_class="biomarker",
           design="review", evidence_tier="review", directness="review",
           year=2005, n_claims=0),
        # Strong cluster: recent direct RCT with claims
        _r(receipt_id="strong", outcome_class="mortality",
           design="rct", evidence_tier="rct", directness="direct",
           year=2024, n_claims=15),
    ]
    clusters = cluster_receipts(
        rs, evidence_hierarchy=("rct", "cohort", "review"),
    )
    assert clusters[0].outcome_class == "mortality"
    assert clusters[1].outcome_class == "biomarker"


def test_default_top_n_is_three():
    assert DEFAULT_TOP_N_PER_CLUSTER == 3


def test_empty_receipts_returns_empty_clusters():
    assert cluster_receipts([]) == []


# ---------- format_cluster_summary ------------------------------------

def test_format_cluster_summary_compact():
    """Cluster summary is a short paragraph (Slice 8 E uses these
    instead of paper-by-paper dump). Output should be <300 chars
    for a typical 2-3 receipt cluster."""
    rs = [
        _r(receipt_id="A_2024", outcome_class="mortality",
           design="rct", evidence_tier="rct"),
        _r(receipt_id="B_2023", outcome_class="mortality",
           design="rct", evidence_tier="rct"),
    ]
    c = cluster_receipts(rs)[0]
    summary = format_cluster_summary(c)
    assert "mortality" in summary
    assert "rct" in summary
    assert "A_2024" in summary or "B_2023" in summary
    assert len(summary) < 300


# ---------- cluster_funnel_summary ------------------------------------

def test_funnel_summary_shape_for_dashboard():
    rs = [
        _r(receipt_id="A", outcome_class="mortality", design="rct"),
        _r(receipt_id="B", outcome_class="mortality", design="cohort"),
        _r(receipt_id="C", outcome_class="function", design="rct"),
    ]
    clusters = cluster_receipts(rs)
    summary = cluster_funnel_summary(clusters)
    assert summary["n_clusters"] == 3
    assert summary["n_outcome_classes"] == 2
    assert summary["n_design_types"] == 2
    assert summary["n_total_receipts"] == 3
    assert summary["n_top_receipts"] == 3
