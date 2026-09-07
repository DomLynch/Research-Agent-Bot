"""Fix #4: evidence_taxonomy — A1/A2/B1/B2/C1/C2 classification from
structured metadata. Discriminating tests isolate each tier path."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evidence_taxonomy as et  # type: ignore[import-not-found]  # noqa: E402


def test_human_rct_with_clinical_endpoint_is_a1() -> None:
    cls = et.classify_evidence(
        study_design="randomized controlled trial",
        species="human",
        endpoint_kind="clinical",
    )
    assert cls.tier == "A1"
    assert cls.directness == "direct"


def test_human_rct_with_functional_endpoint_is_a1() -> None:
    """Functional endpoints (walk speed, grip strength) are clinical-
    grade. MET-PREVENT (Witham 2025) belongs here."""
    cls = et.classify_evidence(
        study_design="RCT",
        species="human",
        endpoint_kind="functional",
    )
    assert cls.tier == "A1"


def test_human_rct_with_mechanistic_endpoint_is_a2() -> None:
    """A2: human RCT but the endpoint is biomarker / mechanism, not
    clinical outcome. Walton MASTERS (resistance + lean mass) lives
    here when classified by endpoint type."""
    cls = et.classify_evidence(
        study_design="randomized clinical trial",
        species="humans",
        endpoint_kind="mechanistic",
    )
    assert cls.tier == "A2"
    assert cls.directness == "indirect"


def test_systematic_review_is_b1() -> None:
    cls = et.classify_evidence(
        study_design="systematic review",
        species=None,
        endpoint_kind=None,
    )
    assert cls.tier == "B1"
    assert cls.directness == "review"


def test_meta_analysis_is_b1() -> None:
    cls = et.classify_evidence(
        study_design="meta-analysis", species=None, endpoint_kind=None,
    )
    assert cls.tier == "B1"


def test_human_observational_cohort_is_b2_not_mechanistic() -> None:
    """The reviewer-flagged bug: human observational mortality studies
    were tagged `directness=mechanistic`. They are B2 (human, but
    confounding-prone) — directly NOT mechanistic."""
    cls = et.classify_evidence(
        study_design="cohort",
        species="human",
        endpoint_kind="mortality",
    )
    assert cls.tier == "B2"
    assert cls.directness == "indirect"
    assert cls.directness != "mechanistic"


def test_public_directness_phrase_keeps_observational_human_evidence_visible() -> None:
    phrase = et.public_directness_phrase(["B2"], ["indirect"])
    assert phrase == "human observational/prognostic evidence is present"
    assert "no direct clinical evidence" not in phrase


def test_public_directness_phrase_separates_review_and_preclinical_only() -> None:
    assert et.public_directness_phrase(["B1"], ["review"]) == "review-level evidence is present"
    assert et.public_directness_phrase(["C1"], ["mechanistic"]) == "preclinical/mechanistic evidence is present"


def test_target_trial_emulation_is_b2() -> None:
    """Target trial emulation = observational cohort with RCT-style
    framing. Still B2, not A1."""
    cls = et.classify_evidence(
        study_design="target trial emulation",
        species="human",
        endpoint_kind="mortality",
    )
    assert cls.tier == "B2"


def test_mouse_study_is_c1() -> None:
    cls = et.classify_evidence(
        study_design="preclinical",
        species="mouse",
        endpoint_kind="mechanistic",
    )
    assert cls.tier == "C1"
    assert cls.directness == "mechanistic"


def test_c_elegans_study_is_c1() -> None:
    cls = et.classify_evidence(
        study_design=None, species="C. elegans", endpoint_kind=None,
    )
    assert cls.tier == "C1"


def test_unknown_metadata_returns_unknown() -> None:
    """Fail-loud: zero metadata → 'unknown' so the audit can flag it
    for manual annotation rather than silently picking a wrong tier."""
    cls = et.classify_evidence(
        study_design=None, species=None, endpoint_kind=None,
    )
    assert cls.tier == "unknown"
    assert "metadata insufficient" in cls.rationale


def test_classification_is_frozen() -> None:
    cls = et.classify_evidence(
        study_design="RCT", species="human", endpoint_kind="clinical",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        setattr(cls, "tier", "X")


# ----- infer_from_paper_meta best-effort extraction --------------------


def test_infer_human_rct_from_title_keywords() -> None:
    """Classic title pattern: 'A randomized controlled trial of
    metformin in older adults' → human RCT, A1."""
    meta = {
        "title": "A randomized controlled trial of metformin in older adults",
        "abstract": "We assessed walk speed in 100 participants.",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "A1"


def test_infer_human_rct_from_young_males_title() -> None:
    """Human-sex terms in titles must count as human markers."""
    meta = {
        "title": (
            "Creatine Loading Does Not Preserve Muscle Mass or Strength "
            "During Leg Immobilization in Healthy, Young Males: "
            "A Randomized Controlled Trial"
        ),
        "abstract": "",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "A1"
    assert cls.directness == "direct"


def test_infer_observational_cohort_from_title() -> None:
    """'Cohort study' / 'registry-based' titles → B2 (NOT mechanistic
    even though receipt_id may start with PMC). This is THE bug Fix #4
    addresses."""
    meta = {
        "title": (
            "Metformin use and the risk of incident dementia: a registry-"
            "based cohort study"
        ),
        "abstract": "We followed 12,000 patients with type 2 diabetes ...",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "B2"
    assert cls.directness != "mechanistic"


def test_infer_mouse_preclinical_from_title() -> None:
    meta = {
        "title": "Metformin extends lifespan in C57BL/6 mice via AMPK",
        "abstract": "Aged mice were treated with metformin ...",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "C1"


def test_infer_model_fish_preclinical_from_title() -> None:
    meta = {
        "title": (
            "Dietary berberine alleviates high carbohydrate diet-induced "
            "intestinal damages in largemouth bass"
        ),
        "abstract": "",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "C1"
    assert cls.directness == "mechanistic"


def test_infer_mechanism_title_as_mechanistic_context() -> None:
    meta = {
        "title": "Modulating gut microbiota as an anti-diabetic mechanism of berberine",
        "abstract": "",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "C1"
    assert cls.directness == "mechanistic"


def test_infer_review_from_title() -> None:
    meta = {
        "title": "Metformin: a critical review of anti-aging evidence",
        "abstract": "We surveyed the published literature ...",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "B1"


def test_infer_returns_unknown_on_empty_meta() -> None:
    """Empty metadata → unknown (no silent miscalssification). The
    receipt_id heuristic in run_v06_synthesis falls back from here."""
    meta = {"title": "", "abstract": ""}
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "unknown"


def test_explicit_metadata_overrides_inference() -> None:
    """If the paper_meta has explicit `study_design` / `species` /
    `endpoint_kind`, the classifier uses those directly. The legacy
    title-keyword inference is only a fallback for unannotated papers."""
    explicit = et.classify_evidence(
        study_design="cohort", species="human", endpoint_kind="mortality",
    )
    inferred = et.infer_from_paper_meta({
        "title": "Mouse mechanistic study of metformin",
    })
    # Explicit said B2 (human cohort); inferred said C1 (mouse). They
    # produce different tiers — proving the classifier is metadata-
    # driven, not heuristic-only.
    assert explicit.tier == "B2"
    assert inferred.tier == "C1"
    assert explicit.tier != inferred.tier


# ----- Reviewer-fix discriminating tests (post-2x review) ---------------


def test_canonical_pubmed_publication_type_classifies_correctly() -> None:
    """Pre-fix: exact-string `frozenset` match dropped real publication
    types like 'Randomised, double-blind, placebo-controlled trial' to
    'unknown'. Substring matching now classifies them as RCT."""
    cls = et.classify_evidence(
        study_design="Randomised, double-blind, placebo-controlled trial",
        species="human",
        endpoint_kind="clinical",
    )
    assert cls.tier == "A1"


def test_phase3_rct_publication_type_classifies_correctly() -> None:
    cls = et.classify_evidence(
        study_design="Phase 3 randomized controlled trial",
        species="humans",
        endpoint_kind="mortality",
    )
    assert cls.tier == "A1"


def test_meta_analysis_of_rcts_classifies_as_b1_not_a1() -> None:
    """Pre-fix `_TITLE_RCT_RE` matched 'systematic review of randomized
    controlled trials' first → A1. Now review check is FIRST → B1."""
    meta = {
        "title": (
            "Systematic review and meta-analysis of randomized controlled "
            "trials of metformin in older adults"
        ),
        "abstract": "We searched PubMed for RCTs ...",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "B1"


def test_primary_randomized_study_detector_rejects_reviews_and_protocols() -> None:
    assert et.is_primary_randomized_study(
        "A randomized controlled trial of metformin in older adults",
    )
    assert not et.is_primary_randomized_study(
        "A systematic review and meta‐analysis of randomized controlled trials",
    )
    assert not et.is_primary_randomized_study(
        "A randomized controlled trial of metformin: study protocol",
    )
    assert not et.is_primary_randomized_study(
        "Protocol of a randomized controlled trial of metformin",
    )
    assert not et.is_primary_randomized_study(
        "Meta‐analyses of randomized controlled trials",
    )
    assert et.is_primary_randomized_study(
        "A randomized controlled trial of metformin",
        "A prior systematic review motivated this study.",
    )


def test_design_string_with_rct_substring_classifies_correctly() -> None:
    """Single-token 'RCT (double-blind)' must classify as RCT."""
    cls = et.classify_evidence(
        study_design="RCT (double-blind)",
        species="human",
        endpoint_kind="clinical",
    )
    assert cls.tier == "A1"


def test_future_trials_do_not_promote_pilots_or_protocols() -> None:
    for title, abstract, tier in (
        ("Single-group pilot in older adults", "Fully powered randomized controlled trials are needed.", "B2"),
        ("Fasting pilot in adults", "We conducted a single-arm study. Results support larger randomized trials to confirm efficacy.", "B2"),
        ("Hormone prediction in adults", "This retrospective cohort requires confirmation in larger randomised trials.", "B2"),
        ("INTERFAST study design", "This randomized controlled trial is designed to investigate adults.", "D1"),
    ):
        assert not et.is_primary_randomized_study(title, abstract)
        assert et.infer_from_paper_meta({"title": title, "abstract": abstract}).tier == tier
    for title, abstract in (
        ("A fasting intervention in adults", "Adults were randomized to fasting or placebo. Larger trials are needed."),
        ("Prospective pilot in adults", "Patients were randomly assigned to two drugs. Larger randomised trials are required."),
        ("Fasting and blood pressure in adults",
         "Prior observational studies suggested benefit. We randomized 100 adults to fasting or usual diet and measured blood pressure."),
        ("Fasting and blood pressure in adults",
         "We randomized 100 adults with hypertension who were required to have stable medication to fasting or usual diet."),
        ("Fasting effects in adults", "Adults were randomized in a trial required by the funding agency."),
        ("Fasting in adults: study design and results of a randomized controlled trial",
         "We randomized 100 adults to fasting or usual diet and report blood pressure outcomes."),
    ):
        assert et.is_primary_randomized_study(title, abstract)
        assert et.infer_from_paper_meta({"title": title, "abstract": abstract}).tier == "A1"
    assert et.is_primary_randomized_study("Prospective randomized controlled trial in adults")
    assert not et.is_primary_randomized_study(
        "INTERFAST study design", "This trial is designed to investigate adults.", study_design="randomized trial",
    )


def test_surrogate_endpoint_in_human_rct_is_a1() -> None:
    """Reviewer P2 fix: surrogate endpoints (HbA1c, BP, LDL) are
    validated clinical biomarkers per regulatory convention; they
    belong with A1, not A2."""
    cls = et.classify_evidence(
        study_design="RCT", species="human", endpoint_kind="surrogate",
    )
    assert cls.tier == "A1"


def test_observational_rationale_includes_endpoint_kind() -> None:
    """Reviewer P2 fix: B2 rationale must surface endpoint_kind so
    the audit can distinguish 'B2 mortality' (strong) from 'B2
    biomarker' (weak)."""
    cls = et.classify_evidence(
        study_design="cohort", species="human", endpoint_kind="mortality",
    )
    assert "mortality" in cls.rationale


def test_animal_study_with_unknown_endpoint_is_c1_not_unknown() -> None:
    """Reviewer P1 fix: dropped duplicate dead branch — animal study
    with no endpoint_kind still classifies as C1."""
    cls = et.classify_evidence(
        study_design=None, species="mouse", endpoint_kind=None,
    )
    assert cls.tier == "C1"


def test_review_with_bare_word_review_in_abstract_does_not_misclassify() -> None:
    """Pre-fix '_TITLE_REVIEW_RE' matched bare 'review' so an RCT paper
    with 'review' in abstract wrongly classified as B1. Now only
    multi-word review patterns count → this trial paper stays A1."""
    meta = {
        "title": "A randomized trial of metformin in older adults",
        "abstract": "We review the prior literature briefly ...",
    }
    cls = et.infer_from_paper_meta(meta)
    # 'older adults' provides the human marker; bare 'review' in abstract
    # no longer hijacks the design classification.
    assert cls.tier == "A1"


def test_human_observational_at_pmcid_paper_is_b2_not_c1() -> None:
    """The bug Fix #4 was built to address: a human observational
    cohort whose receipt_id starts with 'PMC' must NOT be tagged
    mechanistic / C1. Title-driven inference catches it."""
    meta = {
        "title": (
            "Metformin use and the risk of incident dementia in older "
            "adults: a prospective cohort study"
        ),
        "abstract": "We followed 14,000 patients ...",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "B2"
    assert cls.directness != "mechanistic"


def test_lower_case_design_string_classifies_correctly() -> None:
    """Robustness: lowercase normalization + substring match handles
    sloppy input."""
    cls = et.classify_evidence(
        study_design="randomized", species="human", endpoint_kind="clinical",
    )
    assert cls.tier == "A1"


# ----- Registered-protocol detection (credibility-killer fix) ----------


def test_registered_protocol_is_not_direct_a1() -> None:
    """A registered trial protocol matches the RCT tokens ('randomized,
    double-blind, placebo-controlled') but has NO results — it must NOT
    be graded A1/direct efficacy evidence."""
    cls = et.classify_evidence(
        study_design="randomized double-blind placebo-controlled study protocol",
        species="human",
        endpoint_kind="clinical",
    )
    assert cls.tier == "D1"
    assert cls.directness == "protocol"
    assert cls.directness != "direct"


def test_protocol_title_infers_protocol_not_a1() -> None:
    """Title-driven inference: a protocol paper announces itself in its
    title — graded D1/protocol, never A1, despite RCT keywords."""
    meta = {
        "title": (
            "Resveratrol in older adults: rationale and design of a "
            "randomized, double-blind, placebo-controlled trial"
        ),
        "abstract": "We will randomize 200 participants ... endpoint walk speed.",
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "D1"
    assert cls.directness == "protocol"


def test_results_rct_mentioning_protocol_in_abstract_stays_a1() -> None:
    """Precision guard: a RESULTS RCT that merely references 'the study
    protocol' in its abstract must stay graded on its real design (A1),
    not be downgraded. Protocol detection is title-only."""
    meta = {
        "title": "A randomized controlled trial of resveratrol in older adults",
        "abstract": (
            "Following the study protocol, we randomized 200 patients; "
            "walk speed improved (p<0.01)."
        ),
    }
    cls = et.infer_from_paper_meta(meta)
    assert cls.tier == "A1"
    assert cls.directness == "direct"


def test_protocol_for_a_systematic_review_is_protocol_not_review() -> None:
    """A protocol *for* a systematic review (Cochrane-style) has no
    results either — protocol wins over the review bucket."""
    cls = et.classify_evidence(
        study_design="protocol for a systematic review and meta-analysis",
        species=None,
        endpoint_kind=None,
    )
    assert cls.tier == "D1"
    assert cls.directness == "protocol"


def test_public_directness_phrase_protocol_only() -> None:
    """A corpus of only registered protocols is reported as such — never
    as direct or preclinical evidence."""
    phrase = et.public_directness_phrase(["D1", "D1"], ["protocol", "protocol"])
    assert "protocol" in phrase
    assert "direct" not in phrase


def test_public_directness_phrase_protocol_does_not_mask_real_direct() -> None:
    """A protocol mixed with real direct evidence must not suppress the
    'direct evidence is present' headline."""
    phrase = et.public_directness_phrase(["A1", "D1"], ["direct", "protocol"])
    assert phrase == "direct interventional evidence is present"
