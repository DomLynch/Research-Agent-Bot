from __future__ import annotations

import json
import importlib
from pathlib import Path
from typing import Any

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
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "everolimus", "receipts": [
        {"outcome_class": "cardiometabolic", "n_claims": 4, "effect_direction": "mixed", "directness": "indirect"},
        {"outcome_class": "cardiometabolic", "n_claims": 5, "effect_direction": "null", "directness": "indirect"},
    ]}), encoding="utf-8")
    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    assert logs
    assert "| Everolimus / Cardiometabolic | n=2; claims=9 |" in fixed
    assert "### Cardiometabolic Outcomes\n\nCardiometabolic remains a separate Results slice for Everolimus" in fixed


def test_phase_f_fills_outcome_heading_with_source_level_findings(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=1; claims=54 | unclear | 1 direct | limited |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "## References\n\n- Wang 2024.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "vascular_age", "receipts": [
        {
            "citation_token": "Wang 2024",
            "source_title": "Impact of a Precision Intervention for Vascular Health",
            "outcome_class": "cardiometabolic",
            "n_claims": 54,
            "effect_direction": "unclear",
            "directness": "direct",
            "evidence_tier": "A1",
            "p_values": ["p < 0.05"],
        },
    ]}), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert logs
    section = fixed.split("### Cardiometabolic Outcomes", 1)[1].split("## References", 1)[0]
    assert "Wang 2024 (Impact of a Precision Intervention for Vascular Health" in section
    assert "representative statistic p < 0.05" in section
    assert "direction=unclear; directness=direct; tier=A1" in section
    assert "Direction reconciliation:" in section


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


def test_phase_f_distinguishes_source_statistics_from_null_receipt_summary(tmp_path: Path) -> None:
    paper = "## Results\n\nShort.\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "everolimus",
        "receipts": [
            {
                "outcome_class": "contextual_other",
                "n_claims": 28,
                "effect_direction": "null",
                "directness": "indirect",
                "p_values": ["p < 0.001"],
                "source_title": "STAT3 Polymorphism Associates With mTOR Inhibitor-Induced Interstitial Lung Disease in Patients With Renal Cell Carcinoma",
            },
            {
                "outcome_class": "contextual_other",
                "n_claims": 24,
                "effect_direction": "null",
                "directness": "indirect",
                "p_values": ["p = 0.034"],
                "source_title": "Vitamin D Reverts Cancer Resistance to the mTOR Inhibitor Everolimus in Hepatocellular Carcinoma",
            },
            {
                "outcome_class": "immune_inflammation",
                "n_claims": 17,
                "effect_direction": "null",
                "directness": "review",
                "p_values": ["P = 0.025"],
                "source_title": "TORC1 Inhibition with RTB101 to Decrease Respiratory Tract Infections in Older Adults",
            },
        ],
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert logs
    assert "significant source statistic in 2/2 sources; receipt-level direction coded null" in fixed
    assert "significant source statistic in 1/1 sources; receipt-level direction coded null" in fixed
    assert "no extracted directional signal in 2/2 sources" not in fixed
    assert "Source-context map" in fixed
    assert "- Oncology and cancer context: 2 sources; significant source statistic in 2/2 sources; receipt-level direction coded null." in fixed
    assert "- Infectious-disease and immunology context: 1 sources; significant source statistic in 1/1 sources; receipt-level direction coded null." in fixed


def test_phase_f_refreshes_stale_generated_outcome_blocks(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Contextual Other | n=1; claims=28 | no extracted directional signal in 1/1 sources | 1 indirect | limited |\n\n"
        "### Contextual Other Outcomes\n\n"
        "1 included source was assigned to this outcome class. Directional coding: null=1. Directness coding: indirect=1.\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "everolimus",
        "receipts": [{
            "outcome_class": "contextual_other",
            "n_claims": 28,
            "effect_direction": "null",
            "directness": "indirect",
            "p_values": ["p < 0.001"],
            "source_title": "STAT3 Polymorphism Associates With mTOR Inhibitor-Induced Interstitial Lung Disease in Patients With Renal Cell Carcinoma",
        }],
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert logs
    assert "Directional coding: null=1" not in fixed
    assert (
        "Contextual Adjacent Evidence remains a separate Results slice for Everolimus "
        "(n=1; claims=28; significant source statistic in 1/1 sources; receipt-level direction coded null"
    ) in fixed


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


def test_public_surface_backstop_reuses_shared_prose_with_section_scope() -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    orch: Any = importlib.import_module("scripts.run_v06_synthesis")

    orch._ACTIVE_TOPIC = "glp_1_longevity"
    orch._ACTIVE_MANIFEST = {
        "topic": "glp_1_longevity",
        "total_words": 4000,
        "n_receipts": 52,
        "n_high_confidence_claims_total": 2000,
        "n_non_orthogonal_tensions": 136,
        "receipts": [
            {
                "outcome_class": "longevity",
                "effect_direction": "positive",
                "directness": "direct",
                "evidence_tier": "A1",
                "citation_token": "Impact of GLP Receptor 2026",
            },
            {
                "outcome_class": "cardiometabolic",
                "effect_direction": "null",
                "directness": "mechanistic",
                "evidence_tier": "C1",
                "citation_token": "Effect of Oral Semaglutide 2026",
            },
            {
                "outcome_class": "safety_comorbidity",
                "effect_direction": "negative",
                "directness": "indirect",
                "evidence_tier": "B2",
                "citation_token": "Safety Trial 2025",
            },
        ],
    }

    discussion = orch._compile_public_section_backstop("Discussion", 800, "")
    cross_domain = orch._compile_public_section_backstop("Cross-Domain Synthesis", 850, discussion)

    assert len(cross_domain.split()) >= 850
    assert not _duplicate_paragraph_issue_messages(discussion + "\n\n" + cross_domain)


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


def test_admission_funnel_clarification_covers_coherent_accounting_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Reconcile the admission funnel numbers to a single coherent accounting, "
        "and explain how '63 admitted sources' is derived."
    )
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Mixed partial-or-none claim-binding candidates | 70 |\n"
        "| Admitted final sources | 63 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "Admission-bucket note:" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_admission_funnel_clarification_covers_search_summary_selection_logic(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Rewrite the Search Summary to describe the actual selection logic."
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Source candidates | 43 |\n"
        "| Admitted final sources | 13 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "Admission-bucket note:" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_admission_funnel_clarification_adds_additive_screening_flow(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Replace or supplement the non-additive claim-binding funnel with a clearly "
        "additive screening flow (records screened -> excluded with reasons -> "
        "eligible -> admitted) so the funnel is auditable."
    )
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Receipt candidate union | 50 |\n"
        "| Admitted final sources | 12 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "methods_pack.json").write_text(json.dumps({
        "screening_flow": {
            "n_screened": 50,
            "n_excluded_at_full_text": 10,
            "admitted_receipts": 12,
        }
    }))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "Additive screening flow: records screened (50)" in fixed
    assert "excluded with reasons (10) -> eligible (40) -> admitted (12)" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "insert_additive_screening_flow"


def test_admission_funnel_clarification_replaces_non_additive_table_when_requested(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Fix the admissions-funnel presentation: either provide a true PRISMA-style "
        "exclusion cascade with mutually exclusive and additive rows, or remove the table "
        "and replace with a textual description that does not invite arithmetic scrutiny."
    )
    paper = (
        "## Methods\n\n"
        "### source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Receipt candidate union | 187 |\n"
        "| Mixed partial-or-none claim-binding candidates | 70 |\n"
        "| Admitted final sources | 64 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "| Admission bucket |" not in fixed
    assert "Admission-bucket note:" in fixed
    assert "not an additive conservation table" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_admission_funnel_clarification",
            rule="replace_non_additive_admission_table",
            n_changes=1,
            detail="replaced non-additive admission-funnel table with textual clarification",
        )
    ]


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


def test_directional_coding_note_repairs_null_coded_source_bundle_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Resolve the disconnect between the '47/48 null-coded' framing and the clearly directional "
        "findings visible in the source bundle excerpts."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Brain age | no extracted directional signal in 47/48 sources |\n\n"
        "## Key Findings\n\n"
        "Some source bundle excerpts report positive and mixed findings.\n"
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


def test_run_text_phases_strips_late_outcome_route_duplicates(tmp_path, monkeypatch) -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    duplicate = (
        "Evidence for this outcome class is represented in the structured results table, "
        "but the retained narrative paragraphs were more strongly assigned to adjacent "
        "outcome classes. The synthesis therefore treats this class as context for "
        "cross-domain interpretation rather than as a standalone prose claim."
    )
    calls = 0

    def route(text: str, _out_dir):
        nonlocal calls
        calls += 1
        if calls < 2:
            return text, []
        return (
            text + "\n\n### Contextual Outcomes\n\n" + duplicate
            + "\n\n### Frailty Outcomes\n\n" + duplicate,
            [],
        )

    monkeypatch.setattr(journal_finalizer, "_phase_k_route_outcome_paragraphs", route)

    fixed, logs = journal_finalizer._run_text_phases(
        "## Results\n\n"
        "The structured evidence table separates direct, adjacent, and contextual "
        "evidence before narrative interpretation.",
        tmp_path,
    )

    assert _duplicate_paragraph_issue_messages(fixed) == ()
    assert fixed.count(duplicate) == 1
    assert "### Frailty Outcomes" not in fixed
    assert any(log.phase == "M_duplicate_paragraph_strip" for log in logs)
    assert any(log.detail == "empty_subheading=1" for log in logs)


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


def test_surface_artifact_cleanup_removes_empty_subheading_before_h2() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\n"
        "### Immune Inflammation Outcomes\n\n"
        "\n\n"
        "## Limitations\n\n"
        "Boundary text.\n"
    )

    assert any("empty heading: Immune Inflammation Outcomes" in i.detail for i in evaluate_journal_surface(paper).issues)

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    assert "### Immune Inflammation Outcomes" not in fixed
    assert not any("empty heading: Immune Inflammation Outcomes" in i.detail for i in evaluate_journal_surface(fixed).issues)
    assert any(log.detail == "empty_subheading=1" for log in logs)


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

    assert "Numeric reconciliation note: Waghmare 2024 reported a non-significant mapped comparison (p = 0.08)" in fixed
    assert "Numeric correction:" not in fixed.split("## Abstract", 1)[1].split("## Evidence Landscape", 1)[0]
    assert "not every within-source contrast" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].n_changes == 1


def test_numeric_significance_correction_repairs_verify_statistic_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Verify the Brouwers 2016 direction/statistic mapping (p=0.88 vs. reported "
        "comparable decrease) and correct the representative statistic if miscoded."
    )
    paper = (
        "## Abstract\n\n"
        "The corpus remains mixed.\n\n"
        "## Evidence Landscape\n\n"
        "Brouwers 2016 contributed a mapped outcome row.\n\n"
        "## Conclusion\n\nThe interpretation remains bounded.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "Numeric reconciliation note: Brouwers 2016 reported a non-significant mapped comparison (p = 0.88)" in fixed
    assert "Numeric correction:" not in fixed.split("## Abstract", 1)[1].split("## Evidence Landscape", 1)[0]
    assert "not every within-source contrast" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "repair_non_significant_numeric_effect_claims"


def test_numeric_significance_correction_removes_positive_label_for_non_significant_source(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Reconcile the Brouwers 2016 frailty coding: if p=0.88 is the headline statistic, "
        "the source should be recoded as null/mixed in the frailty outcome class, or the "
        "'positive signal' label should be removed and the non-significant result stated explicitly."
    )
    paper = (
        "## Abstract\n\n"
        "Numeric correction: Brouwers 2016 reported a non-significant result (p = 0.88); "
        "this synthesis treats that finding as non-significant. Positive study-level signals "
        "are summarized in the frailty outcome class.\n\n"
        "## Evidence Landscape\n\n"
        "| Telomere / Frailty | n=1 | positive signal in 1/1 sources |\n\n"
        "### Frailty\n\n"
        "positive signal in 1/1 sources.\n"
        "- Brouwers 2016: outcome=Frailty; direction=positive; directness=indirect; "
        "tier=B2; finding=representative statistic p = 0.88.\n\n"
        "## Conclusion\n\nThe interpretation remains bounded.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "non-significant mapped comparison (p = 0.88)" in fixed
    assert "Numeric correction:" not in fixed.split("## Abstract", 1)[1].split("## Evidence Landscape", 1)[0]
    assert "not every within-source contrast" in fixed
    assert "Non-significant or mixed study-level signals are summarized in the frailty outcome class" in fixed
    assert "non-significant or mixed signal in 1/1 sources" in fixed
    assert "positive signal in 1/1 sources" not in fixed
    assert "direction=null" in fixed
    assert "direction=positive" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].n_changes == 6


def test_numeric_significance_correction_moves_inline_markup_to_evidence_landscape(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Remove or properly contextualize the in-text 'Numeric correction' sentence — it reads "
        "as leftover editing markup and does not belong in the Abstract or Research Question."
    )
    paper = (
        "## Abstract\n\n"
        "Numeric correction: Brouwers 2016 reported a non-significant mapped comparison (p = 0.88); "
        "this synthesis treats that mapped comparison as non-significant.\n\n"
        "The corpus is mixed.\n\n"
        "## Research Question\n\n"
        "Numeric correction: Brouwers 2016 reported a non-significant mapped comparison (p = 0.88).\n\n"
        "What does the evidence show?\n\n"
        "## Evidence Landscape\n\n"
        "Brouwers 2016 contributed a mapped outcome row.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    reader_facing = fixed.split("## Evidence Landscape", 1)[0]
    assert "Numeric correction:" not in reader_facing
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_numeric_significance_correction"


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
            "source_title": "Clinical source one",
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
    assert "- Smith 2024: Clinical source one: outcome=Cardiometabolic; direction=unclear; directness=direct; tier=A1." in fixed
    assert "- Jones 2025: outcome=Immune and Inflammation; direction=unclear; directness=review; tier=B1." in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_repairs_findings_map_accounting_ask(tmp_path: Path) -> None:
    ask = (
        "Attribute every admitted source to at least one mapped outcome class or contextual role; "
        "Holmes 2026 currently appears in the bundle but is unaccounted for in the Findings Map. "
        "Reclassify Membrez 2024 as translational/mechanistic with human correlational component. "
        "Reconcile the 0 cross-study disagreements claim with the divergence between biomarker-positive "
        "studies and clinical-endpoint null studies. Expand Tensions and Gaps to cover cognition, "
        "menopause, and acute-care contexts including Gao 2026 and Qader 2025."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "### Source Classification Map\n\n"
        "- Old row.\n\n"
        "## Results\n\nThe corpus includes several sources.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Holmes 2026",
            "source_title": "Menopause pilot trial",
            "outcome_class": "contextual_other",
            "directness": "indirect",
            "evidence_tier": "B2",
        },
    ]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "Old row" not in fixed
    assert "Holmes 2026: Menopause pilot trial: outcome=Contextual Adjacent Evidence" in fixed
    assert "Signal-accounting note: biomarker-positive source-level findings" in fixed
    assert "Role-accounting note: retained translational or mechanistic-with-human-correlational evidence" in fixed
    assert "Tension-accounting note: disagreement counts are claim-level" in fixed
    assert "across cognition, menopause, acute-care" in fixed
    assert "3 reviewer-named sources are not retained in this source map" in fixed
    assert "source(s)" not in fixed
    assert "Gao 2026" not in fixed
    assert "Qader 2025" not in fixed
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_emits_findings_map_with_finding_field(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Reconstruct the Findings Map so that each retained source has an explicit "
        "per-source direction on its primary outcome, with the specific effect "
        "estimate or qualitative finding attached."
    )
    paper = "## Evidence Snapshot\n\nThe source map needs repair.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{
        "citation_token": "Smith 2024",
        "source_title": "Clinical source one",
        "outcome_class": "cardiometabolic",
        "effect_direction": "null",
        "directness": "indirect",
        "evidence_tier": "B2",
        "p_values": ["p = 0.04"],
        "n_claims": 7,
    }]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "### Findings Map" in fixed
    assert "direction=null; directness=indirect; tier=B2; finding=representative statistic p = 0.04" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_includes_all_rows_for_each_retained_source_ask(tmp_path: Path) -> None:
    ask = (
        "For each outcome class, extract at least 2-3 specific findings from "
        "individual cited sources (study design, population, effect direction, "
        "effect size where available) and present them in prose, not just in the "
        "coding tally."
    )
    rows = [
        {
            "citation_token": f"Smith {2000 + idx}",
            "source_title": f"Clinical source {idx}",
            "outcome_class": "cardiometabolic",
            "effect_direction": "mixed",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": idx,
        }
        for idx in range(1, 46)
    ]
    paper = "## Evidence Landscape\n\nThe source map needs repair.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "### Findings Map" in fixed
    assert "Smith 2001" in fixed
    assert "Smith 2045" in fixed
    assert "finding=45 extracted claim(s); receipt-level direction is the coded finding" in fixed
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_repairs_surface_every_admitted_source_feedback(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Claims n=26 admitted sources, but many are not surfaced in Evidence Landscape. "
        "Surface every admitted source; redesign outcome taxonomy; recode direction values."
    )
    paper = "## Evidence Landscape\n\nThe source table needs repair.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Smith 2026",
            "source_title": "Clinical intervention source",
            "outcome_class": "clinical_intervention",
            "effect_direction": "mixed",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 3,
        },
        {
            "citation_token": "Jones 2025",
            "source_title": "Mechanistic source",
            "outcome_class": "mechanism",
            "effect_direction": "unclear",
            "directness": "mechanistic",
            "evidence_tier": "C1",
            "n_claims": 2,
        },
    ]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "### Findings Map" in fixed
    assert "Smith 2026: Clinical intervention source" in fixed
    assert "Jones 2025: Mechanistic source" in fixed
    assert "finding=3 extracted claim(s); receipt-level direction is the coded finding" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_tensions_and_gaps_breadth_repairs_revision_ask(tmp_path: Path) -> None:
    ask = (
        "Expand Tensions and Gaps to cover the full outcome breadth of the corpus, "
        "including cognition, menopause, and acute-care contexts."
    )
    paper = "## Results\n\nThe corpus has unresolved heterogeneity.\n\n## References\n\nR01.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_tensions_and_gaps_breadth(paper, tmp_path)

    assert "## Tensions and Gaps" in fixed
    assert "spans cognition, menopause, acute-care" in fixed
    assert "Biomarker-positive source-level findings are not pooled" in fixed
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_tensions_and_gaps_breadth",
            rule="state_revision_tension_breadth",
            n_changes=1,
            detail="added Tensions and Gaps breadth note for cognition, menopause, acute-care",
        )
    ]


def test_tensions_and_gaps_breadth_repairs_cross_source_disagreement_ask(tmp_path: Path) -> None:
    ask = (
        "Expand the Tensions and Gaps section to enumerate at least three specific "
        "cross-source disagreements with named sources on each side."
    )
    rows = [
        {"citation_token": "Grazuleviciene 2026", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "direct"},
        {"citation_token": "Durstenfeld 2026", "outcome_class": "cardiometabolic", "effect_direction": "unclear", "directness": "review"},
        {"citation_token": "Salerno 2026", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "indirect"},
        {"citation_token": "Riquelme-Hernandez 2026", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review"},
        {"citation_token": "Liu 2025", "outcome_class": "frailty", "effect_direction": "unclear", "directness": "indirect"},
        {"citation_token": "Garcia 2026", "outcome_class": "frailty", "effect_direction": "null", "directness": "direct"},
    ]
    paper = "## Results\n\nThe corpus has unresolved heterogeneity.\n\n## References\n\nR01.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"n_non_orthogonal_tensions": 367, "receipts": rows}))

    fixed, logs = journal_finalizer._phase_d_tensions_and_gaps_breadth(paper, tmp_path)

    assert "## Tensions and Gaps" in fixed
    assert "Grazuleviciene 2026 vs Durstenfeld 2026" in fixed
    assert "Salerno 2026 vs Riquelme-Hernandez 2026" in fixed
    assert "Liu 2025 vs Garcia 2026" in fixed
    assert logs[0].phase == "D_tensions_and_gaps_breadth"


def test_tensions_and_gaps_replaces_stale_cross_outcome_surface_tensions(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Replace the three Curran 2025-based 'surfaced tensions' with genuinely "
        "comparable within-outcome tensions (e.g., Martens 2018 vs Connell 2021; "
        "Yi 2022 vs Katayoshi 2023; Baichuan 2023 meta-analysis vs individual null RCTs)."
    )
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "### Load-Bearing Tensions\n\n"
        "- Zhao 2024 vs Curran 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus positive.\n"
        "- Pei 2024 vs Curran 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus positive.\n"
        "- Zhao 2024 vs Ministrini 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus null.\n\n"
        "## References\n\nR01.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"n_non_orthogonal_tensions": 146, "receipts": [
        {"citation_token": "Curran 2025", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "positive", "directness": "review"},
        {"citation_token": "Zhao 2024", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "negative", "directness": "review"},
        {"citation_token": "Katayoshi 2023", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect"},
        {"citation_token": "Martens 2018", "outcome_class": "cardiometabolic", "effect_direction": "unclear", "directness": "indirect"},
        {"citation_token": "Yi 2022", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "unclear", "directness": "direct"},
        {"citation_token": "Simic 2020", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "null", "directness": "review"},
        {"citation_token": "Gao 2025", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "null", "directness": "direct"},
        {"citation_token": "Simon 2024", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "unclear", "directness": "direct"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_tensions_and_gaps_breadth(paper, tmp_path)

    assert "Curran 2025: surfaced tension" not in fixed
    assert "Katayoshi 2023 vs Martens 2018" in fixed
    assert "Yi 2022 vs Simic 2020" in fixed
    assert "Gao 2025 vs Simon 2024" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_tensions_and_gaps_breadth"


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


def test_substantive_evidence_synthesis_creates_landscape_and_key_findings(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Provide an actual evidence synthesis in the Evidence Landscape and Key Findings sections. "
        "At minimum, surface the key positive, negative, and mixed findings from the bundle and "
        "explain how they inform the bounded conclusion."
    )
    paper = "## Results\n\nThe corpus includes several sources.\n\n## Conclusion\n\nThe conclusion is bounded.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Smith 2025", "outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "indirect", "evidence_tier": "B2", "n_claims": 12},
        {"citation_token": "Jones 2024", "outcome_class": "immune", "effect_direction": "negative", "directness": "review", "evidence_tier": "B1", "n_claims": 8},
        {"citation_token": "Patel 2023", "outcome_class": "cognitive", "effect_direction": "mixed", "directness": "direct", "evidence_tier": "A1", "n_claims": 6},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_substantive_evidence_synthesis(paper, tmp_path)

    assert "## Evidence Landscape" in fixed
    assert "## Key Findings" in fixed
    assert "Smith 2025: outcome=Cardiometabolic; direction=positive" in fixed
    assert "Key findings from source synthesis" in fixed
    assert "bounded conclusion" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_substantive_evidence_synthesis"


def test_substantive_evidence_synthesis_surfaces_all_named_missing_sources(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add the missing bundle sources to the Results outcome slices (Andreikos 2024, "
        "Chen 2023, Wan 2023) so the evidence map covers the full admitted corpus."
    )
    paper = "## Evidence Landscape\n\nExisting summary.\n\n## Key Findings\n\nThin summary.\n"
    rows = [
        {
            "citation_token": "Andreikos 2024",
            "outcome_class": "frailty",
            "effect_direction": "null",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 9,
        },
        {
            "citation_token": "Chen 2023",
            "outcome_class": "cancer_risk",
            "effect_direction": "mixed",
            "directness": "review",
            "evidence_tier": "B1",
            "n_claims": 7,
        },
        {
            "citation_token": "Wan 2023",
            "outcome_class": "mechanism",
            "effect_direction": "unclear",
            "directness": "mechanistic",
            "evidence_tier": "C1",
            "n_claims": 5,
        },
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_substantive_evidence_synthesis(paper, tmp_path)
    key_findings = fixed.split("## Key Findings", 1)[1]

    assert all(row["citation_token"] in key_findings for row in rows)
    assert "Source-level findings by outcome class" in key_findings
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_substantive_evidence_synthesis"


def test_finalizer_disaggregates_contextual_bundle_and_tightens_scope(tmp_path: Path) -> None:
    feedback = (
        "Reframe the research question to ask a substantive scientific question rather than "
        "a self-referential description of the corpus.; Expand the Evidence Landscape to "
        "cover all admitted sources.; Disaggregate the Contextual Adjacent Evidence class "
        "into clinically meaningful sub-domains.; Tighten the conclusion to remove "
        "geroscience rationale framing."
    )
    paper = (
        "## Abstract\n\n"
        "The paper therefore interprets the corpus as a tiered evidence profile rather than as a single pooled effect. "
        "The conclusion is that telomere cancer effects remains a bounded geroscience case: the retained clinical "
        "and adjacent evidence profile defines the scope for targeted testing, while mixed and null findings limit "
        "any unqualified anti-aging claim.\n\n"
        "## Methods\n\nDeterministic methods.\n\n"
        "## Evidence Landscape\n\nThin summary.\n\n"
        "## Key Findings\n\nThin summary.\n\n"
        "## Conclusion\n\n"
        "The conclusion is that telomere cancer effects remains a bounded geroscience case: indirect evidence is mixed.\n"
    )
    rows = [
        {"citation_token": "Sasmita 2025", "source_title": "Shorter telomere length as a prognostic marker for survival and recurrence in breast cancer", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "review", "evidence_tier": "B2", "n_claims": 113},
        {"citation_token": "Markozannes 2022", "source_title": "Systematic review of Mendelian randomization studies on risk of cancer", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review", "evidence_tier": "B2", "n_claims": 61},
        {"citation_token": "Jaeger 2024", "source_title": "A nutritional supplement lengthens telomeres in a randomized population", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "indirect", "evidence_tier": "B2", "n_claims": 90},
        {"citation_token": "Afolabi 2026", "source_title": "Telomere-driven dysfunctional changes in gynecological cancers: mechanistic insights", "outcome_class": "mechanism", "effect_direction": "null", "directness": "mechanistic", "evidence_tier": "C1", "n_claims": 3},
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "telomere_cancer_effects", "receipts": rows}))

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "## Research Question" in fixed
    assert "prognostic or risk-marker associations" in fixed
    assert "bounded geroscience case" not in fixed
    assert "bounded geroscience hypothesis" not in fixed
    assert "source-directness and outcome-class map" in fixed
    assert "Contextual-adjacent subdomain map" in fixed
    assert "prognostic and survival-marker evidence" in fixed
    assert "causal-risk and Mendelian-randomization evidence" in fixed
    assert "Full source-level signals are" in fixed
    assert {entry.phase for entry in logs} >= {
        "D_research_question_scope",
        "D_substantive_evidence_synthesis",
        "D_evidence_honesty_guard",
    }


def test_search_summary_scope_note_repairs_date_operationalization_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Tighten Search Summary to specify date ranges, topic-operationalization criteria, "
        "and the rationale for the 73→25 narrowing."
    )
    paper = "## Methods\n\nRetrieval was deterministic.\n\n## Evidence Landscape\n\nThin summary.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "vascular_age"}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_search_summary_scope_note(paper, tmp_path)

    assert "Search-summary scope note:" in fixed
    assert "date ranges" in fixed
    assert "operationalized" in fixed
    assert "candidate-to-admitted narrowing" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_search_summary_scope"


def test_outcome_label_cleanup_repairs_non_pk_slice_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Re-label or remove the Dosing and Pharmacokinetics outcome class, which does "
        "not contain any actual dosing/PK studies."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Dosing and Pharmacokinetics\n\n"
        "This slice contains exposure-adjacent evidence.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_outcome_label_cleanup(paper, tmp_path)

    assert "Dosing and Pharmacokinetics" not in fixed
    assert "Exposure and Dose-Adjacent Evidence" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_outcome_label_cleanup"


def test_finalizer_answers_within_class_narrative_and_research_question(tmp_path: Path) -> None:
    from scripts import revision_coverage

    feedback = (
        "Provide actual within-class synthesis narrative for each outcome class "
        "describing what the cited studies found, not just metadata counts. "
        "Fix the Research Question to state a concrete, answerable question "
        "rather than 'what does the corpus establish.'"
    )
    asks = revision_coverage.revision_asks(feedback)
    paper = (
        "# Hypothesis-Generating Brief: Vascular age\n\n"
        "## Abstract\n\nEvidence remains bounded.\n\n"
        "## Methods\n\nDeterministic methods.\n\n"
        "## Results\n\nThe corpus includes several sources.\n\n"
        "## Conclusion\n\nThe conclusion is bounded.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "vascular_age",
        "receipts": [
            {
                "citation_token": "Wang 2024",
                "outcome_class": "cardiometabolic",
                "effect_direction": "unclear",
                "directness": "direct",
                "evidence_tier": "A1",
                "p_values": ["p < 0.05"],
                "n_claims": 54,
            },
            {
                "citation_token": "Sheng 2025",
                "outcome_class": "contextual_adjacent_evidence",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "p_values": ["p < 0.001"],
                "n_claims": 102,
            },
        ],
    }))

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == asks
    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "## Research Question" in fixed
    assert "prognostic or risk-marker associations" in fixed
    assert "## Evidence Landscape" in fixed
    assert "## Key Findings" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {
        "D_research_question_scope",
        "D_substantive_evidence_synthesis",
    }


def test_finalizer_answers_sirtuin_revision_count_and_positive_finding_asks(tmp_path: Path) -> None:
    from scripts import revision_coverage

    asks = [
        "Remove or correct the '116 cross-study disagreements' figure if it cannot be substantiated with enumerated examples; or replace it with a count of actually-surfaced tensions.",
        "Add a brief enumeration of the strongest 3-5 positive findings in the corpus (with source citations) even if the overall conclusion is null, so the map honors the evidence that does exist rather than collapsing everything to a null verdict.",
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "The evidence profile contains 116 cross-study disagreements across the evidence base.\n\n"
        "## Results\n\n"
        "The corpus is mostly null.\n\n"
        "## Conclusion\n\n"
        "The bounded conclusion does not support clinical claims.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": "; ".join(asks)}))
    (tmp_path / "manifest.json").write_text(json.dumps({"n_non_orthogonal_tensions": 116, "receipts": [
        {"citation_token": "Smith 2025", "outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "direct", "evidence_tier": "A1", "n_claims": 12},
        {"citation_token": "Jones 2024", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "review", "evidence_tier": "B1", "n_claims": 8},
        {"citation_token": "Patel 2023", "outcome_class": "immune", "effect_direction": "mixed", "directness": "indirect", "evidence_tier": "B2", "n_claims": 6},
        {"citation_token": "Chen 2022", "outcome_class": "muscle_function", "effect_direction": "negative", "directness": "indirect", "evidence_tier": "B2", "n_claims": 5},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == asks
    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Actually surfaced tensions include:" in fixed
    assert "Smith 2025 vs Jones 2024" in fixed
    assert "Key findings from source synthesis" in fixed
    assert "Smith 2025: outcome=Cardiometabolic; direction=positive" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {"D_substantive_evidence_synthesis", "D_tensions_and_gaps_breadth"}


def test_finalizer_answers_vascular_source_level_revision_bundle(tmp_path: Path) -> None:
    from scripts import revision_coverage

    asks = [
        "Recode directional findings to match source abstracts; remove/qualify 11/13 null framing as receipt-level not source-level.",
        "Include all 13 admitted sources in Evidence Landscape tables; remove repetitive boilerplate and replace with findings.",
        "Enumerate the 12 cross-study disagreements or replace the count with a qualitative description of where the disagreements lie.",
        "Expand Key Findings with concrete bounded findings per outcome class from source abstracts.",
        "Strengthen Gaps with at least 3 concrete actionable studies.",
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "The source table needs repair.\n\n"
        "## Key Findings\n\n"
        "The conclusion is bounded.\n\n"
        "## Discussion\n\n"
        "Evidence remains incomplete.\n\n"
        "## References\n\n"
        "- Sheng 2025.\n"
    )
    rows = [
        {"citation_token": "Sheng 2025", "source_title": "Integrating Vascular Aging and Genetic Risk: The Combined Impact of Estimated Pulse Wave Velocity and Genetic Predisposition on Coronary Artery Disease", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "p_values": ["p < 0.001"], "n_claims": 102},
        {"citation_token": "Nguyen 2026", "outcome_class": "deficiency_prevalence", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "p_values": ["p = 0.032"], "n_claims": 64},
        {"citation_token": "Wang 2024", "source_title": "Impact of a Precision Intervention for Vascular Health in Middle-Aged and Older Postmenopausal Women Using Polar Heart Rate Sensors", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "direct", "evidence_tier": "A1", "p_values": ["p < 0.05"], "n_claims": 54},
        {"citation_token": "Rodilla 2026", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "n_claims": 28},
        {"citation_token": "Alanis 2025", "outcome_class": "mechanism", "effect_direction": "null", "directness": "mechanistic", "evidence_tier": "C1", "n_claims": 27},
        {"citation_token": "Luo 2025", "source_title": "Effects of L-citrulline supplementation and watermelon intake on arterial stiffness and endothelial function in middle-aged and older adults", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review", "evidence_tier": "B2", "p_values": ["p = 0.0007"], "n_claims": 22},
        {"citation_token": "Vicente-Gabriel 2024", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "protocol", "evidence_tier": "D1", "n_claims": 20},
        {"citation_token": "Azizzadeh 2026", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "n_claims": 16},
        {"citation_token": "Lu 2026", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "indirect", "evidence_tier": "B2", "n_claims": 14},
        {"citation_token": "Kozlik 2026", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "n_claims": 14},
        {"citation_token": "Joshi 2025", "outcome_class": "safety_comorbidity", "effect_direction": "null", "directness": "protocol", "evidence_tier": "D1", "n_claims": 10},
        {"citation_token": "Carmo 2025", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review", "evidence_tier": "B2", "n_claims": 5},
        {"citation_token": "Kakaletsis 2024", "outcome_class": "longevity", "effect_direction": "unclear", "directness": "review", "evidence_tier": "B1", "n_claims": 4},
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": "; ".join(asks)}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "vascular_age",
        "n_non_orthogonal_tensions": 12,
        "receipts": rows,
    }))

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Receipt-level direction is not a statement that the source abstracts lack directional statistics" in fixed
    assert "### Findings Map" in fixed
    assert "Sheng 2025" in fixed
    assert "Kakaletsis 2024" in fixed
    assert "- Sheng 2025: Integrating Vascular Aging and Genetic Risk" in fixed
    assert "- Wang 2024: Impact of a Precision Intervention for Vascular Health" in fixed
    assert "- Luo 2025: Effects of L-citrulline supplementation" in fixed
    assert "Synthesis interpretation: These source-level findings connect" in fixed
    assert "Publication-year note: citation years follow the manifest metadata" in fixed
    assert "finding=representative statistic p < 0.001; source-level statistic reported" in fixed
    assert "Actually surfaced tensions include:" in fixed
    assert "## Gaps Identified" in fixed
    assert "1. Run adequately powered prospective trials" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {
        "D_directional_coding_note",
        "D_substantive_evidence_synthesis",
        "D_source_outcome_class_map",
        "D_tensions_and_gaps_breadth",
        "D_actionable_gaps",
    }


def test_rct_count_reconciliation_removes_single_rct_claim(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Verify and correct the single RCT claim because one included source aggregates data from two RCTs."
    paper = "## Evidence Landscape\n\nThe synthesis compares a single direct RCT with indirect evidence.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_rct_count_reconciliation(paper, tmp_path)

    assert "single direct RCT" not in fixed
    assert "single direct-source coding row" in fixed
    assert "RCT-count reconciliation" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_rct_count_reconciliation"


def test_unbacked_appraisal_names_are_removed_without_ratings(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Report actual RoB-2/ROBINS-I/AMSTAR-2 results for included sources, or remove the framework name if no appraisal was performed."
    paper = (
        "## Methods\n\nRisk-of-bias framework assignment follows study design "
        "(RoB-2 for RCTs, ROBINS-I for non-randomised studies, AMSTAR-2 for systematic reviews).\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_unbacked_appraisal_names(paper, tmp_path)

    assert "RoB-2" not in fixed
    assert "ROBINS-I" not in fixed
    assert "AMSTAR-2" not in fixed
    assert "Risk-of-bias honesty note" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_unbacked_appraisal_names"


def test_populated_appraisal_artifact_is_summarized(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Report actual RoB-2/ROBINS-I/AMSTAR-2 results for included sources, or remove the framework name if no appraisal was performed."
    paper = (
        "## Methods\n\nRisk-of-bias framework assignment follows study design "
        "(RoB-2 for RCTs, ROBINS-I for non-randomised studies, AMSTAR-2 for systematic reviews).\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "risk_of_bias.json").write_text(json.dumps([
        {"study_id": "Smith 2025", "tool": "robins_i", "overall_rating": "some_concerns"},
        {"study_id": "Jones 2024", "tool": "amstar_2", "overall_rating": "low"},
    ]))

    fixed, logs = journal_finalizer._phase_d_unbacked_appraisal_names(paper, tmp_path)

    assert "RoB-2" in fixed
    assert "Risk-of-bias appraisal summary" in fixed
    assert "2 source-level rating row(s)" in fixed
    assert "low=1" in fixed
    assert "some concerns=1" in fixed
    assert "robins_i" not in fixed
    assert "some_concerns" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "summarize_populated_appraisal_artifact"


def test_populated_appraisal_artifact_is_summarized_for_rob_judgment_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Relabel review-level rows and report RoB judgments for the admitted RCT and cohort sources."
    paper = "## Methods\n\nRisk-of-bias judgments are source-level where reported.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "risk_of_bias.json").write_text(json.dumps([
        {"study_id": "Smith 2025", "tool": "rob2", "overall_rating": "some_concerns"},
        {"study_id": "Jones 2024", "tool": "robins_i", "overall_rating": "low"},
    ]))

    fixed, logs = journal_finalizer._phase_d_unbacked_appraisal_names(paper, tmp_path)

    assert "Risk-of-bias appraisal summary" in fixed
    assert "2 source-level rating row(s)" in fixed
    assert "RoB-2" in fixed
    assert "ROBINS-I" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "summarize_populated_appraisal_artifact"


def test_existing_appraisal_summary_labels_are_normalized(tmp_path: Path) -> None:
    ask = "Report actual RoB-2/ROBINS-I/AMSTAR-2 results for included sources."
    paper = (
        "## Methods\n\n"
        "Risk-of-bias appraisal summary: The public appraisal artifact reports "
        "65 source-level rating row(s) using robins_i, syrcle; overall ratings "
        "are some_concerns=65.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "risk_of_bias.json").write_text(json.dumps([
        {"study_id": "Smith 2025", "tool": "robins_i", "overall_rating": "some_concerns"},
    ]))

    fixed, logs = journal_finalizer._phase_d_unbacked_appraisal_names(paper, tmp_path)

    assert "ROBINS-I" in fixed
    assert "SYRCLE" in fixed
    assert "some concerns=65" in fixed
    assert "robins_i" not in fixed
    assert "some_concerns" not in fixed
    assert logs[0].rule == "normalize_public_appraisal_labels"


def test_reference_closure_removes_registry_unsupported_orphan_reference(tmp_path: Path) -> None:
    paper = (
        "## Conclusion\n\nBounded conclusion.\n\n"
        "## References\n\n"
        "- **Huang 2025.** Registry-backed source.\n"
        "- **Ioannidis 2005.** Unsupported context source.\n"
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "huang": {"body_citation": "Huang 2025"},
    }))

    fixed, logs = journal_finalizer._phase_d_reference_closure(paper, tmp_path)

    assert "Huang 2025" in fixed
    assert "Ioannidis 2005" not in fixed
    assert logs[0].rule == "remove_registry_unsupported_orphan_references"


def test_reference_closure_preserves_title_derived_registry_reference(tmp_path: Path) -> None:
    from agent.journal_surface_gate import orphan_reference_tokens

    paper = (
        "## Conclusion\n\nBounded conclusion.\n\n"
        "## References\n\n"
        "- **Effects of Daily Taurine 2025.** "
        "_Effects Of Daily Taurine Intake For 6 Months On Biological Age._\n"
        "- **Ioannidis 2005.** Unsupported context source.\n"
    )
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "taurine": {"body_citation": "Effects of Daily Taurine 2025"},
    }))

    fixed, logs = journal_finalizer._phase_d_reference_closure(paper, tmp_path)

    assert "Effects of Daily Taurine 2025" in fixed
    assert "Ioannidis 2005" not in fixed
    assert "Taurine 2025" in fixed
    assert orphan_reference_tokens(fixed) == ()
    assert logs[0].rule == "remove_registry_unsupported_orphan_references"
    assert logs[1].rule == "supporting_corpus_cluster"


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


def test_species_study_design_summary_repairs_revision_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the bounded geroscience claim."
    )
    paper = "## Evidence Landscape\n\nThe bundle is mixed.\n\n## Results\n\nEvidence remains bounded.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Parker 2020",
            "source_title": "Human plasma transfusion safety and tolerability in Parkinson disease",
            "directness": "direct",
        },
        {
            "citation_token": "Zhao 2020",
            "source_title": "Young plasma improves pathology in 3xTg-AD mice",
            "directness": "mechanistic",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_species_study_design_summary(paper, tmp_path)

    assert "### Species and Study-Design Summary" in fixed
    assert "source(s)" not in fixed
    assert "| Human n=1 | clinical trial/intervention or safety cohort | 1 | Parker 2020" in fixed
    assert "| Preclinical rodent n=1 | animal/preclinical experiment | 1 | Zhao 2020" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_species_study_design_summary",
            rule="insert_species_study_design_summary_table",
            n_changes=1,
            detail="added species/study-design summary for 2 manifest receipt(s)",
        )
    ]


def test_species_study_design_summary_normalizes_existing_header(tmp_path: Path) -> None:
    ask = (
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the bounded geroscience claim."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Species and Study-Design Summary\n\n"
        "| Evidence group | Study-design signal | n | Example source(s) | Interpretation boundary |\n"
        "|---|---|---:|---|---|\n"
        "| Preclinical rodent n=1 | animal/preclinical experiment | 1 | Zhao 2020 | Mechanistic only. |\n"
        "| Human n=1 | observational/donor or cohort evidence | 1 | Parker 2020 | Association only. |\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_species_study_design_summary(paper, tmp_path)

    assert "Example sources" in fixed
    assert "source(s)" not in fixed
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_species_study_design_summary",
            rule="normalize_species_study_design_summary_header",
            n_changes=1,
            detail="removed public template token from species/study-design summary",
        )
    ]


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


def test_source_directness_breakdown_repairs_direct_vs_adjacent_scope_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Clarify the scope statement: explicitly state which included sources are direct "
        "ABT-263 (navitoclax) studies versus other senolytics used as adjacent context, "
        "and justify why each non-ABT-263 source is included in an ABT-263 evidence map."
    )
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Smith 2024", "outcome_class": "longevity", "directness": "direct", "evidence_tier": "A1"},
        {"citation_token": "Jones 2025", "outcome_class": "contextual_other", "directness": "indirect", "evidence_tier": "B2"},
        {"citation_token": "Lee 2026", "outcome_class": "mechanism", "directness": "mechanistic", "evidence_tier": "C1"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert "Source directness breakdown:" in fixed
    assert fixed.count("directness=") == 3
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_directness_breakdown",
            rule="insert_manifest_source_directness_map",
            n_changes=1,
            detail="added source directness breakdown from 3 manifest receipt(s)",
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

    assert "Evidence type metadata note:" in fixed
    assert "evidence_type" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_source_directness_breakdown_repairs_human_intervention_misclassification(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Human intervention studies were misclassified as indirect/review evidence."
    paper = "## Evidence Landscape\n\nThe corpus is summarized.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Trialists 2026",
            "outcome_class": "clinical_intervention",
            "effect_direction": "mixed",
            "directness": "direct",
            "evidence_tier": "A1",
        },
        {
            "citation_token": "Reviewers 2025",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear",
            "directness": "review",
            "evidence_tier": "B2",
        },
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert "Source directness breakdown:" in fixed
    assert "Trialists 2026: outcome=Clinical Intervention; direction=mixed; directness=direct; tier=A1." in fixed
    assert "Reviewers 2025: outcome=Contextual Adjacent Evidence; direction=unclear; directness=review; tier=B2." in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_directness_breakdown"


def test_evidence_type_note_added_when_directness_breakdown_already_exists(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Evidence Landscape\n\n"
        "Source directness breakdown: 0/2 retained sources directly address the stated topic; "
        "2/2 are adjacent or review-level.\n\n"
        "### Source Classification Map\n\n"
        "- Marco 2024: outcome=sleep; direction=unclear; directness=review; tier=B2.\n"
        "- Yagi 2026: outcome=contextual; direction=unclear; directness=indirect; tier=B2.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"citation_token": "Marco 2024", "outcome_class": "sleep", "directness": "review", "evidence_tier": "B2"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert fixed.count("Source directness breakdown:") == 1
    assert "Evidence type metadata note:" in fixed
    assert "evidence_type" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_source_directness_breakdown",
            rule="insert_evidence_type_metadata_note",
            n_changes=1,
            detail="added evidence_type metadata note to Evidence Landscape",
        )
    ]


def test_existing_evidence_type_note_is_public_prose_normalized(tmp_path: Path) -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Evidence Landscape\n\n"
        "Source directness breakdown: 0/1 retained sources directly address the stated topic; "
        "1/1 are adjacent or review-level.\n\n"
        "Evidence_type metadata note: evidence_type labels are resolved against source excerpts.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_source_directness_breakdown(paper, tmp_path)

    assert logs == []
    assert "Evidence type metadata note:" in fixed
    assert "evidence-type labels" in fixed
    assert "evidence_type" not in fixed


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


def test_source_inclusion_rationale_repairs_operational_subgroup_definition(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Define 'cardiovascular subgroup' operationally at the start "
        "(which subgrouping axes, which population strata, which outcomes)."
    )
    paper = "## Evidence Snapshot\n\nThe corpus is summarized.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "cardiovascular_subgroups", "receipts": [
        {"citation_token": "Smith 2024", "outcome_class": "cardiometabolic", "directness": "direct"},
        {"citation_token": "Jones 2025", "outcome_class": "frailty", "directness": "indirect"},
    ]}))

    fixed, logs = journal_finalizer._phase_d_source_inclusion_rationale(paper, tmp_path)

    assert "Topic-fit rationale:" in fixed
    assert "operationalize cardiovascular subgroups directly" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_inclusion_rationale"


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


def test_single_source_proportionality_covers_n_equals_one_context_only_ask(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "For outcome classes with n=1 sources, either merge them into adjacent "
        "classes or explicitly flag them as context-only and do not present them "
        "as parallel evidence domains."
    )
    paper = "## Evidence Landscape\n\nEvidence summary.\n\n## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"outcome_class": "safety"},
        {"outcome_class": "cardiometabolic"},
        {"outcome_class": "cardiometabolic"},
    ]}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_single_source_proportionality(paper, tmp_path)

    assert "Single-source outcome classes" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


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


def test_forward_dated_ai_disclosure_note_moves_to_limitations(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "In Limitations, add a specific statement about forward-dated (2026) "
        "citations and the implications for reproducibility, and remove or "
        "relocate the AI-use disclosure so it does not crowd the substantive sections."
    )
    paper = (
        "## Methods\n\n"
        "### AI-use disclosure\n\n"
        "Source retrieval and prose drafting were assisted by large language models.\n\n"
        "## Limitations\n\n"
        "The retained corpus remains observational and mechanistic.\n\n"
        "## Conclusion\n\n"
        "Several limitations bound this synthesis: the inclusion of forward-dated "
        "2026 citations means that the reproducibility of their reported numbers "
        "requires source-record verification.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}), encoding="utf-8")

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_forward_dated_ai_disclosure_note(paper, tmp_path)

    assert "Forward-dated citation note:" in fixed
    assert fixed.index("Forward-dated citation note:") < fixed.index("## Conclusion")
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_forward_dated_ai_disclosure_note",
            rule="move_forward_dated_note_to_limitations",
            n_changes=1,
            detail="added Limitations note for forward-dated citations while AI-use disclosure remains methods/supplemental",
        )
    ]


def test_publication_year_note_handles_prepublication_sources(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Add a brief note flagging 2026-dated sources as in-press or "
        "pre-publication where applicable, consistent with the eligibility "
        "criterion that preprints are accepted only when source-traceable."
    )
    paper = (
        "## Methods\n\nSources were screened.\n\n"
        "## Limitations\n\nThe corpus is bounded.\n\n"
        "## References\n\n- Smith 2026. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_forward_dated_ai_disclosure_note(paper, tmp_path)

    assert "Publication-year note:" in fixed
    assert "DOI/PubMed metadata" in fixed
    assert "bibliographic/in-press metadata" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "move_forward_dated_note_to_limitations"


def test_publication_year_note_ignores_unrelated_revision_feedback(tmp_path: Path) -> None:
    paper = (
        "## Limitations\n\nThe corpus is bounded.\n\n"
        "## References\n\n- Smith 2026. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Add clearer source attribution in the Evidence Landscape.",
    }))

    fixed, logs = journal_finalizer._phase_d_forward_dated_ai_disclosure_note(paper, tmp_path)

    assert fixed == paper
    assert logs == []


def test_forward_dated_ai_disclosure_note_is_revision_scoped(tmp_path: Path) -> None:
    paper = (
        "## Limitations\n\n"
        "The retained corpus remains observational and mechanistic.\n\n"
        "## Conclusion\n\n"
        "Forward-dated 2026 citations require reproducibility checks.\n"
    )

    fixed, logs = journal_finalizer._phase_d_forward_dated_ai_disclosure_note(paper, tmp_path)

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


def test_revision_audit_notes_answer_claim_count_and_doi_gap_asks(tmp_path: Path) -> None:
    from scripts import revision_coverage

    feedback = (
        "Audit the claim count for the Dosing and Pharmacokinetics slice "
        "(79 claims attributed to one mouse PK study) against the claim registry "
        "and report the corrected number, or explain the claim-derivation protocol if 79 is accurate. "
        "Add an explicit verification-gap note for sources without DOIs, distinguishing them "
        "from peer-reviewed sources in the source-context map."
    )
    paper = "## Evidence Landscape\n\nThe source-context map is summarized.\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "dosing_pharmacokinetics", "n_claims": 79},
            {"outcome_class": "contextual_other", "n_claims": 2},
        ],
    }), encoding="utf-8")
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {"body_citation": "Smith 2024"},
        "r2": {"body_citation": "Jones 2025", "source_doi": "10.1000/example"},
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_d_revision_audit_notes(paper, tmp_path)

    assert "Claim-count audit note: The Dosing and Pharmacokinetics slice count" in fixed
    assert "1 retained source contribute 79 extracted claims" in fixed
    assert "source(s)" not in fixed
    assert "claim(s)" not in fixed
    assert "Source-context verification gap: 1 source-bundle record have no DOI" in fixed
    assert "record(s)" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, revision_coverage.revision_asks(feedback)) == []
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_revision_audit_notes",
            rule="answer_structural_reviewer_audit_asks",
            n_changes=2,
            detail="added claim-count/source-identifier revision audit note(s)",
        )
    ]
    again, second_logs = journal_finalizer._phase_d_revision_audit_notes(fixed, tmp_path)
    assert again == fixed
    assert second_logs == []


def test_source_verification_phase_adds_citation_traceability_note(tmp_path: Path) -> None:
    from scripts import revision_coverage

    ask = (
        "Provide a complete, auditable in-text citation list mapping every author-year "
        "prose reference to a specific source bundle entry; add a methods_pack.json-style "
        "table or appendix in the manuscript itself so the reader can verify grounding "
        "without external artifacts."
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}), encoding="utf-8")
    paper = (
        "## Methods\n\n"
        "Sources were extracted under a reproducible protocol.\n\n"
        "## Evidence Snapshot\n\n"
        "### Source Classification Map\n\n"
        "- Smith 2024: outcome=frailty; directness=direct; tier=A1.\n\n"
        "## References\n\n"
        "- **Smith 2024.** Example source.\n"
    )

    fixed, logs = journal_finalizer._phase_d_source_verification_transparency(paper, tmp_path)

    assert "Citation traceability map:" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs and logs[0].phase == "D_source_verification_transparency"


def test_revision_audit_notes_add_source_label_disambiguation(tmp_path: Path) -> None:
    from agent.journal_surface_gate import evaluate_journal_surface
    from scripts import revision_coverage

    ask = (
        "Clarify the apparent Ward 2026 / Filev 2026 / Chen 2026 duplication and ensure "
        "each cited_as label maps to exactly one bundle entry."
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": ask}),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Ward 2026",
            "outcome_class": "immune_inflammation",
            "effect_direction": "null",
            "directness": "indirect",
            "source_title": "Icosapent ethyl modulates macrophages",
        },
        {
            "citation_token": "Filev 2026",
            "outcome_class": "immune",
            "effect_direction": "unclear",
            "directness": "indirect",
            "source_title": "Acute-phase IL-6 and SAA after COVID-19",
        },
        {
            "citation_token": "Chen 2026",
            "outcome_class": "cardiometabolic",
            "effect_direction": "mixed",
            "directness": "review",
            "source_title": "Cardiovascular subgroup signals",
        },
    ]}), encoding="utf-8")
    paper = "## Evidence Landscape\n\nExisting evidence text.\n\n## References\n\n- **Ward 2026.** X.\n"

    fixed, logs = journal_finalizer._phase_d_revision_audit_notes(paper, tmp_path)

    assert "Source-label disambiguation note:" in fixed
    assert "citation label Ward (2026) maps to one retained manifest receipt" in fixed
    assert "citation label Filev (2026) maps to one retained manifest receipt" in fixed
    assert "citation label Chen (2026) maps to one retained manifest receipt" in fixed
    assert "cited_as" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    surface_issues = evaluate_journal_surface(fixed).issues
    assert not any("unreferenced citation: Chen 2026" in issue.detail for issue in surface_issues)
    assert not any(issue.code == "topic_slug_artifact" for issue in surface_issues)
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="D_revision_audit_notes",
            rule="answer_structural_reviewer_audit_asks",
            n_changes=1,
            detail="added structural revision audit note(s)",
        )
    ]


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


def test_review_noise_strips_unsupported_inline_citation_marker() -> None:
    from agent.journal_surface_gate import unreferenced_citation_tokens
    from scripts.review_noise_control import apply_review_noise_control

    paper = (
        "## Discussion\n\n"
        "The hallmarks frame is discussed (López-Otín et al. 2013, as cited across the corpus; "
        "canonical threshold anchors include Studenski 2011 and Cruz-Jentoft 2019).\n\n"
        "## References\n\n"
        "- **Studenski 2011.** Gait speed and survival.\n"
        "- **Cruz-Jentoft 2019.** Sarcopenia consensus thresholds.\n"
    )

    fixed, changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "López-Otín" not in fixed
    assert "canonical threshold anchors include Studenski 2011 and Cruz-Jentoft 2019" in fixed
    assert unreferenced_citation_tokens(fixed) == ()
    assert ("strip_unsupported_inline_citation", 1, "removed 1 unsupported inline citation marker(s)") in changes


def test_review_noise_repairs_public_artifact_phrase() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface
    from scripts.review_noise_control import apply_review_noise_control

    paper = (
        "## Results\n\n"
        "The p-values should be read as descriptive only. The accepted receipt "
        "bundle contains one mapped source, and missing duration was not extracted "
        "from the receipt set.\n"
    )

    fixed, changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "should be read as" not in fixed
    assert "accepted receipt" not in fixed
    assert "receipt set" not in fixed
    assert "bundle contains" not in fixed
    assert "not extracted" not in fixed
    assert "p-values can be interpreted as descriptive only" in fixed
    assert "included-source bundle" in fixed
    assert "source bundle includes" in fixed
    assert "not available" in fixed
    assert ("repair_public_artifact_phrase", 4, "rewrote 4 public artifact phrase(s)") in changes
    issue_codes = {issue.code for issue in evaluate_journal_surface(fixed).issues}
    assert "public_artifact" not in issue_codes
    assert "template_meta" not in issue_codes


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


def test_phase_h_humanizes_unknown_public_topic_slug(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"topic": "epigenome_editing_longevity"}), encoding="utf-8",
    )
    paper = (
        "# Research Synthesis: epigenome_editing_longevity\n\n"
        "## Background\n\n"
        "The epigenome_editing_longevity corpus is bounded. "
        "`epigenome_editing_longevity` is a file slug.\n"
    )

    fixed, logs = journal_finalizer._phase_h_topic_slug_normalise(paper, tmp_path)

    assert "epigenome_editing_longevity corpus" not in fixed
    assert "epigenome editing longevity corpus" in fixed
    assert "`epigenome_editing_longevity`" in fixed
    assert any(e.rule == "slug_to_display_form" for e in logs)


def test_surface_artifact_cleanup_repairs_abbrev_and_duplicate_heading() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\n"
        "The direction remained uncertain.g., the corpus stayed indirect.\n\n"
        "### Immune and Inflammation Outcomes\n\n"
        "### Immune and Inflammation Outcomes\n\n"
        "The immune slice was retained.\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    before = evaluate_journal_surface(paper)
    assert any(i.code == "grammar_artifact" for i in before.issues)
    assert any(i.code == "duplicate_heading" for i in before.issues)

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)
    after = evaluate_journal_surface(fixed)
    assert "uncertain.g.," not in fixed
    assert fixed.count("### Immune and Inflammation Outcomes") == 1
    assert not any(i.code == "grammar_artifact" for i in after.issues)
    assert not any(i.code == "duplicate_heading" for i in after.issues)
    assert any(e.rule == "repair_known_surface_artifacts" for e in logs)


def test_phase_b_labels_weak_corpus_from_manifest_directness(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [
            {"directness": "mechanistic"},
            {"directness": "mechanistic"},
            {"directness": "adjacent"},
        ]}),
        encoding="utf-8",
    )

    fixed, logs = journal_finalizer._phase_b_corpus_strength_label(
        "# Research Synthesis: Alpha-ketoglutarate Effects\n\n## Results\n\nBody.\n",
        tmp_path,
    )

    assert fixed.startswith("# Mechanistic Evidence Map: Alpha-ketoglutarate Effects")
    assert any(e.rule == "label_weak_corpus_from_directness_profile" for e in logs)


def test_phase_b_labels_adjacent_corpus_from_manifest_directness(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [
            {"directness": "review"},
            {"directness": "adjacent"},
            {"directness": "indirect"},
        ]}),
        encoding="utf-8",
    )

    fixed, _logs = journal_finalizer._phase_b_corpus_strength_label(
        "# Research Synthesis: EGCG Effects\n\n## Results\n\nBody.\n",
        tmp_path,
    )

    assert fixed.startswith("# Adjacent Evidence Brief: EGCG Effects")


def test_phase_b_labels_low_direct_human_corpus_as_hypothesis_generating(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [
            {"directness": "direct"},
            {"directness": "review"},
            {"directness": "mechanistic"},
            {"directness": "adjacent"},
        ]}),
        encoding="utf-8",
    )

    fixed, _logs = journal_finalizer._phase_b_corpus_strength_label(
        "# Research Synthesis: Mixed Effects\n\n## Results\n\nBody.\n",
        tmp_path,
    )

    assert fixed.startswith("# Hypothesis-Generating Brief: Mixed Effects")


def test_phase_b_keeps_research_synthesis_when_direct_corpus_is_sufficient(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [
            {"directness": "direct"},
            {"directness": "direct"},
            {"directness": "review"},
        ]}),
        encoding="utf-8",
    )
    paper = "# Research Synthesis: Acarbose Effects\n\n## Results\n\nBody.\n"

    fixed, logs = journal_finalizer._phase_b_corpus_strength_label(paper, tmp_path)

    assert fixed == paper
    assert logs == []


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


def test_run_text_phases_restores_discussion_markers_after_surface_floors(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import scripts.review_noise_control as review_noise_control

    def strip_discussion_markers(
        text: str, _out_dir: Path, entries: list[journal_finalizer.FinalizerLogEntry],
        _entry_cls: type[journal_finalizer.FinalizerLogEntry],
    ) -> tuple[str, list[journal_finalizer.FinalizerLogEntry]]:
        return (
            text.replace("**Thesis:** ", "").replace("**Resolution criteria:** ", ""),
            entries,
        )

    monkeypatch.setattr(
        review_noise_control, "restore_surface_floors", strip_discussion_markers,
    )
    paper = (
        "# T\n\n## Discussion\n\n"
        "The corpus supports a bounded cardiometabolic interpretation.\n\n"
        "Future trials with clinical endpoints would settle the open threats.\n\n"
        "## Limitations\n\nstub.\n"
    )

    fixed, _log = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "**Thesis:**" in fixed
    assert "**Resolution criteria:**" in fixed


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


def test_phase_k_no_duplicate_fallback_for_multiple_thin_outcome_classes(tmp_path: Path) -> None:
    """Repro: 2+ thin outcome classes must NOT each receive the same long
    fallback paragraph — that produced two near-identical >=30-token paragraphs
    that tripped the journal-surface duplicate_paragraph gate (sirtuin L3).
    Only one long fallback; the rest get short distinct pointers (<30 tokens)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [{"receipt_id": "R1", "outcome_class": "cardiometabolic"}]}),
        encoding="utf-8",
    )
    (tmp_path / "citation_registry.json").write_text(
        json.dumps({"R1": {"body_citation": "Smith 2024"}}), encoding="utf-8",
    )
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "### Cognitive Outcomes\n\n"
        "## Discussion\n\nContext.\n"
    )
    out, _ = journal_finalizer._phase_k_route_outcome_paragraphs(text, tmp_path)
    # exactly one long fallback paragraph across both thin classes
    assert out.count("Evidence for this outcome class is represented") == 1
    # and the duplicate_paragraph detector finds nothing
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from journal_surface_batch_audit import scan_duplicate_paragraphs  # type: ignore[import-not-found]
    assert not any("duplicate_paragraph" in str(i) for i in scan_duplicate_paragraphs(out))


def test_phase_g_restores_registry_references_before_artifact_refresh(tmp_path: Path) -> None:
    """A finalizer pass may rewrite prose after the deterministic reference
    append. Before Phase G recomputes artifact consistency, References must be
    rebuilt from manifest + citation_registry so registry coverage cannot drift.
    """
    (tmp_path / "full_paper.md").write_text(
        "## Results\n\nSauna evidence remains bounded.\n\n"
        "## References\n\n"
        "- **Passive Heat Therapy 2023.** _Passive heat therapy improves cognitive and cerebrovascular function in healthy midlife and older adults._ DOI: 10.3390/jcm14103566. PMID: 40429561.\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {
                "receipt_id": "r14",
                "source_title": "Passive heat therapy improves cognitive and cerebrovascular function in healthy midlife and older adults",
                "source_doi": "10.1152/physiol.2023.38.s1.5731414",
            },
            {
                "receipt_id": "r15",
                "source_title": "The Effect of Eight Weeks of Passive Heat Therapy on Mental Health, Sleep, and Chronic Pain in Persons with Spinal Cord Injury: A Pilot Study",
                "source_doi": "10.3390/jcm14103566",
                "source_pmid": "40429561",
            },
        ],
    }), encoding="utf-8")
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r14": {
            "receipt_id": "r14",
            "body_citation": "Passive Heat Therapy 2023",
            "source_year": 2023,
            "source_doi": "10.1152/physiol.2023.38.s1.5731414",
        },
        "r15": {
            "receipt_id": "r15",
            "body_citation": "Uhlig-Reche 2025",
            "source_year": 2025,
            "source_doi": "10.3390/jcm14103566",
            "source_pmid": "40429561",
        },
    }), encoding="utf-8")
    from agent.artifact_consistency import verify_run_artifacts
    before = verify_run_artifacts(tmp_path)
    assert any(c.name == "citation_registry_coverage" and not c.passed for c in before.checks)

    log = journal_finalizer._phase_g_refresh_sidecars(tmp_path)
    rules = [entry.rule for entry in log]
    assert "restore_registry_references_post_finalizer" in rules
    assert "close_registry_orphan_references_post_finalizer" in rules

    paper = (tmp_path / "full_paper.md").read_text(encoding="utf-8")
    assert "**Passive Heat Therapy 2023.**" in paper
    assert "DOI: 10.1152/physiol.2023.38.s1.5731414." in paper
    assert "**Uhlig-Reche 2025.**" in paper
    assert "DOI: 10.3390/jcm14103566." in paper
    assert "PMID: 40429561." in paper
    assert "Additional corpus sources informed the synthesis" in paper
    from agent.journal_surface_gate import evaluate_journal_surface
    assert not any(i.code == "citation_artifact" for i in evaluate_journal_surface(paper).issues)
    after = verify_run_artifacts(tmp_path)
    assert after.passed is True


def test_revision_surface_notes_insert_manifest_backed_thin_brief_notes(tmp_path: Path) -> None:
    feedback = (
        "Add substantive narrative under each outcome subsection that links at least one "
        "specific quantitative or qualitative finding to its source; In the Conclusion, "
        "tie the tiered interpretation to the specific bundle: name which 1 direct source "
        "carries the most interpretive weight and explain why the remaining sources do not "
        "change that weight; Expand the Limitations to specifically note that several "
        "admitted sources are protocols or cross-sectional observational designs that cannot "
        "support causal claims even individually."
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": feedback}), encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {
                "citation_token": "Wang 2024",
                "outcome_class": "cardiometabolic",
                "directness": "direct",
                "evidence_tier": "A1",
                "effect_direction": "null",
            },
            {
                "citation_token": "Vicente-Gabriel 2024",
                "source_title": "Vascular aging protocol cross-sectional study",
                "outcome_class": "contextual_other",
                "directness": "protocol",
                "evidence_tier": "D1",
                "effect_direction": "null",
            },
        ],
    }), encoding="utf-8")
    paper = (
        "## Results\n\n"
        "| Evidence domain | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n\n"
        "## Limitations\n\nThin corpus.\n\n"
        "## Conclusion\n\nBounded conclusion.\n"
    )

    fixed, logs = journal_finalizer._phase_d_revision_surface_notes(paper, tmp_path)

    assert [entry.rule for entry in logs] == ["insert_manifest_backed_revision_surface_notes"]
    assert "Source examples: Cardiometabolic: Wang 2024" in fixed
    assert "**Direct-source ceiling:** The direct clinical source set is Wang 2024." in fixed
    assert "**Design-limit note:** Protocol, mechanistic, observational, or cross-sectional sources" in fixed
    assert "Vicente-Gabriel 2024" in fixed
