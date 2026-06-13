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


def test_finalize_run_preserves_unproven_human_longevity_after_surface_restore(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits "
        "are currently unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = (
        "## Abstract\n\n" + ("alpha " * 160) + "\n\n"
        "## Introduction\n\n" + ("intro " * 420) + "\n\n"
        "## Background\n\n" + ("background " * 320) + "\n\n"
        "## Methods\n\n" + ("methods " * 320) + "\n\n"
        "## Results\n\n" + ("results " * 520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + ("synthesis " * 870) + "\n\n"
        "## Discussion\n\n" + ("discussion " * 820) + "\n\n"
        "## Limitations\n\n" + ("limits " * 165) + "\n\n"
        "## Conclusion\n\nThe evidence remains incomplete and biologically plausible.\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "glp_1_longevity",
        "total_words": 4000,
        "section_words": {"limitations": 165, "conclusion": 8},
        "receipts": [],
    }), encoding="utf-8")
    (tmp_path / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": False,
        "issues": [{"code": "structure_surface", "detail": "section too short: Limitations 165/250 words"}],
    }), encoding="utf-8")

    report = journal_finalizer.finalize_run(tmp_path)
    text = (tmp_path / "full_paper.md").read_text(encoding="utf-8")

    assert "Longevity benefits are currently unproven in humans" in text
    assert revision_coverage.deterministic_unmet_asks(text, [ask]) == []
    assert any(entry.phase == "D_unproven_human_longevity" for entry in report.entries)


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


def test_classification_criteria_note_repairs_outcome_directness_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Define the classification criteria used to assign studies to outcome classes "
        "(Contextual Adjacent Evidence, Cardiometabolic, etc.) and to code directness "
        "as 'indirect', 'mechanistic', or 'review'."
    )
    paper = "## Methods\n\nSources were grouped from the manifest.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_classification_criteria_note(paper, tmp_path)

    assert "Classification criteria:" in fixed
    assert "Outcome class assignment" in fixed
    assert "Directness is coded as direct" in fixed
    assert "Evidence tier records" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_classification_criteria",
            rule="define_outcome_directness_tier_criteria",
            n_changes=1,
            detail="added outcome/directness/evidence-tier classification criteria",
        )
    ]


def test_classification_criteria_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Methods\n\nSources were grouped from the manifest.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Rewrite the Gaps Identified section with actionable future research steps.",
    }))

    fixed, logs = journal_finalizer._phase_d_classification_criteria_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_conflict_severity_note_repairs_disagreement_scoring_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add a brief explanation in the main text of how 'severity-level-3' and "
        "'severity-level-4' disagreements are defined and scored, or provide a "
        "clear pointer to the exact supplementary file where this is defined."
    )
    paper = "## Methods\n\nSources were grouped from the manifest.\n\n## Results\n\nDisagreements are summarized.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_conflict_severity_note(paper, tmp_path)

    assert "Conflict-map severity note:" in fixed
    assert "severity-level-3 disagreements are defined and scored" in fixed
    assert "severity-level-4 disagreements are defined and scored" in fixed
    assert "supplementary contradiction-map" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_conflict_severity_note",
            rule="define_conflict_map_severity_scoring",
            n_changes=1,
            detail="added severity-level disagreement scoring note",
        )
    ]


def test_conflict_severity_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Methods\n\nSources were grouped from the manifest.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Rewrite the Gaps Identified section with actionable future research steps.",
    }))

    fixed, logs = journal_finalizer._phase_d_conflict_severity_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_evidence_boundary_repairs_population_proof_calibration_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "The manuscript is technically sound and highly bounded, but per calibration rules, "
        "the explicit absence of direct clinical evidence and the reliance on adjacent/mechanistic "
        "data requires a 'revise' status to signal that broad population-level proof is missing."
    )
    paper = (
        "## Abstract\n\nThis synthesis is bounded.\n\n"
        "## Key Findings\n\nSignals are mixed.\n\n"
        "## Conclusion\n\nClinical translation remains limited.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert fixed.count("Evidence-boundary note:") == 3
    assert "broad population-level proof is missing" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_boundary",
            rule="state_no_broad_population_level_proof",
            n_changes=3,
            detail="added evidence-boundary note to 3 section(s)",
        )
    ]


def test_evidence_boundary_population_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Abstract\n\nThis synthesis is bounded.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Rewrite the Gaps Identified section with actionable future research steps.",
    }))

    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_evidence_boundary_repairs_mixed_indirect_overclaim_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add explicit language in the abstract and conclusion highlighting the mixed "
        "and indirect nature of the evidence base to preempt any overclaiming."
    )
    paper = "## Abstract\n\nResveratrol has signals.\n\n## Conclusion\n\nTranslation remains limited.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert "mixed, indirect" in fixed
    assert "does not support broad causal or policy claims" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_boundary",
            rule="state_no_broad_population_level_proof",
            n_changes=2,
            detail="added evidence-boundary note to 2 section(s)",
        )
    ]


def test_directional_coding_note_repairs_contextual_claims_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify what the contextual claims contain if no directional signal was "
        "extracted, and explain the discrepancy between the organized evidence "
        "landscape and the near-total absence of directional findings."
    )
    paper = "## Evidence Landscape\n\nNo extracted directional signal dominates.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert "Contextual claims contain bibliographic background" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_directional_coding_note_repairs_live_strongest_signal_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "In the Evidence Landscape table, the column 'Strongest signal' states "
        "'no extracted directional signal in 20/20 sources'. Given that some "
        "sources in the bundle report directional results, reconcile the table "
        "coding with the narrative."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Contextual Adjacent Evidence | no extracted directional signal in 20/20 sources |\n\n"
        "## Key Findings\n\n"
        "Some bundle sources report directional results.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert "Directional coding note:" in fixed
    assert "specific outcome class" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_directional_coding_note",
            rule="define_directional_coding_schema",
            n_changes=1,
            detail="added directional coding schema note to Evidence Landscape",
        )
    ]


def test_directional_coding_note_repairs_no_signal_proportion_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Ensure all outcome-class summaries in the 'Evidence Landscape' table explicitly "
        "note the proportion of sources with no extracted directional signal to avoid ambiguity."
    )
    paper = "## Evidence Landscape\n\n| Outcome | Strongest signal |\n|---|---|\n| Immune | no extracted directional signal |\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert "source proportion" in fixed
    assert "X/Y sources" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_directional_coding_note",
            rule="define_directional_coding_schema",
            n_changes=1,
            detail="added directional coding schema note to Evidence Landscape",
        )
    ]


def test_directional_coding_note_upgrades_existing_contextual_claims_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify what the contextual claims contain if no directional signal was "
        "extracted, and explain the discrepancy between the organized evidence "
        "landscape and the near-total absence of directional findings."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means "
        "no coded positive, negative, or mixed effect was extracted for that "
        "specific outcome class; it is not an absence-of-support finding. Positive, "
        "negative, mixed, unclear, and null are outcome-specific codes, so a bounded "
        "rationale can be supported by adjacent or different outcome evidence while "
        "another outcome remains null or unclear.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_directional_coding_note(paper, tmp_path)

    assert "Contextual claims contain bibliographic background" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_directional_coding_note",
            rule="upgrade_contextual_claims_explanation",
            n_changes=1,
            detail="expanded existing directional coding note with contextual-claims explanation",
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
    assert "## Key Findings" in fixed
    assert "does not support broad causal or policy claims" in fixed
    assert "broad population-level proof is missing" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_boundary",
            rule="state_no_broad_population_level_proof",
            n_changes=2,
            detail="added evidence-boundary note to 2 section(s)",
        )
    ]


def test_evidence_boundary_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Abstract\n\nThe evidence supports a plausible signal.\n"

    fixed, logs = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_evidence_honesty_guard_bounds_null_and_non_direct_manifest(tmp_path: Path) -> None:
    paper = (
        "## Abstract\n\nThis synthesis supports clinical translation.\n\n"
        "## Conclusion\n\nThe current corpus may support the topic as a general health or lifestyle intervention where otherwise indicated.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"effect_direction": "null", "directness": "indirect"},
            {"effect_direction": "no_extracted_directional_signal", "directness": "review"},
            {"effect_direction": "no signal", "directness": "adjacent"},
            {"effect_direction": "positive", "directness": "mechanistic"},
        ],
    }))

    fixed, logs = journal_finalizer._phase_d_evidence_honesty_guard(paper, tmp_path)
    refixed, relogs = journal_finalizer._phase_d_evidence_honesty_guard(fixed, tmp_path)

    assert fixed.count("Evidence-honesty note:") == 2
    assert "non-supportive for clinical efficacy claims" in fixed
    assert "hypothesis-generating only" in fixed
    assert "no direct interventional hard-endpoint evidence" in fixed
    assert "does not support broad causal, clinical, or policy claims" in fixed
    assert "may support the topic as a general health or lifestyle intervention" not in fixed
    assert "non-supportive for clinical efficacy or general health-intervention claims" in fixed
    assert refixed == fixed
    assert relogs == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_honesty_guard",
            rule="bound_null_signal_and_directness_claims",
            n_changes=3,
            detail="added evidence-honesty note to 2 section(s); replaced unsupported conclusion claims=1; null_or_no_signal=3/4; direct=0/4",
        )
    ]


def test_evidence_honesty_guard_preserves_count_and_reconciles_source_bundle(tmp_path: Path) -> None:
    paper = "## Abstract\n\nInitial synthesis.\n\n## Conclusion\n\nInitial conclusion.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"effect_direction": "null", "directness": "indirect"}
            for _ in range(15)
        ] + [{"effect_direction": "positive", "directness": "indirect"}],
    }))

    fixed, logs = journal_finalizer._phase_d_evidence_honesty_guard(paper, tmp_path)

    assert "15/16 retained sources are coded as null or no extracted directional signal" in fixed
    assert "Source-bundle reconciliation note:" in fixed
    assert "not a statement that the source texts contain no directional findings" in fixed
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_evidence_honesty_guard",
            rule="bound_null_signal_and_directness_claims",
            n_changes=2,
            detail="added evidence-honesty note to 2 section(s); replaced unsupported conclusion claims=0; null_or_no_signal=15/16; direct=0/16",
        )
    ]


def test_strip_surface_duplicate_paragraphs_repairs_journal_surface_gate() -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    duplicate = (
        "The retained corpus is interpreted as hypothesis-generating because it combines indirect, "
        "review-level, and adjacent mechanistic sources rather than direct interventional hard-endpoint "
        "evidence. This paragraph deliberately contains enough distinct scientific tokens for the public "
        "surface gate to treat a later repeated copy as a duplicate paragraph artifact."
    )
    paper = (
        "## Abstract\n\n"
        f"{duplicate}\n\n"
        "## Results\n\n"
        "The results table separates cardiometabolic, immune, and longevity outcomes without making a "
        "clinical efficacy claim from indirect evidence.\n\n"
        "## Discussion\n\n"
        f"{duplicate}\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )

    assert _duplicate_paragraph_issue_messages(paper)
    fixed, logs = journal_finalizer._phase_m_strip_surface_duplicate_paragraphs(paper)

    assert _duplicate_paragraph_issue_messages(fixed) == ()
    assert fixed.count(duplicate) == 1
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="M_duplicate_paragraph_strip",
            rule="remove_later_surface_duplicate_paragraphs",
            n_changes=1,
            detail="removed 1 duplicate public prose paragraph(s)",
        )
    ]


def test_surface_artifact_cleanup_repairs_grammar_and_empty_subheading() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\n"
        "### Results Summary\n\n"
        "### Metabolic Outcomes\n\n"
        "The causal bridge to be rigorously is bounded by directness and follow-up limits.\n\n"
        "A signal in one domain does not automatically is consistent with the same signal in another.\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    assert any(i.code == "grammar_artifact" for i in evaluate_journal_surface(paper).issues)
    assert any("empty heading: Results Summary" in i.detail for i in evaluate_journal_surface(paper).issues)

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    assert "### Results Summary" not in fixed
    assert "to be rigorously is" not in fixed
    assert "is rigorously bounded" in fixed
    assert "does not automatically is" not in fixed
    assert "is not automatically consistent" in fixed
    assert not any(i.code == "grammar_artifact" for i in evaluate_journal_surface(fixed).issues)
    assert not any("empty heading: Results Summary" in i.detail for i in evaluate_journal_surface(fixed).issues)
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="M_surface_artifact_cleanup",
            rule="repair_known_surface_artifacts",
            n_changes=3,
            detail="grammar_artifact=2; empty_subheading=1",
        )
    ]


def test_lane_qualifier_preserves_bullet_marker(tmp_path: Path) -> None:
    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Curran 2025"}],
        "lanes": {"Curran 2025": "animal_preclinical"},
    }))
    paper = (
        "## Results\n\n"
        "- Curran 2025 reported a model-system finding.\n\n"
        "## References\n\n- Curran 2025.\n"
    )

    fixed, logs = journal_finalizer._phase_b_lane_qualifier(paper, tmp_path)

    assert "evidence; -" not in fixed
    # Citation tokens keep their capitalization: lowercasing "Curran 2025"
    # breaks exact reference matching and trips the unreferenced-citation
    # gate (live failure: "Abu-Zaid 2025" -> "abu-Zaid 2025" on 2026-06-11).
    assert "- In animal/preclinical evidence, Curran 2025 reported" in fixed
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="B_lane_qualifier",
            rule="animal_preclinical_lead_in",
            n_changes=1,
            detail="prepended lane qualifier to 1 paragraph(s)",
        )
    ]


def test_surface_artifact_cleanup_keeps_parent_heading_with_child_content() -> None:
    paper = (
        "## Results\n\n"
        "### Results Summary\n\n"
        "#### Metabolic Outcomes\n\n"
        "The child section carries the result text.\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    assert fixed == paper
    assert logs == []


def test_relabel_public_metadata_table_headers_repairs_surface_gate(tmp_path: Path) -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=4 | mixed | indirect | short follow-up |\n\n"
        "## Discussion\n\n"
        "| Outcome class | Direct sources | Indirect / mechanism sources | Direction profile | Interpretation boundary |\n"
        "|---|---:|---:|---|---|\n"
        "| Immune | 0 | 3 | null | indirect evidence only |\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    assert any(
        "classification metadata leaked as study row" in issue.detail
        for issue in evaluate_journal_surface(paper).issues
    )
    fixed, logs = journal_finalizer._phase_m_relabel_public_metadata_table_headers(paper, tmp_path)

    assert "| Evidence domain | Corpus slice | Strongest signal | Directness | Main limitation |" in fixed
    assert "| Evidence domain | Direct sources | Indirect / mechanism sources | Direction profile | Interpretation boundary |" in fixed
    assert not any(
        "classification metadata leaked as study row" in issue.detail
        for issue in evaluate_journal_surface(fixed).issues
    )
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="M_public_metadata_header_relabel",
            rule="relabel_surface_metadata_table_headers",
            n_changes=2,
            detail="relabelled 2 public metadata table header(s)",
        )
    ]


def test_long_term_safety_scope_repairs_older_adult_safety_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add a brief statement in the abstract and conclusion about the lack of "
        "long-term safety data in older adults."
    )
    paper = "## Abstract\n\nThe evidence is mixed.\n\n## Conclusion\n\nClinical translation remains premature.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_long_term_safety_scope(paper, tmp_path)

    assert fixed.count("Long-term safety scope:") == 2
    assert "Long-term safety data in older adults remain insufficient" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_long_term_safety_scope",
            rule="state_long_term_safety_gap_in_older_adults",
            n_changes=2,
            detail="added long-term safety scope note to 2 section(s)",
        )
    ]


def test_long_term_safety_scope_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Abstract\n\nThe evidence is mixed.\n\n## Conclusion\n\nClinical translation remains premature.\n"

    fixed, logs = journal_finalizer._phase_d_long_term_safety_scope(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_unproven_human_longevity_repairs_conclusion_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits "
        "are currently unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = "## Conclusion\n\nThe evidence remains incomplete and biologically plausible.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_unproven_human_longevity(paper, tmp_path)

    assert "Longevity benefits are currently unproven in humans" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_unproven_human_longevity",
            rule="state_longevity_benefits_unproven_in_humans",
            n_changes=1,
            detail="added unproven human longevity boundary to Conclusion",
        )
    ]


def test_numeric_significance_correction_repairs_p_value_revision(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Correct the factual error in the abstract regarding Waghmare 2024: the source excerpt "
        "reports a non-significant result (p = 0.08), not a significant reduction in LF HRV power."
    )
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "non-significant reduction in LF HRV power (p = 0.08)" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_numeric_significance_correction",
            rule="repair_non_significant_numeric_effect_claims",
            n_changes=1,
            detail="corrected explicit p-value/CI significance contradictions",
        )
    ]


def test_numeric_significance_correction_keeps_existing_non_significant_wording(tmp_path: Path) -> None:
    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction."
    )
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_numeric_significance_correction_adds_audit_statement_when_requested(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction. Audit all reported "
        "p-values and effect directions."
    )
    paper = (
        "## Methods\n\nExisting methods.\n\n"
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "Numeric effect audit: all reported p-values and effect directions were checked" in fixed
    assert "non-significant reduction in LF HRV power (p = 0.08)" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].n_changes == 2


def test_numeric_significance_correction_adds_missing_named_result(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Correct the factual error in the abstract regarding Waghmare 2024: the source excerpt "
        "reports a non-significant result (p = 0.08), not a significant reduction in LF HRV power."
    )
    paper = (
        "## Abstract\n\n"
        "The HRV evidence base remains mixed across observational cohorts.\n\n"
        "## Evidence Landscape\n\n"
        "Waghmare 2024 contributed cardiometabolic evidence.\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "Numeric correction: Waghmare 2024 reported a non-significant result (p = 0.08)" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].n_changes == 1


def test_source_statistics_landscape_maps_reviewer_named_statistic(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "For cited sources with specific statistics (e.g., Weiss 2026 33% lifespan increase), "
        "ensure these appear in the evidence landscape and are connected to the appropriate "
        "outcome class rather than buried in the source bundle."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_statistics_landscape(paper, tmp_path)

    assert "Weiss 2026 is mapped to outcome class=longevity and reports 33% lifespan increase" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_statistics_landscape",
            rule="map_named_source_statistic_to_outcome_class",
            n_changes=1,
            detail="added reviewer-named source statistic to Evidence Landscape",
        )
    ]


def test_source_outcome_class_map_repairs_mapping_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"
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
            "outcome_class": "immune",
            "directness": "review",
            "evidence_tier": "B1",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "### Source Outcome-Class Map" in fixed
    assert "- Smith 2024: outcome=Cardiometabolic; directness=direct; tier=A1." in fixed
    assert "- Jones 2025: outcome=Immune; directness=review; tier=B1." in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_no_receipts_does_not_crash(tmp_path: Path) -> None:
    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_source_statistics_landscape_creates_missing_section(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "For cited sources with specific statistics (e.g., Weiss 2026 33% lifespan increase), "
        "ensure these appear in the evidence landscape and are connected to the appropriate "
        "outcome class rather than buried in the source bundle."
    )
    paper = "## Results\n\nThe corpus includes several sources.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_source_statistics_landscape(paper, tmp_path)

    assert fixed.startswith("## Evidence Landscape")
    assert "Weiss 2026 is mapped to outcome class=longevity and reports 33% lifespan increase" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_statistics_landscape"


def test_prisma_all_included_rationale_repairs_revision_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Clarify why 100% of retrieved records were included, given the stated PRISMA-ScR methodology and eligibility criteria."
    paper = "## Methods\n\nThe PRISMA-ScR flow retained all records.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_prisma_all_included_rationale(paper, tmp_path)

    assert "100% of retrieved records were included because" in fixed
    assert "prequalified eligibility criteria" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_prisma_all_included_rationale",
            rule="explain_all_retrieved_records_included",
            n_changes=1,
            detail="added PRISMA-ScR 100%-included rationale to Methods",
        )
    ]


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


def test_source_inclusion_rationale_repairs_umbrella_source_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add a note explaining why sources on adjacent biomarkers are included "
        "under the digital frailty index umbrella, given that none appear to "
        "operationalize a frailty index."
    )
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "digital_frailty_index", "receipts": [
        {
            "citation_token": "Smith 2024",
            "outcome_class": "frailty",
            "directness": "direct",
        },
        {
            "citation_token": "Jones 2025",
            "outcome_class": "contextual_other",
            "directness": "indirect",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_inclusion_rationale(paper, tmp_path)

    assert "Topic-fit rationale:" in fixed
    assert "operationalize digital frailty index directly" in fixed
    assert "reclassified as boundary evidence" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_inclusion_rationale",
            rule="state_topic_fit_rationale",
            n_changes=1,
            detail="added source inclusion rationale from 2 manifest receipt(s)",
        )
    ]


def test_source_inclusion_rationale_is_revision_scoped(tmp_path: Path) -> None:
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{"citation_token": "Smith 2024"}]}))

    fixed, logs = journal_finalizer._phase_d_source_inclusion_rationale(paper, tmp_path)

    assert fixed == paper
    assert logs == []


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


def test_review_noise_repairs_public_artifact_phrase() -> None:
    from scripts.review_noise_control import apply_review_noise_control

    paper = "## Results\n\nThe p-values should be read as descriptive only.\n"

    fixed, changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "should be read as" not in fixed
    assert "p-values can be interpreted as descriptive only" in fixed
    assert ("repair_public_artifact_phrase", 1, "rewrote 1 public artifact phrase(s)") in changes


def test_dedupe_keeps_methods_search_query_list_with_subset_vocab() -> None:
    """Regression: a templated search-query list has a tiny vocabulary that is
    a SUBSET of richer earlier prose. The asymmetric near-duplicate test
    (overlap / min-len) would score it 1.0 and prune it, blanking the
    Methods "Search strategy" body. A bulleted block is structured
    enumeration — pruned only on EXACT duplication, never fuzzy overlap.
    Universal across domains (no per-topic vocabulary)."""
    from scripts.review_noise_control import _dedupe_repeated_blocks

    paper = (
        "## Results\n\n"
        "Across the corpus, fasting and intermittent fasting as an "
        "intervention showed mixed effects on aging outcomes in older adults, "
        "with several randomized controlled trial reports and review sources "
        "disagreeing here.\n\n"
        "## Methods\n\n### Search strategy\n\n"
        "- `fasting intervention intermittent fasting effects aging`\n"
        "- `fasting intervention intermittent fasting effects older adults`\n"
        "- `fasting intervention intermittent fasting randomized controlled trial`\n"
        "- `fasting aging older adults randomized trial`\n\n"
        "### Eligibility criteria\n\n- Sources addressing fasting.\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    out, removed = _dedupe_repeated_blocks(paper)
    assert removed == 0, f"list block wrongly pruned: {out!r}"
    assert out.count("- `") == 4
    assert "fasting aging older adults randomized trial" in out


def test_unreferenced_citation_ignores_reference_title_fragment() -> None:
    from agent.journal_surface_gate import unreferenced_citation_tokens

    paper = (
        "## Results\n\n"
        "World Health Organization 2020 guidelines on physical activity are contextual.\n\n"
        "## References\n\n"
        "- **Bull 2020.** _World Health Organization 2020 guidelines on physical activity and sedentary behaviour._ British Journal of Sports Medicine, 2020.\n"
    )

    assert unreferenced_citation_tokens(paper) == ()


def test_phase_n_labels_discussion_thesis_and_resolution_markers() -> None:
    # Blocker #3: gate requires literal **Thesis:** / **Resolution criteria:**
    # markers in Discussion; the finalizer now labels the existing first/last
    # paragraphs (no fabrication) so the gate is self-healing.
    paper = (
        "# T\n\n## Discussion\n\n"
        "Metformin shows a context-dependent metabolic profile across the corpus.\n\n"
        "Future trials with longer follow-up would settle the open threats.\n\n"
        "## Limitations\n\nstub.\n"
    )
    out, log = journal_finalizer._phase_n_declare_discussion_thesis(paper)
    assert "**Thesis:**" in out and "**Resolution criteria:**" in out
    assert len(log) == 1 and out.count("**Thesis:**") == 1
    # idempotent: a second pass makes no change
    assert journal_finalizer._phase_n_declare_discussion_thesis(out)[1] == []


def test_smoke_combo_paper_finalizes_to_clean_surface() -> None:
    # End-to-end smoke (#10): a combo-topic paper with a legitimate cross-outcome
    # reference and a Discussion missing the thesis markers must finalize to a
    # CLEAN journal surface — i.e. it would clear pre-submit instead of looping.
    # Locks blockers #2 (sentence-dominant routing) + #3 (marker self-heal).
    from agent.journal_surface_gate import evaluate_journal_surface
    paper = (
        "# Research Synthesis: Test\n\n"
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The exposure in Sahay 2026 maps onto the cardiometabolic effects in "
        "Hong 2026 and Lim 2026.\n\n"
        "## Discussion\n\n"
        "The corpus supports a context-dependent cardiometabolic profile.\n\n"
        "Future randomized trials with longer follow-up would settle the open threats.\n\n"
        "## Limitations\n\nBounded by the accepted receipts.\n"
    )
    cmap = {"Sahay 2026": "dosing_pharmacokinetics",
            "Hong 2026": "cardiometabolic", "Lim 2026": "cardiometabolic"}
    before = evaluate_journal_surface(paper, citation_outcome_map=cmap)
    assert any(i.code == "undeclared_thesis" for i in before.issues)        # starts blocked
    assert not any(i.code == "outcome_routing" for i in before.issues)      # #2: cross-ref not a routing error
    fixed, _log = journal_finalizer._phase_n_declare_discussion_thesis(paper)
    after = evaluate_journal_surface(fixed, citation_outcome_map=cmap)
    assert not any(i.code == "undeclared_thesis" for i in after.issues)     # #3: markers injected
    assert not any(i.code == "outcome_routing" for i in after.issues)


def test_phase_k_relocates_misrouted_cite_in_lowercase_led_sentence(tmp_path: Path) -> None:
    # Regression for task_a7129e8b — the residual the gate flagged but Phase K
    # could not repair. Phase K's sentence splitter used a `(?=[A-Z])`
    # lookahead; the journal_surface outcome_routing gate uses none. When a
    # misrouted citation lived in a sentence that opens with a lowercase word or
    # numeral (here "to isolate ... (Sahay 2026)."), the lookahead failed to
    # split it out, the dosing sentence stayed merged in the contextual-majority
    # paragraph, and Phase K left it unmoved — so the gate flagged a routing
    # error the finalizer could not clear. Aligning the splitter to the gate's
    # `(?<=[.!?])\s+` makes Phase K relocate exactly what the gate flags.
    # Paragraph shape is taken verbatim from the live metformin R2 run.
    from agent.journal_surface_gate import evaluate_journal_surface
    paper = (
        "# T\n\n## Results\n\n"
        "### Contextual Adjacent Evidence Outcomes\n\n"
        "Hamsho 2026's negative label sits in partial conflict with the null "
        "directional labels carried by Tahir 2026 and Rattarasarn 2026. "
        "to isolate the contribution of the fixed-dose combination to glycemic "
        "and pharmacokinetic outcomes, the metformin component is embedded "
        "within both arms of the comparison (Sahay 2026).\n\n"
        "### Dosing and Pharmacokinetics Outcomes\n\n"
        "The pharmacokinetic context is shaped by the gut-liver axis.\n\n"
        "## References\n\n- Sahay 2026.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "r1", "outcome_class": "contextual_other"},
        {"receipt_id": "r2", "outcome_class": "contextual_other"},
        {"receipt_id": "r3", "outcome_class": "contextual_other"},
        {"receipt_id": "r4", "outcome_class": "dosing_pharmacokinetics"},
    ]}), encoding="utf-8")
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {"body_citation": "Hamsho 2026"},
        "r2": {"body_citation": "Tahir 2026"},
        "r3": {"body_citation": "Rattarasarn 2026"},
        "r4": {"body_citation": "Sahay 2026"},
    }), encoding="utf-8")
    cmap = {"Hamsho 2026": "contextual_other", "Tahir 2026": "contextual_other",
            "Rattarasarn 2026": "contextual_other", "Sahay 2026": "dosing_pharmacokinetics"}

    # Precondition: the gate flags the misroute on the un-finalized paper.
    assert any(i.code == "outcome_routing"
               for i in evaluate_journal_surface(paper, citation_outcome_map=cmap).issues)

    fixed, logs = journal_finalizer._phase_k_route_outcome_paragraphs(paper, tmp_path)
    assert any(e.rule == "route_paragraph_by_citation_class" and e.n_changes >= 1 for e in logs)

    # Sahay's sentence now lives under Dosing, not Contextual.
    ctx = fixed.split("### Contextual Adjacent Evidence Outcomes", 1)[1].split("###", 1)[0]
    dosing = fixed.split("### Dosing and Pharmacokinetics Outcomes", 1)[1].split("### ", 1)[0]
    assert "Sahay 2026" not in ctx
    assert "Sahay 2026" in dosing
    # End-to-end: the gate is now clean of routing errors.
    assert not any(i.code == "outcome_routing"
                   for i in evaluate_journal_surface(fixed, citation_outcome_map=cmap).issues)
