"""Tests for agent/topic_maturity.py — L0-L5 ladder + Journal-Ready
(Wave 7 Evidence Factory slice 3).

Pure-function tests. Universal across topics — every assertion uses
manifest-shaped dicts with no drug names.
"""
from __future__ import annotations

from agent.topic_maturity import (
    compute_maturity_level,
    format_maturity_label,
    format_maturity_description,
    is_journal_ready,
)


# ---------- L0–L2: corpus thinness gates ----------------------------

def test_l0_when_no_receipts():
    m = {"n_receipts": 0, "n_high_confidence_claims_total": 0,
         "n_non_orthogonal_tensions": 0}
    assert compute_maturity_level(m, verdict="SHIP-BLOCKED") == 0


def test_l1_when_receipts_but_no_claims():
    m = {"n_receipts": 5, "n_high_confidence_claims_total": 0,
         "n_non_orthogonal_tensions": 0}
    assert compute_maturity_level(m, verdict="SHIP-BLOCKED") == 1


def test_l2_when_below_cert_floor():
    m = {"n_receipts": 5, "n_high_confidence_claims_total": 12,
         "n_non_orthogonal_tensions": 1}
    assert compute_maturity_level(m, verdict="Trust-Spine Pass") == 2


# ---------- L3: floor met but audit blocks ---------------------------

def test_l3_when_floor_met_but_verdict_below_aaa():
    """Substance is there but the audit found issues — clearly L3,
    not L2 (L2 is corpus-thinness)."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    # Trust-Spine Pass even with floor met means audits had P2s
    assert compute_maturity_level(
        m, verdict="Trust-Spine Pass",
    ) == 3


def test_l3_when_grok_unresolved_blocks_aaa():
    """Stage1+2 clean + floor met but Grok flagged a P1 → L3."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    assert compute_maturity_level(
        m,
        verdict="Trust-Spine Pass — Agent Review Unresolved",
        grok_unresolved_p1=2,
    ) == 3


# ---------- L4 vs L5: AAA vs Journal-Ready ---------------------------

def test_l4_when_aaa_with_auto_strip_surgery():
    """AAA achieved but auto-strip had to remove sentences → L4
    (not L5). The pipeline cleared the gates but only after surgery
    that a journal reviewer might catch as 'lost claims'."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    assert compute_maturity_level(
        m, verdict="AAA", grok_unresolved_p1=0, auto_stripped_count=3,
    ) == 4


def test_l5_when_aaa_clean_no_surgery():
    """AAA + zero unresolved Grok + zero auto-strip → Journal-Ready."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    assert compute_maturity_level(
        m, verdict="AAA", grok_unresolved_p1=0, auto_stripped_count=0,
    ) == 5


def test_l4_when_journal_surface_gate_fails():
    """Analytical AAA with visible manuscript residue is L4, not L5."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    assert compute_maturity_level(
        m, verdict="AAA", grok_unresolved_p1=0, auto_stripped_count=0,
        journal_surface_pass=False,
    ) == 4


def test_l5_unreachable_when_grok_unresolved_even_at_aaa():
    """Defensive: an AAA verdict with grok_unresolved>0 should NOT
    happen (verdict logic downgrades it). But if the inputs say so,
    L5 is gated correctly."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    assert compute_maturity_level(
        m, verdict="AAA", grok_unresolved_p1=1, auto_stripped_count=0,
    ) == 4  # AAA path but degraded by grok flag


# ---------- cert-floor override --------------------------------------

def test_topic_pack_can_raise_floor_changing_l3_to_l2():
    """A pack with strict floors (e.g. min_receipts=20) drops a
    15-receipt corpus from L3 to L2 — same global-policy semantics
    as the verdict cert floor."""
    m = {"n_receipts": 15, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    # Default floors: 15/60/12 meets all → L3
    assert compute_maturity_level(m, verdict="Trust-Spine Pass") == 3
    # Strict floors: 20/100/15 → 15 receipts is short → L2
    assert compute_maturity_level(
        m, verdict="Trust-Spine Pass",
        cert_floors={"min_receipts": 20,
                     "min_high_conf_claims": 100,
                     "min_non_orthogonal_tensions": 15},
    ) == 2


def test_topic_pack_cannot_lower_below_default():
    """Pack saying min_receipts=2 is ignored — default 10 still
    applies. Mirrors run_v06_synthesis._compute_unified_verdict."""
    m = {"n_receipts": 5, "n_high_confidence_claims_total": 60,
         "n_non_orthogonal_tensions": 12}
    # Pack-tries-to-lower but max() pins to default → 5 still below 10 → L2
    assert compute_maturity_level(
        m, verdict="Trust-Spine Pass",
        cert_floors={"min_receipts": 2},
    ) == 2


# ---------- formatters / Journal-Ready gate --------------------------

def test_label_formatting_for_each_level():
    for lvl, expected in [
        (0, "L0 — UNSEEDED"), (1, "L1 — SEEDED"), (2, "L2 — PARTIAL"),
        (3, "L3 — FLOOR-MET"), (4, "L4 — ANALYTICALLY CERTIFIED"),
        (5, "L5 — JOURNAL-READY"),
    ]:
        assert format_maturity_label(lvl) == expected


def test_unknown_level_label_falls_back():
    """Defensive: unknown level still returns a sensible label."""
    out = format_maturity_label(99)
    assert "L99" in out
    assert "UNKNOWN" in out


def test_description_explains_each_level():
    for lvl in range(6):
        desc = format_maturity_description(lvl)
        assert isinstance(desc, str) and len(desc) > 20


def test_is_journal_ready_only_at_l5():
    for lvl in range(5):
        assert is_journal_ready(lvl) is False
    assert is_journal_ready(5) is True
