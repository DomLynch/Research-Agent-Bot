from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import revision_coverage  # type: ignore[import-not-found]  # noqa: E402


def _chat(parsed: dict[str, Any]) -> Any:
    async def fake(**_kwargs: Any) -> Any:
        return type("Resp", (), {"parsed": parsed})()
    return fake


def _unmet(asks: list[str], parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unmet_asks("MANUSCRIPT BODY", asks, chat=_chat(parsed), settings=object())


def test_unmet_asks_empty_when_all_addressed(monkeypatch) -> None:
    assert _unmet(["a", "b"], {"addressed": [True, True]}, monkeypatch) == []


def test_unmet_asks_flags_unaddressed_in_order(monkeypatch) -> None:
    assert _unmet(["hedge claims", "clarify scope"], {"addressed": [True, False]}, monkeypatch) == ["clarify scope"]


def test_unmet_asks_failopen_on_malformed_verdict(monkeypatch) -> None:
    # Length mismatch / wrong shape must not block submit.
    assert _unmet(["a", "b"], {"addressed": [True]}, monkeypatch) == []
    assert _unmet(["a"], {"addressed": "nope"}, monkeypatch) == []


def test_unmet_asks_empty_for_no_asks(monkeypatch) -> None:
    assert _unmet([], {"addressed": []}, monkeypatch) == []


def test_unmet_asks_failopen_on_judge_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unmet_asks("M", ["a"], chat=boom, settings=object()) == []


def test_deterministic_unmet_flags_missing_classification_criteria() -> None:
    ask = "Define the classification criteria used to assign studies to outcome classes and to code directness."

    assert revision_coverage.deterministic_unmet_asks("## Methods\n\nMethods.\n", [ask]) == [ask]


def test_deterministic_unmet_accepts_classification_criteria_and_map() -> None:
    paper = (
        "## Methods\n\n"
        "### Classification criteria\n\n"
        "**Outcome class** records the endpoint family. **Directness** records whether evidence is direct, "
        "indirect, mechanistic, or review. **Evidence tier** records A1, A2, B1, B2, C1, or C2.\n\n"
        "### Source classification map\n\n"
        "- Smith 2024: outcome=cardiometabolic; directness=indirect; tier=B2.\n"
    )
    asks = [
        "Define the classification criteria used to assign studies to outcome classes and to code directness.",
        "Provide a mapping table or list showing which sources were assigned to which outcome class.",
    ]

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_unmet_flags_weak_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable research gaps."
    paper = "## Gaps Identified\n\nMore research is needed because the current corpus is limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_actionable_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable future research directions."
    paper = (
        "## Gaps Identified\n\n"
        "The next study should use a powered randomized trial in an older adult priority population, "
        "with a prespecified comparator, 12-month follow-up duration, clinically meaningful endpoint "
        "selection, dose documentation, and safety monitoring. Measurement should separate sleep, "
        "functional, and cardiometabolic endpoints so the evidence gap is testable rather than generic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_unbounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = "## Conclusion\n\nThis synthesis supports a bounded geroscience rationale for clinical use.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_bounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = (
        "## Conclusion\n\n"
        "Because most directional signals are null or mixed, this synthesis is hypothesis-generating and "
        "does not support a clinical recommendation. The bounded rationale is limited to study design.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_internal_duplication() -> None:
    ask = "Remove internal duplication of content across the Evidence Landscape and Key Findings sections."
    repeated = (
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and "
        "shows that the current evidence base remains mixed, hypothesis-generating, and not sufficient "
        "for broad clinical or policy claims."
    )
    paper = f"## Evidence Landscape\n\n{repeated}\n\n## Key Findings\n\n{repeated}\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_near_duplicate_narrative() -> None:
    ask = "Remove repetitive narrative across the Evidence Landscape and Key Findings sections."
    paper = (
        "## Evidence Landscape\n\n"
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and shows "
        "that the current evidence base remains mixed, hypothesis-generating, and insufficient for broad "
        "clinical or policy claims.\n\n"
        "## Key Findings\n\n"
        "The synthesis separates direct intervention evidence from indirect biomarker evidence, showing "
        "that the current evidence base remains mixed and hypothesis-generating rather than sufficient "
        "for broad clinical policy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_non_repetitive_sections() -> None:
    ask = "Remove internal duplication and present a single, non-repetitive narrative."
    paper = (
        "## Evidence Landscape\n\n"
        "The evidence landscape separates direct intervention evidence from indirect biomarker evidence "
        "and identifies mixed signals across outcome domains.\n\n"
        "## Key Findings\n\n"
        "The key finding is that clinical translation remains premature because source directness and "
        "endpoint maturity vary across the corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = "## Abstract\n\nThe evidence is mixed.\n\n## Conclusion\n\nClinical translation remains premature.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = (
        "## Abstract\n\n"
        "The evidence is mixed, and long-term safety data in older adults remain insufficient.\n\n"
        "## Conclusion\n\n"
        "Because long-term safety in older adults is not established, clinical translation remains premature.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_reference_without_identifier() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults.\n"
        "- Jones 2025. Cohort evidence. DOI: 10.1000/example.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_reference_identifiers() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n"
        "- Jones 2025. Cohort evidence. PMID: 12345678.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_reference_identifier_caveat() -> None:
    ask = "Make every reference traceable to the source bundle and clarify missing DOI/PMID entries."
    paper = (
        "## References\n\n"
        "- Smith 2024. Registered trial. Trial registration: NCT01234567.\n"
        "- Jones 2025. Registry protocol. Identifier unavailable; no DOI or PMID in source metadata.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


_PAPER = "## Abstract\n\nEGCG reverses aging in humans.\n\n## Results\n\nMixed, mostly null.\n"


def _claims(parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unsupported_abstract_claims(_PAPER, chat=_chat(parsed), settings=object())


def test_unsupported_abstract_claims_flags_overclaim(monkeypatch) -> None:
    assert _claims({"unsupported": ["EGCG reverses aging in humans."]}, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_ignores_neutral_profile_summaries(monkeypatch) -> None:
    parsed = {
        "unsupported": [
            "The evidence profile contains no sources classified primarily as mechanistic evidence.",
            "Positive study-level signals concentrate in no dominant outcome class.",
            "positive signals concentrated in contextual cardioprotection, negative signals in cardiometabolic domains",
            "EGCG reverses aging in humans.",
        ],
    }
    assert _claims(parsed, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_empty_when_supported(monkeypatch) -> None:
    assert _claims({"unsupported": []}, monkeypatch) == []


def test_unsupported_abstract_claims_no_abstract_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    assert revision_coverage.unsupported_abstract_claims("## Results\n\nx\n", chat=_chat({"unsupported": ["x"]}), settings=object()) == []


def test_unsupported_abstract_claims_failopen_on_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unsupported_abstract_claims(_PAPER, chat=boom, settings=object()) == []


def test_numeric_effect_direction_flags_non_significant_p_value_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "non-significant p-value described as significant: Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08)."
    ]


def test_numeric_effect_direction_allows_explicit_non_significant_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_allows_not_significantly_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 did not significantly reduce LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_flags_ci_crossing_null_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "The pooled effect was statistically significant (95% CI 0.84-1.18).\n\n"
        "## Results\n\nThe confidence interval crosses the null.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "CI crossing null described as significant: The pooled effect was statistically significant (95% CI 0.84-1.18)."
    ]
