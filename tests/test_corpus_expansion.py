"""Tests for agent/corpus_expansion.py — Corpus Expansion Mode (Wave 7).

The module turns a sub-AAA verdict into an actionable expansion to-do
list. Universal across topics — pure manifest signals, no drug names,
no per-topic logic.
"""
from __future__ import annotations

from agent.corpus_expansion import (
    compute_corpus_gaps, format_expansion_section,
)


# ---------- quantity gaps -------------------------------------------

def test_no_gaps_when_all_floors_met():
    manifest = {
        "n_receipts": 15,
        "n_high_confidence_claims_total": 60,
        "n_non_orthogonal_tensions": 12,
        "receipts": [
            {"outcome_class": "muscle_function", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": f"P{i}"}
            for i in range(5)
        ] + [
            {"outcome_class": "cardiometabolic", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": f"Q{i}"}
            for i in range(5)
        ] + [
            {"outcome_class": "longevity", "evidence_tier": "A2",
             "directness": "direct", "receipt_id": f"R{i}"}
            for i in range(5)
        ],
    }
    gaps, targets = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert gaps == ()
    assert targets == ()


def test_receipts_gap_emits_delta_and_seed_command():
    manifest = {
        "n_receipts": 3, "n_high_confidence_claims_total": 100,
        "n_non_orthogonal_tensions": 50, "receipts": [],
    }
    gaps, targets = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("3/10" in g and "short by 7" in g for g in gaps)
    assert any("seed_topic_corpus.py" in t for t in targets)


def test_claims_gap_emits_delta():
    manifest = {
        "n_receipts": 50, "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 50, "receipts": [],
    }
    gaps, targets = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("12/50" in g for g in gaps)
    assert any("38" in t for t in targets)  # delta 50-12


def test_tensions_gap_emits_delta():
    manifest = {
        "n_receipts": 50, "n_high_confidence_claims_total": 100,
        "n_non_orthogonal_tensions": 1, "receipts": [],
    }
    gaps, targets = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("1/10" in g for g in gaps)
    assert any("9" in t for t in targets)


# ---------- quality gaps --------------------------------------------

def test_outcome_diversity_gap_when_only_one_class():
    manifest = {
        "n_receipts": 12, "n_high_confidence_claims_total": 60,
        "n_non_orthogonal_tensions": 12,
        "receipts": [
            {"outcome_class": "longevity", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": f"P{i}"}
            for i in range(12)
        ],
    }
    gaps, _ = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("Outcome diversity" in g and "1 classes" in g
               for g in gaps)


def test_direct_evidence_gap_when_only_reviews():
    manifest = {
        "n_receipts": 12, "n_high_confidence_claims_total": 60,
        "n_non_orthogonal_tensions": 12,
        "receipts": [
            {"outcome_class": ["muscle_function", "cardiometabolic",
                               "longevity"][i % 3],
             "evidence_tier": "A1", "directness": "review",
             "receipt_id": f"P{i}"}
            for i in range(12)
        ],
    }
    gaps, targets = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("Direct-evidence" in g for g in gaps)
    assert any("RCT" in t or "trial" in t.lower() for t in targets)


def test_a_tier_gap_when_corpus_leans_b_c():
    manifest = {
        "n_receipts": 12, "n_high_confidence_claims_total": 60,
        "n_non_orthogonal_tensions": 12,
        "receipts": [
            {"outcome_class": ["muscle_function", "cardiometabolic",
                               "longevity"][i % 3],
             "evidence_tier": "B1", "directness": "direct",
             "receipt_id": f"P{i}"}
            for i in range(12)
        ],
    }
    gaps, _ = compute_corpus_gaps(
        manifest, min_receipts=10, min_claims=50, min_tensions=10,
    )
    assert any("A-tier" in g and "0/" in g for g in gaps)


def test_single_paper_dominance_flag():
    manifest = {
        "n_receipts": 5, "n_high_confidence_claims_total": 60,
        "n_non_orthogonal_tensions": 12,
        "receipts": [
            # 3 receipts share the same paper_id (60% > 40% threshold)
            {"outcome_class": "longevity", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": "Big_2024"},
            {"outcome_class": "longevity", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": "Big_2024"},
            {"outcome_class": "longevity", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": "Big_2024"},
            {"outcome_class": "muscle_function", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": "Other_2024"},
            {"outcome_class": "cardiometabolic", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": "Third_2024"},
        ],
    }
    gaps, _ = compute_corpus_gaps(
        manifest, min_receipts=4, min_claims=50, min_tensions=10,
    )
    assert any("Single-paper dominance" in g and "Big_2024" in g
               for g in gaps)


# ---------- formatter ------------------------------------------------

def test_format_expansion_section_pairs_gap_with_action():
    gaps = ("Receipts: 3/10 (short by 7)",)
    targets = ("Add ≥7 more topic-fit receipts...",)
    md = format_expansion_section(gaps, targets)
    assert "## Corpus Expansion To-Do" in md
    assert "Gap:" in md
    assert "Action:" in md
    assert "3/10" in md


def test_format_expansion_section_empty_when_no_gaps():
    assert format_expansion_section((), ()) == ""


def test_format_expansion_section_handles_unequal_lengths():
    """Defensive: gap without paired action still renders."""
    md = format_expansion_section(("Gap A", "Gap B"), ("Action A",))
    assert "Gap A" in md and "Gap B" in md
    assert "Action A" in md
