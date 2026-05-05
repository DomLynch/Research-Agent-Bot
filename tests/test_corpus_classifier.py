"""Tests for agent/corpus_classifier.py — 5-class corpus classifier
(Wave 7 Evidence Factory slice 2 full).

Universal across topics — every assertion uses topic_aliases as a
parameter, no hardcoded drug names in the assertion logic itself.
"""
from __future__ import annotations

from agent.corpus_classifier import (
    CorpusClassification,
    classify_corpus,
    classify_paper,
    score_paper,
)


def _paper(title: str = "", abstract: str = "",
           paper_id: str = "P1") -> dict:
    return {
        "paper_id": paper_id, "title": title,
        "sections": {"abstract": abstract},
    }


# ---------- 5-class boundary tests ----------------------------------

def test_core_on_thesis_when_topic_alias_plus_rct():
    p = _paper(
        title="Metformin and all-cause mortality",
        abstract="A randomized controlled trial of metformin showed "
                 "lower all-cause mortality at 5 years.",
    )
    c = classify_paper(p, topic_aliases=("metformin",))
    assert c.classification == "core_on_thesis"
    assert c.score == 100
    assert "clinical evidence" in c.reason.lower()


def test_background_mechanism_when_in_vitro_marker():
    p = _paper(
        title="Cellular signaling of statins",
        abstract="In vitro analysis of HMG-CoA reductase pathway "
                 "and kinase activity in cell culture.",
    )
    c = classify_paper(p, topic_aliases=("statin",))
    assert c.classification == "background_mechanism"
    assert "preclinical" in c.reason.lower() or "mechanism" in c.reason.lower()


def test_adjacent_clinical_when_alias_but_no_clinical_signal():
    p = _paper(
        title="Statin prescribing patterns review",
        abstract="A narrative review of statin use trends; no "
                 "outcome reporting.",
    )
    c = classify_paper(p, topic_aliases=("statin",))
    assert c.classification == "adjacent_clinical"


def test_off_thesis_when_no_alias_no_mechanism():
    p = _paper(
        title="Marketing of nutritional supplements",
        abstract="A survey of consumer behavior in vitamin shops.",
    )
    c = classify_paper(p, topic_aliases=("metformin",))
    assert c.classification == "off_thesis"


def test_reject_when_hard_signal_and_no_alias():
    p = _paper(
        title="Cardioversion outcomes in atrial fibrillation",
        abstract="Patients with stroke and atrial fibrillation "
                 "underwent cardioversion.",
    )
    c = classify_paper(p, topic_aliases=("statin",))
    assert c.classification == "reject"
    assert c.score == 0


def test_reject_signal_with_alias_keeps_paper():
    """A paper that mentions a hard-reject signal AND the topic
    alias is NOT rejected (alias rescue)."""
    p = _paper(
        title="Statins after stroke patients",
        abstract="Patients on statins had RCT-confirmed lower "
                 "all-cause mortality post-stroke.",
    )
    c = classify_paper(p, topic_aliases=("statin",))
    # Hard reject is suppressed by alias hit → paper survives as core
    assert c.classification == "core_on_thesis"


# ---------- score_paper combinator -----------------------------------

def test_score_paper_adds_tier_directness_recency():
    classification = CorpusClassification(
        paper_id="P1", classification="core_on_thesis",
        score=100, reason="r", signals=(),
    )
    # Already at 100 → cap, even with bonuses
    s = score_paper(
        classification, evidence_tier="A1", directness="direct",
        publication_year=2024,
    )
    assert s == 100


def test_score_paper_starts_low_when_class_is_low():
    """A 'reject' baseline can never climb above its bonuses."""
    classification = CorpusClassification(
        paper_id="P1", classification="reject", score=0,
        reason="r", signals=(),
    )
    s = score_paper(
        classification, evidence_tier="A1", directness="direct",
        publication_year=2024,
    )
    # 0 + 30 (A1) + 20 (direct) + 10 (recency) = 60
    assert s == 60


def test_score_paper_old_publication_no_recency_bonus():
    classification = CorpusClassification(
        paper_id="P1", classification="adjacent_clinical",
        score=40, reason="r", signals=(),
    )
    s = score_paper(
        classification, evidence_tier="B1", directness="review",
        publication_year=2005, current_year=2026,
    )
    # 40 + 15 (B1) + 15 (review) + 0 (>10y) = 70
    assert s == 70


# ---------- batch classify -------------------------------------------

def test_classify_corpus_returns_one_entry_per_paper():
    papers = [
        _paper(title="A", paper_id="A"),
        _paper(title="Statin RCT mortality", paper_id="B",
               abstract="randomized controlled trial all-cause mortality"),
        _paper(title="Statin kinase", paper_id="C", abstract="in vitro kinase"),
    ]
    out = classify_corpus(papers, topic_aliases=("statin",))
    assert len(out) == 3
    classes = {c.paper_id: c.classification for c in out}
    assert classes["B"] == "core_on_thesis"
    assert classes["C"] == "background_mechanism"


# ---------- universal-across-topics check ---------------------------

def test_classifier_works_for_any_topic_alias():
    """No drug-name hardcoding — same input becomes core_on_thesis
    when the alias matches and off_thesis when it doesn't."""
    p = _paper(
        title="A randomized controlled trial of widgets",
        abstract="A randomized controlled trial showed widgets reduced "
                 "all-cause mortality.",
    )
    # Aliases match → core
    c1 = classify_paper(p, topic_aliases=("widget", "widgets"))
    # No alias → off-thesis (no mechanism, no alias)
    c2 = classify_paper(p, topic_aliases=("nothing",))
    assert c1.classification == "core_on_thesis"
    # mortality is in CORE_CLINICAL_SIGNALS but no alias → off_thesis
    assert c2.classification == "off_thesis"


def test_alias_match_is_case_normalized_and_boundary_scoped():
    """Short aliases must not match inside unrelated words."""
    p = _paper(
        title="Age-dependent effect of ticagrelor monotherapy",
        abstract="A randomized controlled trial of cardiovascular events.",
    )
    c = classify_paper(p, topic_aliases=("RAP", "mTOR inhibitor"))
    assert c.classification == "off_thesis"


def test_alias_match_accepts_phrase_with_punctuation():
    p = _paper(
        title="Urolithin A improves mitochondrial biomarkers",
        abstract="A randomized controlled trial in older adults.",
    )
    c = classify_paper(p, topic_aliases=("urolithin-a", "urolithin A"))
    assert c.classification == "core_on_thesis"


def test_alias_match_ignores_device_only_context():
    p = _paper(
        title="Ticagrelor after sirolimus-eluting stent implantation",
        abstract="A randomized controlled trial of cardiovascular events.",
    )
    c = classify_paper(p, topic_aliases=("sirolimus",))
    assert c.classification == "off_thesis"


def test_off_topic_mechanism_does_not_enter_background_pool():
    p = _paper(
        title="Unrelated diabetic swine stent biology",
        abstract="Expression of inflammatory signaling in animal models.",
    )
    c = classify_paper(p, topic_aliases=("everolimus",))
    assert c.classification == "off_thesis"


def test_core_requires_topic_alias_in_title():
    p = _paper(
        title="Clinical outcomes of a different intervention",
        abstract="This randomized controlled trial review mentions sirolimus.",
    )
    c = classify_paper(p, topic_aliases=("sirolimus",))
    assert c.classification == "off_thesis"


def test_alias_match_ignores_target_of_eponym_context():
    p = _paper(
        title="Branched-chain amino acids signal through mammalian target of rapamycin",
        abstract="A randomized controlled trial is not about the named treatment.",
    )
    c = classify_paper(p, topic_aliases=("rapamycin",))
    assert c.classification == "off_thesis"


def test_animal_core_signal_is_background_not_core():
    p = _paper(
        title="Rapamycin slows aging in mice",
        abstract="A meta-analysis of animal models reported lifespan outcomes.",
    )
    c = classify_paper(p, topic_aliases=("rapamycin",))
    assert c.classification == "background_mechanism"


def test_exclusion_terms_downgrade_wrong_indication_from_core():
    p = _paper(
        title="Sirolimus in older kidney transplant recipients",
        abstract="A randomized controlled trial evaluated transplant outcomes.",
    )
    c = classify_paper(
        p,
        topic_aliases=("sirolimus",),
        exclude_terms=("transplant only",),
    )
    assert c.classification == "adjacent_clinical"


def test_classifier_reason_is_human_readable():
    """Reason field must be non-empty and informative for the
    rejected-paper reason log (Slice 2 deliverable)."""
    out = classify_paper(
        _paper(abstract="cardioversion atrial fibrillation"),
        topic_aliases=("statin",),
    )
    assert out.reason.strip()
    assert len(out.reason) > 10
