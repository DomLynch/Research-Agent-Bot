from __future__ import annotations

from typing import Any

from agent.revision_quality import (
    findings_map_row,
    repair_revision_quality,
    revision_quality_ask_known,
    revision_quality_proof_is_stated,
)
from scripts import revision_coverage


ROWS = [
    {
        "citation_token": "Razny 2021",
        "source_title": "Human caloric-restriction trial",
        "receipt_id": "razny",
        "directness": "direct",
        "outcome_class": "cardiometabolic",
        "effect_direction": "mixed",
        "endpoints": ["body mass index"],
        "endpoint_directions": {"body mass index": "negative"},
        "n_claims": 10,
        "p_values": ["P = 0.003"],
        "thesis_text": "The retained excerpt reports body-composition findings without an endpoint-bound exact statistic.",
        "population_summary": "adults",
    },
    {
        "citation_token": "Control 2020",
        "source_title": "Comparator trial",
        "receipt_id": "control",
        "directness": "direct",
        "outcome_class": "cardiometabolic",
        "effect_direction": "null",
        "endpoints": ["body mass index"],
        "endpoint_directions": {"body mass index": "null"},
        "n_claims": 5,
        "thesis_text": "The comparator was null on body mass index.",
        "population_summary": "adults",
    },
    {
        "citation_token": "Jorgensen 2026",
        "source_title": "Caloric restriction in overweight cats",
        "receipt_id": "jorgensen",
        "directness": "indirect",
        "outcome_class": "cardiometabolic",
        "effect_direction": "unclear",
        "endpoints": ["body weight"],
        "endpoint_directions": {"body weight": "unclear"},
        "n_claims": 2,
        "thesis_text": "A veterinary randomized trial in cats.",
        "population_summary": "cats",
    },
    {
        "citation_token": "Houston 2018",
        "source_title": "Look AHEAD physical function",
        "receipt_id": "houston",
        "directness": "review",
        "outcome_class": "muscle_function",
        "effect_direction": "unclear",
        "endpoints": ["muscle strength"],
        "endpoint_directions": {"muscle strength": "unclear"},
        "n_claims": 3,
        "thesis_text": "The retained review reports a functional finding.",
        "population_summary": "older adults",
    },
]

ASKS = [
    "Renumber and re-list the cross-outcome tensions so they form a coherent 1-N series; replace 'A fifth' with the correct ordinal or restructure.",
    "Reconcile the 'claims' totals across the Findings Map, Evidence Snapshot, Results, and the abstract so that the traceable claim count is internally consistent and externally verifiable.",
    "Add explicit per-endpoint, per-study p-value and direction mapping so that any cited statistic in the Results can be located in the source excerpt; clarify which endpoint in Razny 2021 the P = 0.003 corresponds to.",
    "Recompute the severity 4 load-bearing tensions using per-endpoint direction codes, and label tensions as coding-artifact possible where sources disagree only because of per-source direction.",
    "Add a consistent, prominent flag for Jorgensen 2026 (veterinary RCT) wherever it appears in results tables and prose, and exclude it from aggregate human accounting.",
    "Recheck direction coding for Houston 2018; the bundle supports a clearer positive functional finding than the manuscript's coded direction reflects.",
    "Remove or rephrase the Metabolic-Functional Tradeoff Framework so it does not read as an unsupported organizing claim.",
    "Add a one-paragraph substantive background with the biological and clinical rationale before the methodological framing.",
]


def test_every_number_and_unit_reviewer_ask_is_deterministic() -> None:
    ask = (
        "Align every number and unit in the abstract and conclusion with its "
        "cited evidence span."
    )

    assert revision_quality_ask_known(ask, ROWS)


PAPER = """# Research Synthesis: Caloric Restriction Effects

## Abstract

This review contains 19 high-confidence extracted claims.

## Background

The review uses a structured method.

## Evidence Landscape

Jorgensen 2026: outcome=cardiometabolic; directness=indirect.

## Results

Razny 2021 reported P = 0.003. Houston 2018 is coded direction=unclear.

## Cross-Domain Synthesis

The clearest cross-outcome tension compares proximal and distal outcomes.

Another tension compares biomarker and functional evidence.

A third tension concerns population.

A fifth and overarching tension concerns translation.

## Metabolic-Functional Tradeoff Framework

We propose a novel framework.

## Discussion

The retained sources require cautious interpretation.

## Evidence Snapshot

### Load-Bearing Tensions

- Severity 4 null vs negative: Razny 2021 vs Control 2020 - partial conflict.

- Jorgensen 2026: outcome=cardiometabolic; directness=indirect; claims=2.

## Conclusion

Houston 2018 remains direction=unclear.

## References

- Jorgensen 2026.
"""


def test_latest_reviewer_consistency_bundle_is_repaired_and_proven() -> None:
    feedback = "; ".join(ASKS)

    fixed, details = repair_revision_quality(PAPER, ROWS, feedback)

    assert set(details) == {
        "tension_series",
        "claim_total_reconciliation",
        "endpoint_tension_recompute",
        "framework_cleanup",
        "substantive_background",
        "named_direction_reconciliation",
        "named_statistic_reconciliation",
        "consistent_animal_source_flags",
    }
    assert all(revision_quality_ask_known(ask, ROWS) for ask in ASKS)
    assert all(
        revision_quality_proof_is_stated(fixed, ask, ROWS)
        for ask in ASKS if ask != ASKS[2]
    )
    assert not revision_quality_proof_is_stated(fixed, ASKS[2], ROWS)
    assert revision_coverage.deterministic_unmet_asks(
        fixed, ASKS, evidence_rows=ROWS,
    ) == [ASKS[2]]
    assert "A fourth and overarching tension" in fixed
    assert "20 high-confidence extracted claims" in fixed
    assert "extracted-claim counts across 4 included sources" in fixed
    assert "n_claims" not in fixed
    assert "manifest receipts" not in fixed
    assert "P = 0.003" not in fixed
    assert "reviewer-reconciled direction=positive" in fixed
    assert "## Metabolic-Functional Tradeoff Framework" not in fixed
    assert "coding-artifact possible" in fixed
    assert fixed.count(
        "Jorgensen 2026 [veterinary; preclinical context only; excluded from human aggregates]"
    ) == 1

    stable, second_details = repair_revision_quality(fixed, ROWS, feedback)
    assert stable == fixed
    assert second_details == []


def test_decision_grade_answer_is_scoped_to_receipt_evidence_and_idempotent() -> None:
    ask = (
        "Add a direct answer to the research question for the cardiometabolic and contextual "
        "adjacent evidence slice: state explicitly whether the direct evidence supports a "
        "decision-grade conclusion, and on what conditions."
    )
    rows: list[dict[str, Any]] = [
        {
            "citation_token": f"Direct {index}",
            "directness": "direct",
            "outcome_class": "cardiometabolic",
            "effect_direction": direction,
            "population_summary": "adults with type 2 diabetes",
        }
        for index, direction in enumerate(
            ("positive", "negative", "null", "unclear", "unclear"), start=1,
        )
    ] + [
        {
            "citation_token": "Context 1",
            "directness": "indirect",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear",
            "population_summary": "adults",
        },
        {
            "citation_token": "Immune 1",
            "directness": "direct",
            "outcome_class": "immune",
            "effect_direction": "positive",
            "population_summary": "older adults",
        },
    ]
    paper = "## Research Question\n\nDoes the evidence support action?\n\n## Conclusion\n\nBounded conclusion.\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["decision_grade_answer"]
    assert "No broad decision-grade conclusion is supported" in fixed
    assert "cardiometabolic and contextual adjacent evidence slice" in fixed
    assert "5/6 direct sources" in fixed
    assert "positive=1, negative=1, null=1, unclear=2" in fixed
    assert "adults with type 2 diabetes" in fixed
    assert "older adults" not in fixed
    assert revision_quality_ask_known(ask, rows)
    assert revision_quality_proof_is_stated(fixed, ask, rows)
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []
    assert repair_revision_quality(fixed, rows, ask) == (fixed, [])


def test_decision_grade_answer_keeps_consistent_direct_slice_source_bounded() -> None:
    ask = (
        "State explicitly whether the direct evidence gives a direct answer to the research "
        "question and supports a decision-grade conclusion, including the conditions."
    )
    rows = [
        {
            "directness": "direct",
            "outcome_class": "frailty",
            "effect_direction": "null",
            "population_summary": "older adults",
        }
        for _ in range(4)
    ]

    fixed, _details = repair_revision_quality(
        "## Conclusion\n\nBounded conclusion.\n", rows, ask,
    )

    assert "No broad decision-grade conclusion is supported" in fixed
    assert "direct sources converge on a source-bounded null direction" in fixed
    assert "4/4 direct sources" in fixed


def test_exclusion_count_and_directness_classification_are_reconciled() -> None:
    ask = (
        "Reconcile the Methods' 0-exclusion claim with the Abstract's claim that 2/4 sources "
        "are indirect/adjacent; present this as a directness classification, not an exclusion."
    )
    rows = [
        {"directness": directness, "outcome_class": "cardiometabolic"}
        for directness in ("direct", "direct", "indirect", "review")
    ]
    paper = (
        "## Abstract\n\nEvidence scope: 2/4 sources are indirect or adjacent.\n\n"
        "## Methods\n\nOf 4 records screened, 4 were included and 0 were excluded at full-text review.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["directness_flow_reconciliation"]
    assert "All 4 retained sources remain in the descriptive map" in fixed
    assert "2/4 are classified as indirect" in fixed
    assert "0 full-text exclusions" in fixed
    assert "different stages and are not contradictory" in fixed
    assert revision_quality_ask_known(ask, rows)
    assert revision_quality_proof_is_stated(fixed, ask, rows)
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []
    assert repair_revision_quality(fixed, rows, ask) == (fixed, [])


def test_latest_metformin_consistency_feedback_is_repaired_generically() -> None:
    asks = [
        (
            "Reconcile the immune outcome class internally: either describe Schiapaccassa 2019 as concordant "
            "anti-inflammatory direction across endpoints (matching the Results paragraph) and remove 'mixed' "
            "from the Findings Map direction, or describe the class as heterogeneous with mixed findings. "
            "Do not both label it mixed in the table and concordant in the prose."
        ),
        (
            "Either remove the external reference citations (Ioannidis 2005, Perera 2006, Studenski 2011, "
            "Cesari 2009, Cruz-Jentoft 2019, Bohannon 1997) from manuscript text or add them to the source "
            "bundle with verification tokens. Currently they appear as authoritative anchors without bundle provenance."
        ),
        (
            "Reconcile the denominator in the Conclusion's direct-source count (2+2+1+6=11 of 26 vs 15 total "
            "direct sources) and clearly state which outcome slice the count applies to."
        ),
        (
            "Decide consistently on the mechanistic-evidence framing: either explicitly separate the "
            "mechanistic/biomarker RCTs (Mueller 2021, Marcelo-Calvo 2026, Tavabi 2021, Effects of Metformin "
            "on Biomarkers 2026, Bilusic 2026) into a separate evidence tier or correct the Introduction "
            "claim that the corpus contains 'no sources classified primarily as mechanistic or model-system evidence'."
        ),
        (
            "Tighten the Cross-Domain Synthesis so that load-bearing tensions match the direction-codes in "
            "the Findings Map (e.g., the 'null vs negative' Qin 2025 vs Agarwal 2026 entry uses the same "
            "generic 'endpoint-distance/population-stratified' explanation for every tension, which is "
            "template prose, not synthesis)."
        ),
        (
            "Correct the Methods section to remove the implication of quantitative pooling that does not occur, "
            "or add the pooling artifact."
        ),
    ]
    rows = [
        {
            "citation_token": "Schiapaccassa 2019",
            "directness": "direct",
            "outcome_class": "immune",
            "effect_direction": "mixed",
            "population_summary": "older adults",
        },
        {
            "citation_token": "Qin 2025",
            "directness": "direct",
            "outcome_class": "cardiometabolic",
            "effect_direction": "null",
            "population_summary": "adults",
        },
        {
            "citation_token": "Agarwal 2026",
            "directness": "direct",
            "outcome_class": "cardiometabolic",
            "effect_direction": "negative",
            "population_summary": "adults",
        },
        *[
            {
                "citation_token": f"Direct {index} 2024",
                "directness": "direct",
                "outcome_class": "cardiometabolic",
                "effect_direction": "unclear",
            }
            for index in range(12)
        ],
        {"citation_token": "Context 2023", "directness": "indirect", "outcome_class": "contextual_other"},
    ]
    paper = """## Evidence Landscape

The corpus contains no sources classified primarily as mechanistic evidence.
Findings Map: Qin 2025 outcome=cardiometabolic, direction=null, directness=direct.
Findings Map: Agarwal 2026 outcome=cardiometabolic, direction=negative, directness=direct.

## Methods

Quantitative pooling applied only where >=3 sources reported comparable endpoints.

## Results

Within-corpus tension is resolved as agreement rather than disagreement: both Schiapaccassa 2019 and
another trial are coded as reporting a negative effect, and the profile is directionally concordant
and anti-inflammatory.

## Cross-Domain Synthesis

- Qin 2025 versus Agarwal 2026: null vs negative. Leading explanations: Effect is endpoint-distance
dependent; Effect is population-stratified.

## Conclusion

Decision-grade answer: No broad decision-grade conclusion is supported for the cardiometabolic evidence slice. The retained slice contains 11/26 direct sources.
**Direct-source ceiling:** The direct clinical source set is Qin 2025; Agarwal 2026. The remaining 14 accepted sources are indirect.
Ioannidis 2005 defines the surrogate boundary. Perera 2006 and Studenski 2011 define gait thresholds.
Cesari 2009, Cruz-Jentoft 2019, and Bohannon 1997 provide external numeric anchors.

## References

- **Ioannidis 2005.** External reference.
- **Perera 2006.** External reference.
"""
    feedback = "; ".join(asks)

    fixed, details = repair_revision_quality(paper, rows, feedback)

    assert set(details) == {
        "named_direction_reconciliation",
        "unbundled_citation_cleanup",
        "decision_denominator_reconciliation",
        "mechanistic_content_framing",
        "cross_domain_tension_specificity",
        "pooling_claim_cleanup",
    }
    assert all(revision_quality_ask_known(ask, rows) for ask in asks)
    assert all(revision_quality_proof_is_stated(fixed, ask, rows) for ask in asks)
    assert revision_coverage.deterministic_unmet_asks(fixed, asks, evidence_rows=rows) == []
    assert "reviewer-reconciled direction=mixed" in fixed
    assert "directionally concordant" not in fixed
    assert "heterogeneous across inflammatory endpoints" in fixed
    assert "14/14 direct sources" in fixed
    assert "14/14 direct-source fraction applies only to the cardiometabolic evidence slice" in fixed
    assert "all-corpus direct-source denominator is 15/16" in fixed
    assert "The corpus contains 15 direct clinical sources" in fixed
    assert "10 additional direct sources are listed in the Findings Map" in fixed
    assert "direct clinical source set is" not in fixed
    assert "No quantitative pooling was performed" in fixed
    assert fixed.count("No quantitative pooling was performed") == 1
    assert "Leading explanations:" not in fixed
    assert "Qin 2025 versus Agarwal 2026" not in fixed
    assert "Qin 2025: direction=null" in fixed
    assert "Agarwal 2026: direction=negative" in fixed
    assert "Ioannidis 2005" not in fixed
    assert "Perera 2006" not in fixed
    assert "Mechanistic-content clarification:" in fixed

    stable, second_details = repair_revision_quality(fixed, rows, feedback)
    assert stable == fixed
    assert second_details == []


def test_denominator_repair_fails_closed_without_a_named_scope() -> None:
    ask = "Reconcile the direct-source denominator and state which outcome slice it applies to."
    paper = "## Conclusion\n\nDecision-grade answer: The retained slice contains 2/9 direct sources.\n"
    rows = [{"directness": "direct", "outcome_class": "immune"}]

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert fixed == paper
    assert details == []
    assert revision_quality_proof_is_stated(fixed, ask, rows) is False


def test_unbundled_cleanup_preserves_bundle_grounded_result_sentence() -> None:
    ask = "Remove the external reference citation Ioannidis 2005 because it lacks bundle provenance."
    rows = [{"citation_token": "Trial 2024", "directness": "direct", "outcome_class": "immune"}]
    paper = (
        "## Results\n\nTrial 2024 [bundle:1] reported a 20% reduction, consistent with Ioannidis 2005.\n\n"
        "## References\n\n- **Ioannidis 2005.** External reference.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["unbundled_citation_cleanup"]
    assert "Trial 2024 [bundle:1] reported a 20% reduction." in fixed
    assert "Ioannidis 2005" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_unbundled_cleanup_preserves_exact_source_doi() -> None:
    ask = "Remove the external reference citation Ioannidis 2005 because it lacks bundle provenance."
    rows = [{"citation_token": "Park 2024", "directness": "direct", "outcome_class": "cardiometabolic"}]
    source_sentence = (
        "Most cardiometabolic RCTs (Park 2024 [bundle:2]) report HbA1c as the primary endpoint, "
        "which Ioannidis 2005 flags as a surrogate whose hard-outcome association is imperfect "
        "[exact source: https://doi.org/10.4093/dmj.2023.0259]."
    )
    paper = f"## Limitations\n\n{source_sentence}\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["unbundled_citation_cleanup"]
    assert (
        "Most cardiometabolic RCTs (Park 2024 [bundle:2]) report HbA1c as the primary endpoint "
        "[exact source: https://doi.org/10.4093/dmj.2023.0259]."
    ) in fixed
    assert ".org/" not in fixed.replace("doi.org/", "")
    assert "Ioannidis 2005" not in fixed


def test_unbundled_cleanup_preserves_bundled_source_in_mixed_parenthetical() -> None:
    ask = "Remove the external reference citation Ioannidis 2005 because it lacks bundle provenance."
    rows = [{"citation_token": "Trial 2024", "directness": "direct", "outcome_class": "immune"}]
    paper = "## Results\n\nTrial 2024 reported the endpoint (Ioannidis 2005; Trial 2024 [bundle:1]).\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["unbundled_citation_cleanup"]
    assert fixed == "## Results\n\nTrial 2024 reported the endpoint (Trial 2024 [bundle:1])."
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_cross_domain_repair_uses_findings_map_resolved_direction() -> None:
    ask = (
        "Tighten the Cross-Domain Synthesis tension for Null 2025 versus Control 2026 so direction-codes "
        "match the Findings Map and template prose is removed."
    )
    rows: list[dict[str, Any]] = [
        {
            "citation_token": "Null 2025",
            "directness": "direct",
            "outcome_class": "immune",
            "effect_direction": "null",
            "source_title": "Higher inflammation risk",
            "thesis_text": "Higher inflammation risk was reported (p=0.01).",
            "p_values": ["p=0.01"],
        },
        {
            "citation_token": "Control 2026",
            "directness": "direct",
            "outcome_class": "immune",
            "effect_direction": "positive",
        },
    ]
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "- Null 2025 versus Control 2026: null versus positive. "
        "Leading explanations: endpoint-distance/population-stratified.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["cross_domain_tension_specificity"]
    assert "Null 2025 versus Control 2026" not in fixed
    assert "direction=negative" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_cross_domain_repair_removes_stale_bundled_tension() -> None:
    ask = (
        "Tighten the Cross-Domain Synthesis so that load-bearing tensions match the direction-codes "
        "in the Findings Map for Qin 2025 versus Agarwal 2026."
    )
    rows = [
        {
            "citation_token": "Qin 2025",
            "outcome_class": "cardiometabolic",
            "effect_direction": "unclear",
            "source_title": "No clear primary-endpoint direction",
        },
        {
            "citation_token": "Agarwal 2026",
            "outcome_class": "cardiometabolic",
            "effect_direction": "negative",
        },
    ]
    paper = (
        "## Cross-Domain Synthesis\n\n### Load-Bearing Tensions\n\n"
        "- Qin 2025 [bundle:3] versus Agarwal 2026 [bundle:16]: "
        "a Cardiometabolic null vs negative tension. Leading explanations: generic template.\n\n"
        "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n"
        "- Severity 4 null vs negative: Qin 2025 [bundle:3] vs Agarwal 2026 [bundle:16]: stale conflict.\n"
        "- Severity 4 negative vs null: Agarwal 2026 [bundle:16] vs Qin 2025 [bundle:3]: reversed stale conflict.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["cross_domain_tension_specificity"]
    assert "null vs negative tension" not in fixed
    assert "Qin 2025 [bundle:3] versus Agarwal 2026 [bundle:16]" not in fixed
    assert "Severity 4 null vs negative: Qin 2025 [bundle:3]" not in fixed
    assert "Severity 4 negative vs null: Agarwal 2026 [bundle:16]" not in fixed
    assert "Qin 2025: direction=unclear" in fixed
    assert "Agarwal 2026: direction=negative" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_mixed_repair_preserves_source_specific_results() -> None:
    ask = (
        "Reconcile Schiapaccassa 2019 labelled mixed in the table but directionally concordant in prose; "
        "do not both label it mixed and concordant."
    )
    rows = [{
        "citation_token": "Schiapaccassa 2019",
        "directness": "direct",
        "outcome_class": "immune",
        "effect_direction": "mixed",
    }]
    paper = (
        "## Results\n\nSchiapaccassa 2019 randomized 120 participants and reported the CRP estimate. "
        "The endpoints were directionally concordant and anti-inflammatory, meaning both Schiapaccassa 2019 "
        "and Comparator 2020 trend in the direction of reduced inflammation against their respective controls. "
        "The profile is directionally heterogeneous - anti-inflammatory - across panels.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["named_direction_reconciliation"]
    assert "randomized 120 participants" in fixed
    assert "reported the CRP estimate" in fixed
    assert "heterogeneous across inflammatory endpoints" in fixed
    assert "do not establish one shared source-level direction" in fixed
    assert "trend in the direction of reduced inflammation" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_mechanistic_note_is_derived_from_manifest_classification() -> None:
    ask = (
        "Correct the claim that there are no sources classified primarily as mechanistic and reconcile "
        "the mechanistic content framing."
    )
    rows = [{
        "citation_token": "Biomarker 2024",
        "directness": "mechanistic",
        "outcome_class": "immune",
        "population_summary": "human adults",
    }]
    paper = "## Evidence Landscape\n\nThe corpus contains no sources classified primarily as mechanistic evidence.\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["mechanistic_content_framing"]
    assert "Biomarker 2024 (Human mechanistic / biomarker study)" in fixed
    assert "No retained source is classified primarily as mechanistic" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_pooling_repair_removes_generic_positive_meta_analysis_claim() -> None:
    ask = "Remove the implication of quantitative pooling that does not occur, or add the pooling artifact."
    rows: list[dict[str, Any]] = []
    paper = (
        "## Methods\n\nWe conducted a random-effects meta-analysis of all retained risk ratios. "
        "Study eligibility was assessed independently.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["pooling_claim_cleanup"]
    assert "random-effects meta-analysis" not in fixed
    assert "Study eligibility was assessed independently." in fixed
    assert "No quantitative pooling was performed" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows)


def test_tension_series_repairs_the_prefixed_out_of_sequence_ordinals() -> None:
    paper = """## Results

The fourth tension compares proximal and distal outcomes.

The fifth tension compares biomarker and functional evidence.

## Cross-Domain Synthesis

The evidence is interpreted across outcome classes.
"""
    ask = ASKS[0]

    fixed, details = repair_revision_quality(paper, [], ask)

    assert details == ["tension_series"]
    assert "The first tension" in fixed
    assert "A second tension" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, [])


def test_animal_receipt_is_never_rendered_as_human_outcome_evidence() -> None:
    outcome, _source, _direction, directness, _tier, role, _finding = findings_map_row(ROWS[2])

    assert outcome == "Animal/Preclinical Context (Cardiometabolic)"
    assert directness == "directness=animal/preclinical context"
    assert role.startswith("outcome=Animal/Preclinical Context")


def test_animal_flag_does_not_reclassify_a_human_row_that_mentions_it() -> None:
    paper = """## Results

- Human 2020: outcome=muscle function; directness=indirect. Jorgensen 2026 provides context.

## References

- Jorgensen 2026.
"""
    ask = ASKS[4]

    fixed, _details = repair_revision_quality(paper, ROWS, ask)

    assert "Human 2020: outcome=muscle function; directness=indirect." in fixed
    assert (
        "Jorgensen 2026 [veterinary; preclinical context only; excluded from human aggregates]"
        in fixed
    )


def test_endpoint_tensions_exclude_source_level_only_directions() -> None:
    rows = [
        {
            "citation_token": "Source 2024",
            "outcome_class": "cardiometabolic",
            "effect_direction": direction,
            "endpoints": ["body mass index"],
        }
        for direction in ("positive", "null")
    ]
    paper = "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n- Severity 4 source-level conflict.\n"

    fixed, _details = repair_revision_quality(paper, rows, ASKS[3])

    assert "No endpoint-coded severity-4 tension is retained." in fixed
    assert "endpoint-coded conflict" not in fixed


def test_endpoint_tensions_use_canonical_severity_and_exact_proof() -> None:
    rows = [
        {
            "citation_token": f"Source {year}",
            "outcome_class": "cardiometabolic",
            "endpoint_directions": {"body mass index": direction},
        }
        for year, direction in ((2024, "positive"), (2025, "negative"))
    ]
    paper = "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n- Severity 4 invented conflict.\n"

    assert not revision_quality_proof_is_stated(paper, ASKS[3], rows)
    fixed, _details = repair_revision_quality(paper, rows, ASKS[3])

    assert "Severity 5 disagreement" in fixed
    assert "Severity 4 invented conflict" not in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[3], rows)


def test_requested_direction_uses_supported_value_not_negated_current_value() -> None:
    paper = "## Results\n\nHouston 2018 is coded direction=negative.\n"
    row = {**ROWS[3], "effect_direction": "negative"}
    asks = (
        "Recheck direction coding for Houston 2018; the bundle supports positive, "
        "not the negative direction currently shown.",
        "Recheck direction coding for Houston 2018; the bundle supports null "
        "rather than positive direction currently shown.",
        "Recheck direction coding for Houston 2018; the evidence does not support "
        "positive and it should be coded as null.",
        "Recheck direction coding for Houston 2018; the evidence does not clearly "
        "support positive and it should remain null.",
        "Recheck direction coding for Houston 2018; no evidence supports positive, "
        "so retain null.",
    )

    positive, _details = repair_revision_quality(paper, [row], asks[0])
    null, _details = repair_revision_quality(paper, [row], asks[1])
    negated, _details = repair_revision_quality(paper, [row], asks[2])
    qualified, _details = repair_revision_quality(paper, [row], asks[3])
    no_evidence, _details = repair_revision_quality(paper, [row], asks[4])

    assert "reviewer-reconciled direction=positive" in positive
    assert "reviewer-reconciled direction=null" in null
    assert "reviewer-reconciled direction=null" in negated
    assert "reviewer-reconciled direction=null" in qualified
    assert "reviewer-reconciled direction=null" in no_evidence


def test_named_statistic_repair_requires_the_requested_effect_estimate() -> None:
    row = {
        "citation_token": "Study 2025",
        "source_title": "Trial with HR = 0.72 and SMD = -0.31",
        "thesis_text": "The source reports HR = 0.72 and SMD = -0.31.",
        "outcome_class": "longevity",
        "effect_direction": "positive",
    }
    ask = (
        "For Study 2025, verify and transcribe the exact effect estimate "
        "HR = 0.72 from the source excerpt."
    )
    paper = "## Results\n\nStudy 2025 [bundle:1] reports SMD = -0.31.\n"

    assert not revision_quality_proof_is_stated(paper, ask, [row])
    fixed, details = repair_revision_quality(paper, [row], ask)

    assert "named_statistic_reconciliation" in details
    assert "retains HR = 0.72 as bundle-traceable" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, [row])


def test_named_statistic_correction_requires_requested_metric_family() -> None:
    row = {
        "citation_token": "Study 2025",
        "source_title": "Trial with HR = 0.72 and SMD = -0.31",
        "thesis_text": "The source reports HR = 0.72 and SMD = -0.31.",
        "outcome_class": "longevity",
        "effect_direction": "positive",
    }
    ask = "For Study 2025, correct the reported HR = 0.72 using the source excerpt."
    paper = "## Results\n\nStudy 2025 [bundle:1] reports SMD = -0.31.\n"

    assert revision_quality_proof_is_stated(paper, ask, [row]) is False


def test_named_statistic_must_be_bound_to_the_requested_source() -> None:
    smith = {
        "citation_token": "Smith 2025", "source_title": "Smith trial",
        "thesis_text": "The source reports RR = 0.81.",
        "outcome_class": "longevity", "effect_direction": "positive",
    }
    jones = {
        "citation_token": "Jones 2025", "source_title": "Jones trial",
        "thesis_text": "The source reports HR = 0.72.",
        "outcome_class": "longevity", "effect_direction": "positive",
    }
    ask = "For Smith 2025, correct the reported HR = 0.72 using the source excerpt."
    paper = (
        "## Results\n\nSmith 2025 [bundle:1] reports RR = 0.81; "
        "Jones 2025 [bundle:2] reports HR = 0.72.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, [smith, jones]) is False


def test_named_statistic_support_preserves_effect_sign() -> None:
    from agent.revision_quality import _stat_key, _stat_supported

    row = {"thesis_text": "The source reports SMD = 0.31."}
    assert _stat_key("SMD = -0.31") != _stat_key("SMD = 0.31")
    assert not _stat_supported("SMD = -0.31", row)


def test_animal_proof_requires_source_accounting_not_only_marker() -> None:
    marker = "[veterinary; preclinical context only; excluded from human aggregates]"
    paper = (
        "## Results\n\n"
        f"- Jorgensen 2026 {marker}: outcome=cardiometabolic; directness=direct.\n"
    )

    assert not revision_quality_proof_is_stated(paper, ASKS[4], ROWS)
    fixed, _details = repair_revision_quality(paper, ROWS, ASKS[4])

    assert "outcome=animal/preclinical context" in fixed
    assert "directness=animal/preclinical context" in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[4], ROWS)


def test_animal_flag_canonicalizes_bundle_order_and_duplicates() -> None:
    marker = "[veterinary; preclinical context only; excluded from human aggregates]"
    paper = (
        "## Results\n\n"
        f"- Jorgensen 2026 [bundle:9] {marker} {marker}: "
        "outcome=cardiometabolic; directness=direct.\n"
    )

    fixed, _details = repair_revision_quality(paper, ROWS, ASKS[4])
    stable, second_details = repair_revision_quality(fixed, ROWS, ASKS[4])

    assert f"Jorgensen 2026 {marker} [bundle:9]" in fixed
    assert fixed.count(marker) == 1
    assert stable == fixed
    assert second_details == []


def test_targeted_animal_repair_preserves_other_animal_markers() -> None:
    marker = "[veterinary; preclinical context only; excluded from human aggregates]"
    mouse = {
        "citation_token": "Mouse 2020",
        "source_title": "Trial in mice",
        "directness": "indirect",
        "outcome_class": "cardiometabolic",
    }
    paper = (
        "## Results\n\n"
        f"- Mouse 2020 {marker}: outcome=animal/preclinical context; "
        "directness=animal/preclinical context.\n"
        "- Jorgensen 2026: outcome=cardiometabolic; directness=indirect.\n"
    )

    fixed, _details = repair_revision_quality(paper, [*ROWS, mouse], ASKS[4])

    assert f"Mouse 2020 {marker}" in fixed
    assert f"Jorgensen 2026 {marker}" in fixed


def test_framework_cleanup_rephrases_claim_outside_named_section() -> None:
    paper = (
        "## Discussion\n\n"
        "We propose the Metabolic Functional Tradeoff Framework as a novel organizing claim.\n\n"
        "## References\n\n"
        "- Author 2025. Metabolic Functional Tradeoff Framework.\n"
    )

    fixed, _details = repair_revision_quality(paper, ROWS, ASKS[6])

    body, _separator, references = fixed.partition("\n## References")
    assert "Metabolic Functional Tradeoff Framework" not in body
    assert "novel organizing claim" not in body
    assert "The paper describes a source-bounded metabolic and functional evidence contrast" in body
    assert "Metabolic Functional Tradeoff Framework" in references
    assert revision_quality_proof_is_stated(fixed, ASKS[6], ROWS)


def test_framework_cleanup_keeps_embedded_sentence_grammatical() -> None:
    paper = (
        "## Discussion\n\n"
        "The paper applies the Metabolic-Functional Tradeoff Framework to the retained outcomes.\n"
    )

    fixed, _details = repair_revision_quality(paper, ROWS, ASKS[6])

    assert "applies the source-bounded metabolic and functional evidence contrast" in fixed
    assert "applies The source map" not in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[6], ROWS)


def test_framework_cleanup_removes_article_variant_and_novel_model() -> None:
    paper = (
        "## Discussion\n\n"
        "We propose a Metabolic-Functional Tradeoff Framework as a novel model.\n"
    )

    fixed, _details = repair_revision_quality(paper, ROWS, ASKS[6])

    assert "We propose a source-bounded" not in fixed
    assert "novel model" not in fixed
    assert "The paper describes a source-bounded" in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[6], ROWS)


def test_cross_stratum_direction_difference_is_not_load_bearing() -> None:
    rows = [
        {
            "citation_token": "Human 2024",
            "outcome_class": "cardiometabolic",
            "directness": "direct",
            "endpoint_directions": {"body mass index": "positive"},
        },
        {
            "citation_token": "Mouse 2025",
            "source_title": "Mechanistic trial in mice",
            "outcome_class": "cardiometabolic",
            "directness": "mechanistic",
            "endpoint_directions": {"body mass index": "null"},
        },
    ]
    paper = "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n- Severity 4 invalid conflict.\n"

    fixed, _details = repair_revision_quality(paper, rows, ASKS[3])

    assert "No endpoint-coded severity-4 tension is retained." in fixed
    assert "null vs positive" not in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[3], rows)


def test_direct_labelled_animal_is_not_a_human_load_bearing_tension() -> None:
    rows = [
        {
            "citation_token": "Human 2024",
            "source_title": "Randomized trial in adults",
            "outcome_class": "cardiometabolic",
            "directness": "direct",
            "endpoint_directions": {"body mass index": "positive"},
        },
        {
            "citation_token": "Mouse 2025",
            "source_title": "Mechanistic trial in mice",
            "outcome_class": "cardiometabolic",
            "directness": "direct",
            "endpoint_directions": {"body mass index": "null"},
        },
    ]
    paper = "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n- Severity 4 invalid conflict.\n"

    fixed, _details = repair_revision_quality(paper, rows, ASKS[3])

    assert "No endpoint-coded severity-4 tension is retained." in fixed
    assert "null vs positive" not in fixed


def test_indirect_human_and_mechanistic_animal_are_not_load_bearing() -> None:
    rows = [
        {
            "citation_token": "Human 2024",
            "source_title": "Observational study in adults",
            "outcome_class": "cardiometabolic",
            "directness": "indirect",
            "endpoint_directions": {"body mass index": "positive"},
        },
        {
            "citation_token": "Mouse 2025",
            "source_title": "Mechanistic trial in mice",
            "outcome_class": "cardiometabolic",
            "directness": "mechanistic",
            "endpoint_directions": {"body mass index": "negative"},
        },
    ]
    paper = "## Evidence Snapshot\n\n### Load-Bearing Tensions\n\n- Severity 5 invalid conflict.\n"

    fixed, _details = repair_revision_quality(paper, rows, ASKS[3])

    assert "No endpoint-coded severity-4 tension is retained." in fixed
    assert "Severity 5" not in fixed
    assert revision_quality_proof_is_stated(fixed, ASKS[3], rows)


def test_mechanistic_animal_row_is_reclassified_and_proven() -> None:
    row = {
        "citation_token": "Mouse 2020",
        "source_title": "Mechanistic trial in mice",
        "directness": "mechanistic",
        "outcome_class": "cardiometabolic",
    }
    ask = (
        "Add a consistent prominent flag for Mouse 2020 as animal/preclinical evidence "
        "wherever it appears and exclude it from the human aggregate."
    )
    paper = "## Results\n\n- Mouse 2020: outcome=cardiometabolic; directness=mechanistic.\n"

    fixed, _details = repair_revision_quality(paper, [row], ask)
    outcome, _source, _direction, directness, _tier, _role, _finding = findings_map_row(row)

    assert "directness=animal/preclinical context" in fixed
    assert "outcome=animal/preclinical context" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, [row])
    assert outcome.startswith("Animal/Preclinical Context")
    assert directness == "directness=animal/preclinical context"


def test_non_actionable_animal_statement_does_not_trigger_repair() -> None:
    asks = (
        "Animal evidence is consistent with the human aggregate and needs no reclassification.",
        "Do not flag or reclassify animal evidence in the human aggregate.",
    )

    for ask in asks:
        assert not revision_quality_ask_known(ask, ROWS)
        fixed, details = repair_revision_quality(PAPER, ROWS, ask)
        assert fixed == PAPER
        assert details == []


def test_live_fasting_revision_repairs_counts_and_external_citation() -> None:
    rows = [
        {
            "citation_token": "Trial 2025",
            "source_title": "Human fasting randomized trial",
            "directness": "direct",
            "evidence_tier": "A1",
            "outcome_class": "cardiometabolic",
            "effect_direction": "positive",
        },
        {
            "citation_token": "Review 2024",
            "source_title": "Clinical fasting evidence review",
            "directness": "review",
            "evidence_tier": "B1",
            "outcome_class": "cardiometabolic",
            "effect_direction": "unclear",
        },
    ]
    asks = [
        (
            "Either explicitly enumerate which source counts as the '1 mechanistic "
            "or model-system source' in the Findings Map or remove the mechanistic-count "
            "claim from the Abstract and Methods."
        ),
        (
            "Add the surrogate-endpoint citation (Ioannidis 2005) to the References "
            "section or remove the inline citation."
        ),
    ]
    paper = (
        "## Abstract\n\n"
        "The evidence profile contains 1 direct clinical sources, 0 adjacent, review, "
        "or context sources, and 1 mechanistic or model-system source.\n\n"
        "## Methods\n\n"
        "The corpus contains 1 direct clinical sources, 0 adjacent, review, or context "
        "sources, and 1 mechanistic or model-system source.\n\n"
        "## Evidence Landscape\n\n### Findings Map\n\nRows are source coded.\n\n"
        "## Discussion\n\n"
        "Surrogate outcomes require caution (Ioannidis 2005).\n\n"
        "## References\n\n"
        "- **Ioannidis 2005.** Methodological reference.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, "; ".join(asks))

    expected = (
        "1 direct clinical sources, 1 adjacent, review, or context sources, "
        "and 0 mechanistic or model-system sources"
    )
    assert fixed.count(expected) == 2
    assert "1 mechanistic or model-system source" not in fixed
    assert "Mechanistic-content clarification:" in fixed
    assert "Ioannidis 2005" not in fixed
    assert {
        "mechanistic_content_framing",
        "unbundled_citation_cleanup",
    }.issubset(details)
    assert all(revision_quality_proof_is_stated(fixed, ask, rows) for ask in asks)
