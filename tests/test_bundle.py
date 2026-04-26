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
        title="RCT in older adults",
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
        title="Randomized trial in older adults",
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


# --- Topic relevance gate --------------------------------------------------


def test_off_topic_paper_marked_indirect():
    """Topic 'rapamycin' against an abstract that's about RTB101 only —
    even though it's human-clinical evidence, it doesn't mention rapamycin
    so it must NOT be marked direct."""
    src = Source(ref=1, title="RTB101 in older adults", year=2024, url="", source="pubmed")
    items = bundle(
        [src],
        {1: "We randomized 200 older adults to RTB101 or placebo. RTB101 reduced respiratory infections by 22% (p=0.01)."},
        topic="rapamycin",
        domain="aging older adults human",
    )
    assert items[0].direct is False
    assert items[0].strict is False


def test_on_topic_paper_marked_direct():
    src = Source(ref=1, title="Rapamycin trial in older adults", year=2024, url="", source="pubmed")
    items = bundle(
        [src],
        {1: "We randomized 200 older adults to rapamycin or placebo. Rapamycin reduced X by 22% (p=0.01)."},
        topic="rapamycin",
        domain="aging older adults human",
    )
    assert items[0].direct is True


# --- Phrase-aware topic gate (P1 audit fix) --------------------------------


def test_topic_anchors_compound_entity_kept_as_bigram():
    """Vitamin D and Vitamin K differ by one letter — the topic gate must
    treat the 2-content-token topic as a single phrase anchor, not fall
    back to 'vitamin' alone (which over-matches Vitamin K, multivitamin).

    The bigram heuristic fires only when exactly 2 content tokens remain
    after stopword removal. Topics with 3+ content tokens use unigrams
    (the user is naming alternatives, e.g. dasatinib/quercetin) — known
    limitation: 'vitamin a deficiency' (3 content tokens) loses the
    compound-entity preservation. Acceptable for V1; revisit if a fixture
    proves the limitation hurts.
    """
    from agent.bundle import _topic_anchors

    assert _topic_anchors("vitamin D supplementation mortality elderly") == ("vitamin d",)
    assert _topic_anchors("rapamycin older adults") == ("rapamycin",)
    # 3+ content words: list of compounds, unigrams only (>=3 chars).
    assert _topic_anchors("senolytics dasatinib quercetin older adults") == (
        "senolytics", "dasatinib", "quercetin",
    )
    # Empty / stopwords-only -> gate disabled
    assert _topic_anchors("") == ()
    assert _topic_anchors("older adults aging human") == ()


def test_vitamin_k_paper_indirect_for_vitamin_d_topic():
    """The exact reviewer-flagged P1: Vitamin K trial under a Vitamin D topic
    must NOT be marked direct."""
    src = Source(
        ref=1,
        title="Vitamin K Supplementation in Elderly Adults",
        year=2024, url="", source="pubmed",
    )
    items = bundle(
        [src],
        {1: "Trial of phytomenadione (vitamin K) in 200 elderly adults reduced fractures by 22% (p=0.01)."},
        topic="vitamin D supplementation mortality elderly",
        domain="aging older adults human",
    )
    assert items[0].direct is False


def test_multivitamin_paper_indirect_for_vitamin_d_topic():
    """Word-boundary matching: 'vitamin' inside 'multivitamin' must NOT trip
    the anchor (and the bigram 'vitamin d' wouldn't either)."""
    src = Source(
        ref=1,
        title="Multivitamin Supplementation in Older Adults",
        year=2024, url="", source="pubmed",
    )
    items = bundle(
        [src],
        {1: "Trial of multivitamin in 200 older adults reduced fractures by 22% (p=0.01)."},
        topic="vitamin D supplementation mortality elderly",
        domain="aging older adults human",
    )
    assert items[0].direct is False


def test_aging_domain_excludes_pcos_paper_with_topic_in_title():
    """PCOS paper that mentions metformin in its title still has zero aging
    relevance markers — for an aging domain, that's noise that should not
    appear as direct evidence."""
    src = Source(
        ref=1,
        title="Serum Biomarker Levels Improvement in Polycystic Ovarian Syndrome: Impact of Metformin Compared to Healthy Controls",
        year=2025, url="", source="clinicaltrials",
    )
    items = bundle(
        [src],
        {1: "Trial of metformin in PCOS patients to assess insulin resistance markers."},
        topic="metformin aging older adults",
        domain="aging older adults longevity",
    )
    assert items[0].direct is False


def test_aging_domain_excludes_pediatric_swallowing_study():
    """Pediatric swallowing/PK study is off-question for longevity."""
    src = Source(
        ref=1,
        title="Pediatric Participants With Type 2 Diabetes to Swallow MK-0431A XR Tablets",
        year=2014, url="", source="clinicaltrials",
    )
    items = bundle(
        [src],
        {1: "Pharmacokinetic study in children with type 2 diabetes."},
        topic="metformin aging older adults",
        domain="aging older adults longevity",
    )
    assert items[0].direct is False


def test_aging_domain_keeps_frailty_trial_direct():
    """Direct aging-relevance markers (frailty, sarcopenia, healthspan,
    physical function) keep a paper as direct evidence."""
    src = Source(
        ref=1,
        title="Metformin for Preventing Frailty in High-risk Older Adults",
        year=2024, url="", source="clinicaltrials",
    )
    items = bundle(
        [src],
        {1: "RCT of metformin to prevent frailty in adults aged 65 and older."},
        topic="metformin aging older adults",
        domain="aging older adults longevity",
    )
    assert items[0].direct is True


def test_non_aging_domain_skips_aging_relevance_gate():
    """Obesity / weight-loss domain: aging relevance check should NOT fire,
    so a real semaglutide weight RCT stays direct even without aging markers."""
    src = Source(
        ref=1,
        title="Once-Weekly Semaglutide in Adults with Overweight or Obesity",
        year=2024, url="", source="europepmc",
    )
    items = bundle(
        [src],
        {1: "We randomized 200 adults to semaglutide 2.4 mg or placebo for 68 weeks."},
        topic="semaglutide weight loss adults",
        domain="obesity adults",
    )
    assert items[0].direct is True


def test_vitamin_d_paper_direct_for_vitamin_d_topic():
    """Sanity: the actual on-topic paper IS direct."""
    src = Source(
        ref=1,
        title="Vitamin D Supplementation in Older Adults",
        year=2024, url="", source="pubmed",
    )
    items = bundle(
        [src],
        {1: "Trial of cholecalciferol (vitamin D) in 200 older adults reduced mortality by 22% (p=0.01)."},
        topic="vitamin D supplementation mortality elderly",
        domain="aging older adults human",
    )
    assert items[0].direct is True


# --- Tightened outcome regex (P0 audit fix) --------------------------------


def test_protocol_with_percentage_does_not_classify_as_results():
    """Real-world: a protocol abstract that mentions enrollment demographics
    ('60% female') used to flip role to published_results because the regex
    matched any digit-percentage pair. The bug class we rebuilt to prevent."""
    item = _bundle_one(
        title="A study to evaluate sirolimus in older adults: protocol",
        abstract="This study to evaluate sirolimus enrolls 200 patients (60% female) over 12 months.",
    )
    assert item.role == "published_protocol", (
        f"protocol misclassified as {item.role} (this is the rapamycin bug class)"
    )


def test_mechanistic_with_n_count_does_not_classify_as_results():
    """'n=24 mice' used to trip the n=\\d{2,} branch of the outcome regex."""
    item = _bundle_one(
        abstract="n=24 mice were treated; 80% showed reduced expression in cell culture."
    )
    assert item.role == "mechanistic"


# --- Protocol marker expansion (caught by audit) ---------------------------


def test_protocol_evaluates_safety_and_efficacy_phrasing():
    """RAPA-EX protocol paper PMID 39354527 used this exact phrasing and was
    misclassified as mechanistic before the audit fix."""
    item = _bundle_one(
        title="Sirolimus in older adults",
        abstract="This study evaluates the safety and efficacy of once-weekly sirolimus on muscle strength.",
    )
    assert item.role == "published_protocol"


def test_protocol_we_will_assess_phrasing():
    item = _bundle_one(
        abstract="We will assess functional outcomes in older adults randomized to drug or placebo."
    )
    assert item.role == "published_protocol"


# --- clean_text math characters (P1 audit fix) -----------------------------


def test_clean_text_preserves_pvalue_inequality():
    """clean_text used to strip '<' and '>' as HTML, destroying 'p<0.05'."""
    from agent.sources._base import clean_text

    assert clean_text("p<0.05") == "p<0.05"
    assert clean_text("x>2") == "x>2"
    # But still strips real HTML tags
    assert clean_text("<i>in vitro</i> study") == "in vitro study"
    assert clean_text("<sup>13</sup>C-labeled") == "13C-labeled"


# --- RAPA-EX regression — the actual V0 bug case ---------------------------


def test_rapamycin_fixture_contains_rapaex_papers():
    """The fixture must include both RAPA-EX papers; otherwise the role/protocol
    distinction can't be tested against real data and the regression coverage
    is theatrical."""
    hits = _load_topic("rapamycin")
    pmids = {h.pmid for h in hits if h.pmid}
    assert "41985884" in pmids, "RAPA-EX-01 results paper missing from rapamycin fixture"
    assert "39354527" in pmids, "RAPA-EX protocol paper missing from rapamycin fixture"


def test_rapamycin_fixture_classifies_rapaex_correctly():
    """End-to-end: the published RAPA-EX paper must classify as published_results
    and the protocol paper must classify as published_protocol. Same NCT
    must NOT cause them to dedup into a single ref."""
    hits = _load_topic("rapamycin")
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    items = bundle(
        sources,
        abstracts,
        topic="rapamycin older adults",
        domain="aging older adults human",
        raw_signals=raw_signals,
    )
    by_pmid = {it.source.pmid: it for it in items if it.source.pmid}

    results_item = by_pmid.get("41985884")
    assert results_item is not None, (
        "RAPA-EX-01 results paper not in bundle — likely lost to OpenAlex/EuropePMC "
        "winning dedup over PubMed; check adapter priority"
    )
    assert results_item.role == "published_results", (
        f"RAPA-EX results paper classified as {results_item.role!r}"
    )
    assert results_item.design == "rct"

    protocol_item = by_pmid.get("39354527")
    assert protocol_item is not None, "RAPA-EX protocol paper not in bundle"
    assert protocol_item.role == "published_protocol", (
        f"RAPA-EX protocol paper classified as {protocol_item.role!r} "
        f"— this is the V0 bug class that bundle.py was rebuilt to prevent"
    )


# --- Snapshot tests: full pipeline against real fixtures -------------------


# Mirror the adapter priority used by capture_fixtures.py and the production
# retrieve.py call site. PubMed first ensures PMIDs survive cross-source dedup
# (OpenAlex carries the same DOI but no PMID — alphabetical ordering would
# silently let it win and drop the PMID).
_ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


def _load_topic(slug: str) -> list[RawHit]:
    hits: list[RawHit] = []
    for source in _ADAPTER_PRIORITY:
        path = FIXTURES / slug / f"{source}.json"
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    return hits


# Topic queries that match the capture script. These also drive topic-anchor
# relevance gating in bundle() so the snapshot reflects production behavior.
SNAPSHOT_TOPIC_QUERIES = {
    "rapamycin": "rapamycin older adults",
    "metformin": "metformin aging older adults",
    "senolytics": "senolytics dasatinib quercetin older adults",
    "semaglutide_weight": "semaglutide weight loss adults",
    "vitamin_d_mortality": "vitamin D supplementation mortality elderly",
}


@pytest.mark.parametrize("topic", TOPICS)
def test_bundle_snapshot_per_topic(topic: str, snapshot):
    """Per-source classification snapshot.

    Per-source rows (not aggregate counts) so a role swap between two
    individual sources is visible — aggregates can mask them. Refresh with
    UPDATE_SNAPSHOTS=1 only after reviewing whether the new rows are
    intentional improvements.
    """
    hits = _load_topic(topic)
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    items = bundle(
        sources,
        abstracts,
        topic=SNAPSHOT_TOPIC_QUERIES[topic],
        domain="aging older adults human",
        raw_signals=raw_signals,
    )
    rows = [
        {
            "ref": it.source.ref,
            "src": it.source.source,
            "ident": it.source.doi or it.source.pmid or it.source.nct or "",
            "year": it.source.year,
            "role": it.role,
            "design": it.design,
            "tier": it.tier,
            "direct": it.direct,
            "strict": it.strict,
            # Title trimmed for snapshot readability; full title is in the fixture.
            "title": it.source.title[:80],
        }
        for it in items
    ]
    summary = {
        "topic_query": SNAPSHOT_TOPIC_QUERIES[topic],
        "raw_hits": len(hits),
        "unique_sources": len(sources),
        "totals": {
            "role_counts": dict(Counter(it.role for it in items)),
            "design_counts": dict(Counter(it.design for it in items)),
            "tier_counts": dict(Counter(it.tier for it in items)),
            "direct_count": sum(1 for it in items if it.direct),
            "strict_count": sum(1 for it in items if it.strict),
        },
        "rows": rows,
    }
    snapshot(summary)
