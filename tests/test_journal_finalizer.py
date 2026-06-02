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
