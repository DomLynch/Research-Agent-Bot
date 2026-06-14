"""Recursive rubric-tree primitive for layered evidence / quality appraisal.

Stdlib-only, no external deps, no LLM. Re-implemented (NOT copied) from the
rubric-tree idea in OSU-NLP-Group/QUEST (MIT) — generalized to a
dependency-free dataclass that fits our appraisal layer.

WHY: our current appraisal is FLAT. `agent/risk_of_bias_schema.StudyAssessment`
carries a separate `overall_rating` that is not derived from its domains, so
nothing enforces RoB-2's actual rule ("overall = the worst domain") or lets a
single critical sub-item fail its parent. A tree models that explicitly:

  - PARALLEL  aggregation = independent children -> mean score.
  - SEQUENTIAL aggregation = chained children -> weakest link (min score),
    which is exactly the RoB-2 "worst-domain-wins" rule.
  - `critical=True` on a child whose status is "failed" forces the parent to
    fail (score 0) regardless of strategy.

This module imports nothing from the rest of the codebase and nothing in the
live pipeline imports it yet — it is a ready-to-adopt primitive with zero
blast radius. Adopt incrementally (e.g. give StudyAssessment a
`.as_rubric_tree()` view) in a separate, reviewed change.

Hard rule, same as the rest of the appraisal layer: CODE DISPOSES. Scores and
statuses are computed deterministically; no model is consulted here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

__all__ = [
    "PASS_THRESHOLD",
    "AggregationStrategy",
    "NodeStatus",
    "VerificationNode",
    "leaf",
    "aggregate",
]

# score >= PASS_THRESHOLD -> "passed"; score <= 0 -> "failed"; between -> "partial".
PASS_THRESHOLD: float = 0.8


class AggregationStrategy(str, Enum):
    PARALLEL = "parallel"      # independent children -> mean
    SEQUENTIAL = "sequential"  # chained children -> weakest link (min)


NodeStatus = Literal["passed", "failed", "partial", "skipped", "initialized"]


def status_for(score: float) -> NodeStatus:
    """Deterministic status from a [0,1] score."""
    if score <= 0.0:
        return "failed"
    if score >= PASS_THRESHOLD:
        return "passed"
    return "partial"


def _assert_status_consistent(status: str, score: float) -> None:
    # "initialized"/"skipped" carry no score meaning, so they are unconstrained.
    if status in ("initialized", "skipped"):
        return
    expected = status_for(score)
    if status != expected:
        raise ValueError(
            f"status {status!r} inconsistent with score {score!r} "
            f"(expected {expected!r})"
        )


@dataclass
class VerificationNode:
    """One node in a rubric tree. A leaf has no children; an internal node
    aggregates its children per `strategy`, with critical-failure propagation.

    Validation at construction: id non-empty; score in [0,1]; status (when not
    'initialized'/'skipped') consistent with score. `compute()` is pure — it
    returns a NEW computed tree and never mutates the original.
    """

    id: str
    desc: str = ""
    critical: bool = False
    score: float = 0.0
    status: NodeStatus = "initialized"
    strategy: AggregationStrategy = AggregationStrategy.PARALLEL
    children: list["VerificationNode"] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("node id must be a non-empty string")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError(
                f"score {self.score!r} out of range [0,1] for node {self.id!r}"
            )
        _assert_status_consistent(self.status, float(self.score))

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def add_child(self, node: "VerificationNode") -> None:
        self.children.append(node)

    def compute(self) -> "VerificationNode":
        """Return a NEW node with score+status aggregated bottom-up. Pure."""
        if self.is_leaf:
            return self
        kids = [c.compute() for c in self.children]
        if any(c.critical and c.status == "failed" for c in kids):
            score = 0.0
        else:
            scored = [c.score for c in kids if c.status != "skipped"]
            if not scored:
                score = 0.0
            elif self.strategy is AggregationStrategy.SEQUENTIAL:
                score = min(scored)
            else:
                score = sum(scored) / len(scored)
        score = round(float(score), 6)
        return VerificationNode(
            id=self.id, desc=self.desc, critical=self.critical,
            score=score, status=status_for(score),
            strategy=self.strategy, children=kids,
        )


def leaf(
    id: str, score: float, *, desc: str = "", critical: bool = False,
) -> VerificationNode:
    """Build a leaf node with status derived from its score."""
    return VerificationNode(
        id=id, desc=desc, critical=critical, score=float(score),
        status=status_for(float(score)),
    )


def aggregate(
    id: str,
    children: list[VerificationNode],
    *,
    desc: str = "",
    strategy: AggregationStrategy = AggregationStrategy.PARALLEL,
    critical: bool = False,
) -> VerificationNode:
    """Build an internal node over `children` and return it COMPUTED."""
    node = VerificationNode(
        id=id, desc=desc, critical=critical, strategy=strategy,
        children=list(children),
    )
    return node.compute()
