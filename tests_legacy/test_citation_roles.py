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


def test_animal_title_is_animal_model() -> None:
    entry = {
        "title": "Metformin improves frailty in MitoPark mice",
        "excerpt": "Preclinical work in mice.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "frailty"])
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


def test_off_domain_longevity_entry_is_off_domain_indirect() -> None:
    entry = {
        "title": "Metformin in pregnancy and gestational diabetes",
        "excerpt": "Pregnancy outcomes rather than healthy aging.",
        "evidence_type": "primary",
    }
    role = classify_citation_role(entry, _card(entry), "longevity", ["metformin", "aging"])
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


def test_directness_for_published_aging_trial_is_direct() -> None:
    entry = {
        "title": "Metformin and cognitive decline in older adults",
        "excerpt": "Randomized trial in older adults with aging outcomes.",
        "evidence_type": "primary",
    }
    card = _card(entry)
    role = classify_citation_role(entry, card, "longevity", ["metformin", "older", "adults"])
    assert citation_directness(role, entry, card, "longevity", ["metformin", "older", "adults"]) == "direct"


def test_off_domain_entry_is_indirect() -> None:
    entry = {
        "title": "Metformin in esophageal carcinoma",
        "excerpt": "Oncology outcomes.",
        "evidence_type": "primary",
    }
    card = _card(entry)
    role = classify_citation_role(entry, card, "longevity", ["metformin", "aging"])
    assert citation_directness(role, entry, card, "longevity", ["metformin", "aging"]) == "indirect"
