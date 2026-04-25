from __future__ import annotations

from agent.citation_roles import classify_citation_role, citation_directness
from agent.evidence_cards import build_card


def _card(entry: dict) -> dict:
    return build_card(entry)


def test_ctgov_registry_without_results_is_registered_pending() -> None:
    entry = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "source_type": "clinicaltrials",
        "has_results": False,
        "trial_status": "registered",
        "evidence_type": "interventional",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "frailty"])
    assert role == "registered_pending"


def test_ctgov_with_results_is_published_results() -> None:
    entry = {
        "title": "MET-PREVENT",
        "excerpt": "Posted outcomes for older adults.",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "evidence_type": "interventional",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "frailty"])
    assert role == "published_results"


def test_chembl_entry_is_mechanistic() -> None:
    entry = {"title": "Everolimus mechanism", "source_type": "chembl", "evidence_type": "mechanism"}
    role = classify_citation_role(entry, _card(entry), "longevity", ["everolimus"])
    assert role == "mechanistic"


def test_protocol_title_is_published_protocol() -> None:
    entry = {
        "title": "Metformin and longevity: rationale and design for a clinical trial",
        "excerpt": "Protocol in older adults.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "longevity"])
    assert role == "published_protocol"


def test_study_to_evaluate_title_is_published_protocol() -> None:
    entry = {
        "title": "A single-center, double-blind, randomized, placebo-controlled, two-arm study to evaluate the safety and efficacy of once-weekly sirolimus on muscle strength and endurance in older adults",
        "excerpt": "Protocol paper in Trials describing design and planned endpoints.",
        "evidence_type": "review",
        "source_type": "pubmed",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["rapamycin", "sirolimus", "older", "adults"])
    assert role == "published_protocol"


def test_animal_title_is_animal_model() -> None:
    entry = {
        "title": "Metformin improves frailty in MitoPark mice",
        "excerpt": "Preclinical work in mice.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "frailty"])
    assert role == "animal_model"


def test_insect_model_title_is_animal_model() -> None:
    entry = {
        "title": "Galleria mellonella pathogen infection models",
        "excerpt": "Insect infection model unrelated to senolytic therapy in older adults.",
        "evidence_type": "review",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["senolytic", "dasatinib", "quercetin"])
    assert role == "animal_model"


def test_meta_analysis_is_meta_analysis_role() -> None:
    entry = {
        "title": "Metformin for aging: a meta-analysis",
        "excerpt": "Systematic review and meta-analysis in older adults.",
        "evidence_type": "review",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging"])
    assert role == "meta_analysis"


def test_review_is_review_role() -> None:
    entry = {
        "title": "Metformin review in skeletal muscle aging",
        "excerpt": "Narrative review in older adults.",
        "evidence_type": "review",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging"])
    assert role == "review"


def test_reviewish_primary_entry_is_review_role() -> None:
    entry = {
        "title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging.",
        "excerpt": "Metformin has attracted increasing interest as a geroprotective therapy. Observational and epidemiological studies suggest lower sarcopenia prevalence in metabolically compromised populations.",
        "evidence_type": "primary",
        "source_type": "europepmc",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging", "older", "adults"])
    assert role == "review"


def test_pathophysiology_frontier_primary_entry_is_review_role() -> None:
    entry = {
        "title": "Vascular Dementia: From Pathophysiology to Therapeutic Frontiers",
        "excerpt": "This article reviews mechanisms and therapeutic opportunities.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["senolytic", "dasatinib", "quercetin"])
    assert role == "review"


def test_off_domain_longevity_entry_is_off_domain_indirect() -> None:
    entry = {
        "title": "Metformin in pregnancy and gestational diabetes",
        "excerpt": "Pregnancy outcomes rather than healthy aging.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging"])
    assert role == "off_domain_indirect"


def test_embryo_entry_is_off_domain_for_longevity() -> None:
    entry = {
        "title": "FOXO1-mediated lipid metabolism maintains mammalian embryos in dormancy",
        "excerpt": "Embryo dormancy pathways in mammals.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging", "older", "adults"])
    assert role == "off_domain_indirect"


def test_observational_entry_is_observational_role() -> None:
    entry = {
        "title": "Prospective cohort of metformin and mortality in older adults",
        "excerpt": "Association study in older adults.",
        "evidence_type": "observational",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "older", "adults"])
    assert role == "observational"


def test_published_aging_trial_is_published_results() -> None:
    entry = {
        "title": "Metformin and physical performance in older people with frailty",
        "excerpt": "Randomized trial in older adults with aging outcomes.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "frailty"])
    assert role == "published_results"


def test_rct_like_review_entry_is_promoted_to_published_results() -> None:
    entry = {
        "title": "Exercise and Weekly Sirolimus (Rapamycin) in Older Adults: RAPA-EX-01 Randomised, Double-Blind, Placebo-Controlled Trial",
        "excerpt": "Older adults completed a randomized placebo-controlled sirolimus trial with strength outcomes. Protocol language may appear in indexing metadata.",
        "evidence_type": "review",
    }
    card = _card(entry)
    card["study_type"] = "rct"
    role = classify_citation_role(entry, card, "longevity", ["rapamycin", "older", "adults", "sirolimus"])
    assert role == "published_results"


def test_in_vitro_entry_is_mechanistic() -> None:
    entry = {
        "title": "Dasatinib and Quercetin Limit Gingival Senescence, Inflammation, and Bone Loss",
        "excerpt": "In vitro gingival fibroblast assays showed reduced SA-beta-gal activity.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["senolytic", "dasatinib", "quercetin"])
    assert role == "mechanistic"


def test_directness_for_published_aging_trial_is_direct() -> None:
    entry = {
        "title": "Metformin and cognitive decline in older adults",
        "excerpt": "Randomized trial in older adults with aging outcomes.",
        "evidence_type": "primary",
    }
    card = _card(entry)
    role = classify_citation_role(entry, card, "longevity", ["metformin", "older", "adults"])
    assert citation_directness(role, entry, card, "longevity", ["metformin", "older", "adults"]) == "direct"


def test_longevity_review_without_topic_token_in_title_is_indirect() -> None:
    entry = {
        "title": "Pain and aging: A unique challenge in neuroinflammation and behavior",
        "excerpt": "Review in aging adults without metformin in the title.",
        "evidence_type": "review",
    }
    card = _card(entry)
    role = classify_citation_role(entry, card, "longevity", ["metformin", "aging", "older", "adults"])
    assert role == "review"
    assert citation_directness(role, entry, card, "longevity", ["metformin", "aging", "older", "adults"]) == "indirect"


def test_off_domain_entry_is_indirect() -> None:
    entry = {
        "title": "Metformin in esophageal carcinoma",
        "excerpt": "Oncology outcomes.",
        "evidence_type": "primary",
    }
    card = _card(entry)
    role = classify_citation_role(entry, card, "longevity", ["metformin", "aging"])
    assert citation_directness(role, entry, card, "longevity", ["metformin", "aging"]) == "indirect"
