from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import apply_patches as ap  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as orch  # type: ignore[import-not-found]  # noqa: E402
from agent.synthesis_schemas import ReceiptSummary, SynthesisSection  # noqa: E402


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def _receipt(rid: str, directness: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid,
        receipt_path=f"runs/{rid}",
        topic="topic",
        thesis_text="bounded evidence",
        spar_verdict="accept_clean",
        n_claims=1,
        n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier="B2",
        directness=directness,
        outcome_class="immune",
        effect_direction="mixed",
        p_values=(),
        population_summary="adults",
    )


def test_restore_rendered_section_headings_from_typed_sections() -> None:
    paper = (
        "## Limitations\n\n"
        "The corpus remains limited.\n\n"
        "The boundary conditions remain unresolved.\n\n"
        "## References\n\n"
        "Ref.\n"
    )
    sections = (
        SynthesisSection(
            name="limitations_full",
            body_md="## Limitations\n\nThe corpus remains limited.\n",
            anchors=(),
        ),
        SynthesisSection(
            name="conclusion",
            body_md=(
                "## Conclusion\n\n"
                "The boundary conditions remain unresolved.\n"
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Conclusion\n\nThe boundary conditions remain unresolved." in out
    assert out.index("## Conclusion") < out.index("## References")


def test_ensure_references_section_restores_from_registry() -> None:
    paper = "## Abstract\n\nText.\n\n## Conclusion\n\nDone.\n"
    registry = {
        "A": SimpleNamespace(
            reference_id="R02",
            body_citation="Smith 2024",
            title="Example title",
            source_journal="Journal",
            source_year=2024,
            source_doi="10.1/example",
            source_pmid="123",
        )
    }
    out, changed = orch._ensure_references_section(paper, registry)
    assert changed
    assert "## References" in out
    assert "- **Smith 2024.** _Example title._ Journal, 2024." in out
    assert "DOI: 10.1/example." in out


def test_organize_run_artifacts_keeps_core_top_level(tmp_path: Path) -> None:
    for name in (
        "full_paper.md",
        "manifest.json",
        "citation_registry.json",
        "full_paper.audit.json",
        "full_paper.certification.json",
        "full_paper.certification.md",
        "full_paper.final_verdict.json",
        "full_paper.review_patch_log.json",
        "biomed_normalization.json",
        "docling_fallback.json",
        "offline_eval_harness.json",
        "quality_methods.json",
        "quality_methods.md",
        "polish_compiler.json",
        "polish_compiler.md",
        "polish_tensions_appendix.json",
        "structured_output_contract.json",
    ):
        (tmp_path / name).write_text("x")
    (tmp_path / "full_paper.pdf").write_text("x")
    (tmp_path / "forest_plots").mkdir()
    moved = orch._organize_run_artifacts(tmp_path)
    assert (tmp_path / "full_paper.md").exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "full_paper.audit.json").exists()
    assert (tmp_path / "debug" / "full_paper.review_patch_log.json").exists()
    assert (tmp_path / "audit" / "full_paper.certification.json").exists()
    assert (tmp_path / "readable" / "full_paper.certification.md").exists()
    assert (tmp_path / "audit" / "quality_methods.json").exists()
    assert (tmp_path / "audit" / "polish_compiler.json").exists()
    assert (tmp_path / "audit" / "polish_tensions_appendix.json").exists()
    assert (tmp_path / "audit" / "biomed_normalization.json").exists()
    assert (tmp_path / "audit" / "docling_fallback.json").exists()
    assert (tmp_path / "audit" / "offline_eval_harness.json").exists()
    assert (tmp_path / "audit" / "structured_output_contract.json").exists()
    assert (tmp_path / "readable" / "polish_compiler.md").exists()
    assert (tmp_path / "plots" / "full_paper.pdf").exists()
    assert (tmp_path / "readable" / "quality_methods.md").exists()
    assert (tmp_path / "plots" / "forest_plots").is_dir()
    assert moved["quality_methods.json"] == "audit/quality_methods.json"


def test_organize_run_artifacts_replaces_stale_sidecar(tmp_path: Path) -> None:
    (tmp_path / "audit").mkdir()
    (tmp_path / "audit" / "publication_score.json").write_text("old")
    (tmp_path / "publication_score.json").write_text("new")
    moved = orch._organize_run_artifacts(tmp_path)
    assert (tmp_path / "audit" / "publication_score.json").read_text() == "new"
    assert not (tmp_path / "publication_score.json").exists()
    assert moved["publication_score.json"] == "audit/publication_score.json"


def test_pre_submit_revise_blocks_submission_without_runtime_failure() -> None:
    gate = SimpleNamespace(passed=True, summary="PASS — evidence bundle clean")
    score = SimpleNamespace(verdict="revise", summary="REVISE - 26/30")
    assert (
        orch._pre_submit_blocker_summary({"gate": gate, "score": score})
        == "PASS — evidence bundle clean; REVISE - 26/30"
    )
    score = SimpleNamespace(verdict="accept", summary="ACCEPT - 30/30")
    assert orch._pre_submit_blocker_summary({"gate": gate, "score": score}) == ""


def test_polish_compiler_gate_allows_optional_tool_skips(monkeypatch, tmp_path) -> None:
    def fake_compile(run_dir: Path) -> dict:
        assert run_dir == tmp_path
        return {
            "passed": True,
            "typst": {"status": "skipped"},
            "sciwrite_lint": {"status": "skipped"},
            "gates": {"raw_pipe_tables": {"status": "passed"}},
        }

    monkeypatch.setattr(orch._polish_compiler, "compile_run", fake_compile)
    monkeypatch.setattr(orch._paper_ir, "compile_run", lambda _run_dir: {"paper_ir": {"schema": "test"}})
    assert orch._run_polish_compiler_gate(tmp_path)["passed"] is True


def test_polish_compiler_gate_writes_paper_ir_sidecars(monkeypatch, tmp_path) -> None:
    (tmp_path / "audit").mkdir()
    (tmp_path / "paper_ir.json").write_text(
        json.dumps({"schema": "stale", "title": "Old Paper"}),
        encoding="utf-8",
    )
    (tmp_path / "full_paper.md").write_text(
        "# Research Synthesis: Demo\n\n"
        "## Abstract\n\nThis paper is bounded.\n\n"
        "## Methods\n\nSources were admitted through deterministic gates.\n\n"
        "## Results\n\n| Study | Result |\n|---|---|\n| A | B |\n\n"
        "## Discussion\n\nThis corpus supports a bounded thesis.\n\n"
        "## Conclusion\n\nFuture work should run a registered trial.\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "demo_topic"}), encoding="utf-8")
    monkeypatch.setattr(orch._polish_compiler, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(orch._polish_compiler, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(orch._polish_compiler, "_run_sciwrite", lambda _paper: {"status": "skipped"})

    report = orch._run_polish_compiler_gate(tmp_path)

    assert report["passed"] is True
    assert report["paper_ir"]["paper_ir"]["schema"] == "researka.paper_ir.v1"
    assert report["paper_quality_score"]["schema"] == "researka.paper_quality_score.v1"
    assert report["public_export_manifest"]["files"]["paper_ir"]["exists"] is True
    paper_ir = json.loads((tmp_path / "paper_ir.json").read_text(encoding="utf-8"))
    score = json.loads((tmp_path / "paper_quality_score.json").read_text(encoding="utf-8"))
    exports = json.loads((tmp_path / "public_export_manifest.json").read_text(encoding="utf-8"))
    assert paper_ir["title"] == "Research Synthesis: Demo"
    assert paper_ir["schema"] == "researka.paper_ir.v1"
    assert paper_ir["tables"] == []
    assert score["schema"] == "researka.paper_quality_score.v1"
    assert exports["files"]["paper_ir"] == {"path": "paper_ir.json", "exists": True}
    for name in ("paper_ir.json", "paper_quality_score.json", "public_export_manifest.json"):
        assert (tmp_path / name).is_file()


def test_polish_compiler_gate_calls_paper_ir_from_production_boundary(monkeypatch, tmp_path) -> None:
    calls: list[Path] = []

    def fake_polish(_run_dir: Path) -> dict:
        return {
            "passed": True,
            "typst": {"status": "skipped"},
            "sciwrite_lint": {"status": "skipped"},
            "gates": {"raw_pipe_tables": {"status": "passed"}},
        }

    def fake_paper_ir(run_dir: Path) -> dict:
        calls.append(run_dir)
        (run_dir / "paper_ir.json").write_text(json.dumps({"schema": "direct"}), encoding="utf-8")
        return {
            "paper_ir": {"schema": "direct"},
            "quality_score": {"schema": "score"},
            "export_manifest": {"schema": "manifest"},
        }

    monkeypatch.setattr(orch._polish_compiler, "compile_run", fake_polish)
    monkeypatch.setattr(orch._paper_ir, "compile_run", fake_paper_ir)

    report = orch._run_polish_compiler_gate(tmp_path)

    assert calls == [tmp_path]
    assert report["paper_ir"]["paper_ir"] == {"schema": "direct"}
    assert report["paper_quality_score"] == {"schema": "score"}
    assert report["public_export_manifest"] == {"schema": "manifest"}
    assert json.loads((tmp_path / "paper_ir.json").read_text(encoding="utf-8")) == {"schema": "direct"}


def test_polish_compiler_gate_overwrites_indirect_paper_ir_artifact(monkeypatch, tmp_path) -> None:
    def fake_polish(run_dir: Path) -> dict:
        (run_dir / "paper_ir.json").write_text(json.dumps({"schema": "indirect"}), encoding="utf-8")
        return {
            "passed": True,
            "typst": {"status": "skipped"},
            "sciwrite_lint": {"status": "skipped"},
            "gates": {"raw_pipe_tables": {"status": "passed"}},
            "paper_ir": {"paper_ir": {"schema": "indirect"}},
        }

    def fake_paper_ir(run_dir: Path) -> dict:
        (run_dir / "paper_ir.json").write_text(json.dumps({"schema": "direct"}), encoding="utf-8")
        return {
            "paper_ir": {"schema": "direct"},
            "quality_score": {"schema": "score"},
            "export_manifest": {"schema": "manifest"},
        }

    monkeypatch.setattr(orch._polish_compiler, "compile_run", fake_polish)
    monkeypatch.setattr(orch._paper_ir, "compile_run", fake_paper_ir)

    report = orch._run_polish_compiler_gate(tmp_path)

    assert report["paper_ir"]["paper_ir"]["schema"] == "direct"
    assert report["paper_quality_score"]["schema"] == "score"
    assert json.loads((tmp_path / "paper_ir.json").read_text(encoding="utf-8")) == {"schema": "direct"}


def test_polish_compiler_gate_failsofts_paper_ir_export(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(orch._polish_compiler, "compile_run", lambda _run_dir: {
        "passed": True,
        "typst": {"status": "skipped"},
        "sciwrite_lint": {"status": "skipped"},
        "gates": {"raw_pipe_tables": {"status": "passed"}},
    })

    def boom(_run_dir: Path) -> dict:
        raise OSError("disk full")

    monkeypatch.setattr(orch._paper_ir, "compile_run", boom)

    report = orch._run_polish_compiler_gate(tmp_path)

    assert report["passed"] is True
    assert report["paper_ir"]["status"] == "failed"
    assert "disk full" in report["paper_ir"]["error"]
    assert "PaperIR export failed" in capsys.readouterr().err


def test_polish_compiler_gate_blocks_deterministic_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(orch._polish_compiler, "compile_run", lambda _run_dir: {
        "passed": False,
        "typst": {"status": "skipped"},
        "sciwrite_lint": {"status": "skipped"},
        "gates": {
            "raw_pipe_tables": {"status": "failed"},
            "top_claim_source_ids": {"status": "skipped"},
        },
    })
    try:
        orch._run_polish_compiler_gate(tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "polish_compiler_failed:raw_pipe_tables"
    else:  # pragma: no cover
        raise AssertionError("expected deterministic polish failure")


def test_section_backstop_counts_model_system_sources_from_receipts() -> None:
    old_manifest = orch._ACTIVE_MANIFEST
    try:
        orch._ACTIVE_MANIFEST = {
            "n_receipts": 1,
            "n_high_confidence_claims_total": 1,
            "n_non_orthogonal_tensions": 0,
            "receipts": [{
                "paper_id": "PMC9539808_dietary_berberine_alleviates_in_largemouth_bass",
                "citation_token": "Gong 2022",
                "directness": "indirect",
                "evidence_tier": "B2",
                "effect_direction": "positive",
                "outcome_class": "cardiometabolic",
                "n_claims": 1,
            }],
        }
        ctx = orch._section_backstop_context()
    finally:
        orch._ACTIVE_MANIFEST = old_manifest
    assert ctx["mechanistic"] == 1
    assert ctx["mech_refs"] == "Gong 2022"


def test_review_heavy_abstraction_note_distinguishes_reference_papers_from_trials() -> None:
    receipts = [_receipt(f"review-{i}", "review") for i in range(5)]
    receipts += [_receipt("indirect-1", "indirect"), _receipt("mechanistic-1", "mechanistic")]
    paper = "## Abstract\n\nThis synthesis maps the evidence.\n\n## Introduction\n\nIntro.\n"

    out = orch._insert_review_heavy_abstraction_note(paper, receipts)

    assert "not 7 independent primary clinical trials" in out
    assert "review-level, preclinical, and other indirect evidence" in out
    assert out.count("Evidence-abstraction note.") == 1
    assert out.index("Evidence-abstraction note.") < out.index("## Introduction")


def test_review_heavy_abstraction_note_is_not_added_to_direct_trial_corpus() -> None:
    receipts = [_receipt(f"direct-{i}", "direct") for i in range(5)]
    paper = "## Abstract\n\nThis synthesis maps the evidence.\n\n## Introduction\n\nIntro.\n"

    assert orch._insert_review_heavy_abstraction_note(paper, receipts) == paper


def test_restore_rendered_section_headings_is_idempotent() -> None:
    paper = (
        "## Conclusion\n\n"
        "The boundary conditions remain unresolved.\n"
    )
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md=paper,
            anchors=(),
        ),
    )
    assert orch._restore_rendered_section_headings(paper, sections) == paper


def test_pop_h2_section_by_prefix_routes_qei_to_supplement() -> None:
    paper = (
        "## Abstract\n\nAbstract body.\n\n"
        "## Quantitative Evidence Index — demo\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Smith 2024 | weight | CR | 2 kg | kg | — |\n\n"
        "## Methods\n\nMethods body.\n"
    )
    main, supplement = orch._pop_h2_section_by_prefix(
        paper, "Quantitative Evidence Index",
    )
    assert "Quantitative Evidence Index" not in main
    assert "## Methods" in main
    assert "## Quantitative Evidence Index — demo" in supplement


def test_pop_h2_section_by_prefix_routes_inferential_bridge_to_supplement() -> None:
    paper = (
        "## Results\n\nResults body.\n\n"
        "## Inferential Bridge\n\n"
        "[D1_inferential_bridge | confidence=medium]\n\n"
        "## Discussion\n\nDiscussion body.\n"
    )
    main, supplement = orch._pop_h2_section_by_prefix(
        paper, "Inferential Bridge",
    )
    assert "Inferential Bridge" not in main
    assert "[D1_inferential_bridge" not in main
    assert "## Discussion" in main
    assert "## Inferential Bridge" in supplement


def test_absent_flagged_patch_resolved_after_final_cleanup() -> None:
    result = ap.PatchResult(
        patch_id="P02",
        patch_type="structure",
        severity="P1",
        decision="flagged",
        reason_for_decision="structure patch flag-only",
        before="8. Results-like prose leaked into Methods.",
        after="",
    )
    clean_paper = "## Methods\n\nDeterministic Methods only.\n"
    resolved = orch._resolve_absent_flagged_patches([result], clean_paper)
    assert resolved[0].decision == "applied"
    assert "FINAL-CLEANUP-RESOLVED" in resolved[0].reason_for_decision


def test_absent_rejected_patch_resolved_after_final_cleanup() -> None:
    result = ap.PatchResult(
        patch_id="P07",
        patch_type="formatting",
        severity="P1",
        decision="rejected",
        reason_for_decision="truncated patch contract",
        before="DOI: 10.1007/example.",
        after="",
    )
    clean_paper = "## What This Synthesis Adds\n\nClean prose only.\n"
    resolved = orch._resolve_absent_flagged_patches([result], clean_paper)
    assert resolved[0].decision == "applied"
    assert "FINAL-CLEANUP-RESOLVED" in resolved[0].reason_for_decision


def test_restore_cross_domain_heading_by_structural_boundary() -> None:
    paper = (
        "## Results\n\n"
        "### Immune Outcomes\n\n"
        "Metformin changed inflammatory markers.\n\n"
        " _Cited: `A 2020`_\n\n"
        "A cross-domain tension concerns immune signals that do not "
        "translate into functional improvement.\n\n"
        " _Cited: `A 2020`, `B 2021`_\n\n"
        "## Discussion\n\n"
        "Interpretation follows.\n"
    )
    sections = (
        SynthesisSection(
            name="cross_domain_synthesis",
            body_md=(
                "## Cross-Domain Synthesis\n\n"
                "The original anchor was revised by review."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Cross-Domain Synthesis\n\nA cross-domain tension" in out
    assert out.index("## Cross-Domain Synthesis") < out.index("## Discussion")


def test_restore_conclusion_heading_after_limitations_citations() -> None:
    paper = (
        "## Limitations\n\n"
        "The corpus remains limited.\n\n"
        " _Cited: `A 2020`_\n\n"
        "The synthesis therefore remains conditional.\n\n"
        "## Structured Evidence Tables\n\n"
        "Table body.\n"
    )
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md=(
                "## Conclusion\n\n"
                "The original anchor was revised by review."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Conclusion\n\nThe synthesis therefore remains conditional." in out
    assert out.index("## Conclusion") < out.index("## Structured Evidence Tables")


def test_public_evidence_snapshot_stays_in_body_without_raw_tables() -> None:
    paper = "## Conclusion\n\nThe synthesis remains bounded."
    tables = "## Evidence Snapshot\n\n- Study A; N=n=120; p=0.01.\n"
    out = orch._append_structured_tables_to_public_body(paper, tables)
    assert "## Evidence Snapshot" in out
    assert "|---|" not in out
    assert out.index("## Conclusion") < out.index("## Evidence Snapshot")


def test_restore_required_section_body_when_post_processing_strips_depth() -> None:
    paper = (
        "## Results\n\n"
        f"{_words(500)}\n\n"
        "## Cross-Domain Synthesis\n\n"
        "Too short.\n\n"
        "## Discussion\n\n"
        f"{_words(800)}\n"
    )
    full_cross_domain = (
        "## Cross-Domain Synthesis\n\n"
        f"{_words(850)}\n"
    )
    sections = (
        SynthesisSection(
            name="cross_domain_synthesis",
            body_md=full_cross_domain,
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    assert "Too short." not in out
    match = orch._rendered_section_match(out, "## Cross-Domain Synthesis")
    assert match is not None
    assert orch._word_count(match.group(1)) >= 850
    assert "compiled from" not in out
    assert "compiler" not in out
    assert "word849" in out


def test_restore_required_section_body_does_not_reintroduce_unsafe_source() -> None:
    paper = "## Introduction\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="introduction",
            body_md=(
                "## Introduction\n\n"
                "Unsafe numeric source-context sentence 5 mg."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    assert "Unsafe numeric source-context sentence" not in out
    assert "compiled from" not in out
    assert "compiler" not in out
    assert "direct clinical evidence" in out
    match = orch._rendered_section_match(out, "## Introduction")
    assert match is not None
    assert orch._word_count(match.group(1)) >= 400


def test_restore_required_section_body_compiles_safe_fallback() -> None:
    paper = "## Conclusion\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md="## Conclusion\n\nStill short.\n",
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    match = orch._rendered_section_match(out, "## Conclusion")
    assert match is not None
    assert orch._word_count(match.group(1)) >= 250
    assert orch._word_count(match.group(1).split("\n\n", 1)[0]) >= 250
    assert "Too short." not in out
    assert "compiled from" not in out
    assert "compiler" not in out
    assert "final interpretation is deliberately tiered" in out
    assert "receipt-bound synthesis" not in out


def test_restore_public_surface_floors_without_typed_sections() -> None:
    paper = (
        "## Abstract\n\n" + _words(160) + "\n\n"
        "## Introduction\n\nToo short.\n\n"
        "## Background\n\n" + _words(320) + "\n\n"
        "## Methods\n\n" + _words(320) + "\n\n"
        "## Results\n\n" + _words(520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + _words(870) + "\n\n"
        "## Discussion\n\n" + _words(820) + "\n\n"
        "## Limitations\n\n" + _words(260) + "\n\n"
        "## Conclusion\n\n" + _words(260) + "\n"
    )
    out, log = orch._restore_public_surface_floors(paper)
    assert log == [{
        "fix_type": "surface_floor_backstop",
        "section": "Introduction",
        "reason": "replace_short_section",
    }]
    match = orch._rendered_section_match(out, "## Introduction")
    assert match is not None
    body = match.group(1)
    assert "Too short." not in body
    assert orch._word_count(body) >= 400


def test_restore_public_surface_floors_replaces_overlong_abstract() -> None:
    paper = (
        "## Abstract\n\n" + _words(330) + "\n\n"
        "## Introduction\n\n" + _words(420) + "\n\n"
        "## Background\n\n" + _words(320) + "\n\n"
        "## Methods\n\n" + _words(320) + "\n\n"
        "## Results\n\n" + _words(520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + _words(870) + "\n\n"
        "## Discussion\n\n" + _words(820) + "\n\n"
        "## Limitations\n\n" + _words(260) + "\n\n"
        "## Conclusion\n\n" + _words(260) + "\n"
    )

    out, log = orch._restore_public_surface_floors(paper)

    assert log == [{
        "fix_type": "surface_floor_backstop",
        "section": "Abstract",
        "reason": "replace_long_section",
    }]
    match = orch._rendered_section_match(out, "## Abstract")
    assert match is not None
    assert 150 <= orch._word_count(match.group(1)) <= 300


def test_restore_public_surface_floors_respects_thin_review_type() -> None:
    paper = (
        "## Abstract\n\n" + _words(120) + "\n\n"
        "## Methods\n\n" + _words(220) + "\n\n"
        "## Results\n\n" + _words(220) + "\n\n"
        "## Limitations\n\n" + _words(100) + "\n\n"
        "## Conclusion\n\n" + _words(100) + "\n"
    )
    out, log = orch._restore_public_surface_floors(paper, review_type="thin_corpus_brief")
    assert log == []
    assert "## Introduction" not in out
    assert "## Cross-Domain Synthesis" not in out
    assert "## Discussion" not in out


def test_abstract_claim_strength_repair_runs_before_gate() -> None:
    paper = (
        "# Research Synthesis\n\n"
        "## Abstract\n\n"
        "Robust signals demonstrated in preclinical models justify further targeted testing.\n\n"
        "## Methods\n\n" + _words(320) + "\n\n"
        "## Results\n\n" + _words(520) + "\n\n"
        "## Limitations\n\n" + _words(260) + "\n\n"
        "## Conclusion\n\n" + _words(260) + "\n\n"
        "## References\n\nRef.\n"
    )

    out, changed = orch._repair_abstract_claim_strength_before_gate(paper)

    assert changed is True
    assert "context-dependent signals" in out
    assert "suggested by preclinical models" in out
    assert "can motivate further targeted testing" in out


def test_abstract_claim_strength_repair_records_pre_gate_log() -> None:
    paper = (
        "## Abstract\n\n"
        "Robust signals demonstrated in preclinical models justify further targeted testing.\n\n"
        "## Methods\n\nMethods.\n"
    )
    log: list[dict[str, str]] = []

    out = orch._apply_abstract_claim_strength_repair(paper, log)

    assert "context-dependent signals" in out
    assert log == [{"fix_type": "abstract_claim_strength_pre_gate"}]
    out2 = orch._apply_abstract_claim_strength_repair(out, log)
    assert out2 == out
    assert log == [{"fix_type": "abstract_claim_strength_pre_gate"}]


def test_stage_5c_repairs_abstract_before_surface_gate() -> None:
    source = Path(orch.__file__).read_text(encoding="utf-8")
    stage = source.split("# Stage 5c: paper-quality pre-submit gate.", 1)[1]
    assert (
        stage.index("_apply_abstract_claim_strength_repair")
        < stage.index("evaluate_journal_surface")
        < stage.index("write_final_quality_gates")
    )


def test_restore_required_section_body_can_refuse_dirty_typed_restore() -> None:
    paper = "## Results\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="results",
            body_md="## Results\n\n" + _words(500),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(
        paper, sections, prefer_typed_sections=False,
    )
    match = orch._rendered_section_match(out, "## Results")
    assert match is not None
    body = match.group(1)
    assert "word499" not in body
    assert "study-level summaries" in body
    assert orch._word_count(body) >= 500


def test_restore_contract_collapses_consecutive_qei_headings() -> None:
    paper = (
        "## Quantitative Evidence Index — Urolithin A\n\n"
        "## Quantitative Evidence Index — urolithin_a\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Acevedo 2025 | muscle strength | ua | 57% | % | — |\n"
    )
    out = orch._restore_rendered_section_contract(paper, ())
    assert out.count("## Quantitative Evidence Index") == 1
    assert "## Quantitative Evidence Index — Urolithin A" in out
    assert "57%" in out


def test_public_section_backstop_covers_abstract() -> None:
    md = orch._compile_public_section_backstop("Abstract", 150)
    assert md.startswith("## Abstract")
    assert orch._word_count(md) >= 150


def test_public_section_backstop_bounds_no_positive_abstract_profile() -> None:
    old_manifest = orch._ACTIVE_MANIFEST
    try:
        orch._ACTIVE_MANIFEST = {
            "n_receipts": 1,
            "n_high_confidence_claims_total": 8,
            "n_non_orthogonal_tensions": 2,
            "receipts": [{
                "directness": "indirect",
                "effect_direction": "null",
                "outcome_class": "frailty",
                "citation_token": "Example 2025",
            }],
        }
        md = orch._compile_public_section_backstop("Abstract", 150)
    finally:
        orch._ACTIVE_MANIFEST = old_manifest

    assert "Positive study-level signals concentrate in no dominant outcome class" not in md
    assert "mechanistic plausibility" not in md
    assert "No single positive outcome class dominates the retained corpus" in md
    assert "the retained clinical and adjacent evidence profile defines the scope" in md


def test_public_section_backstop_covers_results_without_duplicate_paragraphs() -> None:
    md = orch._compile_public_section_backstop("Results", 500)
    body = md.split("\n\n", 1)[1]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    assert orch._word_count(body) >= 500
    assert len(paragraphs) == len(set(paragraphs))


def test_results_summary_table_is_manifest_driven_and_idempotent() -> None:
    paper = "## Results\n\n### Cardiometabolic Outcomes\n\nFindings.\n"
    manifest = {
        "receipts": [
            {
                "outcome_class": "cardiometabolic",
                "effect_direction": "positive",
                "directness": "direct",
                "n_claims": 4,
            },
            {
                "outcome_class": "cardiometabolic",
                "effect_direction": "null",
                "directness": "indirect",
                "n_claims": 3,
            },
            {
                "outcome_class": "muscle_function",
                "effect_direction": "negative",
                "directness": "direct",
                "n_claims": 2,
            },
        ],
    }
    out, inserted = orch._ensure_results_summary_table(paper, manifest)
    assert inserted is True
    assert "### Results Summary" in out
    assert "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |" not in out
    assert "|---|" not in out
    assert "- Cardiometabolic: n=2; claims=7; benefit signal in 1/2 sources" in out
    assert "- Muscle Function: n=1; claims=2; adverse or limiting signal in 1/1 sources" in out
    out2, inserted2 = orch._ensure_results_summary_table(out, manifest)
    assert inserted2 is False
    assert out2 == out


def test_results_summary_treats_null_as_unadjudicated_not_negative() -> None:
    paper = "## Results\n\nBody.\n"
    manifest = {"receipts": [
        {"outcome_class": "skeletal_fracture_bone", "effect_direction": "null", "directness": "review", "n_claims": 100},
        {"outcome_class": "skeletal_fracture_bone", "effect_direction": "null", "directness": "review", "n_claims": 42},
    ]}
    out, inserted = orch._ensure_results_summary_table(paper, manifest)
    assert inserted is True
    assert "no extracted directional signal in 2/2 sources" in out
    assert "directness: 2 review" in out
    assert "null signal in 2/2 sources" not in out


def test_canonical_rct_topic_pack_override_wins_before_abstract_inference() -> None:
    old_pack = orch._TOPIC_PACK
    try:
        orch._TOPIC_PACK = cast(Any, SimpleNamespace(canonical_rct_paper_ids=("Depommier",)))
        tier, directness = orch._classify_paper_tier(
            "Depommier_2019_akkermansia",
            1,
            {
                "title": "Akkermansia abundance observational cohort",
                "abstract": "This observational cohort associated abundance with biomarkers.",
            },
        )
    finally:
        orch._TOPIC_PACK = old_pack
    assert (tier, directness) == ("A1", "direct")
