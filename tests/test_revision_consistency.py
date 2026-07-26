from __future__ import annotations

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
    assert all(revision_quality_proof_is_stated(fixed, ask, ROWS) for ask in ASKS)
    assert revision_coverage.deterministic_unmet_asks(fixed, ASKS, evidence_rows=ROWS) == []
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
