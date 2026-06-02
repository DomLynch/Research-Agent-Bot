from __future__ import annotations

import json
from pathlib import Path

from agent import journal_finalizer


def test_phase_f_fills_existing_empty_results_outcome_heading(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=2; claims=9 | mixed | 2 indirect | limited |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"outcome_class": "cardiometabolic", "n_claims": 4, "effect_direction": "mixed", "directness": "indirect"},
        {"outcome_class": "cardiometabolic", "n_claims": 5, "effect_direction": "null", "directness": "indirect"},
    ]}), encoding="utf-8")
    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    assert logs
    assert "### Cardiometabolic Outcomes\n\nCardiometabolic remains a separate Results slice" in fixed


def test_phase_f_does_not_render_extraction_null_as_outcome_null(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n"
        "### Results Summary\n\n"
        "- Skeletal, Fracture, and Bone: n=2; claims=142; null signal in 2/2 sources.\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"outcome_class": "skeletal_fracture_bone", "n_claims": 142, "effect_direction": "null", "directness": "review"},
        {"outcome_class": "skeletal_fracture_bone", "n_claims": 0, "effect_direction": "null", "directness": "review"},
    ]}), encoding="utf-8")
    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    assert logs
    assert "no extracted directional signal in 2/2 sources" in fixed
    assert "null signal in 2/2 sources" not in fixed


def test_phase_n_restores_short_limitations_after_finalizer(tmp_path: Path) -> None:
    from scripts.review_noise_control import restore_surface_floors

    paper = (
        "## Abstract\n\n" + ("alpha " * 160) + "\n\n"
        "## Introduction\n\n" + ("intro " * 420) + "\n\n"
        "## Background\n\n" + ("background " * 320) + "\n\n"
        "## Methods\n\n" + ("methods " * 320) + "\n\n"
        "## Results\n\n" + ("results " * 520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + ("synthesis " * 870) + "\n\n"
        "## Discussion\n\n" + ("discussion " * 820) + "\n\n"
        "## Limitations\n\n" + ("limits " * 165) + "\n\n"
        "## Conclusion\n\n" + ("conclusion " * 260) + "\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "hydrogen_water",
        "total_words": 4000,
        "section_words": {"limitations": 165},
        "receipts": [
            {
                "receipt_id": "r1",
                "outcome_class": "metabolic",
                "effect_direction": "positive",
                "directness": "direct",
                "evidence_tier": "A1",
            }
        ],
        "n_receipts": 1,
        "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 1,
    }), encoding="utf-8")
    (tmp_path / "full_paper.journal_surface.json").write_text("{}", encoding="utf-8")

    fixed, logs = restore_surface_floors(
        paper,
        tmp_path,
        [],
        journal_finalizer.FinalizerLogEntry,
    )

    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="N_surface_floor_backstop",
            rule="replace_short_section",
            n_changes=1,
            detail="Limitations: restored journal-surface floor",
        )
    ]
    limitations = fixed.split("## Limitations", 1)[1].split("## Conclusion", 1)[0]
    assert len(limitations.split()) >= 250


def test_finalize_run_applies_surface_floor_backstop_for_production_manifest(tmp_path: Path) -> None:
    paper = (
        "## Abstract\n\n" + ("alpha " * 160) + "\n\n"
        "## Introduction\n\n" + ("intro " * 420) + "\n\n"
        "## Background\n\n" + ("background " * 320) + "\n\n"
        "## Methods\n\n" + ("methods " * 320) + "\n\n"
        "## Results\n\n" + ("results " * 520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + ("synthesis " * 870) + "\n\n"
        "## Discussion\n\n" + ("discussion " * 820) + "\n\n"
        "## Limitations\n\n" + ("limits " * 165) + "\n\n"
        "## Conclusion\n\n" + ("conclusion " * 260) + "\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "hydrogen_water",
        "total_words": 4000,
        "section_words": {"limitations": 165},
        "receipts": [],
    }), encoding="utf-8")
    (tmp_path / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": False,
        "issues": [{"code": "structure_surface", "detail": "section too short: Limitations 165/250 words"}],
    }), encoding="utf-8")

    report = journal_finalizer.finalize_run(tmp_path)

    text = (tmp_path / "full_paper.md").read_text(encoding="utf-8")
    limitations = text.split("## Limitations", 1)[1].split("## Conclusion", 1)[0]
    assert len(limitations.split()) >= 250
    assert any(entry.phase == "N_surface_floor_backstop" for entry in report.entries)


def test_source_verification_transparency_is_inserted_into_methods(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add a verification transparency statement acknowledging that the reference-only source bundle "
        "limits external verification of detailed quantitative claims, and that readers should consult "
        "supplementary artifacts (manifest.json, methods_pack.json)."
    )
    paper = "## Methods\n\nWe screened sources.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_source_verification_transparency(paper, tmp_path)

    assert "source bundle and supplementary artifacts" in fixed
    assert "manifest.json" in fixed and "methods_pack.json" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_verification_transparency",
            rule="state_source_bundle_verification_boundary",
            n_changes=1,
            detail="added source-bundle verification transparency sentence to Methods",
        )
    ]


def test_source_verification_transparency_is_not_duplicated(tmp_path: Path) -> None:
    paper = (
        "## Methods\n\nThe source bundle and supplementary artifacts "
        "(manifest.json and methods_pack.json when present) define the evidence state; "
        "detailed quantitative claims should be externally verified against those artifacts "
        "and the cited source records.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )

    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": (
            "reference-only source bundle limits external verification of detailed "
            "quantitative claims; consult supplementary artifacts manifest.json and "
            "methods_pack.json"
        ),
    }))
    fixed, logs = journal_finalizer._phase_d_source_verification_transparency(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_source_verification_transparency_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Methods\n\nWe screened sources.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"

    fixed, logs = journal_finalizer._phase_d_source_verification_transparency(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_admission_funnel_clarification_repairs_numeric_inconsistency_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Resolve the numerical inconsistency in the admission funnel where "
        "'No extractable claims' and 'Admitted final sources' both equal 56."
    )
    paper = (
        "## Methods\n\n"
        "### source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 56 |\n"
        "| Admitted final sources | 56 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "Admission-bucket note:" in fixed
    assert "not an additive conservation table" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_admission_funnel_clarification",
            rule="state_non_additive_admission_buckets",
            n_changes=1,
            detail="added admission-funnel non-additive bucket clarification",
        )
    ]


def test_admission_funnel_clarification_covers_partial_binding_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify the admission funnel numbers; 'Partial/none-only claim binding: 24' "
        "and 'Partial-only candidates: 11' appear contradictory."
    )
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Mixed partial-or-none claim-binding candidates | 24 |\n"
        "| Partial-only claim-binding candidates | 11 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "claim-binding states" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_admission_funnel_clarification_is_revision_scoped(tmp_path: Path) -> None:
    paper = (
        "## Methods\n\n"
        "### source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 56 |\n"
        "| Admitted final sources | 56 |\n"
    )

    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_prior_publication_differentiation_repairs_overlap_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "High overlap with publication 5f852f5b. Differentiate angle, "
        "findings, or population to resubmit."
    )
    paper = "## Introduction\n\nThis evidence brief summarizes the current corpus.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "melatonin_aging",
        "receipts": [
            {"outcome_class": "sleep_architecture"},
            {"outcome_class": "safety_comorbidity"},
        ],
    }))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_prior_publication_differentiation(paper, tmp_path)

    assert "Prior-brief differentiation:" in fixed
    assert "angle, findings, and population boundary" in fixed
    assert "retained outcome classes" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_prior_publication_differentiation",
            rule="state_angle_findings_population_boundary",
            n_changes=1,
            detail="added prior-brief differentiation note to Introduction",
        )
    ]


def test_prior_publication_differentiation_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Introduction\n\nThis evidence brief summarizes the current corpus.\n"

    fixed, logs = journal_finalizer._phase_d_prior_publication_differentiation(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_directional_coding_note_repairs_schema_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Define the directional coding schema (null, unclear, positive, mixed) "
        "in the Evidence Landscape section so readers can audit how claims were classified."
    )
    paper = "## Evidence Landscape\n\nNo extracted directional signal dominates.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert "Directional coding note:" in fixed
    assert "Positive, negative, mixed, unclear, and null" in fixed
    assert "different outcome evidence" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_directional_coding_note",
            rule="define_directional_coding_schema",
            n_changes=1,
            detail="added directional coding schema note to Evidence Landscape",
        )
    ]


def test_evidence_boundary_note_repairs_broad_claim_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify in the abstract and key findings that the evidence is mixed and does not "
        "support broad causal or policy claims. Explicitly state that the synthesis is "
        "mechanistic and hypothesis-generating rather than definitive."
    )
    paper = "## Abstract\n\nThe evidence supports a plausible anti-aging signal.\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert "Evidence-boundary note:" in fixed
    assert "does not support broad causal or policy claims" in fixed
    assert "broad population-level proof is missing" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_boundary",
            rule="state_no_broad_population_level_proof",
            n_changes=1,
            detail="added evidence-boundary note to Abstract",
        )
    ]


def test_evidence_boundary_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Abstract\n\nThe evidence supports a plausible signal.\n"

    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_tier_directness_boundary_repairs_key_findings_conclusion_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = (
        "## Key Findings\n\nThe signal is promising.\n\n"
        "## Conclusion\n\nClinical translation remains plausible.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"evidence_tier": "B2", "directness": "indirect"},
        {"evidence_tier": "C1", "directness": "mechanistic"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_tier_directness_boundaries(paper, tmp_path)

    assert fixed.count("Evidence-tier/directness boundary") == 2
    assert "evidence tier B2, C1" in fixed
    assert "directness ratings indirect, mechanistic" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_tier_directness_boundaries",
            rule="bound_key_findings_and_conclusion_by_tier_directness",
            n_changes=2,
            detail="added tier/directness boundary note to 2 section(s)",
        )
    ]


def test_tier_directness_boundary_inserts_missing_key_findings(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = "## Results\n\nMixed evidence.\n\n## Conclusion\n\nClinical translation remains plausible.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"evidence_tier": "B1", "directness": "review"},
    ]}))

    fixed, _ = journal_finalizer._phase_d_tier_directness_boundaries(paper, tmp_path)

    assert "## Key Findings" in fixed
    assert fixed.index("## Key Findings") < fixed.index("## Results")
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_directional_coding_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Evidence Landscape\n\nNo extracted directional signal dominates.\n"

    fixed, logs = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_source_directness_breakdown_repairs_source_bundle_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify source directness: explicitly note which sources directly address "
        "the topic and aging-relevant hard endpoints versus which are adjacent."
    )
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Smith 2024",
            "outcome_class": "cardiometabolic",
            "directness": "direct",
            "evidence_tier": "A1",
        },
        {
            "citation_token": "Jones 2025",
            "outcome_class": "contextual_other",
            "directness": "mechanistic",
            "evidence_tier": "C1",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert "Source directness breakdown:" in fixed
    assert "Source Classification Map" in fixed
    assert "directness=direct" in fixed and "directness=mechanistic" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_directness_breakdown",
            rule="insert_manifest_source_directness_map",
            n_changes=1,
            detail="added source directness breakdown from 2 manifest receipt(s)",
        )
    ]


def test_source_directness_breakdown_repairs_evidence_type_metadata_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Marco 2024",
            "outcome_class": "sleep",
            "directness": "review",
            "evidence_tier": "B2",
        },
        {
            "citation_token": "Yagi 2026",
            "outcome_class": "contextual_other",
            "directness": "indirect",
            "evidence_tier": "B2",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert "Evidence_type metadata note:" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_evidence_type_note_added_when_directness_breakdown_already_exists(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Evidence Landscape\n\n"
        "Source directness breakdown: 0/2 retained sources directly address the stated topic; "
        "2/2 are adjacent or review-level.\n\n"
        "### Source Classification Map\n\n"
        "- Marco 2024: outcome=sleep; directness=review; tier=B2.\n"
        "- Yagi 2026: outcome=contextual; directness=indirect; tier=B2.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Marco 2024", "outcome_class": "sleep", "directness": "review", "evidence_tier": "B2"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert fixed.count("Source directness breakdown:") == 1
    assert "Evidence_type metadata note:" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_directness_breakdown",
            rule="insert_evidence_type_metadata_note",
            n_changes=1,
            detail="added evidence_type metadata note to Evidence Landscape",
        )
    ]


def test_section_source_grounding_repairs_section_trace_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, "
        "Limitations, and Conclusion can be traced to at least one source whose "
        "excerpt or title directly supports that specific claim."
    )
    paper = (
        "## Key Findings\n\nThe evidence is mixed.\n\n"
        "## Limitations\n\nThe corpus is indirect.\n\n"
        "## Conclusion\n\nClinical translation remains premature.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Smith 2024", "outcome_class": "cardiometabolic"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_section_source_grounding(paper, tmp_path)

    assert fixed.count("Source-grounding note") == 3
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_section_source_grounding",
            rule="insert_section_source_trace_notes",
            n_changes=3,
            detail="added source-grounding note to 3 section(s)",
        )
    ]


def test_section_source_grounding_inserts_missing_key_findings(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, "
        "Limitations, and Conclusion can be traced to at least one source whose "
        "excerpt or title directly supports that specific claim."
    )
    paper = (
        "## Abstract\n\nThe synthesis is bounded.\n\n"
        "## Results\n\nThe evidence is mixed.\n\n"
        "## Limitations\n\nThe corpus is indirect.\n\n"
        "## Conclusion\n\nClinical translation remains premature.\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Smith 2024", "outcome_class": "cardiometabolic"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_section_source_grounding(paper, tmp_path)

    assert "## Key Findings" in fixed
    assert fixed.index("## Key Findings") < fixed.index("## Results")
    assert fixed.count("Source-grounding note") == 3
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_section_source_grounding",
            rule="insert_section_source_trace_notes",
            n_changes=3,
            detail="added source-grounding note to 3 section(s)",
        )
    ]


def test_single_source_proportionality_statement_is_inserted(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "For single-source outcome classes (frailty, immune/inflammation), "
        "explicitly state upfront that these are hypothesis-generating only and "
        "reduce narrative depth accordingly to maintain proportionality."
    )
    paper = "## Evidence Landscape\n\nEvidence summary.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "frailty"},
            {"outcome_class": "immune_inflammation"},
            {"outcome_class": "cardiometabolic"},
            {"outcome_class": "cardiometabolic"},
        ]
    }))

    fixed, logs = journal_finalizer._phase_d_single_source_proportionality(paper, tmp_path)

    assert "Single-source outcome classes" in fixed
    assert "hypothesis-generating" in fixed
    assert "proportional narrative depth" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_single_source_proportionality",
            rule="state_single_source_proportionality",
            n_changes=1,
            detail="added single-source proportionality statement for 2 outcome class(es)",
        )
    ]


def test_single_source_proportionality_statement_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Evidence Landscape\n\nEvidence summary.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{"outcome_class": "frailty"}]}))

    fixed, logs = journal_finalizer._phase_d_single_source_proportionality(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_single_source_proportionality_statement_is_not_duplicated(tmp_path: Path) -> None:
    ask = "single-source outcome classes should be hypothesis-generating to maintain proportionality"
    paper = (
        "## Evidence Landscape\n\n"
        "Single-source outcome classes are treated as hypothesis-generating and receive "
        "proportional narrative depth rather than standalone evidentiary weight.\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{"outcome_class": "frailty"}]}))

    fixed, logs = journal_finalizer._phase_d_single_source_proportionality(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_actionable_gaps_section_is_inserted_for_revision_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "In the 'Gaps Identified' section, provide a numbered or prioritized list "
        "of the top 3-5 specific, actionable research gaps and future research next steps."
    )
    paper = "## Discussion\n\nEvidence remains mixed.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "glp_1_longevity",
        "receipts": [
            {"outcome_class": "mortality_survival"},
            {"outcome_class": "cardiometabolic"},
        ],
    }))

    fixed, logs = journal_finalizer._phase_d_actionable_gaps(paper, tmp_path)

    assert "## Gaps Identified" in fixed
    assert "1. Run adequately powered prospective trials" in fixed
    assert "prespecified clinical endpoints" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_actionable_gaps",
            rule="write_prioritized_actionable_gaps",
            n_changes=1,
            detail="added prioritized actionable Gaps Identified section",
        )
    ]


def test_actionable_gaps_section_replaces_weak_existing_section(tmp_path: Path) -> None:
    ask = "Gaps Identified should include actionable future research next steps."
    paper = (
        "## Gaps Identified\n\nMore work is needed.\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": []}))

    fixed, _ = journal_finalizer._phase_d_actionable_gaps(paper, tmp_path)

    assert "More work is needed" not in fixed
    assert "Standardize exposure, comparator, dose" in fixed


def test_actionable_gaps_section_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Discussion\n\nEvidence remains mixed.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"

    fixed, logs = journal_finalizer._phase_d_actionable_gaps(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_actionable_gaps_section_is_not_duplicated(tmp_path: Path) -> None:
    ask = "Gaps Identified should include actionable future research next steps."
    paper = (
        "## Gaps Identified\n\n"
        "1. Run adequately powered prospective trials in the priority population with "
        "prespecified clinical endpoints and at least 2-year follow-up so the clinical "
        "signal can be separated from short-term surrogate movement.\n"
        "2. Standardize exposure, comparator, dose, measurement timing, and endpoint definitions "
        "across populations before attempting pooled effects.\n"
        "3. Add safety endpoints in direct human studies with patient-relevant function measures.\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_actionable_gaps(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_reference_identifier_enrichment_uses_registry_ids(tmp_path: Path) -> None:
    paper = (
        "## Abstract\n\nSmith 2024 and Jones 2025 reported.\n\n"
        "## References\n\n"
        "- **Smith 2024.** Trial of X.\n"
        "- **Jones 2025.** Cohort of Y.\n"
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {
            "body_citation": "Smith 2024",
            "source_doi": "10.1000/example",
            "source_pmid": "12345678",
        },
        "r2": {"body_citation": "Jones 2025", "source_pmcid": "PMC1234567"},
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_d_reference_identifier_enrichment(paper, tmp_path)

    assert "DOI: 10.1000/example." in fixed
    assert "PMID: 12345678." in fixed
    assert "PMCID: PMC1234567." in fixed
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_reference_identifier_enrichment",
            rule="restore_registry_identifiers",
            n_changes=2,
            detail="added DOI/PMID/PMCID/caveat to 2 reference line(s)",
        )
    ]


def test_reference_identifier_enrichment_adds_missing_id_caveat(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Make every reference traceable to the source bundle and clarify missing DOI/PMID entries."
    paper = (
        "## References\n\n"
        "- **Smith 2024.** Source metadata row lacks public identifiers.\n"
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {"body_citation": "Smith 2024"},
    }), encoding="utf-8")

    fixed, _ = journal_finalizer._phase_d_reference_identifier_enrichment(paper, tmp_path)

    assert "Identifier unavailable; no DOI or PMID in source metadata." in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_reference_identifier_enrichment_preserves_existing_ids(tmp_path: Path) -> None:
    paper = (
        "## References\n\n"
        "- **Smith 2024.** Trial of X. DOI: 10.1000/example.\n"
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {"body_citation": "Smith 2024", "source_pmid": "12345678"},
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_d_reference_identifier_enrichment(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_review_noise_repairs_unreferenced_inline_citation_year() -> None:
    from scripts.review_noise_control import apply_review_noise_control

    paper = (
        "## Discussion\n\n"
        "The Week 2022 trial is cited with the wrong year.\n\n"
        "## References\n\n"
        "- **Week 2020.** Hydrogen-rich water trial.\n"
    )

    fixed, changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "Week 2022" not in fixed
    assert "Week 2020 trial" in fixed
    assert ("repair_unreferenced_citation_year", 1, "aligned 1 inline citation year(s) with References") in changes
