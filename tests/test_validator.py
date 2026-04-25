from __future__ import annotations

from agent.validator import validate_citations, validate_draft_quality


def _bundle(role: str) -> list[dict]:
    return [{"role": role}]


def test_validator_flags_published_results_with_registry_language() -> None:
    draft = {"sections": {"Key Findings": "The trial is investigating durability [1]."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert any(v["severity"] == "high" and v["issue"] == "forbidden_phrase" for v in violations)


def test_validator_flags_published_results_with_ongoing_trial_language() -> None:
    draft = {"sections": {"Limitations": "The ongoing RCT remains under follow-up [1]."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert any(v["severity"] == "high" and v["issue"] == "forbidden_phrase" for v in violations)


def test_validator_flags_registered_pending_with_outcome_claim() -> None:
    draft = {"sections": {"Key Findings": "The registered study found frailty benefits [1]."}}
    violations = validate_citations(draft, _bundle("registered_pending"))
    assert any(v["severity"] == "high" and v["issue"] == "forbidden_phrase" for v in violations)


def test_validator_flags_animal_model_with_human_language() -> None:
    draft = {"sections": {"Key Findings": "Patients improved substantially [1]."}}
    violations = validate_citations(draft, _bundle("animal_model"))
    assert any(v["severity"] == "high" and v["issue"] == "forbidden_phrase" for v in violations)


def test_validator_requires_domain_hedge_for_off_domain_indirect() -> None:
    draft = {"sections": {"Key Findings": "Reduced mortality was reported [1]."}}
    violations = validate_citations(draft, _bundle("off_domain_indirect"))
    assert any(v["severity"] == "medium" and v["issue"] == "missing_hedge" for v in violations)


def test_validator_accepts_off_domain_with_explicit_hedge() -> None:
    draft = {"sections": {"Key Findings": "In oncology context, reduced mortality was reported [1]."}}
    violations = validate_citations(draft, _bundle("off_domain_indirect"))
    assert not violations


def test_validator_requires_numeric_for_published_results_in_findings() -> None:
    draft = {"sections": {"Key Findings": "Published results were reported [1]."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert any(v["issue"] == "missing_numeric" for v in violations)


def test_validator_accepts_numeric_for_published_results() -> None:
    draft = {"sections": {"Key Findings": "Published results showed 23% improvement [1]."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert not violations


def test_validator_requires_hedge_for_observational() -> None:
    draft = {"sections": {"Conclusion": "Metformin reduced mortality [1]."}}
    violations = validate_citations(draft, _bundle("observational"))
    assert any(v["issue"] == "missing_hedge" for v in violations)


def test_validator_flags_citation_out_of_range() -> None:
    draft = {"sections": {"Key Findings": "Signal was reported [2]."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert any(v["issue"] == "citation_out_of_range" and v["severity"] == "low" for v in violations)


def test_validator_clean_draft_returns_empty() -> None:
    draft = {
        "sections": {
            "Key Findings": "Published results showed 23% improvement [1].",
            "Conclusion": "In observational cohorts, an association was reported [2].",
        }
    }
    bundle = [{"role": "published_results"}, {"role": "observational"}]
    violations = validate_citations(draft, bundle)
    assert violations == []


def test_validator_flags_missing_inline_citation_in_key_findings() -> None:
    draft = {"sections": {"Key Findings": "Published results showed no significant difference in frailty after two years."}}
    violations = validate_citations(draft, _bundle("published_results"))
    assert any(v["severity"] == "high" and v["issue"] == "missing_inline_citation" for v in violations)


def test_draft_quality_validator_requires_numeric_abstract_when_structured_effects_exist() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: metformin aging older adults",
        "abstract": "This rapid review evaluates metformin in older adults and finds mixed evidence.",
        "sections": {"Key Findings": "One trial found no significant difference in frailty [1]."},
    }
    bundle = [
        {
            "role": "published_results",
            "extraction": {"effects": [{"outcome": "frailty index", "metric": "MEAN", "value": "metformin -0.1 vs placebo 0.0"}]},
        }
    ]
    violations = validate_draft_quality(draft, bundle)
    assert any(v["issue"] == "abstract_missing_numeric_effect" and v["severity"] == "high" for v in violations)


def test_draft_quality_validator_rejects_incidental_abstract_numbers_without_effect_size() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: metformin aging older adults",
        "abstract": "One trial found no significant difference in 4-month walk speed in older adults [1].",
        "sections": {"Key Findings": "One trial found no significant difference in frailty [1]."},
    }
    bundle = [
        {
            "role": "published_results",
            "extraction": {"effects": [{"outcome": "walk speed", "metric": "MEAN", "value": "0.57 vs 0.58", "p_value": "0.96"}]},
        }
    ]
    violations = validate_draft_quality(draft, bundle)
    assert any(v["issue"] == "abstract_missing_numeric_effect" and v["severity"] == "high" for v in violations)


def test_draft_quality_validator_uses_excerpt_numeric_results_when_no_structured_table_exists() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: metformin aging older adults",
        "abstract": "One trial found no significant difference in 4-month walk speed in older adults [1].",
        "sections": {"Key Findings": "One trial found no significant difference in frailty [1]."},
    }
    bundle = [
        {
            "role": "published_results",
            "excerpt": "Mean 4-m walk speed was 0.57 m/s in metformin versus 0.58 m/s in placebo (adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96).",
        }
    ]
    violations = validate_draft_quality(draft, bundle)
    assert any(v["issue"] == "abstract_missing_numeric_effect" and v["severity"] == "high" for v in violations)


def test_draft_quality_validator_flags_raw_extraction_leak_in_conclusion() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: metformin aging older adults",
        "abstract": "One trial reported no significant difference (0.57 vs 0.58) [1].",
        "sections": {
            "Conclusion": "Published results [1] report Change From Baseline in Brain PCr/ATP Ratio; mean Placebo -0.045; Metformin -0.016; p=0.854."
        },
    }
    violations = validate_draft_quality(draft, _bundle("published_results"))
    assert any(v["issue"] == "raw_extraction_template" and v["severity"] == "high" for v in violations)


def test_draft_quality_validator_flags_support_claim_missing_topic_distinction() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: metformin aging older adults",
        "abstract": "One trial reported 0.57 versus 0.58 m/s [1].",
        "sections": {
            "Key Findings": "Meta-analysis [1] reported GLP-1RAs reduced major adverse cardiovascular events."
        },
    }
    bundle = [{"role": "meta_analysis", "evidence_tier": "Tier B supporting human evidence"}]
    violations = validate_draft_quality(draft, bundle)
    assert any(v["issue"] == "missing_topic_distinction" for v in violations)


def test_draft_quality_validator_flags_conclusion_contradicting_positive_cited_finding() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: rapamycin aging older adults",
        "abstract": "One trial reported emotional well-being improved (p=0.023) [1].",
        "sections": {
            "Key Findings": "One trial found emotional well-being improved with rapamycin (p=0.023) [1].",
            "Conclusion": "One trial found no significant difference in healthspan compared with placebo [1].",
        },
    }
    violations = validate_draft_quality(draft, _bundle("published_results"))
    assert any(v["issue"] == "conclusion_contradicts_positive_finding" and v["severity"] == "high" for v in violations)


def test_draft_quality_validator_flags_duplicate_abstract_claim_for_same_citation() -> None:
    draft = {
        "title": "Rapid Evidence Synthesis: rapamycin aging older adults",
        "abstract": (
            "Self-reported emotional well-being and general health improved for those using 5 mg rapamycin [1]. "
            "A one-year randomized trial found emotional well-being and general health improved for those using 5 mg rapamycin [1]."
        ),
        "sections": {"Key Findings": "One trial found emotional well-being improved with rapamycin (p=0.023) [1]."},
    }
    violations = validate_draft_quality(draft, _bundle("published_results"))
    assert any(v["issue"] == "abstract_duplicate_cited_claim" and v["severity"] == "high" for v in violations)
