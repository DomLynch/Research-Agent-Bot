from __future__ import annotations

from agent.validator import validate_citations


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
