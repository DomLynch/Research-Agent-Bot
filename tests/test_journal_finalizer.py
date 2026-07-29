from __future__ import annotations

import json
import importlib
import re
import time
from pathlib import Path
from typing import Any

from agent import journal_finalizer, revision_quality
from agent.journal_surface_gate import evaluate_journal_surface
from agent.sources.pubmed import pmid_rows_fingerprint


def test_domain_frame_template_cleanup_removes_submit_blocked_aging_phrases() -> None:
    paper = (
        "## Abstract\n\n"
        "The intervention remains a bounded geroscience case. "
        "Selected biomarkers should not be treated as proof of durable healthspan benefit.\n\n"
        "## Conclusion\n\n"
        "The retained clinical and mechanistic evidence profile defines a bounded geroscience rationale. "
        "The discussion should avoid any unqualified anti-aging claim, broad geroprotection, "
        "or standalone anti-aging or longevity proof."
    )

    fixed, logs = journal_finalizer._phase_d_domain_frame_template_cleanup(paper)

    assert "bounded geroscience" not in fixed
    assert "durable healthspan benefit" not in fixed
    assert "unqualified anti-aging claim" not in fixed
    assert "geroprotection" not in fixed
    assert "standalone anti-aging or longevity proof" not in fixed
    assert "bounded evidence" not in fixed
    assert logs and logs[0].phase == "D_domain_frame_template_cleanup"


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


def test_phase_f_keeps_reviewer_renamed_outcome_heading_idempotent(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n### Exposure and Dose-Adjacent Evidence Outcomes\n\n"
        "Bounded dose-adjacent result.\n\n## Discussion\n\nInterpretation.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{
        "outcome_class": "dosing_pharmacokinetics",
        "effect_direction": "unclear",
        "directness": "indirect",
    }]}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": (
            "Rename the outcome class 'Dosing and Pharmacokinetics' to "
            "'Exposure and Dose-Adjacent Evidence'."
        ),
    }))

    fixed, _ = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    stable, _ = journal_finalizer._phase_f_reconcile_results_table(fixed, tmp_path)

    assert fixed.count("### Exposure and Dose-Adjacent Evidence Outcomes") == 1
    assert "### Dosing and Pharmacokinetics Outcomes" not in fixed
    assert stable == fixed


def test_reviewer_adjusted_outcome_label_does_not_expand_completed_rename() -> None:
    feedback = "Rename the outcome class 'Safety' to 'Safety and Tolerability'."
    label = "Safety and Tolerability Outcomes; Safety remains secondary."

    fixed = journal_finalizer._reviewer_adjusted_outcome_label(label, feedback)
    stable = journal_finalizer._reviewer_adjusted_outcome_label(fixed, feedback)

    assert fixed == (
        "Safety and Tolerability Outcomes; "
        "Safety and Tolerability remains secondary."
    )
    assert stable == fixed
    assert journal_finalizer._reviewer_adjusted_outcome_label(
        "Safety and Tolerability Outcomes",
        "Rename the outcome class 'Safety and Tolerability' to 'Safety'.",
    ) == "Safety Outcomes"


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
            "thesis_text": "The primary outcome was reported at p < 0.05.",
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
    assert "positive=0, negative=0, null=2, mixed=0, unclear=0 (n=2)" in fixed
    assert "null signal in 2/2 sources" not in fixed


def test_phase_f_uses_endpoint_context_before_calcium_bone_fallback(tmp_path: Path) -> None:
    paper = "## Results\n\nShort.\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "calcium_supplementation_effects",
        "receipts": [
            {
                "citation_token": "Kumsa 2025",
                "source_title": "Effects of calcium supplementation on the prevention of preeclampsia",
                "outcome_class": "skeletal_fracture_bone",
                "effect_direction": "unclear",
                "directness": "review",
                "evidence_tier": "B1",
                "n_claims": 12,
            },
            {
                "citation_token": "Abajo 2017",
                "source_title": "Risk of Ischemic Stroke Associated With Calcium Supplements",
                "outcome_class": "skeletal_fracture_bone",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "n_claims": 10,
            },
            {
                "citation_token": "Bone 2024",
                "source_title": "Calcium supplementation and bone fracture risk",
                "outcome_class": "skeletal_fracture_bone",
                "effect_direction": "positive",
                "directness": "direct",
                "evidence_tier": "A1",
                "n_claims": 8,
            },
        ],
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert logs
    assert "| Calcium Supplementation Effects / Cardiometabolic | n=2; claims=22 |" in fixed
    assert "| Calcium Supplementation Effects / Skeletal, Fracture, and Bone | n=1; claims=8 |" in fixed


def test_proactive_findings_map_uses_endpoint_context_before_topic_keyword(tmp_path: Path) -> None:
    paper = "## Evidence Landscape\n\nBrief.\n\n## Results\n\nShort.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "calcium_supplementation_effects",
        "receipts": [
            {
                "citation_token": "Zhang 2026",
                "source_title": "Association Between Calcium Supplementation and Recurrence of Cardiovascular Events",
                "outcome_class": "skeletal_fracture_bone",
                "effect_direction": "null",
                "directness": "indirect",
                "evidence_tier": "B2",
            },
            {
                "citation_token": "Bone 2024",
                "source_title": "Calcium supplementation and bone fracture risk",
                "outcome_class": "skeletal_fracture_bone",
                "effect_direction": "positive",
                "directness": "direct",
                "evidence_tier": "A1",
            },
        ],
    }), encoding="utf-8")

    fixed, logs = journal_finalizer._phase_d_proactive_findings_map(paper, tmp_path)

    assert logs
    assert "### Findings Map" in fixed
    assert "Findings Map completeness note: all 2 admitted manifest rows" in fixed
    assert "Cardiometabolic n=1 (direction: null=1; directness: indirect=1; sources: Zhang 2026)" in fixed
    assert "Skeletal, Fracture, and Bone n=1 (direction: positive=1; directness: direct=1; sources: Bone 2024)" in fixed
    assert "| Cardiometabolic | Zhang 2026: Association Between Calcium Supplementation" in fixed
    assert "| Skeletal, Fracture, and Bone | Bone 2024: Calcium supplementation and bone fracture risk | direction=positive | directness=direct | A1 |" in fixed


def test_findings_map_reconciles_counts_for_exact_reviewer_wording(tmp_path: Path) -> None:
    feedback = (
        "Reconcile the directional-coding counts within each Findings Map subsection "
        "so the n, direction, and directness totals are internally consistent and auditable.; "
        "For each outcome class, explicitly list every admitted source (by cited_as) "
        "with its directness, effect direction, and a one-line finding."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Findings Map\n\n"
        "| Source | Outcome class | Direction | Directness | Tier | Finding |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Old 2024 | Old | null | indirect | B2 | stale row |\n\n"
        "## Results\n\nShort.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Alwhaibi 2024",
            "source_title": "Ramadan fasting cardiometabolic trial",
            "outcome_class": "cardiometabolic",
            "effect_direction": "positive",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 4,
        },
        {
            "citation_token": "Khalil 2025",
            "source_title": "Ramadan fasting diabetes safety cohort",
            "outcome_class": "cardiometabolic",
            "effect_direction": "unclear",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 2,
        },
    ]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert logs
    assert "stale row" not in fixed
    assert "Findings Map accounting note:" in fixed
    assert "Cardiometabolic n=2 (direction: positive=1; unclear=1; directness: direct=1; indirect=1; sources: Alwhaibi 2024; Khalil 2025)" in fixed
    assert "| Cardiometabolic | Alwhaibi 2024: Ramadan fasting cardiometabolic trial | direction=positive | directness=direct | A1 |" in fixed
    assert "| Cardiometabolic | Khalil 2025: Ramadan fasting diabetes safety cohort | direction=unclear | directness=indirect | B2 |" in fixed


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
    assert "positive=0, negative=0, null=2, mixed=0, unclear=0 (n=2)" in fixed
    assert "positive=0, negative=0, null=1, mixed=0, unclear=0 (n=1)" in fixed
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
        "(n=1; claims=28; positive=0, negative=0, null=1, mixed=0, unclear=0 (n=1)"
    ) in fixed


def test_phase_f_replaces_stale_summary_with_one_canonical_direction_table(
    tmp_path: Path,
) -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=3 | unclear | 2 direct | limited |\n\n"
        "### Results Summary\n\n"
        "- Cardiometabolic: n=3; claims=9; mixed signal in 3/3 sources | "
        "directness: 2 direct; 1 review; main limitation: directionally heterogeneous.\n\n"
        "## Cross-Domain Synthesis\n\n"
        "Cardiometabolic (positive=1, null=1, unclear=1).\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "direct"},
            {"outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "direct"},
            {"outcome_class": "cardiometabolic", "effect_direction": "unclear", "directness": "review"},
        ],
    }))

    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    profile = "positive=1, negative=0, null=1, mixed=0, unclear=1 (n=3)"
    results = fixed.split("## Results", 1)[1].split("## Cross-Domain Synthesis", 1)[0]
    assert logs
    assert "| Outcome class | Corpus slice | Direction profile |" in results
    assert results.count(profile) >= 1
    assert "### Results Summary" not in results
    assert "mixed signal in 3/3 sources" not in results


def test_phase_f_removes_legacy_unclassified_results_summary(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n### Results Summary\n\n"
        "- Cardiometabolic: n=1; claims=2; benefit signal in 1/1 sources | "
        "directness: not classified; main limitation: single-source support.\n\n"
        "## Discussion\n\nBounded interpretation.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "cardiometabolic", "effect_direction": "positive"},
        ],
    }))

    fixed, _logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert "### Results Summary" not in fixed


def test_phase_f_preserves_author_written_results_summary(tmp_path: Path) -> None:
    summary = (
        "### Results Summary\n\n"
        "Adjudication found that effect direction differed by endpoint and follow-up."
    )
    paper = f"## Results\n\n{summary}\n\n## Discussion\n\nBounded interpretation.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "cardiometabolic", "effect_direction": "mixed", "directness": "direct"},
        ],
    }))

    fixed, _logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert summary in fixed


def test_phase_f_preserves_structured_author_results_summary(tmp_path: Path) -> None:
    summary = (
        "### Results Summary\n\n"
        "- Cardiometabolic: n=3; claims=9; mixed signal in 3/3 sources.\n\n"
        "This author-written interpretation explains why endpoint timing changes the result."
    )
    paper = f"## Results\n\n{summary}\n\n## Discussion\n\nBounded interpretation.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "cardiometabolic", "effect_direction": "mixed", "directness": "direct"},
        ],
    }))

    fixed, _logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert summary in fixed


def test_phase_f_preserves_authored_single_line_summary(tmp_path: Path) -> None:
    summary = (
        "### Results Summary\n\n"
        "- Cardiometabolic: n=3; claims=9; mixed signal in 3/3 sources | "
        "directness: 2 direct; main limitation: endpoint timing altered interpretation."
    )
    paper = f"## Results\n\n{summary}\n\n## Discussion\n\nBounded interpretation.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [
            {"outcome_class": "cardiometabolic", "effect_direction": "mixed", "directness": "direct"},
        ],
    }))

    fixed, _logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)

    assert summary in fixed


def test_phase_f_uses_canonical_role_for_direct_animal_source(tmp_path: Path) -> None:
    paper = "## Results\n\nExisting bounded results.\n\n## Discussion\n\nInterpretation.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipts": [{
            "outcome_class": "contextual_other",
            "effect_direction": "null",
            "directness": "direct",
            "evidence_tier": "A1",
            "source_title": "Randomized intervention in mice",
        }],
    }))

    fixed, _logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    results = fixed.split("## Results", 1)[1].split("## Discussion", 1)[0]

    assert "| 1 mechanistic |" in results
    assert "| 1 direct |" not in results


def test_phase_n_restores_short_limitations_after_finalizer(tmp_path: Path) -> None:
    restore_surface_floors = journal_finalizer.review_noise_control.restore_surface_floors

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
    import revision_coverage

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


def test_phase_g_refreshes_revision_coverage_gate_after_finalizer_text(tmp_path: Path) -> None:
    ask = (
        "Resolve the Brouwers 2016 direction coding inconsistency: either confirm the "
        "positive frailty coding with the supporting statistic, or correct to unclear/null "
        "to match the p=0.88 numeric correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Numeric verification note: Brouwers 2016 reported a non-significant mapped "
        "comparison (p = 0.88); this synthesis treats that mapped comparison, not every "
        "within-source contrast, as non-significant.\n\n"
        "- Brouwers 2016: outcome=Frailty; direction=null; finding=representative statistic p=0.88.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}), encoding="utf-8")
    (tmp_path / "revision_coverage_gate.json").write_text(
        json.dumps({"passed": False, "ask_count": 1, "unmet_asks": [ask]}),
        encoding="utf-8",
    )

    logs = journal_finalizer._phase_g_refresh_sidecars(tmp_path)

    gate = json.loads((tmp_path / "revision_coverage_gate.json").read_text(encoding="utf-8"))
    assert gate == {
        "passed": True,
        "ask_count": 1,
        "unmet_asks": [],
        "refreshed_by": "journal_finalizer",
    }
    assert any(entry.rule == "refresh_revision_coverage_gate_post_finalizer" for entry in logs)


def test_source_verification_transparency_is_inserted_into_methods(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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


def test_admission_funnel_clarification_covers_live_overlapping_bucket_ask(
    tmp_path: Path,
) -> None:
    import revision_coverage

    ask = (
        "Reconcile the source-admission funnel counts and explain how the 73 "
        "classified candidates resolve to 66 admitted final sources, including "
        "how partial-only and mixed partial-or-none candidates are handled."
    )
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Classified source candidates | 73 |\n"
        "| Mixed partial-or-none claim-binding candidates | 51 |\n"
        "| Partial-only claim-binding candidates | 16 |\n"
        "| Admitted final sources | 66 |\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "n_receipts": 66,
        "receipt_funnel": {
            "classified_receipt_candidates": 73,
            "counts": {
                "admitted_receipts": 66,
                "original_strict_high_confidence_receipts": 29,
            },
        },
    }))
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": ask}),
    )

    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(
        paper, tmp_path,
    )

    assert logs
    assert "classified source candidates (73) -> admitted final sources (66)" in fixed
    assert "overlapping diagnostic states" in fixed
    assert "not admitted" in fixed and "= 7" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_admission_funnel_clarification_covers_search_summary_selection_logic(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

    ask = (
        "Replace or supplement the non-additive claim-binding funnel with a clearly "
        "additive-screening flow (records screened -> excluded with reasons -> "
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
    import revision_coverage

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


def test_methods_funnel_arithmetic_uses_manifest_counts(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Reconcile the Methods funnel arithmetic so the admitted-source count and "
        "classified-candidate count are consistent; either report actual candidate "
        "counts or remove the funnel numbers and state the corpus size directly."
    )
    paper = "## Methods\n\nThe retained corpus contains 33 sources.\n\n## Results\n\nResults.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "n_receipts": 33,
        "receipt_funnel": {
            "classified_receipt_candidates": 61,
            "counts": {"admitted_receipts": 33},
        },
    }))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_admission_funnel_clarification(paper, tmp_path)

    assert "33 admitted sources came from 61 classified source candidates" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "state_receipt_funnel_arithmetic"


def test_outcome_direction_summary_uses_manifest_tallies(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Correct the Results outcome-class directional summaries to match the Findings Map "
        "coded directions (Frailty = null in 2/2; Longevity = unclear in 2/2; "
        "Safety/Comorbidity = unclear in 1/1)."
    )
    rows = [
        {"citation_token": "A 2024", "outcome_class": "frailty", "effect_direction": "null"},
        {"citation_token": "B 2024", "outcome_class": "frailty", "effect_direction": "null"},
        {"citation_token": "C 2024", "outcome_class": "longevity", "effect_direction": "unclear"},
        {"citation_token": "D 2024", "outcome_class": "longevity", "effect_direction": "unclear"},
        {"citation_token": "E 2024", "outcome_class": "safety_comorbidity", "effect_direction": "unclear"},
    ]

    assert revision_coverage.asks_effect_direction_reconciliation(ask)
    note = journal_finalizer._manifest_effect_direction_reconciliation_note(ask, rows)

    assert "Frailty = null in 2/2" in note
    assert "Longevity = unclear in 2/2" in note
    assert "Safety and Comorbidity = unclear in 1/1" in note
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    paper = (
        "## Key Findings\n\nKey findings from source synthesis:\n\nExisting generated summary.\n\n"
        "## Results\n\nExisting directional prose.\n"
    )
    fixed, logs = journal_finalizer._phase_d_substantive_evidence_synthesis(paper, tmp_path)

    assert "Frailty = null in 2/2" in fixed
    assert "Longevity = unclear in 2/2" in fixed
    assert "Safety and Comorbidity = unclear in 1/1" in fixed
    fixed, _ = journal_finalizer._phase_m_strip_surface_duplicate_paragraphs(fixed)
    fixed, _ = journal_finalizer.review_noise_control.apply_review_noise_control(fixed, tmp_path)
    assert "Outcome-class coded-direction reconciliation:" in fixed
    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "add_manifest_grounded_evidence_landscape_and_key_findings"


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


def test_terminal_terminology_scrubs_late_admission_funnel_note(tmp_path: Path) -> None:
    ask = "Fix receipt funnel arithmetic and explain why 25 admitted sources came from 73 candidates."
    paper = (
        "## Methods\n\n"
        "### Source admission funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Source candidates | 73 |\n"
        "| Admitted final sources | 25 |\n\n"
        "## References\n\n- Smith 2024. DOI: 10.1/x.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({
        "n_receipts": 25,
        "receipt_funnel": {
            "classified_receipt_candidates": 73,
            "counts": {"admitted_receipts": 25},
        },
    }))

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Receipt-funnel interpretation:" not in fixed
    assert "receipt-funnel buckets" not in fixed.lower()
    assert "classified receipt candidates" not in fixed.lower()
    assert "Source-selection interpretation:" in fixed
    assert "73 classified source candidates" in fixed
    assert any(log.phase == "D_admission_funnel_clarification" for log in logs)


def test_prior_publication_differentiation_repairs_overlap_ask(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

    ask = (
        "Tighten the Conclusion to match the bounded claim posture and do not "
        "allow soft lifestyle recommendations."
    )
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

    assert fixed.count("Evidence scope:") == 2
    assert "Evidence-honesty note:" not in fixed
    assert "non-supportive for clinical efficacy claims" in fixed
    assert "hypothesis-generating only" in fixed
    assert "no direct interventional hard-endpoint evidence" in fixed
    assert "does not support broad causal, clinical, or policy claims" in fixed
    assert "may support the topic as a general health or lifestyle intervention" not in fixed
    assert "non-supportive for clinical efficacy or general health-intervention claims" in fixed
    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
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


def test_general_health_claim_repair_covers_affirmative_variants() -> None:
    variants = (
        "The intervention can be used as a general health intervention.",
        "The intervention may be used as a general health intervention.",
        "The intervention is appropriate as a lifestyle intervention.",
        "The intervention is suitable as a lifestyle intervention.",
        "The evidence supports its use as a lifestyle intervention.",
        "The evidence supports adoption as a lifestyle intervention.",
    )

    for sentence in variants:
        fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(
            f"## Conclusion\n\n{sentence}\n",
        )
        assert changed == 1
        assert "can be used" not in fixed
        assert "may be used" not in fixed
        assert "is appropriate" not in fixed
        assert "is suitable" not in fixed
        assert "supports its use" not in fixed
        assert "supports adoption" not in fixed
        assert "non-supportive for clinical efficacy or general health-intervention claims" in fixed

    bounded = (
        "## Conclusion\n\n"
        "The evidence does not support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(bounded) == (bounded, 0)
    uncertain = (
        "## Conclusion\n\n"
        "The evidence is insufficient to determine whether the intervention is "
        "appropriate as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(uncertain) == (uncertain, 0)
    contrastive = (
        "## Conclusion\n\nThe intervention does not prevent cancer but is suitable "
        "as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(contrastive)
    assert changed == 1
    assert "is suitable as a lifestyle intervention" not in fixed
    bounded = (
        "## Conclusion\n\nThe evidence fails to support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(bounded) == (bounded, 0)
    past_bounded = (
        "## Conclusion\n\nThe trial failed to support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(past_bounded) == (past_bounded, 0)
    cross_clause = (
        "## Conclusion\n\nThe evidence supports further research but does not "
        "support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(cross_clause) == (cross_clause, 0)
    not_only = (
        "## Conclusion\n\nThe evidence not only supports its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(not_only) == (not_only, 0)
    coordinated = (
        "## Conclusion\n\nThe evidence not only supports its use as a lifestyle "
        "intervention but also recommends adoption.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(coordinated) == (coordinated, 0)
    because = (
        "## Conclusion\n\nThe evidence supports further research because it does "
        "not support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(because) == (because, 0)
    unlikely = (
        "## Conclusion\n\nThe evidence is unlikely to support its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(unlikely) == (unlikely, 0)
    coordinated_safe = (
        "## Conclusion\n\nThe evidence does not support or recommend its use as a lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(coordinated_safe) == (coordinated_safe, 0)
    coordinated_unsafe = (
        "## Conclusion\n\nThe evidence supports adoption and use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(coordinated_unsafe)
    assert changed == 1
    assert "cannot establish adoption and use" in fixed
    not_merely = (
        "## Conclusion\n\nThe evidence does not merely support its use as a lifestyle intervention; it establishes it.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(not_merely) == (not_merely, 0)
    for bounded in (
        "The authors recommend against using it as a lifestyle intervention.",
        "The evidence supports avoiding its use as a lifestyle intervention.",
    ):
        paper = f"## Conclusion\n\n{bounded}\n"
        assert journal_finalizer._replace_unsupported_general_health_claim(paper) == (paper, 0)
    temporal = (
        "## Conclusion\n\nThe intervention has been recommended since 2020 as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(temporal)
    assert changed == 1
    assert "has not been established since 2020" in fixed
    for bounded in (
        "The authors recommend that the intervention not be used as a lifestyle intervention.",
        "The evidence neither supports nor recommends its use as a lifestyle intervention.",
    ):
        paper = f"## Conclusion\n\n{bounded}\n"
        assert journal_finalizer._replace_unsupported_general_health_claim(paper) == (paper, 0)
    temporal_subject = (
        "## Conclusion\n\nThe intervention has been recommended since it was introduced as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(temporal_subject)
    assert changed == 1
    assert "has not been established since it was introduced" in fixed
    decimal = (
        "## Conclusion\n\nBMI changed by 2.1 kg/m2 (Smith 2025), but the intervention "
        "is suitable as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(decimal)
    assert changed == 1
    assert "BMI changed by 2.1 kg/m2 (Smith 2025)" in fixed
    assert "is suitable" not in fixed
    for prefix in (
        "Smith et al. reported a null estimate, but ",
        "The U.S. trial reported a null estimate, but ",
        "The p.o. regimen had a null estimate, but ",
    ):
        fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(
            f"## Conclusion\n\n{prefix}the intervention is suitable as a lifestyle intervention.\n",
        )
        assert changed == 1
        assert prefix.strip() in fixed
        assert "non-supportive for clinical efficacy or general health-intervention claims" in fixed
    for prefix in (
        "The null result was reported by Smith et al.",
        "The null result was reported in the U.S.",
        "The null result followed p.o.",
    ):
        fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(
            f"## Conclusion\n\n{prefix} The intervention is suitable as a lifestyle intervention.\n",
        )
        assert changed == 1
        assert prefix in fixed
        assert "The intervention is suitable" not in fixed
    abbreviation_negation = (
        "## Conclusion\n\nNo evidence from Smith et al. supports its use as a "
        "lifestyle intervention.\n"
    )
    assert journal_finalizer._replace_unsupported_general_health_claim(
        abbreviation_negation,
    ) == (abbreviation_negation, 0)
    abbreviation_boundary = (
        "## Conclusion\n\nNo evidence was reported by Smith et al. Participants report "
        "that the intervention is suitable as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(
        abbreviation_boundary,
    )
    assert changed == 1
    assert "No evidence was reported by Smith et al." in fixed
    assert "is suitable as a lifestyle intervention" not in fixed
    for bounded in (
        "No evidence from Dr. Smith supports its use as a lifestyle intervention.",
        "No U.S. Food and Drug Administration evidence supports its use as a lifestyle intervention.",
        "No evidence was reported by the U.S. Food and Drug Administration to support its use as a lifestyle intervention.",
        "No evidence was found in the U.S. Food and Drug Administration report to support its use as a lifestyle intervention.",
        "No credible evidence from the U.S. FDA supports its use as a lifestyle intervention.",
        "Not any available evidence from the U.S. FDA supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. FDA currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Food and Drug Administration currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Centers for Disease Control and Prevention currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Preventive Services Task Force supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. National Academy of Medicine supports its use as a lifestyle intervention.",
        "No evidence from a U.S. FDA report supports its use as a lifestyle intervention.",
        "No evidence from any U.S. FDA source supports its use as a lifestyle intervention.",
        "No evidence from the U.S. FDA-supported trial supports its use as a lifestyle intervention.",
    ):
        paper = f"## Conclusion\n\n{bounded}\n"
        assert journal_finalizer._replace_unsupported_general_health_claim(paper) == (paper, 0)
    for boundary in ("U.S.", "p.o."):
        paper = (
            f"## Conclusion\n\nNo evidence was reported in the {boundary} Participants report "
            "that the intervention is suitable as a lifestyle intervention.\n"
        )
        fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(paper)
        assert changed == 1
        assert f"No evidence was reported in the {boundary}" in fixed
        assert "is suitable as a lifestyle intervention" not in fixed
    long_subject = (
        "## Conclusion\n\nNo evidence was reported in the U.S. Independent clinical "
        "experts now recommend its use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(long_subject)
    assert changed == 1
    assert "experts now cannot establish its use" in fixed
    from_boundary = (
        "## Conclusion\n\nNo evidence was reported from the U.S. Independent clinical "
        "experts now recommend its use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(from_boundary)
    assert changed == 1
    assert "experts now cannot establish its use" in fixed
    named_boundary = (
        "## Conclusion\n\nNo evidence was reported from the U.S. Food and Drug "
        "Administration recommends its use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(named_boundary)
    assert changed == 1
    assert "Administration cannot establish its use" in fixed
    institutional_boundary = (
        "## Conclusion\n\nNo evidence from the U.S. FDA recommends its use as a "
        "lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(institutional_boundary)
    assert changed == 1
    assert "FDA cannot establish its use" in fixed
    short_boundary = (
        "## Conclusion\n\nThere was no effect in the U.S. Experts recommend its use "
        "as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(short_boundary)
    assert changed == 1
    assert "Experts cannot establish its use" in fixed
    adverb_boundary = (
        "## Conclusion\n\nNo evidence from the U.S. Experts currently recommend its "
        "use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(adverb_boundary)
    assert changed == 1
    assert "Experts currently cannot establish its use" in fixed
    titled_boundary = (
        "## Conclusion\n\nNo evidence from the U.S. Public Health Experts currently "
        "recommend its use as a lifestyle intervention.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(titled_boundary)
    assert changed == 1
    assert "Experts currently cannot establish its use" in fixed
    infinitive = "## Conclusion\n\nThe guidance asks readers to support its use as a lifestyle intervention.\n"
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(infinitive)
    assert changed == 1
    assert "asks readers not to establish its use" in fixed
    trailing_qualifier = (
        "## Conclusion\n\nThe intervention is suitable as a lifestyle intervention "
        "despite no evidence of efficacy.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(
        trailing_qualifier,
    )
    assert changed == 1
    assert "is suitable as a lifestyle intervention" not in fixed
    assert "despite no evidence of efficacy" in fixed
    multiple = (
        "## Conclusion\n\nAlthough efficacy is unproven, it is suitable as a lifestyle intervention. "
        "Evidence is limited and the intervention may be used for general health.\n"
    )
    fixed, changed = journal_finalizer._replace_unsupported_general_health_claim(multiple)
    assert changed == 2
    assert fixed.count("non-supportive for clinical efficacy or general health-intervention claims") == 1


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


def test_strip_surface_duplicate_paragraphs_removes_short_discussion_sentences() -> None:
    sentence_a = "Population specificity constrains external validity in three directions."
    sentence_b = "The endpoint scope of the corpus is narrow."
    paper = (
        "## Discussion\n\n"
        f"{sentence_a}\n\n"
        f"{sentence_b} It does not establish disease incidence.\n\n"
        "The next paragraph preserves distinct evidence.\n\n"
        f"{sentence_a}\n\n"
        f"{sentence_b}\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    fixed, logs = journal_finalizer._phase_m_strip_surface_duplicate_paragraphs(paper)

    assert fixed.count(sentence_a) == 1
    assert fixed.count(sentence_b) == 1
    assert logs and logs[0].n_changes == 2


def test_strip_surface_duplicate_paragraphs_cleans_abstract_intro_repeat() -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    duplicate = (
        "The thesis is: Across curated reference papers, the evidence base shows a "
        "context-dependent profile. Positive signals appear alongside null findings, "
        "and the synthesis surfaces cross-study disagreements across outcome classes. "
        "This thesis is treated as an organizing claim, not as a substitute for the "
        "structured study table, because the source record includes supportive, null, "
        "and adverse signals across different outcome classes."
    )
    intro = (
        "The introduction frames the corpus, evidence hierarchy, and interpretation "
        "boundary before the paper turns to methods and results."
    )
    paper = (
        "## Abstract\n\n"
        f"{duplicate}\n\n"
        "## Introduction\n\n"
        f"{intro}\n\n"
        f"{duplicate}\n\n"
        "## Results\n\n"
        "The structured evidence table separates direct, adjacent, and contextual evidence.\n"
    )

    assert _duplicate_paragraph_issue_messages(paper)
    fixed, logs = journal_finalizer._phase_m_strip_surface_duplicate_paragraphs(paper)

    assert _duplicate_paragraph_issue_messages(fixed) == ()
    assert fixed.count(duplicate) == 1
    assert intro in fixed
    assert any(log.phase == "M_duplicate_paragraph_strip" for log in logs)


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


def test_run_text_phases_strips_thesis_duplicates_added_at_terminal_phase(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    duplicate = (
        "The thesis is: Across curated reference papers, the evidence base shows a "
        "context-dependent profile with supportive, null, and adverse signals across "
        "different outcome classes. The synthesis surfaces cross-study disagreements "
        "and treats the thesis as an organizing claim rather than a substitute for "
        "the structured study table."
    )

    def late_thesis(text: str) -> tuple[str, list[journal_finalizer.FinalizerLogEntry]]:
        return (
            text
            + "\n\n## Discussion\n\n"
            + duplicate,
            [journal_finalizer.FinalizerLogEntry(
                phase="N_declare_thesis",
                rule="inject_discussion_markers",
                n_changes=1,
                detail="test late thesis insertion",
            )],
        )

    monkeypatch.setattr(journal_finalizer, "_phase_n_declare_discussion_thesis", late_thesis)
    paper = (
        "## Abstract\n\n"
        f"{duplicate}\n\n"
        "## Results\n\n"
        "The structured evidence table separates direct, adjacent, and contextual "
        "evidence before narrative interpretation.\n"
    )

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert _duplicate_paragraph_issue_messages(fixed) == ()
    assert fixed.count(duplicate) == 1
    assert any(log.phase == "M_duplicate_paragraph_strip" for log in logs)


def test_run_text_phases_terminal_floor_after_duplicate_intro_cleanup(tmp_path: Path) -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    duplicate = (
        "The thesis is: Across curated reference papers, the evidence base shows a "
        "context-dependent profile with supportive, null, and adverse signals across "
        "different outcome classes. The synthesis surfaces cross-study disagreements "
        "and treats the thesis as an organizing claim rather than a substitute for "
        "the structured study table."
    )
    paper = (
        "# Research Synthesis\n\n"
        "## Abstract\n\n" + ("abstract " * 155) + f"\n\n{duplicate}\n\n"
        "## Introduction\n\n" + ("intro " * 360) + f"\n\n{duplicate}\n\n"
        "## Background\n\n" + ("background " * 310) + "\n\n"
        "## Methods\n\n" + ("methods " * 310) + "\n\n"
        "## Results\n\n" + ("results " * 510) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + ("synthesis " * 810) + f"\n\n{duplicate}\n\n"
        "## Discussion\n\n**Thesis:** bounded.\n\n**Resolution criteria:** direct endpoints.\n\n"
        + ("discussion " * 810) + "\n\n"
        "## Limitations\n\n" + ("limits " * 260) + "\n\n"
        "## Conclusion\n\n" + ("conclusion " * 260) + "\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "ramadan_fasting_effects",
        "total_words": 5000,
        "section_words": {"introduction": 360},
        "receipts": [{"receipt_id": "r1", "outcome_class": "cardiometabolic"}],
        "n_receipts": 1,
        "n_high_confidence_claims_total": 12,
    }), encoding="utf-8")
    (tmp_path / "full_paper.journal_surface.json").write_text("{}", encoding="utf-8")

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)
    report = evaluate_journal_surface(fixed)
    intro = fixed.split("## Introduction", 1)[1].split("## Background", 1)[0]
    cross = fixed.split("## Cross-Domain Synthesis", 1)[1].split("## Discussion", 1)[0]

    assert len(intro.split()) >= 400
    assert len(cross.split()) >= 850
    assert "ramadan_fasting_effects" not in fixed
    assert not any(issue.code == "duplicate_paragraph" for issue in report.issues)
    assert not any(
        issue.code == "structure_surface" and "Introduction" in issue.detail
        for issue in report.issues
    )
    assert any(log.phase == "N_surface_floor_backstop" for log in logs)


def test_surface_artifact_cleanup_removes_pre_reference_bibliography_dump() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\nThe corpus is summarized for public interpretation.\n\n"
        "- **Smith 2024.** _Trial._ DOI: 10.1000/example. PMID: 123456.\n"
        "### Background References\n\n"
        "- **Jones 2023.** _Methods._ DOI: 10.2000/example. PMID: 78910.\n\n"
        "## References\n\n"
        "- **Smith 2024.** _Trial._ DOI: 10.1000/example. PMID: 123456.\n"
    )

    assert any(issue.code == "citation_artifact" for issue in evaluate_journal_surface(paper).issues)
    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    body = fixed.split("## References", 1)[0]
    refs = fixed.split("## References", 1)[1]
    assert "Background References" not in body
    assert "DOI:" not in body and "PMID:" not in body
    assert "DOI: 10.1000/example" in refs
    assert logs[0].detail == "reference_dump=2"


def test_surface_artifact_cleanup_repairs_grammar_and_empty_subheading() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface

    paper = (
        "## Results\n\n"
        "### Results Summary\n\n"
        "### Metabolic Outcomes\n\n"
        "The causal bridge to be rigorously is bounded by directness and follow-up limits.\n\n"
        "A signal in one domain does not automatically is consistent with the same signal in another.\n\n"
        "The comparison remained bounded [sources: Kumari 2026, Malin 2026a].\n\n"
        "## References\n\n- Kumari 2026.\n- Malin 2026a.\n"
    )

    assert any(i.code == "grammar_artifact" for i in evaluate_journal_surface(paper).issues)
    assert any(i.code == "citation_artifact" for i in evaluate_journal_surface(paper).issues)
    assert any("empty heading: Results Summary" in i.detail for i in evaluate_journal_surface(paper).issues)

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    assert "### Results Summary" not in fixed
    assert "to be rigorously is" not in fixed
    assert "is rigorously bounded" in fixed
    assert "does not automatically is" not in fixed
    assert "is not automatically consistent" in fixed
    assert "(Kumari 2026, Malin 2026a)" in fixed
    assert not any(i.code == "grammar_artifact" for i in evaluate_journal_surface(fixed).issues)
    assert not any(i.code == "citation_artifact" for i in evaluate_journal_surface(fixed).issues)
    assert not any("empty heading: Results Summary" in i.detail for i in evaluate_journal_surface(fixed).issues)
    assert logs == [
        journal_finalizer.FinalizerLogEntry(
            phase="M_surface_artifact_cleanup",
            rule="repair_known_surface_artifacts",
            n_changes=4,
            detail="grammar_artifact=3; empty_subheading=1",
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
            detail="added lane qualifier to 1 paragraph(s)",
        )
    ]


def test_lane_qualifier_recognizes_natural_preclinical_leads(tmp_path: Path) -> None:
    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Curran 2025"}],
        "lanes": {"Curran 2025": "animal_preclinical"},
    }))
    for lead in ("In preclinical studies", "In mouse models"):
        paper = f"## Results\n\n{lead}, Curran 2025 reported a bounded result.\n"
        fixed, logs = journal_finalizer._phase_b_lane_qualifier(paper, tmp_path)
        assert fixed == paper
        assert logs == []


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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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

    assert "Numeric verification note: Waghmare 2024 reported a non-significant mapped comparison (p = 0.08)" in fixed
    assert "Numeric correction:" not in fixed.split("## Abstract", 1)[1].split("## Evidence Landscape", 1)[0]
    assert "not every within-source contrast" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].n_changes == 1


def test_numeric_significance_correction_does_not_invent_non_significance(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Verify the Smith 2025 statistic: the mapped comparison reports p = 0.009 "
        "and should be described accurately."
    )
    paper = (
        "## Abstract\n\nThe evidence remains bounded.\n\n"
        "## Evidence Landscape\n\nSmith 2025 contributed the mapped result.\n\n"
        "## Conclusion\n\nThe interpretation remains bounded.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "p = 0.009" in fixed
    assert "nominally statistically significant" in fixed
    assert "non-significant mapped comparison" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs


def test_exact_stat_trace_request_does_not_trigger_legacy_numeric_note(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "For every exact p-value, effect size, or percentage cited (Shoji 2025 P=0.01), "
        "either verify against the bundle or re-label it as an extraction-artifact value."
    )
    rows = [{
        "receipt_id": "r1", "citation_token": "Shoji 2025",
        "source_title": "Shoji report", "thesis_text": "No numeric result in excerpt",
    }]
    paper = (
        "## Evidence Landscape\n\n"
        "Numeric verification note: Shoji 2025 reported a mapped comparison "
        "(p = 0.01) that was nominally statistically significant.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": ask}),
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))

    after_trace, _ = journal_finalizer._phase_d_revision_surface_notes(
        paper, tmp_path,
    )
    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(after_trace, tmp_path)
    second_trace, _ = journal_finalizer._phase_d_revision_surface_notes(fixed, tmp_path)
    stable, _ = journal_finalizer._phase_d_numeric_significance_correction(second_trace, tmp_path)

    assert stable == fixed
    assert "p = 0.01" not in stable
    assert "nominally statistically significant" not in stable
    assert revision_coverage.deterministic_unmet_asks(
        stable, [ask], evidence_rows=rows,
    ) == []


def test_exact_stat_trace_removes_bold_legacy_numeric_note(tmp_path: Path) -> None:
    ask = (
        "For every exact p-value cited (Shoji 2025 P=0.01), verify against the "
        "source bundle or re-label it as an extraction-artifact value."
    )
    rows = [{
        "receipt_id": "r1", "citation_token": "Shoji 2025",
        "source_title": "Shoji report", "thesis_text": "No numeric result in excerpt",
    }]
    paper = (
        "## Evidence Landscape\n\n**Numeric verification note:** Shoji 2025 reported "
        "a mapped comparison (p = 0.01) that was nominally statistically significant.\n"
    )

    fixed, _ = revision_quality.repair_revision_quality(
        paper, rows, ask,
    )

    assert "p = 0.01" not in fixed
    assert "nominally statistically significant" not in fixed


def test_mixed_exact_trace_and_significance_request_repairs_both_clauses(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "For every exact p-value, verify it against the source bundle; the source excerpt "
        "reports Shoji 2025 p = 0.08, not a significant reduction, so correct that factual error."
    )
    rows = [{
        "receipt_id": "r1", "citation_token": "Shoji 2025",
        "source_title": "Shoji report", "thesis_text": "The source excerpt reports p = 0.08.",
    }]
    paper = (
        "## Abstract\n\nShoji 2025 showed a significant reduction.\n\n"
        "## Evidence Landscape\n\nShoji 2025 is retained.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))

    after_numeric, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)
    fixed, _ = journal_finalizer._phase_d_revision_surface_notes(after_numeric, tmp_path)
    second_numeric, _ = journal_finalizer._phase_d_numeric_significance_correction(fixed, tmp_path)
    stable, _ = journal_finalizer._phase_d_revision_surface_notes(second_numeric, tmp_path)

    assert stable == fixed
    assert "Shoji 2025 showed a non-significant reduction" in stable
    assert "Shoji 2025 [bundle:1]" in stable and "p = 0.08" in stable
    assert revision_coverage.deterministic_unmet_asks(
        stable, [ask], evidence_rows=rows,
    ) == []


def test_mixed_ci_trace_and_significance_request_repairs_positive_claim(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Verify every exact interval against the source bundle; Shoji 2025 reports "
        "95% CI 0.80 to 1.20, so correct the significant reduction claim."
    )
    rows = [{
        "receipt_id": "r1", "citation_token": "Shoji 2025",
        "source_title": "Shoji report", "thesis_text": "95% CI 0.80 to 1.20.",
    }]
    paper = (
        "## Results\n\nShoji 2025 showed a significant reduction.\n\n"
        "## Evidence Landscape\n\nShoji 2025 is retained.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))

    after_numeric, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)
    fixed, _ = journal_finalizer._phase_d_revision_surface_notes(after_numeric, tmp_path)

    assert "Shoji 2025 showed a non-significant reduction" in fixed
    assert revision_coverage.deterministic_unmet_asks(
        fixed, [ask], evidence_rows=rows,
    ) == []


def test_named_significance_repair_changes_only_requested_outcome(tmp_path: Path) -> None:
    ask = "Shoji 2025 reports p = 0.08; correct the significant reduction claim."
    paper = (
        "## Results\n\nShoji 2025 showed a significant reduction in endpoint A and "
        "a significant increase in endpoint B.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "non-significant reduction in endpoint A" in fixed
    assert "significant increase in endpoint B" in fixed


def test_named_significance_repair_scopes_same_type_outcomes(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Shoji 2025 reports p = 0.08 for endpoint A; correct the significant "
        "reduction in endpoint A."
    )
    paper = (
        "## Results\n\nShoji 2025 showed a significant reduction in endpoint A and "
        "a significant reduction in endpoint B.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "non-significant reduction in endpoint A" in fixed
    assert "significant reduction in endpoint B" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_named_significance_target_handles_claim_word_order_and_trailing_scope(
    tmp_path: Path,
) -> None:
    import revision_coverage

    asks = (
        "Shoji 2025 reports p = 0.08 for endpoint A; correct the significant "
        "reduction claim in endpoint A.",
        "Shoji 2025 reports p = 0.08; correct the significant reduction in endpoint A "
        "while preserving endpoint B.",
    )
    paper = (
        "## Results\n\nShoji 2025 showed a significant reduction in endpoint A and "
        "a significant reduction in endpoint B.\n"
    )
    for ask in asks:
        (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

        fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

        assert revision_coverage.named_significance_targets(ask) == (
            "reduction in endpoint a",
        )
        assert "non-significant reduction in endpoint A" in fixed
        assert "significant reduction in endpoint B" in fixed
        assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []

    increase_ask = (
        "Shoji 2025 reports p = 0.08 for endpoint A; correct the significant "
        "increase in endpoint A."
    )
    increase_paper = paper.replace("reduction", "increase")
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": increase_ask}),
    )

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(
        increase_paper, tmp_path,
    )

    assert "non-significant increase in endpoint A" in fixed
    assert "significant increase in endpoint B" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [increase_ask]) == []

    preserve_ask = (
        "Shoji 2025 reports p = 0.08; correct the significant increase in endpoint A "
        "and preserve the significant increase in endpoint B."
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": preserve_ask}),
    )

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(
        increase_paper, tmp_path,
    )

    assert revision_coverage.named_significance_targets(preserve_ask) == (
        "increase in endpoint a",
    )
    assert "non-significant increase in endpoint A" in fixed
    assert "significant increase in endpoint B" in fixed


def test_named_significance_repair_ignores_unrelated_negative_clause(tmp_path: Path) -> None:
    ask = (
        "Shoji 2025 reports 95% CI 0.80 to 1.20; correct the significant reduction claim."
    )
    paper = (
        "## Results\n\nShoji 2025 showed a significant reduction, with no significant heterogeneity.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "non-significant reduction" in fixed
    assert "no significant heterogeneity" in fixed


def test_named_numeric_correction_uses_source_nearest_statistic(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Jones 2024 provides contextual evidence. Correct Smith 2025 because "
        "p = 0.08 is non-significant."
    )
    paper = "## Results\n\nJones 2024 reported a non-significant result (p = 0.08).\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    target = revision_coverage.numeric_correction_target(ask)
    assert target is not None and target[0] == "Smith 2025"
    assert "Numeric verification note: Smith 2025" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_disputed_representative_statistic_skips_significance_note(tmp_path: Path) -> None:
    ask = (
        "Verify or correct the representative statistic 'P = 0.001' for Han 2020 "
        "[bundle:1]; the bundled excerpt shows P=0.002 and P=0.049."
    )
    paper = "## Evidence Landscape\n\nHan 2020 reported liver outcomes.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert fixed == paper
    assert logs == []
    assert "P = 0.001" not in fixed


def test_named_significance_repair_preserves_no_significant_reduction(tmp_path: Path) -> None:
    ask = (
        "Shoji 2025 reports p = 0.08, so correct any significant reduction claim."
    )
    paper = "## Results\n\nShoji 2025 showed no significant reduction.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _ = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "no significant reduction" in fixed
    assert "no non-significant reduction" not in fixed


def test_numeric_significance_correction_preserves_stated_adjusted_threshold(tmp_path: Path) -> None:
    ask = (
        "Verify Smith 2025: p = 0.009 did not cross the stated Bonferroni-adjusted "
        "significance threshold."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Smith 2025 reported a non-significant comparison (p = 0.009).\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "nominally statistically significant comparison" in fixed
    assert "did not cross the stated adjusted significance threshold" in fixed


def test_numeric_significance_repair_preserves_references_and_grammar(tmp_path: Path) -> None:
    paper = (
        "## Results\n\nThe comparison did not reach significance (p = 0.01).\n\n"
        "## References\n\n- A title saying non-significant result (p = 0.01).\n"
    )

    fixed, _logs = journal_finalizer._phase_d_numeric_significance_correction(paper, tmp_path)

    assert "was nominally statistically significant (p = 0.01)" in fixed
    assert "title saying non-significant result (p = 0.01)" in fixed


def test_numeric_significance_correction_repairs_verify_statistic_ask(tmp_path: Path) -> None:
    import revision_coverage

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

    assert "Numeric verification note: Brouwers 2016 reported a non-significant mapped comparison (p = 0.88)" in fixed
    assert "Numeric correction:" not in fixed.split("## Abstract", 1)[1].split("## Evidence Landscape", 1)[0]
    assert "not every within-source contrast" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "repair_non_significant_numeric_effect_claims"


def test_numeric_significance_correction_removes_positive_label_for_non_significant_source(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    assert "| Contextual Adjacent Evidence | Holmes 2026: Menopause pilot trial |" in fixed
    assert "outcome=Contextual Adjacent Evidence; direction=unclear" in fixed
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
    import revision_coverage

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
        "thesis_text": "The primary result was p = 0.04.",
        "n_claims": 7,
    }]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "### Findings Map" in fixed
    assert "Cardiometabolic n=1 (direction: null=1; directness: indirect=1; sources: Smith 2024)" in fixed
    assert "| Cardiometabolic | Smith 2024: Clinical source one | direction=null | directness=indirect | B2 |" in fixed
    assert "finding=representative statistic p = 0.04" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_source_outcome_class_map_includes_all_rows_for_each_retained_source_ask(tmp_path: Path) -> None:
    ask = (
        "For each outcome class, extract at least 2-3 specific findings from "
        "individual cited sources (study design, population, effect direction, "
        "effect size where available) and present them in prose, not just in the "
        "coding tally."
    )
    rows: list[dict[str, Any]] = [
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
    import revision_coverage

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


def test_findings_map_separates_mechanistic_and_biomarker_roles(tmp_path: Path) -> None:
    ask = (
        "Recode outcome classes so mechanistic/animal evidence is not silently treated as "
        "clinical outcome classes, e.g. Ng 2019 should be Mechanism/Longevity (C. elegans), "
        "Reid 2023 biomarker/adjacent not clinical cognitive outcome. Surface direction "
        "heterogeneity in Findings Map itself, not only direction profile row."
    )
    paper = "## Evidence Landscape\n\nThe source map needs repair.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {
            "citation_token": "Ng 2019",
            "source_title": "C. elegans mitochondrial free radical theory of aging lifespan model",
            "outcome_class": "longevity",
            "effect_direction": "unclear",
            "directness": "mechanistic",
            "evidence_tier": "C1",
        },
        {
            "citation_token": "Liang 2021",
            "source_title": "Cell model of mitochondrial DNA damage and aging mechanism",
            "outcome_class": "longevity",
            "effect_direction": "null",
            "directness": "mechanistic",
            "evidence_tier": "C1",
        },
        {
            "citation_token": "Reid 2023",
            "source_title": "Blood-based mtDNA deletion biomarker study in cognitive aging",
            "outcome_class": "cognitive",
            "effect_direction": "unclear",
            "directness": "indirect",
            "evidence_tier": "B2",
        },
    ]}))

    fixed, logs = journal_finalizer._phase_d_source_outcome_class_map(paper, tmp_path)

    assert "Ng 2019: C. elegans mitochondrial free radical theory" in fixed
    assert "outcome=Mechanism/Animal/Preclinical Context (Longevity) (C. elegans); direction=unclear" in fixed
    assert "directness=animal/preclinical context" in fixed
    assert "Reid 2023: Blood-based mtDNA deletion biomarker study" in fixed
    assert "outcome=Biomarker/Adjacent Cognitive; direction=unclear" in fixed
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_source_outcome_class_map"


def test_revise_feedback_surfaces_direction_cues_funnel_and_tensions(tmp_path: Path) -> None:
    feedback = (
        "Reconcile source-admission funnel with explicit auditable arithmetic or "
        "tabulate non-additive diagnostic states/glossary.; Map every admitted "
        "bundle source to Findings Map appearance.; Recode effect_direction values "
        "against the actual reported finding in source title/excerpt; correct unclear "
        "where titles state reversal, no relationship, or increased damage.; Add "
        "explicit Tensions and Gaps subsection enumerating at least three specific "
        "cross-source disagreements with named sources.; Reconcile source bundle to "
        "15 admitted sources; add missing source-level finding for Chakraborty 2026 "
        "and/or Chan 2012 in Findings Map or explicitly exclude.; Recode effect "
        "directions: Hsiao 2026 reports significantly higher mtDNA damage, Ng 2019 "
        "null lifespan should be tension with mechanistic plausibility, and Pena "
        "2024 p=0.92 should be a non-significant contrast, not positive direction "
        "evidence.; Redo Tensions and Gaps: enumerate contradictions and do not say "
        "0 disagreements.; Reclassify human cohort/biopsy sources as adjacent human "
        "evidence and update 0/15 direct framing.; Provide auditable admission "
        "funnel with non-overlapping buckets or step-by-step candidate union to "
        "admitted sources."
    )
    rows = [
        {
            "citation_token": "Pena 2024",
            "source_title": "G2019S inhibitor abrogates mitochondrial DNA damage",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear",
            "directness": "indirect",
            "p_values": ["p = 0.92"],
            "thesis_text": "The source reported p = 0.92.",
            "n_claims": 2,
        },
        {
            "citation_token": "Ng 2019",
            "source_title": "Mitochondrial DNA Damage Does Not Determine C. elegans Lifespan",
            "outcome_class": "longevity",
            "effect_direction": "unclear",
            "directness": "mechanistic",
            "n_claims": 1,
        },
        {
            "citation_token": "Shimizu 2026",
            "source_title": "A PUFA-rich diet increases age-related mitochondrial DNA damage",
            "outcome_class": "cardiometabolic",
            "effect_direction": "unclear",
            "directness": "mechanistic",
            "n_claims": 1,
        },
        {
            "citation_token": "Hsiao 2026",
            "source_title": "Airway microbial dysbiosis and oxidative mitochondrial DNA damage in bronchopulmonary dysplasia",
            "outcome_class": "respiratory",
            "effect_direction": "null",
            "directness": "adjacent",
            "p_values": ["p < 0.05"],
            "thesis_text": "The source reported significantly higher mitochondrial DNA damage (p < 0.05).",
            "n_claims": 1,
        },
        {
            "citation_token": "Chan 2012",
            "source_title": "Mitochondrial DNA damage biomarker profile in human patient cohort",
            "outcome_class": "biomarker",
            "effect_direction": "unclear",
            "directness": "indirect",
            "n_claims": 1,
        },
        {
            "citation_token": "Chakraborty 2026",
            "source_title": "F2,6BP restores mitochondrial genome integrity",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear",
            "directness": "indirect",
            "n_claims": 1,
        },
        {
            "citation_token": "Reid 2023",
            "source_title": "Blood-based mtDNA deletion biomarker study in cognitive aging",
            "outcome_class": "cognitive",
            "effect_direction": "unclear",
            "directness": "indirect",
            "n_claims": 1,
        },
        {
            "citation_token": "Roca-Bayerri 2020",
            "source_title": "Human skeletal muscle biopsy mitochondrial DNA damage cohort",
            "outcome_class": "biomarker",
            "effect_direction": "unclear",
            "directness": "indirect",
            "n_claims": 1,
        },
        {
            "citation_token": "Picca 2019",
            "source_title": "Plasma mitochondrial DNA biomarker in older adult cohort",
            "outcome_class": "biomarker",
            "effect_direction": "unclear",
            "directness": "indirect",
            "n_claims": 1,
        },
    ]
    paper = (
        "## Methods\n\n### Source admission funnel\n\n"
        "| Row | Count |\n| --- | --- |\n| Classified source candidates | 18 |\n"
        "| Admitted final sources | 15 |\n\n"
        "## Evidence Landscape\n\n### Findings Map\n\nExisting map.\n\n"
        "## Cross-Domain Synthesis\n\n### Load-Bearing Tensions\n\n"
        "- No load-bearing cross-study disagreements were detected.\n\n"
        "## References\n\nR01.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "receipt_funnel": {
            "classified_receipt_candidates": 18,
            "counts": {
                "admitted_receipts": 15,
                "original_strict_high_confidence_receipts": 2,
            },
        },
        "n_receipts": 15,
        "receipts": rows,
    }), encoding="utf-8")

    asks = journal_finalizer.revision_coverage.revision_asks(feedback)
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(paper, asks) == asks
    fixed, _logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Auditable arithmetic is therefore candidate union -> classified source candidates -> admitted final sources" in fixed
    assert "diagnostic bucket rows do not sum to the classified count" in fixed
    assert "Stepwise reconciliation: classified source candidates (18) -> admitted final sources (15)" in fixed
    assert "Findings Map completeness note: all 9 admitted manifest rows are surfaced below" in fixed
    assert "Pena 2024: G2019S inhibitor abrogates mitochondrial DNA damage" in fixed
    assert "Pena 2024" in fixed and "direction=unclear" in fixed
    assert "representative non-significant statistic p = 0.92" in fixed
    assert "Hsiao 2026" in fixed and "direction=negative" in fixed
    assert "Ng 2019" in fixed and "direction=null" in fixed
    assert "Shimizu 2026" in fixed and "direction=negative" in fixed
    assert "Chakraborty 2026" in fixed and "direction=positive" in fixed
    assert "Chan 2012" in fixed
    assert "Adjacent human evidence rows=" in fixed
    assert "Roca-Bayerri 2020" in fixed and "Picca 2019" in fixed
    assert "Source directness breakdown: 0/9 retained sources directly address" in fixed
    assert "No load-bearing cross-study disagreements were detected" not in fixed
    assert "No semantically comparable source-pair disagreements" in fixed
    assert "Pena 2024 vs Chakraborty 2026" not in fixed
    assert "surfaced tension/disagreement" not in fixed
    unmet = journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, asks)
    assert any("at least three" in ask.lower() for ask in unmet)


def test_revise_feedback_reconciles_inline_citations_and_named_source_direction(tmp_path: Path) -> None:
    feedback = (
        "Reconcile the source bundle against all inline citations: either add bundle entries "
        "for the missing author-year references or remove uncited citations. Maintain a 1:1 "
        "audit trail between prose and manifest.json as the Search Summary promises.; "
        "Reclassify Parkitny 2017 in the Findings Map to reflect the positive direction "
        "reported in the bundle (15% pain reduction, cytokine reductions) rather than 'null' "
        "or 'no extracted directional signal' in Dosing/Pharmacokinetics; flag it as "
        "mechanistic/pilot rather than dosing evidence if appropriate."
    )
    paper = (
        "## Methods\n\nSource retrieval used a manifest.\n\n"
        "## Evidence Landscape\n\n### Findings Map\n\n"
        "- Parkitny 2017: outcome=Dosing/Pharmacokinetics; direction=null; "
        "directness=indirect; tier=B2.\n\n"
        "## References\n\n- Parkitny 2017.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{
        "citation_token": "Parkitny 2017",
        "source_title": (
            "Reduced Pro-Inflammatory Cytokines after Eight Weeks of "
            "Low-Dose Naltrexone for Fibromyalgia"
        ),
        "outcome_class": "dosing_pharmacokinetics",
        "effect_direction": "null",
        "directness": "indirect",
        "evidence_tier": "B2",
        "n_claims": 5,
    }]}))

    asks = journal_finalizer.revision_coverage.revision_asks(feedback)
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(paper, asks) == asks

    fixed, _logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Citation traceability map:" in fixed
    assert "source-bundle entries" in fixed
    assert "Effect-direction reconciliation note:" in fixed
    assert "Parkitny 2017: direction=positive" in fixed
    assert "outcome=mechanistic/pilot evidence" in fixed
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, asks) == []


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


def test_tension_count_revision_renders_dyad_rule_and_outcome_tally(
    tmp_path: Path,
) -> None:
    (tmp_path / "audit").mkdir()
    (tmp_path / "manifest.json").write_text('{"receipts": []}')
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": (
            "Define and audit the pairwise disagreement tension count; "
            "state the dyad rule and per-outcome tally."
        ),
    }))
    (tmp_path / "audit" / "tension_elaboration_plans.json").write_text(
        json.dumps({"calculation": {
            "rule": "Each unordered receipt pair is counted once.",
            "all_dyads": 6,
            "non_orthogonal_dyads": 2,
            "by_outcome": {"immune_inflammation": 2},
        }}),
    )
    paper = (
        "## Tensions and Gaps\n\nThe prior count was not auditable.\n\n"
        "## Evidence Snapshot\n\nBounded."
    )

    fixed, _ = journal_finalizer._phase_d_tensions_and_gaps_breadth(
        paper, tmp_path,
    )

    assert "Each unordered receipt pair is counted once." in fixed
    assert "6 unordered dyads; 2 are non-orthogonal" in fixed
    assert "Immune and Inflammation=2" in fixed


def test_tensions_and_gaps_breadth_repairs_cross_source_disagreement_ask(tmp_path: Path) -> None:
    ask = (
        "Expand the Tensions and Gaps section to enumerate at least three specific "
        "cross-source disagreements with named sources on each side."
    )
    rows = [
        {"citation_token": "Grazuleviciene 2026", "source_title": "Intervention effects on glucose uptake", "endpoints": ["glucose uptake"], "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "direct"},
        {"citation_token": "Durstenfeld 2026", "source_title": "Review of glucose uptake endpoints", "endpoints": ["glucose uptake"], "outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "review"},
        {"citation_token": "Salerno 2026", "source_title": "Intervention effects on sleep duration", "endpoints": ["sleep duration"], "outcome_class": "contextual_other", "effect_direction": "negative", "directness": "indirect"},
        {"citation_token": "Riquelme-Hernandez 2026", "source_title": "Review of sleep duration endpoints", "endpoints": ["sleep duration"], "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review"},
        {"citation_token": "Liu 2025", "source_title": "Intervention effects on frailty index score", "endpoints": ["frailty index score"], "outcome_class": "frailty", "effect_direction": "positive", "directness": "indirect"},
        {"citation_token": "Garcia 2026", "source_title": "Trial reporting frailty index score", "endpoints": ["frailty index score"], "outcome_class": "frailty", "effect_direction": "null", "directness": "direct"},
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


def test_contextual_tensions_require_semantic_title_overlap() -> None:
    unrelated = [
        {"citation_token": "Canine 2024", "source_title": "Urolithin A and canine sperm motility", "outcome_class": "contextual_other", "effect_direction": "positive"},
        {"citation_token": "Assay 2025", "source_title": "Urolithin A chromatographic assay validation", "outcome_class": "contextual_other", "effect_direction": "null"},
    ]
    assert journal_finalizer._manifest_tension_examples(
        unrelated,
    ) == []

    comparable = [
        {"citation_token": "Cells 2024", "source_title": "Urolithin A increases glucose uptake in skeletal muscle", "endpoints": ["glucose uptake"], "outcome_class": "contextual_other", "effect_direction": "positive"},
        {"citation_token": "Null 2025", "source_title": "Urolithin A leaves glucose uptake unchanged in muscle", "endpoints": ["glucose uptake"], "outcome_class": "contextual_other", "effect_direction": "null"},
    ]
    lines = journal_finalizer._manifest_tension_examples(
        comparable,
    )
    assert len(lines) == 1
    assert "Cells 2024 vs Null 2025" in lines[0]

    broad_class_only = [
        {"citation_token": "Lipids 2024", "source_title": "LDL cholesterol reduction in older adults", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"citation_token": "Pressure 2025", "source_title": "Blood pressure unchanged in older adults", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]
    assert journal_finalizer._manifest_tension_examples(broad_class_only) == []
    assert journal_finalizer._manifest_tension_examples([
        {"citation_token": "Lipids 2024", "source_title": "Placebo-controlled LDL outcome", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"citation_token": "Pressure 2025", "source_title": "Placebo-controlled blood pressure outcome", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]) == []
    multi_endpoint_rollups = [
        {
            "citation_token": "Mixed A 2024",
            "outcome_class": "cardiometabolic",
            "effect_direction": "positive",
            "endpoints": ["ldl cholesterol", "blood pressure"],
            "endpoint_directions": {
                "ldl cholesterol": "null", "blood pressure": "positive",
            },
        },
        {
            "citation_token": "Mixed B 2025",
            "outcome_class": "cardiometabolic",
            "effect_direction": "negative",
            "endpoints": ["ldl cholesterol", "heart rate"],
            "endpoint_directions": {
                "ldl cholesterol": "null", "heart rate": "negative",
            },
        },
    ]
    assert journal_finalizer._manifest_tension_examples(multi_endpoint_rollups) == []
    conflicting_endpoint_rollups = [
        multi_endpoint_rollups[0],
        {
            "citation_token": "Mixed B 2025",
            "outcome_class": "cardiometabolic",
            "effect_direction": "negative",
            "endpoints": ["ldl cholesterol", "heart rate"],
            "endpoint_directions": {
                "ldl cholesterol": "positive", "heart rate": "negative",
            },
        },
    ]
    lines = journal_finalizer._manifest_tension_examples(conflicting_endpoint_rollups)
    assert len(lines) == 1
    assert "on ldl cholesterol" in lines[0]
    assert journal_finalizer._manifest_tension_examples([
        {"citation_token": "Untitled 2024", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"citation_token": "Untitled 2025", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]) == []
    assert journal_finalizer._manifest_tension_examples([
        {"citation_token": "Duplicate 2024", "source_title": "Glucose uptake trial", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"citation_token": "Duplicate 2024", "source_title": "Glucose uptake trial", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]) == []
    assert journal_finalizer._manifest_tension_examples([
        {"citation_token": "Lipids 2024", "source_title": "Prospective multicenter intervention for LDL cholesterol", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"citation_token": "Pressure 2025", "source_title": "Prospective multicenter intervention for blood pressure", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]) == []
    for design in (
        "Multisite", "Interventional", "Randomised", "Parallel group", "Pragmatic",
        "Crossover", "Nationwide", "Registry based", "Single center",
        "Open label phase", "Adaptive cluster",
        "Matched blinded", "Pilot feasibility",
        "Double masked allocation", "Intention to treat", "Propensity score",
        "Repeated measures",
    ):
        assert journal_finalizer._manifest_tension_examples([
            {"citation_token": "Lipids 2024", "source_title": f"{design} LDL cholesterol outcome", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
            {"citation_token": "Pressure 2025", "source_title": f"{design} blood pressure outcome", "outcome_class": "cardiometabolic", "effect_direction": "null"},
        ]) == []


def test_tension_repair_does_not_promote_reviewer_named_sources(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "test_topic", "receipts": []}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": (
            "Replace the surfaced tension with a specific cross-source disagreement: "
            "Fake 2024 vs Imaginary 2025."
        ),
    }))
    paper = (
        "# Paper\n\n## Tensions and Gaps\n\n"
        "- Fake 2024 vs Imaginary 2025: surfaced tension/disagreement in function.\n\n"
        "## Discussion\n\nBounded interpretation.\n"
    )

    fixed, logs = journal_finalizer._phase_d_tensions_and_gaps_breadth(paper, tmp_path)
    assert "Fake 2024" not in fixed and "Imaginary 2025" not in fixed
    assert "No semantically comparable source-pair disagreements" in fixed
    assert logs and logs[0].rule == "state_revision_tension_breadth"


def test_tensions_and_gaps_replaces_stale_cross_outcome_surface_tensions(tmp_path: Path) -> None:
    import revision_coverage

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
        "## References\n\n"
        "Katayoshi 2023. Martens 2018. Yi 2022. Simic 2020. Gao 2025. Simon 2024.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"n_non_orthogonal_tensions": 146, "receipts": [
        {"citation_token": "Curran 2025", "source_title": "Canine sperm motility", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "positive", "directness": "review"},
        {"citation_token": "Zhao 2024", "source_title": "Human sleep duration", "outcome_class": "contextual_adjacent_evidence", "effect_direction": "negative", "directness": "review"},
        {"citation_token": "Katayoshi 2023", "source_title": "Trial of arterial stiffness", "endpoints": ["arterial stiffness"], "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect"},
        {"citation_token": "Martens 2018", "source_title": "Study of arterial stiffness", "endpoints": ["arterial stiffness"], "outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "indirect"},
        {"citation_token": "Yi 2022", "source_title": "Dose exposure response trial", "endpoints": ["dose exposure response"], "outcome_class": "dosing_pharmacokinetics", "effect_direction": "positive", "directness": "direct"},
        {"citation_token": "Simic 2020", "source_title": "Review of dose exposure response", "endpoints": ["dose exposure response"], "outcome_class": "dosing_pharmacokinetics", "effect_direction": "null", "directness": "review"},
        {"citation_token": "Gao 2025", "source_title": "Trial of glucose uptake", "endpoints": ["glucose uptake"], "outcome_class": "contextual_adjacent_evidence", "effect_direction": "null", "directness": "direct"},
        {"citation_token": "Simon 2024", "source_title": "Study of glucose uptake", "endpoints": ["glucose uptake"], "outcome_class": "contextual_adjacent_evidence", "effect_direction": "positive", "directness": "direct"},
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
    import revision_coverage

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


def test_substantive_evidence_synthesis_is_idempotent_after_surface_rewrite(tmp_path: Path) -> None:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements

    ask = (
        "Provide an actual evidence synthesis in the Evidence Landscape and Key Findings sections. "
        "Surface positive and mixed findings from the evidence."
    )
    paper = "## Results\n\nInitial result.\n\n## Conclusion\n\nBounded.\n"
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [{
        "citation_token": "Smith 2025",
        "outcome_class": "cardiometabolic",
        "effect_direction": "positive",
        "directness": "direct",
        "evidence_tier": "A1",
        "n_claims": 12,
    }]}))

    fixed, _ = journal_finalizer._phase_d_substantive_evidence_synthesis(paper, tmp_path)
    assert apply_pipeline_jargon_replacements(fixed) == fixed
    rewritten = fixed.replace("not a clinical efficacy claim", "not a standalone clinical efficacy claim")
    again, logs = journal_finalizer._phase_d_substantive_evidence_synthesis(rewritten, tmp_path)

    assert again == rewritten
    assert logs == []
    assert again.count("Key findings from source synthesis:") == 1


def test_substantive_evidence_synthesis_surfaces_all_named_missing_sources(tmp_path: Path) -> None:
    import revision_coverage

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
    assert "Manifest outcome-class count summary" in fixed
    assert "Contextual Adjacent Evidence: admitted n=3" in fixed
    assert "Full source-level signals are" in fixed
    assert {entry.phase for entry in logs} >= {
        "D_research_question_scope",
        "D_substantive_evidence_synthesis",
        "D_evidence_honesty_guard",
    }


def test_latest_telomere_reviewer_asks_are_repaired_generically(tmp_path: Path) -> None:
    import revision_coverage

    feedback = (
        "Add clear specific research question directly answerable by evidence, e.g. "
        "“In cancer populations, does shorter LTL predict survival, and does genetically "
        "predicted longer LTL increase cancer risk across tumor types?”; "
        "Reclassify misclassified sources: Liu 2026 out of dosing/pharmacokinetics "
        "(epigenetic age acceleration), Markozannes 2022 out of immune/inflammation "
        "(cancer MR systematic review), re-examine Brouwers 2016 direction coding.; "
        "Resolve/disclose 17/25 unclear effect_direction codes, re-extract direction "
        "or state cannot determine direction for majority and narrow conclusion.; "
        "Integrate evidence across outcome classes: contrast MR risk findings versus "
        "prognostic biomarker findings versus mechanistic ALT findings.; "
        "Remove/segregate off-topic sources or add adjacent context label/non-pooling rationale.; "
        "Reconcile receipt funnel arithmetic and add one-sentence interpretation why "
        "25 sources from 73 candidates.; Narrow Conclusion: current structural claims go beyond body."
    )
    paper = (
        "## Abstract\n\nThin.\n\n"
        "## Research Question\n\nWhat does this corpus show?\n\n"
        "## Methods\n\nRetrieval was deterministic.\n\n"
        "## Evidence Landscape\n\nThin summary.\n\n"
        "### Source Classification Map\n\n"
        "- Liu 2026: outcome=Dosing and Pharmacokinetics; direction=negative; directness=indirect; tier=B2.\n"
        "- Markozannes 2022: outcome=Immune and Inflammation; direction=null; directness=review; tier=B2.\n\n"
        "## Key Findings\n\nThin summary.\n\n"
        "## Results\n\n"
        "### Dosing and Pharmacokinetics Outcomes\n\n"
        "Dosing and Pharmacokinetics remains a separate Results slice.\n\n"
        "## Conclusion\n\nBroad structural claims.\n"
    )
    rows = [
        {
            "citation_token": "Sasmita 2025",
            "source_title": "Shorter telomere length as a prognostic marker for survival and recurrence in breast cancer",
            "outcome_class": "mortality_survival",
            "effect_direction": "unclear",
            "directness": "review",
            "evidence_tier": "B2",
            "n_claims": 113,
        },
        {
            "citation_token": "Liu 2026",
            "source_title": "The association of epigenetic age acceleration with cancer survival",
            "outcome_class": "dosing_pharmacokinetics",
            "effect_direction": "negative",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 74,
        },
        {
            "citation_token": "Markozannes 2022",
            "source_title": "Systematic review of Mendelian randomization studies on risk of cancer",
            "outcome_class": "immune_inflammation",
            "effect_direction": "null",
            "directness": "review",
            "evidence_tier": "B2",
            "n_claims": 61,
        },
        {
            "citation_token": "Jaeger 2024",
            "source_title": "A Natural Astragalus-Based Nutritional Supplement Lengthens Telomeres in a Middle-Aged Population",
            "outcome_class": "contextual_other",
            "effect_direction": "positive",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 90,
        },
        {
            "citation_token": "Brouwers 2016",
            "source_title": "Frailty-adjacent telomere endpoint study",
            "outcome_class": "frailty",
            "effect_direction": "unclear",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 30,
        },
        {
            "citation_token": "Afolabi 2026",
            "source_title": "Alternative lengthening of telomeres mechanistic insights in cancer",
            "outcome_class": "mechanism",
            "effect_direction": "null",
            "directness": "mechanistic",
            "evidence_tier": "C1",
            "n_claims": 3,
        },
    ]
    rows.extend(
        {
            "citation_token": f"Context {i} 2026",
            "source_title": "Cancer telomere contextual evidence",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear" if i <= 15 else "null",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 1,
        }
        for i in range(1, 20)
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "telomere_cancer_effects",
        "n_receipts": 25,
        "receipt_funnel": {
            "classified_receipt_candidates": 73,
            "counts": {"admitted_receipts": 25},
        },
        "receipts": rows,
    }), encoding="utf-8")
    asks = revision_coverage.revision_asks(feedback)

    assert len(asks) == 7
    assert revision_coverage.deterministic_unmet_asks(paper, asks)
    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Majority-direction note: 17/25" in fixed
    assert "Receipt-funnel interpretation:" not in fixed
    assert "Source-selection interpretation: 25 admitted sources came from 73" in fixed
    assert "outcome-class source-level signals directionally consistent enough" in fixed
    assert "source-title subdomain labels" in fixed
    assert "Liu 2026: outcome=Dosing and Pharmacokinetics" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {
        "D_admission_funnel_clarification",
        "D_directional_coding_note",
        "D_research_question_scope",
        "D_source_directness_breakdown",
    }


def test_substantive_evidence_synthesis_repairs_meta_only_conclusion(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Clarify in the Conclusion what the evidence actually shows about telomere cancer effects, "
        "not just what kind of evidence it is. A conclusion that only describes its own epistemic "
        "status is not informative."
    )
    paper = (
        "## Evidence Landscape\n\nThin summary.\n\n"
        "## Key Findings\n\nThin summary.\n\n"
        "## Conclusion\n\nThe conclusion is bounded and hypothesis-generating.\n"
    )
    rows = [
        {"citation_token": "Sasmita 2025", "source_title": "Shorter telomere length as a prognostic marker for survival and recurrence in breast cancer", "outcome_class": "contextual_other", "effect_direction": "unclear", "directness": "review", "evidence_tier": "B2", "n_claims": 113},
        {"citation_token": "Markozannes 2022", "source_title": "Systematic review of Mendelian randomization studies on risk of cancer", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review", "evidence_tier": "B2", "n_claims": 61},
        {"citation_token": "Jaeger 2024", "source_title": "A nutritional supplement lengthens telomeres in a randomized population", "outcome_class": "contextual_other", "effect_direction": "positive", "directness": "indirect", "evidence_tier": "B2", "n_claims": 90},
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "telomere_cancer_effects", "receipts": rows}))

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    fixed, logs = journal_finalizer._phase_d_substantive_evidence_synthesis(paper, tmp_path)

    assert "Substantive conclusion for Telomere Cancer Effects" in fixed
    assert "Manifest outcome-class count summary" in fixed
    assert "Contextual Adjacent Evidence: admitted n=3" in fixed
    assert "not establish standalone clinical actionability" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].phase == "D_substantive_evidence_synthesis"


def test_latest_telomere_post_submit_reviewer_asks_are_repaired_generically(tmp_path: Path) -> None:
    import revision_coverage

    feedback = (
        "Populate the Key Findings section with a concrete bullet list tied to the explicit "
        "outcome-class slices, naming which sources support each bullet; Restate the research "
        "question to match the two-part claim in the abstract (prognostic value of shorter LTL "
        "for survival; causal-risk direction of genetically predicted longer LTL) and explicitly "
        "answer both halves in the body; Reconcile the corpus-size claims (e.g., 'n=7 causal-risk/MR', "
        "'25 sources', 'n=17 contextual') with the actual supplied bundle and the funnel counts; "
        "correct any overcounts or label them as 'classified' vs 'admitted' consistently; Move "
        "direction-coding 'unclear' status to a more visible position in the narrative so readers "
        "know that the bulk of significant statistics in this corpus are polarity-unsigned at extraction; "
        "Reduce redundant repetition of the evidence-honesty note across Abstract, Research Question, "
        "and Conclusion."
    )
    paper = (
        "## Abstract\n\nEvidence-honesty note: bounded.\n\n"
        "## Research Question\n\nEvidence-honesty note: bounded. What does this corpus show?\n\n"
        "## Evidence Landscape\n\nThin summary.\n\n"
        "## Key Findings\n\nThin summary.\n\n"
        "## Conclusion\n\n"
        "Evidence-honesty note: bounded. Substantive conclusion: the retained source set shows "
        "causal-risk and Mendelian-randomization evidence n=7.\n"
    )
    rows = [
        {
            "citation_token": "Sasmita 2025",
            "source_title": "Shorter telomere length as a prognostic marker for survival and recurrence in breast cancer",
            "outcome_class": "mortality_survival",
            "effect_direction": "unclear",
            "directness": "review",
            "evidence_tier": "B2",
            "n_claims": 113,
        },
        {
            "citation_token": "Markozannes 2022",
            "source_title": "Systematic review of Mendelian randomization studies on risk of cancer",
            "outcome_class": "contextual_other",
            "effect_direction": "null",
            "directness": "review",
            "evidence_tier": "B2",
            "n_claims": 61,
        },
        {
            "citation_token": "Jaeger 2024",
            "source_title": "A nutritional supplement lengthens telomeres in a randomized population",
            "outcome_class": "contextual_other",
            "effect_direction": "positive",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 90,
        },
    ]
    rows.extend(
        {
            "citation_token": f"Context {i} 2026",
            "source_title": "Cancer telomere contextual evidence",
            "outcome_class": "contextual_other",
            "effect_direction": "unclear" if i <= 16 else "null",
            "directness": "indirect",
            "evidence_tier": "B2",
            "n_claims": 1,
        }
        for i in range(1, 23)
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "telomere_cancer_effects",
        "n_receipts": 25,
        "receipt_funnel": {"classified_receipt_candidates": 73, "counts": {"admitted_receipts": 25}},
        "receipts": rows,
    }), encoding="utf-8")
    asks = revision_coverage.revision_asks(feedback)

    assert len(asks) == 5
    assert set(revision_coverage.deterministic_unmet_asks(paper, asks)) == set(asks)
    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Outcome-class key findings:" in fixed
    assert "Two-part research question:" in fixed
    assert "Corpus-count reconciliation:" in fixed
    assert "Direction-coding visibility note: 17/25" in fixed
    assert fixed.count("Evidence scope:") == 1
    assert "causal-risk and Mendelian-randomization evidence n=7" not in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {
        "D_evidence_honesty_deduplicate",
        "D_research_question_scope",
        "D_substantive_evidence_synthesis",
    }


def test_revision_gate_refresh_recomputes_empty_stale_unmet_list(tmp_path: Path) -> None:
    feedback = (
        "Populate the Key Findings section with a concrete bullet list tied to the explicit "
        "outcome-class slices, naming which sources support each bullet; Restate the research "
        "question to match the two-part claim in the abstract (prognostic value of shorter LTL "
        "for survival; causal-risk direction of genetically predicted longer LTL) and explicitly "
        "answer both halves in the body; Reconcile the corpus-size claims with the actual supplied "
        "bundle and the funnel counts; Move direction-coding 'unclear' status to a more visible "
        "position in the narrative; Reduce redundant repetition of the evidence-honesty note."
    )
    paper = (
        "## Abstract\n\nEvidence-honesty note: bounded.\n\n"
        "## Research Question\n\n"
        "Two-part research question: (1) Does the retained evidence address shorter LTL for survival? "
        "(2) Does the retained evidence address genetically predicted longer LTL and cancer risk?\n\n"
        "## Key Findings\n\n"
        "Direction-coding visibility note: 17/25 admitted sources are coded unclear at receipt level.\n\n"
        "Corpus-count reconciliation: count-bearing slices use manifest outcome classes from admitted "
        "sources; classified source candidates and admitted source counts are not interchangeable.\n\n"
        "Outcome-class key findings:\n\n"
        "- Contextual Adjacent Evidence: admitted n=17; direction coding unclear=15/null=2; "
        "directness review=5/indirect=12; supported by Sasmita 2025 and Markozannes 2022.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    (tmp_path / "revision_coverage_gate.json").write_text(json.dumps({
        "passed": True,
        "ask_count": 7,
        "unmet_asks": [],
    }), encoding="utf-8")

    assert journal_finalizer._refresh_revision_coverage_gate(tmp_path) is True
    refreshed = json.loads((tmp_path / "revision_coverage_gate.json").read_text(encoding="utf-8"))
    assert refreshed == {
        "passed": True,
        "ask_count": 5,
        "unmet_asks": [],
        "refreshed_by": "journal_finalizer",
    }


def test_scope_framing_and_direction_tally_audit_repaired_generically(tmp_path: Path) -> None:
    import revision_coverage

    feedback = (
        "Resolve the scope framing. Either retitle and reframe the evidence map as "
        "'Clinical applications of therapeutic plasma exchange across heterogeneous indications' "
        "and drop the anti-aging framing, or restrict the map to aging-relevant evidence; "
        "Make the directional tallies auditable. Provide, in the supplement or inline, the "
        "per-source direction/directness/tier table so the counts in the prose can be verified "
        "against the retained sources."
    )
    paper = (
        "## Abstract\n\nThis anti-aging evidence map is mixed.\n\n"
        "## Research Question\n\nWhat does this corpus show?\n\n"
        "## Evidence Landscape\n\nThin summary.\n\n"
        "## Key Findings\n\n"
        "## Conclusion\n\nThe conclusion is bounded.\n"
    )
    rows = [
        {
            "citation_token": "Boada 2020",
            "source_title": "AMBAR plasma exchange trial",
            "outcome_class": "contextual_other",
            "effect_direction": "mixed",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 10,
        },
        {
            "citation_token": "Ipe 2021",
            "source_title": "Therapeutic plasma exchange response rate",
            "outcome_class": "immune_inflammation",
            "effect_direction": "positive",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 8,
        },
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "therapeutic_plasma_exchange",
        "n_receipts": 2,
        "receipts": rows,
    }), encoding="utf-8")
    asks = revision_coverage.revision_asks(feedback)

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == asks
    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Scope-framing note:" in fixed
    assert "heterogeneous indications" in fixed
    assert "Per-source direction/directness/tier audit table:" in fixed
    assert "direction=mixed" in fixed
    assert "directness=direct" in fixed
    assert "tier=A1" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert {entry.phase for entry in logs} >= {
        "D_scope_framing_note",
        "D_substantive_evidence_synthesis",
    }


def test_search_summary_scope_note_repairs_date_operationalization_ask(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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


def test_outcome_label_cleanup_applies_generic_reviewer_rename(tmp_path: Path) -> None:
    import revision_coverage

    ask = (
        "Rename the 'Longevity' outcome class to reflect the actual endpoint "
        "(e.g. 'Lipoprotein(a) / MACE in CHD') so map labels are not misleading."
    )
    paper = (
        "## Results\n\n### Longevity Outcomes\n\n"
        "| Evidence domain | Sources |\n|---|---|\n| Longevity | 2 |\n\n"
        "- Smith 2024: outcome=Longevity; direction=positive.\n\n"
        "Human longevity remains outside this endpoint.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, logs = journal_finalizer._phase_d_outcome_label_cleanup(paper, tmp_path)

    assert fixed.count("Lipoprotein(a) / MACE in CHD") == 3
    assert "Human longevity remains" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert logs[0].rule == "apply_reviewer_outcome_label_rename"


def test_outcome_label_cleanup_does_not_expand_completed_generic_rename(tmp_path: Path) -> None:
    ask = "Rename the outcome class 'Safety' to 'Safety and Tolerability'."
    paper = (
        "## Results\n\n### Safety Outcomes\n\n"
        "- Smith 2024: outcome=Safety; direction=mixed.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": ask}))

    fixed, _ = journal_finalizer._phase_d_outcome_label_cleanup(paper, tmp_path)
    stable, logs = journal_finalizer._phase_d_outcome_label_cleanup(fixed, tmp_path)

    assert fixed.count("Safety and Tolerability") == 2
    assert stable == fixed
    assert logs == []

    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Rename the outcome class 'Safety and Tolerability' to 'Safety'.",
    }))
    contracted, _ = journal_finalizer._phase_d_outcome_label_cleanup(fixed, tmp_path)
    assert "Safety and Tolerability" not in contracted
    assert contracted.count("Safety") == 2


def test_outcome_router_respects_reviewer_renamed_class(tmp_path: Path) -> None:
    feedback = "Rename the 'Longevity' outcome class to 'Lipoprotein(a) / MACE in CHD'."
    paper = (
        "## Results\n\n### Cardiometabolic Outcomes\n\nSmith 2024 reports an effect.\n\n"
        "### Lipoprotein(a) / MACE in CHD Outcomes\n\nJones 2024 reports an effect.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "r1", "outcome_class": "cardiometabolic"},
        {"receipt_id": "r2", "outcome_class": "longevity"},
    ]}))
    (tmp_path / "citation_registry.json").write_text(json.dumps({
        "r1": {"body_citation": "Smith 2024"},
        "r2": {"body_citation": "Jones 2024"},
    }))

    fixed, logs = journal_finalizer._phase_k_route_outcome_paragraphs(paper, tmp_path)

    assert fixed == paper
    assert logs == []
    report = journal_finalizer._surface_report(fixed, tmp_path)
    assert report is not None
    assert not any(issue.code == "outcome_routing" for issue in report.issues)
    (tmp_path / "researka_revision_request.json").unlink()
    report = journal_finalizer._surface_report(fixed, tmp_path)
    assert report is not None
    assert any(issue.code == "outcome_routing" for issue in report.issues)


def test_finalizer_answers_within_class_narrative_and_research_question(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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
        {"citation_token": "Smith 2025", "source_title": "Sirtuin intervention improves arterial stiffness", "endpoints": ["arterial stiffness"], "outcome_class": "cardiometabolic", "effect_direction": "positive", "directness": "direct", "evidence_tier": "A1", "n_claims": 12},
        {"citation_token": "Jones 2024", "source_title": "Sirtuin review finds null arterial stiffness effects", "endpoints": ["arterial stiffness"], "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "review", "evidence_tier": "B1", "n_claims": 8},
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
    import revision_coverage

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
        {"citation_token": "Sheng 2025", "source_title": "Integrating Vascular Aging and Genetic Risk: The Combined Impact of Estimated Pulse Wave Velocity and Genetic Predisposition on Coronary Artery Disease", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "p_values": ["p < 0.001"], "thesis_text": "The source reported p < 0.001.", "n_claims": 102},
        {"citation_token": "Nguyen 2026", "outcome_class": "deficiency_prevalence", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "p_values": ["p = 0.032"], "thesis_text": "The source reported p = 0.032.", "n_claims": 64},
        {"citation_token": "Wang 2024", "source_title": "Impact of a Precision Intervention for Vascular Health in Middle-Aged and Older Postmenopausal Women Using Polar Heart Rate Sensors", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "direct", "evidence_tier": "A1", "p_values": ["p < 0.05"], "thesis_text": "The source reported p < 0.05.", "n_claims": 54},
        {"citation_token": "Rodilla 2026", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "n_claims": 28},
        {"citation_token": "Alanis 2025", "outcome_class": "mechanism", "effect_direction": "null", "directness": "mechanistic", "evidence_tier": "C1", "n_claims": 27},
        {"citation_token": "Luo 2025", "source_title": "Effects of L-citrulline supplementation and watermelon intake on arterial stiffness and endothelial function in middle-aged and older adults", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "review", "evidence_tier": "B2", "p_values": ["p = 0.0007"], "thesis_text": "The source reported p = 0.0007.", "n_claims": 22},
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
    assert "No semantically comparable source-pair disagreements" in fixed
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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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
    import revision_coverage

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


def test_photobiomodulation_style_reviewer_asks_are_repaired_generically(tmp_path: Path) -> None:
    import revision_coverage

    asks = [
        "Expand the Gaps section to cover all five outcome classes (immune/inflammation, contextual adjacent, mechanism, muscle function, safety/comorbidity), not just two.",
        "Clarify the claim-counting methodology: explain how 433 high-confidence claims map to 17 sources, and what 'high-confidence' means in the extraction protocol.",
        "Remove or temper the 'geroscience case' and 'anti-aging' framing that the corpus does not support.",
    ]
    paper = (
        "## Abstract\n\nThe evidence supports an anti-aging signal.\n\n"
        "## Evidence Landscape\n\nCurrent map.\n\n"
        "## Conclusion\n\nThis remains a geroscience case.\n\n"
        "## References\n\n- Smith 2025.\n"
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": "; ".join(asks)}),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "photobiomodulation_red_light",
        "receipts": [
            {"outcome_class": "immune_inflammation", "n_claims": 81},
            {"outcome_class": "contextual_adjacent", "n_claims": 199},
            {"outcome_class": "mechanism", "n_claims": 14},
            {"outcome_class": "muscle_function", "n_claims": 16},
            {"outcome_class": "safety_comorbidity", "n_claims": 13},
        ],
    }), encoding="utf-8")

    fixed, logs1 = journal_finalizer._phase_d_evidence_boundary_note(paper, tmp_path)
    fixed, logs2 = journal_finalizer._phase_d_revision_audit_notes(fixed, tmp_path)
    fixed, logs3 = journal_finalizer._phase_d_actionable_gaps(fixed, tmp_path)

    assert logs1 and logs2 and logs3
    assert "Evidence-boundary note:" in fixed
    assert "Claim-count audit note:" in fixed
    assert "not independent studies" in fixed
    assert "Immune and Inflammation, Contextual Adjacent, Mechanism, Muscle Function, Safety and Comorbidity" in fixed
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(fixed, asks) == []


def test_source_verification_phase_adds_citation_traceability_note(tmp_path: Path) -> None:
    import revision_coverage

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
    import revision_coverage

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


def test_finalizer_reaches_late_fixed_point(tmp_path: Path, monkeypatch) -> None:
    calls = 0
    (tmp_path / "full_paper.md").write_text("A")

    def staged(text: str, _out: Path) -> tuple[str, list[Any]]:
        nonlocal calls
        calls += 1
        return (text + "x", []) if calls < 8 else (text, [])

    monkeypatch.setattr(journal_finalizer, "_run_text_phases", staged)
    monkeypatch.setattr(journal_finalizer, "_phase_g_refresh_sidecars", lambda _out: [])
    report = journal_finalizer.finalize_run(tmp_path)

    assert calls == 8
    assert report.paper_changed


def test_finalizer_iteration_cap_still_fails_closed(tmp_path: Path, monkeypatch) -> None:
    import pytest

    (tmp_path / "full_paper.md").write_text("A")
    monkeypatch.setattr(journal_finalizer, "_run_text_phases", lambda text, _out: (text + "x", []))
    monkeypatch.setattr(journal_finalizer, "_phase_g_refresh_sidecars", lambda _out: [])

    with pytest.raises(RuntimeError, match="did not reach a fixed point"):
        journal_finalizer.finalize_run(tmp_path)


def test_finalizer_canonicalizes_surface_valid_cycle(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    (tmp_path / "full_paper.md").write_text("A")
    monkeypatch.setattr(journal_finalizer, "_run_text_phases", lambda text, _out: ({"A": "B", "B": "A"}[text], []))
    monkeypatch.setattr(journal_finalizer, "_phase_g_refresh_sidecars", lambda _out: [])
    monkeypatch.setattr(journal_finalizer, "_surface_report", lambda _text, _out: SimpleNamespace(passed=True))

    first = journal_finalizer.finalize_run(tmp_path)
    second = journal_finalizer.finalize_run(tmp_path)

    assert (tmp_path / "full_paper.md").read_text() == "A"
    assert any(entry.rule == "canonicalize_surface_valid_repair_cycle" for entry in first.entries)
    assert not second.paper_changed


def test_finalizer_refreshes_cycle_before_rejecting_stale_surface_state(
    tmp_path: Path, monkeypatch,
) -> None:
    from types import SimpleNamespace

    (tmp_path / "full_paper.md").write_text("A")
    refreshes = 0

    def phase_g(_out_dir: Path) -> list[Any]:
        nonlocal refreshes
        refreshes += 1
        return []

    monkeypatch.setattr(
        journal_finalizer,
        "_run_text_phases",
        lambda text, _out: ({"A": "B", "B": "A"}[text], []),
    )
    monkeypatch.setattr(journal_finalizer, "_phase_g_refresh_sidecars", phase_g)
    monkeypatch.setattr(
        journal_finalizer,
        "_surface_report",
        lambda _text, _out: SimpleNamespace(passed=refreshes >= 3),
    )

    report = journal_finalizer.finalize_run(tmp_path)

    assert refreshes == 3
    assert (tmp_path / "full_paper.md").read_text() == "A"
    assert any(
        entry.rule == "canonicalize_surface_valid_repair_cycle"
        for entry in report.entries
    )


def test_finalizer_revalidates_cycle_after_sidecar_refresh(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from types import SimpleNamespace

    (tmp_path / "full_paper.md").write_text("A")
    calls = 0

    def phase_g(out_dir: Path) -> list[Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            (out_dir / "full_paper.md").write_text("BROKEN")
        return []

    monkeypatch.setattr(journal_finalizer, "_run_text_phases", lambda text, _out: ({"A": "B", "B": "A"}[text], []))
    monkeypatch.setattr(journal_finalizer, "_phase_g_refresh_sidecars", phase_g)
    monkeypatch.setattr(journal_finalizer, "_surface_report", lambda text, _out: SimpleNamespace(passed=text in {"A", "B"}))

    with pytest.raises(RuntimeError, match="did not reach a fixed point"):
        journal_finalizer.finalize_run(tmp_path)


def test_review_noise_repairs_unreferenced_inline_citation_year() -> None:
    apply_review_noise_control = journal_finalizer.review_noise_control.apply_review_noise_control

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


def test_review_noise_expands_unambiguous_title_year_alias() -> None:
    apply_review_noise_control = journal_finalizer.review_noise_control.apply_review_noise_control

    paper = (
        "## Discussion\n\nAtorvastatin 2021 reported a bounded result.\n\n"
        "## References\n\n"
        "- **Atorvastatin for Reduction of Day 2021.** Mortality trial.\n"
        "- **Effects of Atorvastatin in Graves' 2021.** Orbitopathy trial.\n"
    )

    fixed, _changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "Atorvastatin for Reduction of Day 2021 reported" in fixed


def test_review_noise_aliases_only_from_references() -> None:
    _repair_unreferenced_citation_years = journal_finalizer.review_noise_control._repair_unreferenced_citation_years

    paper = (
        "## Discussion\n\nBogus 2021 reported a result.\n\n"
        "- **Bogus Expanded 2021.** Bold body bullet, not a reference.\n\n"
        "## References\n\n- **Smith 2020.** Retained source.\n"
    )

    fixed, changes = _repair_unreferenced_citation_years(paper)

    assert fixed == paper
    assert changes == 0


def test_surface_repair_reframes_summary_language_inside_limitations() -> None:
    paper = (
        "## Results\n\nPositive signals appear in mortality survival as a result summary.\n\n"
        "## Limitations\n\n"
        "The headline statement that positive signals appear in mortality survival "
        "is anchored entirely in observational designs. The direct set includes "
        "Trial in the Elderly ( (tier=A1; directness=direct). The evidence differs "
        "by population elderly), by design (trial vs cohort). The outcomes were "
        "1) mortality, 2) function, a) safety, and ii) durability.\n\n"
        "## Conclusion\n\nThe interpretation remains bounded.\n"
    )

    fixed, logs = journal_finalizer._phase_m_repair_surface_artifacts(paper)

    assert "Positive signals appear in mortality survival as a result summary" in fixed
    assert "The reported positive-signal pattern for mortality survival is anchored" in fixed
    assert "Elderly ( (tier" not in fixed
    assert "elderly), by design" not in fixed
    assert "1. mortality, 2. function, a. safety, and ii. durability" in fixed
    assert not any(issue.code == "limitations_leak" for issue in evaluate_journal_surface(fixed).issues)
    assert any(log.phase == "M_surface_artifact_cleanup" for log in logs)


def test_review_noise_strips_unsupported_inline_citation_marker() -> None:
    from agent.journal_surface_gate import unreferenced_citation_tokens
    apply_review_noise_control = journal_finalizer.review_noise_control.apply_review_noise_control

    paper = (
        "## Discussion\n\n"
        "The hallmarks frame is discussed (López-Otín et al. 2013, as cited across the corpus; "
        "canonical threshold anchors include Studenski 2011 and Cruz-Jentoft 2019). "
        "A second unsupported mention cites López-Otín 2013.\n\n"
        "## References\n\n"
        "- **Studenski 2011.** Gait speed and survival.\n"
        "- **Cruz-Jentoft 2019.** Sarcopenia consensus thresholds.\n"
    )

    fixed, changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "López-Otín" not in fixed
    assert "unsupported mention" not in fixed
    assert "cites." not in fixed
    assert "canonical threshold anchors include Studenski 2011 and Cruz-Jentoft 2019" in fixed
    assert unreferenced_citation_tokens(fixed) == ()
    assert ("strip_unsupported_inline_citation", 2, "removed 2 unsupported inline citation marker(s)") in changes


def test_review_noise_preserves_decimal_before_unsupported_citation_sentence() -> None:
    apply_review_noise_control = journal_finalizer.review_noise_control.apply_review_noise_control

    paper = (
        "## Discussion\n\nThe retained estimate was p=0.05. "
        "Bogus 2021 supplied an unsupported gloss. The bounded result remains.\n"
        "    indented_code_block()\n\n"
        "## References\n\n- **Smith 2020.** Retained source.\n"
    )

    fixed, _changes = apply_review_noise_control(paper, Path("/tmp/no-run"))

    assert "p=0.05" in fixed
    assert "Bogus 2021" not in fixed
    assert "The bounded result remains" in fixed
    assert "\n    indented_code_block()" in fixed


def test_review_noise_repairs_public_artifact_phrase() -> None:
    from agent.journal_surface_gate import evaluate_journal_surface
    apply_review_noise_control = journal_finalizer.review_noise_control.apply_review_noise_control

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
    _dedupe_repeated_blocks = journal_finalizer.review_noise_control._dedupe_repeated_blocks

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


def test_dedupe_keeps_domain_public_extraction_table_with_subset_vocab() -> None:
    _dedupe_repeated_blocks = journal_finalizer.review_noise_control._dedupe_repeated_blocks

    paper = (
        "## Results\n\n"
        "The source design population intervention exposure comparator endpoint "
        "follow-up effect direction directness risk bias map reports Smith 2024 "
        "randomized trial older adults exercise control cognition null direct "
        "some concerns as domain-specific evidence.\n\n"
        "## Domain Interpretation Framework\n\n"
        "### Public Study Extraction Table\n\n"
        "| Source | Design | Population | Intervention/exposure | Comparator | Endpoint | Follow-up | Effect | Direction | Directness | Risk of bias | Why it matters |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| Smith 2024 | randomized trial | older adults | exercise | control | cognition | 24 weeks | null | null | direct | some concerns | direct evidence for cognition |\n\n"
        "## References\n\n- Smith 2024.\n"
    )

    out, removed = _dedupe_repeated_blocks(paper)

    assert removed == 0
    assert "### Public Study Extraction Table" in out
    assert "| Smith 2024 | randomized trial | older adults |" in out


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
        "The retained endpoints were mostly non-significant (e.\n\n"
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
    assert "(e." not in fixed
    assert "The retained endpoints were mostly non-significant" in fixed
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


def test_phase_b_keeps_research_synthesis_for_large_direct_corpus(tmp_path: Path) -> None:
    receipts = [{"directness": "direct"} for _ in range(10)]
    receipts.extend({"directness": "review"} for _ in range(41))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": receipts}),
        encoding="utf-8",
    )
    paper = "# Research Synthesis: Metformin Biomarker Effects\n\n## Results\n\nBody.\n"

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
    review_noise_control = journal_finalizer.review_noise_control

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


def test_run_text_phases_restores_surface_floor_after_terminal_cleanup(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    def restore_introduction(
        text: str, _out_dir: Path, entries: list[journal_finalizer.FinalizerLogEntry],
        _entry_cls: type[journal_finalizer.FinalizerLogEntry],
    ) -> tuple[str, list[journal_finalizer.FinalizerLogEntry]]:
        body = " ".join(["restored"] * 400)
        fixed = re.sub(
            r"(?ms)^## Introduction\b.*?(?=^## (?!#)|\Z)",
            f"## Introduction\n\n{body}\n\n",
            text,
        )
        return fixed, entries

    def shrink_introduction(
        text: str,
    ) -> tuple[str, list[journal_finalizer.FinalizerLogEntry]]:
        fixed = re.sub(
            r"(?ms)^## Introduction\b.*?(?=^## (?!#)|\Z)",
            "## Introduction\n\nshort\n\n",
            text,
        )
        return fixed, []

    monkeypatch.setattr(
        journal_finalizer.review_noise_control,
        "restore_surface_floors",
        restore_introduction,
    )
    monkeypatch.setattr(
        journal_finalizer,
        "_phase_m_scope_restored_backstop_duplicates",
        shrink_introduction,
    )
    paper = (
        "# T\n\n## Introduction\n\nshort\n\n"
        "## Discussion\n\n"
        "The corpus supports a bounded interpretation.\n\n"
        "Future trials would settle the open threats.\n\n"
        "## Limitations\n\nstub.\n"
    )

    fixed, _log = journal_finalizer._run_text_phases(paper, tmp_path)

    introduction = fixed.split("## Introduction", 1)[1].split("## Discussion", 1)[0]
    assert len(introduction.split()) >= 400


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
    stable, _ = journal_finalizer._phase_k_route_outcome_paragraphs(out, tmp_path)
    # exactly one long fallback paragraph across both thin classes
    assert out.count("Evidence for this outcome class is represented") == 1
    assert stable == out
    # and the production journal-surface gate finds no duplicate paragraph
    report = evaluate_journal_surface(out)
    assert not any(issue.code == "duplicate_paragraph" for issue in report.issues)


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


def test_phase_g_refreshes_public_exports_from_final_markdown(tmp_path: Path) -> None:
    import hashlib
    import zipfile

    paper = "# Research Synthesis: Test\n\n## Results\n\nFinal revised evidence.\n"
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "test_effects",
        "receipts": [],
    }), encoding="utf-8")
    (tmp_path / "full_paper.docx").write_bytes(b"stale")
    (tmp_path / "full_paper.typ").write_text("stale", encoding="utf-8")

    from agent.artifact_consistency import refresh_public_exports
    assert refresh_public_exports(tmp_path) is True
    source_hash = hashlib.sha256(paper.encode("utf-8")).hexdigest()
    with zipfile.ZipFile(tmp_path / "full_paper.docx") as archive:
        assert archive.read("researka/source.sha256").decode() == source_hash
        assert b"Final revised evidence" in archive.read("word/document.xml")
    assert (tmp_path / "full_paper.typ").read_text().startswith(f"// source-sha256: {source_hash}\n")
    assert refresh_public_exports(tmp_path) is False


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
    assert "**Direct-source ceiling:** The corpus contains 1 direct clinical source." in fixed
    assert "Representative direct sources are Wang 2024." in fixed
    assert "**Design-limit note:** Protocol, mechanistic, observational, or cross-sectional sources" in fixed
    assert "Vicente-Gabriel 2024" in fixed


def test_second_telomere_revise_asks_repaired_generically(tmp_path: Path) -> None:
    feedback = (
        "Restructure outcome-class taxonomy to separate: (a) telomere length as cancer "
        "prognostic biomarker, (b) telomere length as incident cancer risk factor/MR/causal, "
        "(c) telomere biology mechanisms in tumor cells ALT/TERT, (d) treatment-induced "
        "telomere change, (e) telomere-targeted or supplement interventions. Current seven-class "
        "taxonomy mixes these.; Reconcile directional map with coded extraction: either "
        "re-extract/code directions for all sources, or remove per-class directional summary and "
        "state corpus is predominantly unclear-coded and does not support directional map.; Remove "
        "Jaeger 2024 from cancer-effects bundle or move to clearly labeled non-cancer evidence "
        "annex; healthy-volunteer supplement RCT not appropriate as direct contextual evidence for "
        "telomere-cancer effects.; Recode Ha 2023 in Mortality and Survival: EFS P=.903 no "
        "significant difference; classify null, not \"significant source statistic in 3/3 sources\", "
        "or define significant as \"source reports p-value.\"; Clarify admission funnel arithmetic: "
        "whether 41/8/48/20/3 buckets are mutually exclusive/overlapping/sequential; reconcile "
        "strict high-confidence=3 vs admitted final=25; explain why 25 not 3 source base.; Tighten "
        "conclusion so it does not present bounded risk-marker, causal, mechanistic, or "
        "treatment-response hypotheses as equally supported when corpus is skewed toward prognostic "
        "biomarker studies, MR risk and mechanistic ALT minority slices."
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "telomere_cancer_effects",
        "n_receipts": 25,
        "receipt_funnel": {
            "classified_receipt_candidates": 73,
            "counts": {
                "admitted_receipts": 25,
                "original_strict_high_confidence_receipts": 3,
                "partial_only": 41,
                "none_only": 8,
                "partial_or_none": 48,
                "unmapped": 20,
            },
        },
        "receipts": [
            {
                "citation_token": "Sasmita 2025",
                "source_title": "Telomere length as a cancer prognostic biomarker",
                "outcome_class": "mortality_survival",
                "effect_direction": "unclear",
                "directness": "review",
                "evidence_tier": "B2",
                "n_claims": 113,
            },
            {
                "citation_token": "Markozannes 2022",
                "source_title": "Mendelian randomization of telomere length and cancer risk",
                "outcome_class": "cancer_risk",
                "effect_direction": "null",
                "directness": "review",
                "evidence_tier": "B2",
            },
            {
                "citation_token": "Chen 2023",
                "source_title": "Genetically predicted telomere length and incident cancer risk",
                "outcome_class": "cancer_risk",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
            },
            {
                "citation_token": "Jaeger 2024",
                "source_title": "Healthy-volunteer supplement intervention and telomere change",
                "outcome_class": "contextual_other",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "p_values": ["P = .041"],
            },
            {
                "citation_token": "Ha 2023",
                "source_title": "Telomere length and survival outcomes in cancer cohorts",
                "outcome_class": "mortality_survival",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "p_values": ["P = .903", "P = .019", "P = .026"],
            },
            {
                "citation_token": "Afolabi 2026",
                "source_title": "ALT and TERT telomere biology mechanisms in tumor cells",
                "outcome_class": "mechanism",
                "effect_direction": "null",
                "directness": "mechanistic",
                "evidence_tier": "C1",
            },
        ],
    }), encoding="utf-8")
    paper = (
        "## Methods\n\nScreening summary.\n\n"
        "## Evidence Landscape\n\nThe seven-class taxonomy mixes signals.\n\n"
        "## Key Findings\n\nSignals are summarized broadly.\n\n"
        "## Conclusion\n\n"
        "These source patterns support bounded risk-marker, causal, mechanistic, "
        "or treatment-response hypotheses according to source directness.\n"
    )

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)
    asks = journal_finalizer.revision_coverage.revision_asks(feedback)

    assert any(entry.rule == "mark_reviewer_named_scope_mismatch_sources_contextual" for entry in logs)
    assert "Outcome-taxonomy separation note:" in fixed
    assert "Directional-map boundary:" in fixed
    assert "predominantly unclear-coded" in fixed
    assert "Source-scope annex note:" in fixed
    assert "Jaeger 2024" in fixed
    assert "not pooled as direct evidence" in fixed
    assert "Numeric verification note: Ha 2023" in fixed
    assert "p = .903" in fixed
    assert "Strict high-confidence subset note: 3 strict high-confidence receipt(s)" in fixed
    assert "admitted source base remains 25" in fixed
    assert "Dominant source pattern:" in fixed
    assert "not weighed equally" in fixed
    assert "minority slices" in fixed.lower()
    assert "risk-marker, causal, mechanistic, or treatment-response hypotheses according to source directness" not in fixed
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, asks) == []


def test_third_telomere_revise_asks_repaired_generically(tmp_path: Path) -> None:
    feedback = (
        "Add a clearly scoped Key Findings section that names the 2-3 most-supported outcome-specific "
        "signals with their source citations, rather than only a methodological header.; Reconcile the "
        "five-domain vs. seven-slice source stratification: either consolidate to five outcome domains "
        "matching the abstract, or correct the abstract to state seven slices with their n counts.; "
        "Recompute and report the actual MR/ causal-risk source count from the bundle (Wan 2023, "
        "Song 2022, Chen 2023, Markozannes 2022, plus any others) rather than asserting an unsupported "
        "7/25 figure.; Reclassify Jaeger 2024 as direct interventional evidence (RCT with TL endpoint) "
        "and adjust the direct-evidence count and the '0/25 direct sources' statement in Gaps Identified "
        "accordingly.; Surface the direction-coded findings for at least the top-cited sources in each "
        "outcome class so that significant source statistic rows are interpretable."
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "telomere_cancer_effects",
        "receipts": [
            {
                "citation_token": "Sarkar 2026",
                "source_title": "Leukocyte Telomere Length Variants Are Independently Associated with Survival of Patients with Colorectal Cancer",
                "outcome_class": "mortality_survival",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "p_values": ["p = 0.0005"],
                "thesis_text": "The source reported p = 0.0005.",
                "n_claims": 20,
            },
            {
                "citation_token": "Chen 2023",
                "source_title": "Association between genetically determined telomere length and health-related outcomes: Mendelian randomization studies",
                "outcome_class": "contextual_other",
                "effect_direction": "null",
                "directness": "review",
                "evidence_tier": "B2",
                "n_claims": 14,
            },
            {
                "citation_token": "Markozannes 2022",
                "source_title": "Systematic review of Mendelian randomization studies on risk of cancer",
                "outcome_class": "immune",
                "effect_direction": "null",
                "directness": "review",
                "evidence_tier": "B2",
                "n_claims": 61,
            },
            {
                "citation_token": "Wan 2023",
                "source_title": "Mendelian randomization study on leukocyte telomere length and prostate cancer",
                "outcome_class": "contextual_other",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "n_claims": 12,
            },
            {
                "citation_token": "Song 2022",
                "source_title": "Association Between Telomere Length and Skin Cancer and Aging: A Mendelian Randomization Analysis",
                "outcome_class": "contextual_other",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "n_claims": 8,
            },
            {
                "citation_token": "Jaeger 2024",
                "source_title": "Randomized placebo-controlled supplement trial with telomere length endpoint",
                "outcome_class": "contextual_other",
                "effect_direction": "unclear",
                "directness": "indirect",
                "evidence_tier": "B2",
                "p_values": ["p = 0.01"],
                "thesis_text": "The source reported p = 0.01.",
                "n_claims": 90,
            },
            {
                "citation_token": "Afolabi 2026",
                "source_title": "ALT and TERT telomere biology mechanisms in tumor cells",
                "outcome_class": "mechanism",
                "effect_direction": "null",
                "directness": "mechanistic",
                "evidence_tier": "C1",
                "n_claims": 3,
            },
        ],
    }), encoding="utf-8")
    paper = (
        "## Abstract\n\nThis synthesis uses a five-domain summary.\n\n"
        "## Evidence Landscape\n\n0/25 direct sources.\n\n"
        "## Key Findings\n\nKey findings from source synthesis.\n\n"
        "## Conclusion\n\nThe conclusion is bounded.\n"
    )

    fixed, _logs = journal_finalizer._run_text_phases(paper, tmp_path)
    asks = journal_finalizer.revision_coverage.revision_asks(feedback)

    assert "Most-supported outcome-specific signals:" in fixed
    assert "Sarkar 2026" in fixed and "Chen 2023" in fixed
    assert "Stratification reconciliation note:" in fixed
    assert "MR/causal-risk source count:" in fixed
    assert "Wan 2023" in fixed and "Song 2022" in fixed and "Chen 2023" in fixed and "Markozannes 2022" in fixed
    assert "Direct-interventional endpoint correction:" in fixed
    assert "Jaeger 2024" in fixed
    assert "Jaeger 2024 is counted as direct interventional endpoint evidence" in fixed
    assert "for its measured endpoint" in fixed
    assert "Direct evidence count is 1/7" in fixed
    assert "Direction-coded source highlights:" in fixed
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, asks) == []


def test_fourth_telomere_revise_asks_repaired_generically(tmp_path: Path) -> None:
    feedback = (
        "Reconcile each cited source's effect_direction with the actual reported finding "
        "in excerpt; remove or correct contradicted directionality (Brouwers 2016, "
        "Alhareeri 2020, Sasmita 2025, Ha 2023).; Verify/reconcile admission counts "
        "and receipt-level direction tallies (n=24, negative=1, null=5, positive=2, "
        "unclear=16) against source bundle.; Reframe research question and conclusion "
        "so Telomere Cancer Effects is bounded to retained set: adjacent biomarkers, "
        "prognostic associations, MR causal signals; not direct interventional/clinical "
        "efficacy.; Separate MR cancer-risk sources (Li 2026, Chen 2023, Wan 2023, "
        "Song 2022) from mechanistic/ALT sources (Brown 2026, Genetta 2026, Aierken "
        "2026, Xu 2024, Afolabi 2026) when describing disagreements; don't pool.; "
        "Add explicit statement no direct interventional hard-endpoint sources admitted; "
        "conclusion bounded to association/mechanism/hypothesis-generation; remove "
        "clinical actionability/anti-aging framing.; Verify 2026-dated sources for "
        "actual publication status and preprint vs peer-reviewed distinction; flag preprints."
    )
    rows = [
        {"citation_token": "Brouwers 2016", "source_title": "Telomere association reported in cohort excerpt", "outcome_class": "prognostic_survival", "effect_direction": "negative", "directness": "indirect", "source_year": 2016},
        {"citation_token": "Alhareeri 2020", "source_title": "Telomere clinical association excerpt", "outcome_class": "adjacent_biomarker", "effect_direction": "positive", "directness": "indirect", "source_year": 2020},
        {"citation_token": "Sasmita 2025", "source_title": "Shorter telomere length as prognostic marker for recurrence", "outcome_class": "prognostic_survival", "effect_direction": "unclear", "directness": "review", "source_year": 2025},
        {"citation_token": "Ha 2023", "source_title": "Telomere survival endpoint report", "outcome_class": "mortality_survival", "effect_direction": "null", "directness": "indirect", "source_year": 2023},
        {"citation_token": "Li 2026", "source_title": "Mendelian randomization of telomere length and cancer risk", "outcome_class": "cancer_risk_mr", "effect_direction": "null", "directness": "indirect", "source_year": 2026},
        {"citation_token": "Chen 2023", "source_title": "Genetically predicted telomere length and cancer risk", "outcome_class": "cancer_risk_mr", "effect_direction": "positive", "directness": "review", "source_year": 2023},
        {"citation_token": "Wan 2023", "source_title": "Mendelian randomization study on leukocyte telomere length", "outcome_class": "cancer_risk_mr", "effect_direction": "unclear", "directness": "indirect", "source_year": 2023},
        {"citation_token": "Song 2022", "source_title": "Mendelian randomization analysis of telomere length and skin cancer", "outcome_class": "cancer_risk_mr", "effect_direction": "unclear", "directness": "indirect", "source_year": 2022},
        {"citation_token": "Brown 2026", "source_title": "ALT telomere mechanism in tumor cells", "outcome_class": "mechanism_alt", "effect_direction": "null", "directness": "mechanistic", "source_year": 2026, "source_type": "preprint"},
        {"citation_token": "Genetta 2026", "source_title": "TERT mechanistic telomere biology in cancer", "outcome_class": "mechanism", "effect_direction": "unclear", "directness": "mechanistic", "source_year": 2026},
        {"citation_token": "Aierken 2026", "source_title": "ALT and tumor-cell telomere mechanism", "outcome_class": "mechanism_alt", "effect_direction": "unclear", "directness": "mechanistic", "source_year": 2026},
        {"citation_token": "Xu 2024", "source_title": "Telomerase mechanistic study in cancer", "outcome_class": "mechanism", "effect_direction": "null", "directness": "mechanistic", "source_year": 2024},
        {"citation_token": "Afolabi 2026", "source_title": "Telomere-driven dysfunctional mechanism in gynecological cancers", "outcome_class": "mechanism", "effect_direction": "null", "directness": "mechanistic", "source_year": 2026},
    ]
    rows.extend(
        {
            "citation_token": f"Context {idx} 2021",
            "source_title": "Contextual telomere biomarker source",
            "outcome_class": "adjacent_biomarker",
            "effect_direction": "unclear",
            "directness": "indirect",
            "source_year": 2021,
        }
        for idx in range(1, 12)
    )
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "telomere_cancer_effects",
        "receipts": rows,
    }), encoding="utf-8")
    paper = (
        "## Research Question\n\nIs Telomere Cancer Effects clinically actionable?\n\n"
        "## Evidence Landscape\n\nThe source bundle is summarized.\n\n"
        "## Key Findings\n\nKey findings from source synthesis.\n\n"
        "## Conclusion\n\nThis is an anti-aging clinical actionability signal.\n"
    )

    fixed, _logs = journal_finalizer._run_text_phases(paper, tmp_path)
    asks = journal_finalizer.revision_coverage.revision_asks(feedback)

    assert "Effect-direction reconciliation note:" in fixed
    assert all(label in fixed for label in ("Brouwers 2016", "Alhareeri 2020", "Sasmita 2025", "Ha 2023"))
    assert "Admission and direction-tally reconciliation: n=24; negative=1; null=5; positive=2; unclear=16" in fixed
    assert "Scope-bounded research question note:" in fixed
    assert "not direct interventional or clinical efficacy" in fixed
    assert "MR/mechanism disagreement separation note:" in fixed
    assert all(label in fixed for label in ("Li 2026", "Chen 2023", "Wan 2023", "Song 2022"))
    assert all(label in fixed for label in ("Brown 2026", "Genetta 2026", "Aierken 2026", "Xu 2024", "Afolabi 2026"))
    assert "No direct interventional hard-endpoint sources were admitted" in fixed
    assert "Publication-status/preprint note:" in fixed
    assert "Brown 2026" in fixed and "preprint" in fixed.lower()
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []


def test_revise_feedback_repairs_denominators_tensions_and_findings_map(tmp_path: Path) -> None:
    feedback = (
        "Reconcile all source-count denominators (35 vs 36 vs 39; 12/35 vs 13/36) across "
        "the Evidence Landscape, Findings Map, Source-context map, and Search Summary admission funnel "
        "so the corpus accounting is internally consistent.; "
        "Expand the Tensions and Gaps section to explicitly enumerate the major cross-source disagreements "
        "(fibromyalgia meta-analytic pain reduction vs. null primary RCTs; IBD dispensing reductions in "
        "Raknes 2018 vs. null Raknes 2020 hypothyroidism signal; Moloney 2026 null hsCRP vs. mechanistic "
        "anti-inflammatory claims; Vatvani 2024 positive pooled effect vs. Bruun 2021/Bested 2023 null "
        "or weak primary signals) rather than collapsing them into a single prescriptive sentence.; "
        "Provide source-level attribution rows in the Findings Map for every prose-cited finding, not only "
        "the four currently listed.; "
        "Rewrite the Exposure and Dose-Adjacent Evidence Outcomes section as a real outcome-class synthesis "
        "with its own tensions, directness summary, and representative findings.; "
        "Tighten the scope statement so that Dosing and Pharmacokinetics is not functioning as a proxy for "
        "the entire clinical evidence base."
    )
    rows = [
        {"citation_token": "Vatvani 2024", "source_title": "Meta-analysis of low-dose naltrexone pain response", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "positive", "directness": "review", "evidence_tier": "B1", "n_claims": 41, "p_values": ["p < 0.05"]},
        {"citation_token": "Nazir 2025", "source_title": "Fibromyalgia pain response synthesis", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "positive", "directness": "review", "evidence_tier": "B1", "n_claims": 33},
        {"citation_token": "Tsui 2024", "source_title": "Randomized trial of low-dose naltrexone in fibromyalgia", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "null", "directness": "direct", "evidence_tier": "A1", "n_claims": 29},
        {"citation_token": "Moloney 2026", "source_title": "Low-dose naltrexone trial with null hsCRP endpoint", "outcome_class": "immune", "effect_direction": "null", "directness": "direct", "evidence_tier": "A1", "n_claims": 24},
        {"citation_token": "Raknes 2018", "source_title": "IBD dispensing reductions after low-dose naltrexone", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "positive", "directness": "indirect", "evidence_tier": "B2", "n_claims": 18},
        {"citation_token": "Raknes 2020", "source_title": "Null hypothyroidism dispensing signal", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "n_claims": 16},
        {"citation_token": "Bruun 2021", "source_title": "Weak primary signal in low-dose naltrexone trial", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "unclear", "directness": "direct", "evidence_tier": "A1", "n_claims": 12},
        {"citation_token": "Bested 2023", "source_title": "Weak primary fatigue signal", "outcome_class": "dosing_pharmacokinetics", "effect_direction": "unclear", "directness": "direct", "evidence_tier": "A1", "n_claims": 10},
        {"citation_token": "Parkitny 2017", "source_title": "Reduced inflammatory cytokines after low-dose naltrexone", "outcome_class": "immune", "effect_direction": "positive", "directness": "indirect", "evidence_tier": "B2", "n_claims": 8},
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "topic": "low_dose_naltrexone_inflammation",
        "n_non_orthogonal_tensions": 108,
        "receipts": rows,
    }), encoding="utf-8")
    paper = (
        "## Evidence Landscape\n\n"
        "Current source counts are inconsistent.\n\n"
        "### Findings Map\n\n"
        "- Parkitny 2017: outcome=Dosing and Pharmacokinetics; direction=null; directness=indirect; tier=B2.\n\n"
        "## Results\n\n"
        "### Dosing and Pharmacokinetics Outcomes\n\n"
        "The retained narrative paragraphs were more strongly assigned to adjacent outcome classes.\n\n"
        "## Tensions and Gaps\n\n"
        "Fix the tension section.\n\n"
        "## Conclusion\n\n"
        "The clinical evidence base is broad.\n"
    )

    asks = journal_finalizer.revision_coverage.revision_asks(feedback)
    assert any(ask in journal_finalizer.revision_coverage.deterministic_unmet_asks(paper, asks) for ask in asks)

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert "Corpus-count reconciliation:" in fixed
    assert "Findings Map completeness note: all 9 admitted manifest rows" in fixed
    assert "No semantically comparable source-pair disagreements" in fixed
    assert "Nazir 2025 vs Tsui 2024" not in fixed
    assert "Outcome-class synthesis note: Exposure and Dose-Adjacent Evidence is treated as a real outcome-class synthesis" in fixed
    assert "Directness summary:" in fixed
    assert "Source examples:" in fixed
    assert "direct-source ceiling:" in fixed.lower()
    assert "Dosing and Pharmacokinetics" not in fixed
    unmet = journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, asks, retained_citations={row["citation_token"] for row in rows},
    )
    assert len(unmet) == 1
    assert "cross-source disagreements" in unmet[0].lower()
    assert {entry.phase for entry in logs} >= {
        "D_substantive_evidence_synthesis",
        "D_source_outcome_class_map",
        "D_tensions_and_gaps_breadth",
        "D_outcome_label_cleanup",
        "D_revision_surface_notes",
    }


def test_untraceable_tension_count_cleanup_qualifies_exact_pair_count() -> None:
    paper = (
        "## Results\n\n"
        "Direct and indirect sources generate 22 paired indirectness-gap tensions. "
        "These 22 tensions each reflect directness disparity.\n"
    )

    fixed, logs = journal_finalizer._phase_d_untraceable_tension_count_cleanup(paper)

    assert "22 paired" not in fixed
    assert "These 22 tensions" not in fixed
    assert "paired indirectness-gap tensions" in fixed
    assert "These tensions each reflect" in fixed
    assert logs and logs[0].rule == "qualify_unbacked_tension_count"


def test_author_inference_boundary_is_relocated_to_requested_section(tmp_path: Path) -> None:
    feedback = (
        "Mark mechanism-level explanations in the Cross-Domain Synthesis as "
        "author inference where they go beyond cited sources."
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": feedback}), encoding="utf-8",
    )
    note = journal_finalizer.revision_coverage._AUTHOR_INFERENCE_BOUNDARY
    paper = (
        f"## Results\n\nResults narrative.\n\n{note}\n\n"
        "## Cross-Domain Synthesis\n\nMechanistic interpretation.\n\n"
        "## Discussion\n\nBounded discussion.\n"
    )

    fixed, logs = journal_finalizer._phase_d_author_inference_boundary(paper, tmp_path)

    assert note not in journal_finalizer._section_body(fixed, "Results")
    assert note in journal_finalizer._section_body(fixed, "Cross-Domain Synthesis")
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, [feedback]) == []
    assert logs[0].rule == "place_author_inference_boundary_in_requested_section"


def test_author_inference_boundary_uses_explicit_move_destination(tmp_path: Path) -> None:
    feedback = "Author-inference boundary within Discussion should relocate to Cross-Domain Synthesis."
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": feedback}), encoding="utf-8",
    )
    note = journal_finalizer.revision_coverage._AUTHOR_INFERENCE_BOUNDARY
    paper = (
        "## Cross-Domain Synthesis\n\nMechanistic interpretation.\n\n"
        f"## Discussion\n\n{note}\n"
    )

    fixed, _logs = journal_finalizer._phase_d_author_inference_boundary(paper, tmp_path)

    assert note in journal_finalizer._section_body(fixed, "Cross-Domain Synthesis")
    assert note not in journal_finalizer._section_body(fixed, "Discussion")
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, [feedback]) == []


def test_revision_surface_moves_named_tensions_and_reconciles_mechanistic_framing(tmp_path: Path) -> None:
    feedback = (
        "Fix the typographical artifact in the Abstract ('remains is consistent with before clinical use').; "
        "Rewrite the Conclusion as a bounded, outcome-class-anchored statement that maps cleanly to the "
        "Boundary-Condition Matrix and Quantitative Evidence Index; eliminate repetition with the Discussion.; "
        "Surface the named internal cross-source tensions (Alotaibi 2026 vs Incalzi 2024/Luo 2026; "
        "Wang 2024 vs Szilagyi 2025/Wang 2025b) directly in the Conclusion or Discussion, not only in the Evidence Snapshot.; "
        "Resolve the 'no mechanistic sources' claim with the actual presence of biomarker content and either recode it or adjust the framing."
    )
    (tmp_path / "researka_revision_request.json").write_text(
        json.dumps({"feedback": feedback}), encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"receipts": [{"citation_token": "Alotaibi 2026"}]}), encoding="utf-8",
    )
    (tmp_path / "structured_evidence_tables.md").write_text(
        "## Quantitative Evidence Index\n\n| Study | Outcome | Direction | Estimate | Type | Source |\n"
        "|---|---|---|---|---|---|\n| Alotaibi 2026 | mortality | mixed | P = 0.004 | p-value | bundle |\n",
        encoding="utf-8",
    )
    tension = (
        "Adjudicating the named internal tension: Alotaibi 2026 versus Incalzi 2024 and Luo 2026; "
        "Wang 2024 conflicts with Szilagyi 2025 and Wang 2025b."
    )
    paper = (
        f"## Abstract\n\nThe corrected abstract is bounded.\n\n{tension}\n\n"
        "## Discussion\n\nBounded discussion.\n\n"
        "## Limitations\n\nThe corpus has no sources classified primarily as mechanistic or model-system evidence.\n\n"
        "## Conclusion\n\nBounded conclusion.\n"
    )

    fixed, logs = journal_finalizer._phase_d_revision_surface_notes(paper, tmp_path)

    assert tension not in journal_finalizer._section_body(fixed, "Abstract")
    assert tension in journal_finalizer._section_body(fixed, "Discussion")
    assert "not evidence that mechanistic content is absent" in fixed
    assert "## Quantitative Evidence Index" in fixed
    assert "maps to the Boundary-Condition Matrix" in fixed
    asks = journal_finalizer.revision_coverage.revision_asks(feedback)
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(fixed, asks) == []
    assert logs and "tension_section_placement" in logs[0].detail
    assert "mechanistic_content_framing" in logs[0].detail


def test_influenza_revision_adds_verified_pmid_and_authoritative_tally_notes(
    tmp_path: Path, monkeypatch,
) -> None:
    feedback = (
        "Reconcile the internal count discrepancies in the Conclusion and report a single "
        "authoritative outcome-class tally with explicit numerator definitions.; Resolve PMID "
        "accuracy for every bundle entry; flag any PMID that cannot be verified and either correct it or remove the source."
    )
    rows = [
        {"receipt_id": "PMC1_a", "source_pmid": "12345678", "source_title": "Trial A",
         "source_doi": "10.1000/a", "effect_direction": "positive",
         "outcome_class": "cardiometabolic"},
        {"receipt_id": "PMC2_b", "source_pmid": "23456789", "source_title": "Trial B",
         "source_doi": "10.1000/b", "effect_direction": "null",
         "outcome_class": "contextual_other"},
    ]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    monkeypatch.setattr("agent.revision_identity.verify_pmid_rows", lambda _rows: {
        "provider": "ncbi_pubmed", "entries": 2, "declared": 2, "verified": 2,
        "without_pmid": 0, "issues": [], "status": "verified", "passed": True,
        "input_fingerprint": pmid_rows_fingerprint(_rows), "checked_at": time.time(),
    })
    paper = (
        "## Methods\n\nSource methods.\n\n## Key Findings\n\nPrior synthesis.\n\n"
        "## Conclusion\n\nEffect directions are positive (n=1) and null (n=1).\n"
    )

    fixed, logs = journal_finalizer._phase_d_revision_surface_notes(paper, tmp_path)
    asks = journal_finalizer.revision_coverage.revision_asks(feedback)

    assert "verified=2/2; unverifiable=0" in journal_finalizer._section_body(fixed, "Methods")
    conclusion = journal_finalizer._section_body(fixed, "Conclusion")
    assert "Admission and direction-tally reconciliation:" not in conclusion
    assert "Authoritative outcome-class tally: n=2" in conclusion
    assert "cardiometabolic=1; contextual other=1" in conclusion
    assert "numerator for each category in this tally" in conclusion
    assert "effect_direction" not in fixed
    audit = json.loads((tmp_path / "source_identifier_verification.json").read_text())
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == []
    assert logs and "pmid_identity_verification" in logs[0].detail


def test_pmid_revision_retries_a_transient_provider_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    feedback = "Resolve PMID accuracy for every bundle entry; flag any PMID that cannot be verified."
    rows = [{"receipt_id": "PMC1_a", "source_pmid": "12345678", "source_title": "Trial A"}]
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"feedback": feedback}))
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    audit_path = tmp_path / "source_identifier_verification.json"
    audit_path.write_text(json.dumps({
        "provider": "ncbi_pubmed", "entries": 1, "declared": 1, "verified": 0,
        "passed": False, "status": "provider_unavailable",
    }))
    calls = 0

    def verify(_rows: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "provider": "ncbi_pubmed", "entries": 1, "declared": 1, "verified": 1,
            "without_pmid": 0, "issues": [], "status": "verified", "passed": True,
            "input_fingerprint": pmid_rows_fingerprint(_rows), "checked_at": time.time(),
        }

    monkeypatch.setattr("agent.revision_identity.verify_pmid_rows", verify)

    fixed, _logs = journal_finalizer._phase_d_revision_surface_notes(
        "## Methods\n\nSource methods.\n\n## Conclusion\n\nBounded conclusion.\n", tmp_path,
    )
    journal_finalizer._phase_d_revision_surface_notes(fixed, tmp_path)

    assert "verified=1/1; unverifiable=0" in fixed
    assert json.loads(audit_path.read_text())["status"] == "verified"
    assert calls == 1


def test_revision_surface_notes_proactively_repair_major_claim_trace(tmp_path: Path) -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "10/20 claims are exactly traceable (required 16)."
    )
    rows = [
        {
            "receipt_id": f"r{i}",
            "citation_token": f"Study{i} 2025",
            "source_title": f"Study {i}",
            "source_doi": f"10.1000/study.{i}",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 20 - i,
            "endpoints": [f"Outcome {i}"],
            "thesis_text": (
                f"Source excerpts: Outcome {i} decreased by {i}% after treatment."
            ),
        }
        for i in range(1, 21)
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": ask,
        "required_revisions": [ask],
    }))
    paper = (
        "## Results\n\n"
        + "\n\n".join(
            f"Study{i} 2025 reported bounded manuscript finding {i}."
            for i in range(1, 21)
        )
        + "\n\n"
        "## References\n\n- Study1 2025.\n"
    )

    fixed, logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert any("major_claim_trace" in entry.detail for entry in logs)
    assert "## Major Claim Trace" not in fixed
    assert fixed.count("[exact source: https://doi.org/") >= len(rows)
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, [ask], evidence_rows=rows,
    ) == []
    assert journal_finalizer._phase_d_revision_surface_notes(
        fixed, tmp_path, proactive=True,
    ) == (fixed, [])


def test_run_text_phases_repairs_trace_after_terminal_text_mutation(
    tmp_path: Path, monkeypatch,
) -> None:
    ask = "Add exact source tokens or evidence spans to major claims; required 2."
    rows = [
        {
            "receipt_id": f"r{i}",
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 3,
            "thesis_text": f"Source excerpts: Retained evidence span {i}.",
        }
        for i in range(1, 3)
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": ask,
        "required_revisions": [ask],
    }))
    paper = (
        "## Results\n\n"
        "Study1 2025 [bundle:1] reported bounded manuscript finding 1.\n\n"
        "Study2 2025 [bundle:2] reported bounded manuscript finding 2.\n\n"
        "## References\n\n- Study1 2025.\n"
    )
    original_split = journal_finalizer._phase_i_split_concatenated_headings

    def corrupt_trace(text: str) -> tuple[str, list[journal_finalizer.FinalizerLogEntry]]:
        fixed, logs = original_split(text)
        fixed = fixed.replace(
            " [exact source: https://doi.org/10.1000/study.1]",
            "",
            1,
        )
        return fixed, logs

    monkeypatch.setattr(
        journal_finalizer,
        "_phase_i_split_concatenated_headings",
        corrupt_trace,
    )

    fixed, _logs = journal_finalizer._run_text_phases(paper, tmp_path)

    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, [ask], evidence_rows=rows,
    ) == []


def test_run_text_phases_scrubs_jargon_added_by_terminal_revision_phase(
    tmp_path: Path, monkeypatch,
) -> None:
    def inject_jargon(
        text: str, _out_dir: Path, *, proactive: bool = False,
    ) -> tuple[str, list[Any]]:
        return (
            text + "\n\nThe sum of n_claims across 3 admitted manifest receipts was reconciled.",
            [],
        )

    monkeypatch.setattr(
        journal_finalizer,
        "_phase_d_revision_surface_notes",
        inject_jargon,
    )

    fixed, _logs = journal_finalizer._run_text_phases(
        "## Results\n\nBounded result.\n",
        tmp_path,
    )

    assert "n_claims" not in fixed
    assert "receipts" not in fixed
    assert "extracted-claim counts" in fixed
    assert "sources" in fixed


def test_multi_issue_reviewer_revision_repairs_and_verifies_all_requirements(tmp_path: Path) -> None:
    required = [
        "Reconcile the Findings Map table counts with the actual source bundle and ensure it lists all sources.",
        "For every exact statistic cited in prose, attach the bundle token and ensure the value matches the source excerpt, or use directional language only.",
        "Expand the Tensions and Gaps section to enumerate at least 3-5 specific cross-source tensions "
        "(e.g., review-level benefit vs direct null endpoints; observational benefit vs mixed uptake trials).",
        "Complete the fragmentary prose sections with an ending mid-sentence and an opening comma.",
        "Either discuss all contextual sources or explicitly state that the map selectively discusses a representative subset, with rationale.",
        "Reconcile the claim that Reviewtrial 2025 'functions as a clinical RCT' with evidence_type='review' and directness='review'.",
        "Ensure the evidence-honesty note is consistently reflected throughout: the Longevity prose presents pooled review estimates with directional confidence.",
    ]
    feedback = "; ".join(required)
    rows: list[dict[str, Any]] = [
        {"receipt_id": "r1", "citation_token": "Reviewa 2025", "outcome_class": "longevity", "effect_direction": "positive", "directness": "review", "evidence_tier": "B1", "thesis_text": "Mortality HR = 0.72 (95% CI: 0.63 to 0.82)."},
        {"receipt_id": "r2", "citation_token": "Nulla 2025", "outcome_class": "longevity", "effect_direction": "null", "directness": "indirect", "evidence_tier": "B2", "endpoints": ["mortality"]},
        {"receipt_id": "r3", "citation_token": "Reviewb 2024", "outcome_class": "longevity", "effect_direction": "positive", "directness": "review", "evidence_tier": "B1", "endpoints": ["mortality"]},
        {"receipt_id": "r4", "citation_token": "Directa 2024", "outcome_class": "contextual_other", "effect_direction": "null", "directness": "direct", "evidence_tier": "A1", "endpoints": ["uptake"]},
        {"receipt_id": "r5", "citation_token": "Directb 2023", "outcome_class": "contextual_other", "effect_direction": "mixed", "directness": "direct", "evidence_tier": "A1", "endpoints": ["uptake"]},
        {"receipt_id": "r6", "citation_token": "Reviewtrial 2025", "outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "review", "evidence_tier": "B2"},
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": feedback, "required_revisions": required,
    }))
    paper = (
        "## Evidence Landscape\n\n" + journal_finalizer._findings_map_section(rows) + "\n\n"
        "## Results\n\n"
        "The corpus contains one randomized placebo-controlled trial (Reviewtrial 2025). "
        "Reviewtrial 2025 functions as a clinical RCT.\n\n"
        "### Longevity Outcomes\n\n"
        "Reviewa 2025 significantly reduced mortality (HR = 0.72; 95% CI: 0.63 to 0.82). "
        "These two sources converge on the same directional finding and anchor the upper bound of the signal.\n\n"
        "### Contextual Other Outcomes\n\n"
        "Only Directa 2024 is discussed here.\n\n"
        "### Frailty Outcomes\n\n"
        ", with a missing opening clause. The retained finding remains bounded.\n\n"
        "## Limitations\n\nEvidence-honesty note: review evidence does not establish causality.\n\n"
        "## References\n\n" + "\n".join(f"- {row['citation_token']}." for row in rows) + "\n"
    )

    fixed, _ = journal_finalizer._phase_d_tensions_and_gaps_breadth(paper, tmp_path)
    fixed, logs = journal_finalizer._phase_d_revision_surface_notes(fixed, tmp_path)
    asks = journal_finalizer.revision_coverage.revision_asks(feedback, required)

    assert "Narrative coverage scope:" in fixed
    assert "representative subset to avoid repetitive source-by-source narration" in fixed
    assert "selected to show direct evidence" not in fixed
    assert "Evidence-type reconciliation:" in fixed
    assert "Outcome evidence-role boundary:" in fixed
    assert "functions as a clinical RCT" not in fixed
    assert fixed.count("surfaced cross-source tension") >= 1
    assert "The manuscript surfaces 3 auditable cross-source tensions" in fixed
    assert journal_finalizer.revision_coverage.deterministic_known_asks(asks) == asks
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []
    assert logs and "fragmentary_prose" in logs[0].detail
    repeated, repeat_logs = journal_finalizer._phase_d_revision_surface_notes(fixed, tmp_path)
    assert repeated == fixed
    assert repeat_logs == []

    unsafe_scope = fixed.replace(
        "Outcome prose discusses a representative subset to avoid repetitive source-by-source narration; "
        "mapped rows omitted from prose remain in the auditable accounting and are not treated as excluded.",
        "Outcome prose discusses a representative subset selected to show direct evidence, major outcome "
        "classes, and contrasting or null signals; mapped rows omitted from prose remain in the auditable accounting.",
    )
    assert asks[4] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        unsafe_scope, asks, evidence_rows=rows,
    )
    repaired_scope, scope_details = journal_finalizer.repair_revision_quality(unsafe_scope, rows, feedback)
    assert "selected to show direct evidence" not in repaired_scope
    assert "representative_subset_scope" in scope_details

    wrong_count = fixed.replace("Longevity n=3 (direction:", "Longevity n=99 (direction:")
    assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        wrong_count, asks, evidence_rows=rows,
    )
    wrong_directions = fixed.replace(
        "Longevity n=3 (direction: null=1; positive=2",
        "Longevity n=3 (direction: null=2; positive=1",
    )
    assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        wrong_directions, asks, evidence_rows=rows,
    )
    wrong_row = fixed.replace(
        "| Longevity | Reviewa 2025 | direction=positive |",
        "| Longevity | Reviewa 2025 | direction=null |",
    )
    assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        wrong_row, asks, evidence_rows=rows,
    )
    wrong_roster = fixed.replace(
        "sources: Nulla 2025; Reviewa 2025; Reviewb 2024",
        "sources: Fake 2025; Reviewa 2025; Reviewb 2024",
    )
    assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        wrong_roster, asks, evidence_rows=rows,
    )
    for old, new in (
        ("| B1 | outcome=Longevity;", "| C9 | outcome=Longevity;"),
        ("outcome=Longevity; direction=positive |", "outcome=Cardiometabolic; direction=positive |"),
        ("finding=qualitative receipt-level finding recorded in the manifest", "finding=unsupported replacement"),
    ):
        altered = fixed.replace(old, new, 1)
        assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
            altered, asks, evidence_rows=rows,
        )
    duplicate_map = fixed.replace("## Results", journal_finalizer._findings_map_section(rows) + "\n\n## Results")
    assert asks[0] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        duplicate_map, asks, evidence_rows=rows,
    )
    wrong_role = fixed.replace(
        "## Limitations",
        "Reviewtrial 2025 is a definitive clinical trial proving benefit.\n\n## Limitations",
    )
    assert asks[5] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        wrong_role, asks, evidence_rows=rows,
    )
    role_bypass = fixed.replace(
        "## Limitations",
        "Reviewtrial 2025 is review-level but remains a definitive clinical RCT proving benefit.\n\n## Limitations",
    )
    assert asks[5] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        role_bypass, asks, evidence_rows=rows,
    )
    clause_bypass = fixed.replace(
        "## Limitations",
        "Reviewtrial 2025 is not counted as a direct RCT, but remains a definitive clinical trial proving benefit.\n\n## Limitations",
    )
    assert asks[5] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        clause_bypass, asks, evidence_rows=rows,
    )
    overclaim = fixed.replace(
        "### Longevity Outcomes",
        "### Longevity Outcomes\n\nThe retained evidence proves longer life.",
    )
    assert asks[6] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        overclaim, asks, evidence_rows=rows,
    )
    causal_bypass = fixed.replace(
        "### Longevity Outcomes",
        "### Longevity Outcomes\n\nThe intervention caused longer life and improved survival.",
    )
    assert asks[6] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        causal_bypass, asks, evidence_rows=rows,
    )
    for claim in (
        "The intervention caused patients to live longer.",
        "The intervention extended lifespan.",
    ):
        variant = fixed.replace("### Longevity Outcomes", f"### Longevity Outcomes\n\n{claim}")
        assert asks[6] in journal_finalizer.revision_coverage.deterministic_unmet_asks(
            variant, asks, evidence_rows=rows,
        )
    bounded = fixed.replace(
        "### Longevity Outcomes",
        "### Longevity Outcomes\n\nNo definitive clinical benefit can be inferred; the synthesis reduced uncertainty.",
    )
    assert asks[6] not in journal_finalizer.revision_coverage.deterministic_unmet_asks(
        bounded, asks, evidence_rows=rows,
    )


def test_structured_revision_feedback_is_not_truncated() -> None:
    required = ["A" * 4100, "Ensure the final requirement is repaired."]

    feedback = journal_finalizer._revision_feedback({"feedback": "truncated", "required_revisions": required})

    assert feedback.endswith(required[-1])
    assert len(feedback) > 4000


def test_exact_stat_revision_rebuilds_existing_findings_map(tmp_path: Path) -> None:
    row = {
        "receipt_id": "r1",
        "citation_token": "Smith 2024",
        "source_title": "Randomized trial",
        "outcome_class": "cardiometabolic",
        "effect_direction": "null",
        "directness": "direct",
        "evidence_tier": "A1",
        "p_values": ["p = 0.01"],
        "thesis_text": "The source excerpt reports no exact statistic.",
        "n_claims": 5,
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [row]}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "Provide the exact bundle token supporting every exact p-value or remove it when not verifiable in the source excerpt."
    }))
    paper = (
        "## Evidence Landscape\n\n### Findings Map\n\n"
        "| Source | Finding |\n| --- | --- |\n| Smith 2024 | p = 0.01 |\n\n"
        "## Results\n\nBounded result.\n"
    )

    fixed, log = journal_finalizer._phase_d_proactive_findings_map(paper, tmp_path)

    assert "p = 0.01" not in fixed
    assert "5 extracted claim(s)" in fixed
    assert log and log[0].rule == "reconcile_source_level_findings_map"


def test_live_reviewer_wording_repairs_existing_manuscript_without_regeneration(tmp_path: Path) -> None:
    asks = [
        "Realign the Longevity narrative with the bundle for Orchard 2021. Either revise the prose to reflect the mixed/subgroup-conditional pattern, or recode the source direction.",
        "Verify and disclose the publication status of all '2026' entries; if these are preprints or in-press records, note that.",
        "Add the missing in-text citations to the References list (Cruz-Jentoft 2019, Ioannidis 2005 if retained), or remove the specific claims that depend on them.",
        "Tighten the Frailty Results to state explicitly that no extractable efficacy numerics are available within the corpus, and therefore no quantitative frailty-prevention claim can be supported.",
    ]
    rows = [
        {"citation_token": "Orchard 2021", "source_title": "Cancer incidence and mortality", "outcome_class": "longevity", "effect_direction": "unclear", "directness": "indirect"},
        {"citation_token": "Tavabi 2021", "source_title": "Frailty prevention trial design", "outcome_class": "frailty", "effect_direction": "null", "directness": "direct"},
        {"citation_token": "Future 2026", "source_title": "Forward-dated trial report", "outcome_class": "frailty", "effect_direction": "unclear", "directness": "indirect", "source_year": 2026, "source_type": "preprint"},
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({"required_revisions": asks}))
    paper = (
        "## Evidence Landscape\n\nBounded landscape.\n\n"
        "## Results\n\nThe corpus contains a strong-but-subgroup-conditional positive signal "
        "(Orchard 2021 [bundle:1]).\n\n### Frailty Outcomes\n\nThe quantitative paragraph is intentionally light.\n\n"
        "## Cross-Domain Synthesis\n\nIoannidis 2005 supplies a surrogate caution. "
        "Cruz-Jentoft 2019 supplies a threshold.\n\n"
        "## References\n\n- **Orchard 2021.** Bundled source.\n"
        "- **Cruz-Jentoft 2019.** External source.\n- **Ioannidis 2005.** External source.\n"
    )

    fixed, logs = journal_finalizer._phase_d_revision_surface_notes(paper, tmp_path)

    assert "strong-but-subgroup-conditional mixed signal" in fixed
    assert "Publication-status/preprint note:" in fixed and "Future 2026" in fixed
    assert "No extractable efficacy numerics are available for Frailty" in fixed
    assert "no quantitative frailty claim is supported" in fixed
    assert "Cruz-Jentoft 2019" not in fixed and "Ioannidis 2005" not in fixed
    assert journal_finalizer.revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []
    assert logs and "no_extractable_outcome_numerics" in logs[0].detail
