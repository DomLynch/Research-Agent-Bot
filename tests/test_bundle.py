"""Tests for bundle.py — deterministic role / tier / direct / strict classifier.

Two layers:
  1. Truth-table cases: synthetic minimal inputs probing one rule at a time.
  2. Snapshot tests: full pipeline against real captured fixtures, capturing
     the classifier's role+tier+direct distributions per topic. If the
     classifier rules change, these snapshots flag it for review.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from agent.bundle import bundle
from agent.retrieve import normalize_and_dedup
from agent.types import EvidenceItem, RawHit, Source

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOPICS = ["rapamycin", "metformin", "senolytics", "semaglutide_weight", "vitamin_d_mortality"]


def _src(ref: int = 1, *, source: str = "pubmed", venue: str | None = None, year: int = 2024) -> Source:
    return Source(
        ref=ref,
        title=f"Source {ref}",
        year=year,
        url="",
        source=source,
        doi=f"10.1/{ref}",
        venue=venue,
    )


def _bundle_one(
    *,
    source: str = "pubmed",
    abstract: str = "",
    title: str = "Trial of X",
    venue: str | None = None,
    year: int = 2024,
    domain: str = "aging older adults",
    raw: dict | None = None,
    min_year: int | None = None,
) -> EvidenceItem:
    src = Source(ref=1, title=title, year=year, url="", source=source, venue=venue)
    return bundle(
        [src],
        {1: abstract},
        domain=domain,
        criteria_min_year=min_year,
        raw_signals={1: raw or {}},
    )[0]


# --- Step 1: role classification (truth table) -----------------------------


def test_role_clinicaltrials_with_results_is_published_results():
    item = _bundle_one(source="clinicaltrials", abstract="trial.", raw={"has_results": True})
    assert item.role == "published_results"


def test_role_clinicaltrials_without_results_is_registered_pending():
    item = _bundle_one(source="clinicaltrials", abstract="trial.", raw={"has_results": False})
    assert item.role == "registered_pending"


def test_role_review_marker_in_title_wins():
    item = _bundle_one(title="Systematic review of X", abstract="abstract.")
    assert item.role == "review"


def test_role_meta_analysis_marker_classifies_as_review():
    item = _bundle_one(abstract="We performed a meta-analysis of 12 RCTs.")
    assert item.role == "review"


def test_role_protocol_marker_no_outcome_is_published_protocol():
    item = _bundle_one(abstract="This is a study protocol for an upcoming randomized trial.")
    assert item.role == "published_protocol"


def test_role_reported_outcome_is_published_results():
    item = _bundle_one(abstract="The intervention reduced mortality by 22% (HR 0.78, 95% CI 0.65-0.93, p=0.01).")
    assert item.role == "published_results"


def test_role_mechanistic_default_when_no_signals():
    item = _bundle_one(abstract="We studied molecular mechanism in cell culture.")
    assert item.role == "mechanistic"


# --- Step 2: design classification -----------------------------------------


def test_design_rct_when_randomized_with_outcome():
    item = _bundle_one(
        abstract="In this randomized double-blind trial, mortality was reduced by 22% (p=0.01)."
    )
    assert item.role == "published_results"
    assert item.design == "rct"


def test_design_observational_when_no_randomization_marker():
    item = _bundle_one(
        abstract="Cohort followed for 10 years; mortality reduced by 18% (HR 0.82, p=0.02)."
    )
    assert item.role == "published_results"
    assert item.design == "observational"


def test_design_meta_analysis_for_review_with_marker():
    item = _bundle_one(abstract="We performed a meta-analysis of 12 trials.")
    assert item.design == "meta_analysis"


# --- Step 3: tier ----------------------------------------------------------


def test_tier_a1_for_rct_in_high_impact_venue():
    item = _bundle_one(
        venue="The Lancet",
        abstract="Randomized double-blind trial; mortality reduced 22% (p=0.01).",
    )
    assert item.tier == "A1"


def test_tier_a2_for_rct_in_other_venue():
    item = _bundle_one(
        venue="Geriatric Medicine",
        abstract="Randomized double-blind trial; mortality reduced 22% (p=0.01).",
    )
    assert item.tier == "A2"


def test_tier_b_for_protocol():
    item = _bundle_one(abstract="This is a study protocol for an upcoming trial.")
    assert item.tier == "B"


def test_tier_c_for_mechanistic():
    item = _bundle_one(abstract="We studied molecular mechanism in cell culture.")
    assert item.tier == "C"


# --- Step 4: directness ----------------------------------------------------


def test_direct_false_for_animal_study_in_human_domain():
    item = _bundle_one(
        domain="aging human older adults",
        abstract="We treated transgenic mice with the compound; mortality reduced by 22% (p=0.01).",
    )
    assert item.direct is False


def test_direct_true_for_human_study_in_human_domain():
    item = _bundle_one(
        domain="aging human older adults",
        abstract="We randomized 200 adult patients; mortality reduced by 22% (p=0.01).",
    )
    assert item.direct is True


def test_direct_false_for_pediatric_in_adult_domain():
    item = _bundle_one(
        domain="adult older",
        abstract="We followed 300 children for 5 years; mortality reduced 12% (p=0.04).",
    )
    assert item.direct is False


# --- Step 5: strict eligibility (year filter) ------------------------------


def test_strict_false_when_year_below_min():
    item = _bundle_one(
        year=2010,
        min_year=2015,
        abstract="Randomized trial; mortality reduced 22% (p=0.01).",
    )
    assert item.strict is False


def test_strict_true_when_year_above_min():
    item = _bundle_one(
        year=2024,
        min_year=2015,
        abstract="Randomized trial; mortality reduced 22% (p=0.01).",
    )
    assert item.strict is True


def test_strict_false_when_directness_fails():
    item = _bundle_one(
        domain="aging human older adults",
        abstract="Mice; mortality reduced 22% (p=0.01).",
    )
    assert item.direct is False
    assert item.strict is False


# --- Snapshot tests: full pipeline against real fixtures -------------------


def _load_topic(slug: str) -> list[RawHit]:
    hits: list[RawHit] = []
    for path in sorted((FIXTURES / slug).glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    return hits


@pytest.mark.parametrize("topic", TOPICS)
def test_bundle_snapshot_per_topic(topic: str, snapshot):
    """Per-topic bundle classification distributions are captured as snapshots.

    A change to the classifier rules will surface here as a diff. Refresh with
    UPDATE_SNAPSHOTS=1 only after reviewing whether the new distribution is
    intentional and improves accuracy.
    """
    hits = _load_topic(topic)
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    items = bundle(
        sources,
        abstracts,
        domain="aging older adults human",
        raw_signals=raw_signals,
    )
    summary = {
        "raw_hits": len(hits),
        "unique_sources": len(sources),
        "role_counts": dict(Counter(it.role for it in items)),
        "design_counts": dict(Counter(it.design for it in items)),
        "tier_counts": dict(Counter(it.tier for it in items)),
        "direct_count": sum(1 for it in items if it.direct),
        "strict_count": sum(1 for it in items if it.strict),
    }
    snapshot(summary)
