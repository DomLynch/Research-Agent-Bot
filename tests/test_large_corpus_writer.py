"""Tests for agent/large_corpus_writer.py — Slice 8 step E.

Verifies cluster-summary Results stays compact regardless of
receipt count, plus cluster-aware Methods is grounded in funnel
data (not boilerplate). Universal: dict-shaped clusters keep tests
domain-agnostic.
"""
from __future__ import annotations

from agent.evidence_clusters import EvidenceCluster
from agent.large_corpus_writer import (
    CLUSTER_PARAGRAPH_WORDS, LARGE_CORPUS_THRESHOLD,
    build_methods_section_clustered,
    build_results_section_clustered, is_large_corpus,
)


def _cluster(*, oc="primary", design="rct", n_total=5, n_kept=3,
             score=0.8, top_ids=("R1", "R2", "R3")) -> EvidenceCluster:
    top = tuple(
        {"receipt_id": rid, "evidence_tier": "rct",
         "effect_direction": "+"}
        for rid in top_ids
    )
    return EvidenceCluster(
        outcome_class=oc, design=design,
        receipts=top, top_receipts=top,
        n_total=n_total, n_kept=n_kept,
        cluster_score=score,
    )


# ---------- thresholds ----------------------------------------------

def test_large_corpus_threshold_universal():
    """Threshold = 20 receipts. Universal across topics + domains."""
    assert LARGE_CORPUS_THRESHOLD == 20
    assert not is_large_corpus(19)
    assert is_large_corpus(20)
    assert is_large_corpus(45)


# ---------- Results: cluster-summary mode ----------------------------

def test_results_one_paragraph_per_cluster_not_per_receipt():
    """Body length is O(n_clusters), not O(n_receipts). 100 receipts
    in 5 clusters → ~5 paragraphs of body, not 100."""
    clusters = [
        _cluster(oc=f"oc_{i}", n_total=20, n_kept=3)
        for i in range(5)
    ]
    md = build_results_section_clustered(clusters, topic="x")
    # 5 outcome classes → 5 sub-headers; ~5 cluster summary paragraphs
    n_subheaders = md.count("\n### ")
    assert n_subheaders == 5
    # Word count should be capped — 5 clusters × ~80 words = ~400-500
    n_words = len(md.split())
    assert 100 < n_words < 1500, (
        f"Cluster-summary mode should keep body O(n_clusters); "
        f"got {n_words} words for 5 clusters"
    )


def test_results_compact_even_for_huge_receipt_count():
    """Q13 protection: 200 receipts in 1 cluster → still compact."""
    clusters = [_cluster(oc="primary", n_total=200, n_kept=3)]
    md = build_results_section_clustered(clusters, topic="x")
    n_words = len(md.split())
    assert n_words < 400, (
        f"200-receipt cluster should still summarize compactly; "
        f"got {n_words} words"
    )


def test_results_groups_by_outcome_class():
    clusters = [
        _cluster(oc="mortality", design="rct"),
        _cluster(oc="mortality", design="cohort"),
        _cluster(oc="function", design="rct"),
    ]
    md = build_results_section_clustered(clusters, topic="x")
    # Mortality has 2 clusters but only 1 outcome-class header
    assert md.count("### Mortality") == 1
    assert md.count("### Function") == 1


def test_results_includes_cluster_metadata():
    c = _cluster(
        oc="cardiometabolic", design="rct",
        n_total=8, n_kept=3, top_ids=("PEARL", "MASTERS", "JUPITER"),
    )
    md = build_results_section_clustered([c], topic="x")
    assert "cardiometabolic" in md.lower()
    assert "rct" in md.lower()
    assert "PEARL" in md or "MASTERS" in md
    # Cluster total visible
    assert "8" in md


def test_results_empty_clusters_returns_honest_placeholder():
    """Zero clusters → SPAR-rejected-everything placeholder. Honest:
    audit will catch the thin synthesis."""
    md = build_results_section_clustered([], topic="rapamycin")
    assert "## Results" in md
    assert "zero" in md.lower() or "no evidence" in md.lower()
    assert "rapamycin" in md.lower()


# ---------- Methods: cluster-aware -----------------------------------

def test_methods_grounded_in_funnel_counters():
    """Methods is NOT boilerplate — it surfaces the actual funnel
    numbers from this run."""
    funnel = {
        "retrieved": 583, "classified_keep": 428, "classified_drop": 155,
        "extracted_ok": 200, "extracted_cached": 0, "extracted_failed": 6,
        "spar_accepted": 11,
    }
    clusters = [
        _cluster(oc="mortality", design="rct", n_total=4),
        _cluster(oc="function", design="rct", n_total=3),
    ]
    md = build_methods_section_clustered(
        topic="rapamycin", submission_id="test-001",
        funnel=funnel, clusters=clusters,
    )
    assert "## Methods" in md
    assert "583" in md
    assert "428" in md
    assert "11" in md
    assert "rapamycin" in md
    assert "test-001" in md
    # Universal language about the cluster pipeline
    assert "cluster" in md.lower()


def test_methods_universal_no_topic_hardcoding():
    """Methods text must work for any topic / any domain. No 'mTOR'
    or 'metformin' hardcoded — just topic-name interpolation."""
    md = build_methods_section_clustered(
        topic="legal_precedent", submission_id="test",
        funnel={}, clusters=[],
    )
    assert "legal_precedent" in md
    assert "mTOR" not in md and "metformin" not in md
    assert "Trust spine" in md or "trust spine" in md.lower()
