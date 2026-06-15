"""Tests for the Phase 7 deterministic tension-selection + planning primitive."""
from __future__ import annotations

import pytest

from agent.tension_elaboration import (
    DEFAULT_HYPOTHESES,
    DEFAULT_TOP_N,
    HYPOTHESIS_REGISTRY,
    TensionPlan,
    TensionRecord,
    build_plan,
    select_top_tensions,
)


def _record(
    tid: str = "t",
    paper_a: str = "PA",
    paper_b: str = "PB",
    severity: int = 3,
    weight_a: float = 1.0,
    weight_b: float = 1.0,
    conflict_type: str = "disagreement",
    outcome_class: str = "cardiometabolic",
    **kwargs,
) -> TensionRecord:
    return TensionRecord(
        tension_id=tid, paper_a=paper_a, paper_b=paper_b,
        conflict_type=conflict_type, outcome_class=outcome_class,
        severity=severity, weight_a=weight_a, weight_b=weight_b, **kwargs,
    )


# ---- TensionRecord validation ---------------------------------------------


def test_valid_record_constructs() -> None:
    r = _record()
    assert r.tension_id == "t"
    assert r.total_weight == 2.0


@pytest.mark.parametrize("bad", [0, 6, -1, 100])
def test_severity_out_of_range_rejected(bad) -> None:
    with pytest.raises(ValueError, match="severity"):
        _record(severity=bad)


def test_severity_must_be_int_not_float() -> None:
    with pytest.raises(ValueError, match="severity"):
        _record(severity=3.5)  # type: ignore[arg-type]


def test_identical_papers_rejected() -> None:
    with pytest.raises(ValueError, match="must differ"):
        _record(paper_a="X", paper_b="X")


def test_empty_paper_id_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _record(paper_a="")


def test_empty_tension_id_rejected() -> None:
    with pytest.raises(ValueError, match="tension_id"):
        _record(tid="")


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _record(weight_a=-0.5)


def test_invalid_directness_rejected() -> None:
    with pytest.raises(ValueError, match="invalid directness_a"):
        _record(directness_a="bogus")


# ---- Selection ranking ----------------------------------------------------


def test_empty_records_returns_empty() -> None:
    assert select_top_tensions([]) == []


def test_severity_drives_primary_ranking() -> None:
    records = [
        _record("t1", severity=2, paper_a="a1", paper_b="b1"),
        _record("t2", severity=5, paper_a="a2", paper_b="b2"),
        _record("t3", severity=4, paper_a="a3", paper_b="b3"),
        _record("t4", severity=3, paper_a="a4", paper_b="b4"),
    ]
    plans = select_top_tensions(records, top_n=3)
    assert [p.tension_id for p in plans] == ["t2", "t3", "t4"]


def test_weight_breaks_severity_tie() -> None:
    records = [
        _record("low", severity=4, weight_a=1.0, weight_b=1.0, paper_a="a1", paper_b="b1"),
        _record("hi", severity=4, weight_a=3.0, weight_b=2.0, paper_a="a2", paper_b="b2"),
        _record("mid", severity=4, weight_a=2.0, weight_b=2.0, paper_a="a3", paper_b="b3"),
    ]
    plans = select_top_tensions(records, top_n=3)
    assert [p.tension_id for p in plans] == ["hi", "mid", "low"]


def test_directness_breaks_weight_tie() -> None:
    records = [
        _record("indirect", severity=4, weight_a=1.0, weight_b=1.0,
                directness_a="indirect", directness_b="indirect",
                paper_a="a1", paper_b="b1"),
        _record("direct", severity=4, weight_a=1.0, weight_b=1.0,
                directness_a="direct", directness_b="direct",
                paper_a="a2", paper_b="b2"),
    ]
    plans = select_top_tensions(records, top_n=2)
    assert [p.tension_id for p in plans] == ["direct", "indirect"]


def test_tension_id_lexicographic_final_tie_break() -> None:
    records = [
        _record("zzz", severity=3, paper_a="a1", paper_b="b1"),
        _record("aaa", severity=3, paper_a="a2", paper_b="b2"),
        _record("mmm", severity=3, paper_a="a3", paper_b="b3"),
    ]
    plans = select_top_tensions(records, top_n=3)
    assert [p.tension_id for p in plans] == ["aaa", "mmm", "zzz"]


def test_top_n_caps_returned_count() -> None:
    records = [
        _record(f"t{i}", severity=3, paper_a=f"a{i}", paper_b=f"b{i}")
        for i in range(10)
    ]
    plans = select_top_tensions(records, top_n=5)
    assert len(plans) == 5
    assert DEFAULT_TOP_N == 5


def test_fewer_than_top_n_returns_all() -> None:
    records = [_record("t1", severity=3)]
    plans = select_top_tensions(records, top_n=5)
    assert len(plans) == 1


def test_top_n_zero_or_negative_rejected() -> None:
    with pytest.raises(ValueError, match="top_n"):
        select_top_tensions([], top_n=0)
    with pytest.raises(ValueError, match="top_n"):
        select_top_tensions([], top_n=-1)


def test_duplicate_tension_id_rejected() -> None:
    records = [
        _record("dup", paper_a="A", paper_b="B"),
        _record("dup", paper_a="C", paper_b="D"),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        select_top_tensions(records)


# ---- Single-anchor cap (#5 — one outlier must not spawn N tensions) -------


def test_single_outlier_capped_to_one_plan() -> None:
    """An outlier paper that conflicts with every other receipt produces
    C(N,1) identically-ranked pairs; the cap keeps only one of them."""
    records = [
        _record(f"O-{x}", paper_a="OUTLIER", paper_b=x, severity=4)
        for x in ("A", "B", "C", "D", "E")
    ]
    plans = select_top_tensions(records, top_n=5)
    outlier_plans = [p for p in plans if "OUTLIER" in (p.paper_a, p.paper_b)]
    assert len(outlier_plans) == 1  # default cap = 1


def test_distinct_second_anchor_tension_survives_the_cap() -> None:
    """The cap diversifies, it does not gut: a genuinely distinct tension
    between two OTHER papers still surfaces alongside the outlier's one."""
    records = [
        _record("o1", paper_a="OUTLIER", paper_b="A", severity=5),
        _record("o2", paper_a="OUTLIER", paper_b="B", severity=5),
        _record("o3", paper_a="OUTLIER", paper_b="C", severity=5),
        _record("distinct", paper_a="X", paper_b="Y", severity=4),
    ]
    plans = select_top_tensions(records, top_n=5)
    ids = {p.tension_id for p in plans}
    assert "distinct" in ids
    assert len([p for p in plans if "OUTLIER" in (p.paper_a, p.paper_b)]) == 1


def test_cap_can_be_disabled_with_zero() -> None:
    records = [
        _record(f"O-{x}", paper_a="OUTLIER", paper_b=x, severity=4)
        for x in ("A", "B", "C")
    ]
    plans = select_top_tensions(records, top_n=5, max_per_anchor=0)
    assert len(plans) == 3  # cap off → all kept


# ---- Plan construction ----------------------------------------------------


def test_hypotheses_match_registry_for_known_conflict_type() -> None:
    plan = build_plan(_record(conflict_type="null_vs_positive"))
    assert plan.hypotheses == HYPOTHESIS_REGISTRY["null_vs_positive"]


def test_unknown_conflict_type_falls_back_to_default() -> None:
    plan = build_plan(_record(conflict_type="some_novel_conflict"))
    assert plan.hypotheses == DEFAULT_HYPOTHESES


def test_null_vs_negative_has_its_own_registry_hypotheses() -> None:
    """#5: null_vs_negative must be in the registry — not silently degrade
    to DEFAULT_HYPOTHESES the way an unmapped key would."""
    plan = build_plan(_record(conflict_type="null_vs_negative"))
    assert plan.hypotheses == HYPOTHESIS_REGISTRY["null_vs_negative"]
    assert plan.hypotheses != DEFAULT_HYPOTHESES


def test_corpus_weight_winner_paper_a() -> None:
    plan = build_plan(_record(weight_a=5.0, weight_b=2.0))
    assert plan.corpus_weight_winner == "PA"


def test_corpus_weight_winner_paper_b() -> None:
    plan = build_plan(_record(weight_a=2.0, weight_b=5.0))
    assert plan.corpus_weight_winner == "PB"


def test_corpus_weight_winner_tie() -> None:
    plan = build_plan(_record(weight_a=2.0, weight_b=2.0))
    assert plan.corpus_weight_winner == "tie"


def test_numeric_anchors_combined_in_order() -> None:
    r = _record(
        numeric_anchors_a=("p<0.05", "n=80"),
        numeric_anchors_b=("HbA1c=7.0",),
    )
    plan = build_plan(r)
    assert plan.numeric_anchors == ("p<0.05", "n=80", "HbA1c=7.0")


def test_plan_carries_severity_and_outcome_class() -> None:
    plan = build_plan(_record(severity=4, outcome_class="immune"))
    assert plan.severity == 4
    assert plan.outcome_class == "immune"


def test_invalid_corpus_weight_winner_rejected() -> None:
    with pytest.raises(ValueError, match="corpus_weight_winner"):
        TensionPlan(
            tension_id="t", paper_a="A", paper_b="B",
            conflict_type="x", outcome_class="y", severity=3,
            numeric_anchors=(), hypotheses=("h1", "h2"),
            corpus_weight_winner="not_a_valid_value",
        )


def test_hypotheses_must_be_two_tuple() -> None:
    with pytest.raises(ValueError, match="2-tuple"):
        TensionPlan(
            tension_id="t", paper_a="A", paper_b="B",
            conflict_type="x", outcome_class="y", severity=3,
            numeric_anchors=(),
            hypotheses=("only_one",),  # type: ignore[arg-type]
            corpus_weight_winner="A",
        )


def test_registry_has_expected_conflict_types() -> None:
    """Sanity: every conflict_type the corpus is likely to surface is keyed."""
    expected = {
        "null_vs_positive", "disagreement", "preclinical_vs_clinical",
        "positive_vs_unclear", "null_vs_unclear",
    }
    assert expected.issubset(set(HYPOTHESIS_REGISTRY))
