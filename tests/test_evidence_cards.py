from __future__ import annotations

from agent.evidence_cards import build_card, _format_citation, _infer_quality_signal, _infer_study_type


def test_infer_quality_signal_meta_analysis():
    entry = {"evidence_type": "review", "title": "A meta-analysis of rapamycin in aging"}
    assert _infer_quality_signal(entry) == "meta-analysis"


def test_infer_quality_signal_systematic_review():
    entry = {"evidence_type": "review", "title": "A systematic review of senolytics"}
    assert _infer_quality_signal(entry) == "systematic-review"


def test_infer_quality_signal_plain_review():
    entry = {"evidence_type": "review", "title": "Rapamycin review article"}
    assert _infer_quality_signal(entry) == "review"


def test_infer_quality_signal_rct():
    entry = {"evidence_type": "primary", "title": "Randomized trial of rapamycin", "excerpt": "RCT design"}
    assert _infer_quality_signal(entry) == "rct"


def test_infer_quality_signal_rct_american():
    entry = {"evidence_type": "primary", "title": "Randomized clinical trial of metformin", "excerpt": ""}
    assert _infer_quality_signal(entry) == "rct"


def test_infer_quality_signal_cohort():
    entry = {"evidence_type": "primary", "title": "A prospective cohort study", "excerpt": ""}
    assert _infer_quality_signal(entry) == "cohort"


def test_infer_quality_signal_preprint():
    entry = {"evidence_type": "primary", "title": "Test preprint on rapamycin", "excerpt": ""}
    assert _infer_quality_signal(entry) == "preprint"


def test_infer_quality_signal_protocol():
    entry = {"evidence_type": "primary", "title": "Metformin and longevity: study protocol and rationale", "excerpt": ""}
    assert _infer_quality_signal(entry) == "protocol"


def test_infer_quality_signal_no_evidence_type():
    entry = {"title": "Some paper"}
    assert _infer_quality_signal(entry) == "primary"


def test_format_citation_with_authors():
    entry = {"authors": ["Smith, J", "Jones, A"], "year": 2024}
    assert _format_citation(entry) == "Smith et al., 2024"


def test_format_citation_single_author():
    entry = {"authors": ["Johnson, K"], "year": 2023}
    assert _format_citation(entry) == "Johnson, 2023"


def test_format_citation_no_authors():
    entry = {"title": "Rapamycin effects on aging: a comprehensive review", "year": 2024}
    citation = _format_citation(entry)
    assert "2024" in citation
    assert "Rapamycin effects on aging" in citation


def test_format_citation_no_authors_no_year():
    entry = {"title": "Test paper on longevity"}
    citation = _format_citation(entry)
    assert "n.d." in citation


def test_format_citation_empty():
    entry = {}
    citation = _format_citation(entry)
    assert "Untitled" in citation
    assert "n.d." in citation


def test_build_card_full():
    entry = {
        "title": "A meta-analysis of rapamycin in aging",
        "excerpt": "RCT design study",
        "evidence_type": "review",
        "journal": "Nature Aging",
        "authors": ["Smith, J", "Jones, A"],
        "year": 2024,
    }
    card = build_card(entry)
    assert card["citation"] == "Smith et al., 2024"
    assert card["journal"] == "Nature Aging"
    assert card["quality_signal"] == "meta-analysis"


def test_build_card_minimal():
    entry = {"title": "Test", "evidence_type": "primary"}
    card = build_card(entry)
    assert "citation" in card
    assert card["journal"] == ""
    assert card["quality_signal"] == "primary"


def test_build_card_no_journal():
    entry = {
        "title": "Rapamycin study",
        "evidence_type": "primary",
        "authors": ["Lee, M"],
        "year": 2023,
    }
    card = build_card(entry)
    assert card["journal"] == ""
    assert card["citation"] == "Lee, 2023"


def test_build_card_has_new_fields():
    """Evidence cards must include study_type, population, intervention, outcomes."""
    entry = {
        "title": "A randomized controlled trial of rapamycin in older adults with longevity outcomes",
        "excerpt": "RCT design",
        "evidence_type": "primary",
        "journal": "Nature Aging",
        "authors": ["Smith, J"],
        "year": 2024,
    }
    card = build_card(entry)
    assert card["study_type"] == "rct"
    assert "older adults" in card["population"]
    assert "rapamycin" in card["intervention"]
    assert "longevity" in card["outcomes"]


def test_build_card_infer_study_type_meta():
    entry = {"title": "A meta-analysis of rapamycin in aging", "evidence_type": "review"}
    assert _infer_study_type(entry) == "meta-analysis"


def test_reviewish_primary_title_infers_review_type():
    entry = {
        "title": "The Role of Cellular Senescence and SASP in Atherosclerosis and the Therapeutic Potential of Senolytic Strategies",
        "evidence_type": "primary",
    }
    assert _infer_quality_signal(entry) == "review"
    assert _infer_study_type(entry) == "review"


def test_build_card_infer_study_type_cohort():
    entry = {"title": "Prospective cohort study of exercise", "evidence_type": "primary"}
    assert _infer_study_type(entry) == "cohort"


def test_build_card_infer_study_type_protocol():
    entry = {"title": "Metformin and longevity: protocol for a randomized trial", "evidence_type": "primary"}
    assert _infer_study_type(entry) == "protocol"


def test_build_card_empty_fields_when_no_match():
    entry = {"title": "Some unrelated paper", "evidence_type": "primary"}
    card = build_card(entry)
    assert card["population"] == ""
    assert card["intervention"] == ""
    assert card["outcomes"] == ""


def test_build_card_clinical_trial():
    entry = {
        "title": "A clinical trial of metformin treatment in diabetes patients",
        "excerpt": "double-blind placebo-controlled study",
        "evidence_type": "interventional",
    }
    card = build_card(entry)
    assert card["study_type"] in {"rct", "clinical-trial"}
    assert "metformin" in card["intervention"]
    assert "patients" in card["population"]


def test_infer_quality_signal_primary():
    entry = {"evidence_type": "primary", "title": "Rapamycin study", "excerpt": "observational data"}
    assert _infer_quality_signal(entry) == "primary"


def test_build_card_assigns_high_grade_to_recent_review():
    card = build_card(
        {
            "title": "Rapamycin and aging: a systematic review",
            "excerpt": "Systematic review of aging outcomes in older adults.",
            "evidence_type": "review",
            "year": 2024,
        }
    )
    assert card["evidence_grade"] == "H"
    assert card["context"] == "aging"


def test_build_card_assigns_low_grade_to_mechanism_context():
    card = build_card(
        {
            "title": "Everolimus mechanism of action",
            "excerpt": "mTOR inhibitor mechanism in oncology indications.",
            "evidence_type": "mechanism",
            "source_type": "chembl",
            "year": 2025,
        }
    )
    assert card["evidence_grade"] == "L"
    assert card["context"] == "oncology"


def test_build_card_assigns_low_grade_to_protocol():
    card = build_card(
        {
            "title": "Metformin and longevity: rationale and design for a clinical trial",
            "excerpt": "Study protocol in older adults.",
            "evidence_type": "primary",
            "year": 2024,
        }
    )
    assert card["study_type"] == "protocol"
    assert card["quality_signal"] == "protocol"
    assert card["evidence_grade"] == "L"


def test_build_card_uses_full_text_for_extraction():
    card = build_card(
        {
            "title": "Minimal abstract title",
            "excerpt": "",
            "full_text": "Methods: older adults received rapamycin intervention. Outcomes included frailty and mortality.",
            "evidence_type": "primary",
            "full_text_source": "europepmc",
        }
    )
    assert "older adults" in card["population"]
    assert "rapamycin" in card["intervention"]
    assert "frailty" in card["outcomes"]
    assert card["full_text_found"] is True
    assert card["full_text_source"] == "europepmc"


def test_build_card_prefers_structured_extraction_when_present():
    card = build_card(
        {
            "title": "Metformin paper",
            "excerpt": "",
            "evidence_type": "primary",
            "extraction": {
                "population": "older adults with diabetes",
                "intervention": "metformin",
                "primary_outcome": "all-cause mortality",
                "comparator": "placebo",
                "methods_summary": "double-blind randomized trial",
                "risk_of_bias": "low",
                "effects": [
                    {
                        "outcome": "all-cause mortality",
                        "metric": "HR",
                        "value": "0.77",
                        "ci_low": "0.65",
                        "ci_high": "0.91",
                        "p_value": "0.002",
                        "n": "1240",
                        "source_span": "HR 0.77 (95% CI 0.65-0.91).",
                    }
                ],
                "extractor_version": "tier1.5-v1",
            },
        }
    )
    assert card["population"] == "older adults with diabetes"
    assert card["intervention"] == "metformin"
    assert card["outcomes"] == "all-cause mortality"
    assert card["effects"][0]["metric"] == "HR"
    assert card["extraction_found"] is True
