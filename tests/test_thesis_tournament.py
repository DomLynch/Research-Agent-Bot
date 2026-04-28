"""Tests for agent/thesis_tournament.py — 6-dim deterministic scorer.

Property-style tests for each dimension in isolation, plus integration
tests where multiple dimensions interact and one must dominate per the
documented priority order (directness > tier > confidence > replication
> recency > specificity > claim_id).
"""
from __future__ import annotations

import pytest

from agent.schemas import Claim
from agent.thesis_tournament import (
    ThesisTournamentError,
    pick_thesis,
    score_all,
    score_claim,
)
from agent.types import EvidenceItem, Source


def _claim(
    cid: str = "C001",
    *,
    text: str = "metformin reduced X.",
    refs: tuple[int, ...] = (1,),
    directness: str = "direct",
    tier: str = "A1",
    confidence: str = "high",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier=tier,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        attack_surface=(),
    )


def _item(ref: int, *, year: int | None = 2024) -> EvidenceItem:
    return EvidenceItem(
        source=Source(ref=ref, title="", year=year, url="", source="pubmed"),
        abstract="", design="rct",  # type: ignore[arg-type]
        role="published_results", tier="A1", direct=True, strict=True,
    )


# --- Per-dimension scoring -----------------------------------------------


def test_directness_rank_orders_direct_indirect_mechanistic() -> None:
    direct = score_claim(_claim(directness="direct"))
    indirect = score_claim(_claim(directness="indirect"))
    mech = score_claim(_claim(directness="mechanistic"))
    assert direct.directness == 0
    assert indirect.directness == 1
    assert mech.directness == 2


def test_tier_rank_orders_a1_a2_b_c_mixed() -> None:
    ranks = [score_claim(_claim(tier=t)).tier for t in ("A1", "A2", "B", "C", "mixed")]
    assert ranks == [0, 1, 2, 3, 4]


def test_confidence_rank_orders_high_moderate_low() -> None:
    ranks = [score_claim(_claim(confidence=c)).confidence for c in ("high", "moderate", "low")]
    assert ranks == [0, 1, 2]


def test_replication_rank_negative_count_of_refs() -> None:
    """More supporting refs → smaller (better) rank."""
    one = score_claim(_claim(refs=(1,)))
    three = score_claim(_claim(refs=(1, 2, 3)))
    five = score_claim(_claim(refs=(1, 2, 3, 4, 5)))
    assert one.replication == -1
    assert three.replication == -3
    assert five.replication == -5
    # Verify ordering — five is best, one is worst on this dim
    assert five.replication < three.replication < one.replication


def test_recency_rank_zero_when_items_by_ref_is_none() -> None:
    """No items → recency dim contributes 0, defers to other dims."""
    assert score_claim(_claim()).recency == 0


def test_recency_rank_zero_when_no_year_on_supporting_items() -> None:
    items = {1: _item(1, year=None)}
    assert score_claim(_claim(refs=(1,)), items).recency == 0


def test_recency_rank_baseline_minus_latest_year() -> None:
    """`baseline (2026) - latest_year`. Newer = smaller rank."""
    items = {
        1: _item(1, year=2024),
        2: _item(2, year=2018),
    }
    # Claim refs both; latest is 2024 → rank = 2026 - 2024 = 2
    score = score_claim(_claim(refs=(1, 2)), items)
    assert score.recency == 2


def test_recency_rank_caps_at_zero_for_far_future() -> None:
    """A paper dated 2030 (data error or future preprint) doesn't get a
    negative rank — capped at 0 so it doesn't unfairly beat 2026 papers."""
    items = {1: _item(1, year=2030)}
    assert score_claim(_claim(refs=(1,)), items).recency == 0


def test_specificity_rank_longer_text_is_better() -> None:
    short = score_claim(_claim(text="metformin worked."))
    long = score_claim(_claim(
        text=" ".join(["very"] * 30) + " metformin reduced X by 5% in older adults.",
    ))
    assert short.specificity == -2
    assert long.specificity < short.specificity  # long is better


def test_specificity_rank_caps_at_word_count_50() -> None:
    """Run-on sentences past 50 words don't keep gaining rank."""
    text = "word " * 100
    score = score_claim(_claim(text=text))
    assert score.specificity == -50  # capped


# --- Tournament priority ordering ----------------------------------------


def test_pick_thesis_directness_dominates_over_tier() -> None:
    """A direct + A2 claim beats an indirect + A1 claim."""
    direct_a2 = _claim(cid="C001", directness="direct", tier="A2")
    indirect_a1 = _claim(cid="C002", directness="indirect", tier="A1")
    assert pick_thesis([direct_a2, indirect_a1]) == "C001"


def test_pick_thesis_tier_dominates_over_confidence() -> None:
    """Within direct claims, A1 + moderate beats A2 + high."""
    a1_mod = _claim(cid="C001", tier="A1", confidence="moderate")
    a2_high = _claim(cid="C002", tier="A2", confidence="high")
    assert pick_thesis([a1_mod, a2_high]) == "C001"


def test_pick_thesis_confidence_dominates_over_replication() -> None:
    """Same direct + A1 — high + 1 ref beats moderate + 5 refs."""
    high_one_ref = _claim(cid="C001", confidence="high", refs=(1,))
    mod_many_refs = _claim(cid="C002", confidence="moderate", refs=(1, 2, 3, 4, 5))
    assert pick_thesis([high_one_ref, mod_many_refs]) == "C001"


def test_pick_thesis_replication_dominates_over_recency() -> None:
    """Same first-3 dims — 3 refs (older) beats 1 ref (newer)."""
    items = {
        1: _item(1, year=2018),
        2: _item(2, year=2018),
        3: _item(3, year=2018),
        9: _item(9, year=2025),
    }
    three_refs_old = _claim(cid="C001", refs=(1, 2, 3))
    one_ref_new = _claim(cid="C002", refs=(9,))
    assert pick_thesis([three_refs_old, one_ref_new], items_by_ref=items) == "C001"


def test_pick_thesis_recency_dominates_over_specificity() -> None:
    """Same first-4 dims — newer + short beats older + long claim text."""
    items = {1: _item(1, year=2025), 2: _item(2, year=2010)}
    new_short = _claim(cid="C001", text="X.", refs=(1,))
    old_long = _claim(
        cid="C002",
        text=" ".join(["word"] * 40),
        refs=(2,),
    )
    assert pick_thesis([new_short, old_long], items_by_ref=items) == "C001"


def test_pick_thesis_specificity_dominates_over_claim_id() -> None:
    """All five prior dims tied → longer claim text wins over claim_id."""
    items = {1: _item(1, year=2024), 2: _item(2, year=2024)}
    short = _claim(cid="C001", text="X reduced.", refs=(1,))
    long = _claim(
        cid="C002",
        text=" ".join(["word"] * 20),
        refs=(2,),
    )
    # C002 has more specificity → wins despite higher claim_id
    assert pick_thesis([short, long], items_by_ref=items) == "C002"


def test_pick_thesis_breaks_complete_ties_lexically_by_claim_id() -> None:
    """Two identical claims modulo claim_id → lower id wins."""
    a = _claim(cid="C001")
    b = _claim(cid="C002")
    assert pick_thesis([a, b]) == "C001"
    # Order-independent
    assert pick_thesis([b, a]) == "C001"


# --- Edge cases ----------------------------------------------------------


def test_pick_thesis_empty_raises() -> None:
    with pytest.raises(ThesisTournamentError, match="empty claim list"):
        pick_thesis([])


def test_pick_thesis_single_claim_returns_it() -> None:
    assert pick_thesis([_claim(cid="C042")]) == "C042"


def test_score_all_preserves_input_order() -> None:
    """SPAR (Day 4.2) expects index alignment with input claims."""
    claims = [_claim(cid=f"C{i:03d}") for i in range(1, 6)]
    scores = score_all(claims)
    assert [s.claim_id for s in scores] == [c.claim_id for c in claims]


def test_score_claim_unknown_directness_falls_back_to_high_rank() -> None:
    """Defensive: an unknown directness value (shouldn't happen with
    the Literal type but let's prove the fallback) gets rank 9, putting
    it at the bottom of any sort."""
    # Bypass the type system to inject an invalid value
    bad_claim = _claim(directness="unknown")  # type: ignore[arg-type]
    score = score_claim(bad_claim)
    assert score.directness == 9


def test_score_tuple_has_seven_elements_six_dims_plus_id() -> None:
    """Wire-shape sanity: the sort tuple is six ranks then claim_id."""
    score = score_claim(_claim())
    assert len(score.sort_tuple) == 7
    # claim_id is the last element (deterministic tiebreaker)
    assert score.sort_tuple[-1] == score.claim_id
