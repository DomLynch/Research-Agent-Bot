"""Tests for the recursive rubric-tree primitive (agent/rubric_tree.py).

Covers the contract (status<->score, range validation, purity) and the two
aggregation strategies + critical-failure propagation, including the realistic
RoB-2 'overall = worst domain' case that motivated the port.
"""
from __future__ import annotations

import pytest

from agent.rubric_tree import (
    AggregationStrategy,
    VerificationNode,
    aggregate,
    leaf,
    status_for,
)


def test_status_for_thresholds() -> None:
    assert status_for(0.0) == "failed"
    assert status_for(0.5) == "partial"
    assert status_for(0.8) == "passed"
    assert status_for(1.0) == "passed"


def test_leaf_derives_consistent_status() -> None:
    assert leaf("d", 1.0).status == "passed"
    assert leaf("d", 0.5).status == "partial"
    assert leaf("d", 0.0).status == "failed"


def test_score_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        VerificationNode(id="x", score=1.5)
    with pytest.raises(ValueError):
        VerificationNode(id="x", score=-0.1)


def test_empty_id_rejected() -> None:
    with pytest.raises(ValueError):
        VerificationNode(id="", score=0.0, status="failed")


def test_status_score_inconsistency_rejected() -> None:
    # claiming 'passed' with a 0.0 score must fail construction
    with pytest.raises(ValueError):
        VerificationNode(id="x", score=0.0, status="passed")


def test_parallel_is_mean() -> None:
    node = aggregate(
        "p", [leaf("a", 1.0), leaf("b", 0.0)],
        strategy=AggregationStrategy.PARALLEL,
    )
    assert node.score == 0.5
    assert node.status == "partial"


def test_sequential_is_weakest_link() -> None:
    node = aggregate(
        "p", [leaf("a", 1.0), leaf("b", 0.4), leaf("c", 0.9)],
        strategy=AggregationStrategy.SEQUENTIAL,
    )
    assert node.score == 0.4  # min, not mean
    assert node.status == "partial"


def test_rob2_worst_domain_wins() -> None:
    """The structural upgrade over the flat schema: one high-risk domain
    forces overall high risk (SEQUENTIAL = worst-domain). low/low/high -> fail."""
    ratings = {"randomization": 1.0, "deviations": 1.0, "outcome_measurement": 0.0}
    overall = aggregate(
        "study_overall",
        [leaf(dom, sc) for dom, sc in ratings.items()],
        strategy=AggregationStrategy.SEQUENTIAL,
    )
    assert overall.score == 0.0
    assert overall.status == "failed"  # i.e. overall = high risk of bias


def test_critical_failure_propagates_even_under_parallel() -> None:
    """A failed CRITICAL child zeroes the parent even when the mean would pass."""
    node = aggregate(
        "p",
        [leaf("a", 1.0), leaf("b", 1.0), leaf("crit", 0.0, critical=True)],
        strategy=AggregationStrategy.PARALLEL,
    )
    assert node.score == 0.0
    assert node.status == "failed"


def test_non_critical_failure_does_not_zero_parallel() -> None:
    node = aggregate(
        "p", [leaf("a", 1.0), leaf("b", 1.0), leaf("c", 0.0)],
        strategy=AggregationStrategy.PARALLEL,
    )
    assert node.score == pytest.approx(2 / 3)
    assert node.status == "partial"


def test_skipped_children_excluded_from_aggregation() -> None:
    skipped = VerificationNode(id="s", score=0.0, status="skipped")
    node = aggregate(
        "p", [leaf("a", 1.0), skipped], strategy=AggregationStrategy.PARALLEL,
    )
    assert node.score == 1.0  # skipped 's' not counted
    assert node.status == "passed"


def test_nested_three_levels_compute_bottom_up() -> None:
    inner = aggregate(
        "inner", [leaf("x", 0.6), leaf("y", 0.6)],
        strategy=AggregationStrategy.PARALLEL,
    )  # 0.6
    root = aggregate(
        "root", [inner, leaf("z", 1.0)],
        strategy=AggregationStrategy.PARALLEL,
    )
    assert root.score == pytest.approx(0.8)
    assert root.status == "passed"


def test_compute_is_pure() -> None:
    root = VerificationNode(
        id="root",
        children=[leaf("a", 1.0), leaf("b", 0.0)],
        strategy=AggregationStrategy.PARALLEL,
    )
    computed = root.compute()
    # original untouched (still initialized, score 0), new node carries result
    assert root.status == "initialized"
    assert root.score == 0.0
    assert computed.score == 0.5
    assert computed is not root
