"""Slice 18 regression tests — three reviewer-named polish fixes plus
the accountability-aware readiness contract.

Stdlib-only, no LLM. Covers:
  1. `_lowercase_first_letter` — joins Phase B prepended lane qualifier
     into a natural sentence ("In animal/preclinical evidence, the ..."
     not "...The...") and PRESERVES acronyms (RCT, ATP).
  2. Phase E.3 `_soften` — "We propose" → "We operationalize" preserves
     uppercase; "we propose" → "we operationalize" preserves lowercase.
  3. `_accountability_text` — researka-native vs legacy-journal-submission
     emit different prose; default is researka-native.
  4. Phase G `_phase_g_refresh_sidecars` — refreshes stale verdict
     surface state + rebuilds readiness contract item 13 from manifest
     accountability_model.

Universal — no topic-specific fixtures; uses synthetic minimal sidecars.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from agent.journal_finalizer import (  # type: ignore[import-not-found]
    _additive_screening_flow_note,
    _lowercase_first_letter,
    _phase_a_methods_replace,
    _phase_c_terminology,
    _phase_g_refresh_sidecars,
    _refresh_final_consistency_sidecar,
    _refresh_pre_submit_gate,
    _refresh_readiness_contract_items,
)
from agent.methods_pack import (  # type: ignore[import-not-found]
    REQUIRED_METHODS_H3_MARKERS,
    _accountability_text,
    build_methods_pack,
    render_methods_md,
    write_methods_pack,
)


# ---- Fix 1: _lowercase_first_letter ---------------------------------------


def test_lowercase_first_letter_lowercases_normal_word() -> None:
    assert _lowercase_first_letter("The corpus shows ...") == "the corpus shows ..."


def test_lowercase_first_letter_preserves_acronyms() -> None:
    # RCT, ATP, MTOR — all-caps multi-char words stay capitalized.
    assert _lowercase_first_letter("RCT data suggests ...") == "RCT data suggests ..."
    assert _lowercase_first_letter("ATP levels rose.") == "ATP levels rose."


def test_lowercase_first_letter_keeps_leading_whitespace() -> None:
    assert _lowercase_first_letter("  The mice ...") == "  the mice ..."


def test_lowercase_first_letter_handles_non_alpha_start() -> None:
    assert _lowercase_first_letter("42% of ...") == "42% of ..."
    assert _lowercase_first_letter("") == ""


# ---- Fix 3: accountability-aware Methods prose ----------------------------


def test_accountability_text_default_is_researka_native() -> None:
    text = _accountability_text("")
    assert "researka_agent_certified" in text
    assert "machine-verifiable" in text
    assert "human_signoff.json" not in text


def test_accountability_text_legacy_cites_human_signoff() -> None:
    text = _accountability_text("legacy_journal_submission")
    assert "human_signoff.json" in text
    assert "AI assistance does not transfer authorship" in text


def test_accountability_text_unknown_token_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown accountability model"):
        _accountability_text("nonsense_value")


def test_methods_pack_h3_markers_no_longer_say_human_accountability() -> None:
    # Slice 18: heading was renamed; constant must match the renderer.
    assert "### Accountability" in REQUIRED_METHODS_H3_MARKERS
    assert "### Human accountability" not in REQUIRED_METHODS_H3_MARKERS


def test_phase_c_preserves_clinical_scope_without_inventing_hard_endpoints() -> None:
    original = (
        "The paper has no direct clinical evidence and a direct clinical gap. "
        "Direct clinical evidence carries the highest weight."
    )
    out, log = _phase_c_terminology(original)
    assert out == original
    assert "hard-endpoint" not in out
    assert not log


def test_methods_pack_render_matches_required_markers() -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10, n_screened=10, n_included=8, n_rejected=2,
        outcome_classes=("primary_outcome",),
        accountability_model="researka_agent_certified",
    )
    md = render_methods_md(pack, submission_id="run-0000")
    for marker in REQUIRED_METHODS_H3_MARKERS:
        assert marker in md, f"renderer missing required H3: {marker!r}"


@pytest.mark.parametrize("topic,question", [
    ("resveratrol_measurement_methods", "How are exposure and response endpoints described in the retained adult human records?"),
    ("resistance_training", "What do randomized training comparisons show about strength?"),
    ("metformin", "How do clinical and mechanistic findings differ?"),
])
def test_methods_uses_declared_analysis_scope_without_inventing_screening(topic, question):
    pack = build_methods_pack(
        review_type="curated_evidence_map", topic=topic, research_question=question,
        corpus_search_queries=("original query",), n_retrieved=None, n_screened=None,
        n_included=8, n_rejected=None, outcome_classes=("primary_outcome",),
    )
    md = render_methods_md(pack, submission_id="scope-test")
    assert question in md
    assert "Sources whose primary content addresses" not in md
    assert "prospectively" in pack.eligibility_criteria[0]
    assert pack.search_strings == ("original query",)
    assert pack.screening_flow == {"n_included": 8}


def test_review_manuscript_receives_the_persisted_methods_record(tmp_path: Path) -> None:
    _write_review_methods = importlib.import_module("scripts.run_v06_synthesis")._write_review_methods
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis", topic="example_topic",
        corpus_search_queries=("example frozen query",),
        n_retrieved=120, n_screened=None, n_included=8, n_rejected=None,
        outcome_classes=("primary_outcome",),
        source_inventory=(("PubMed", "succeeded"),), search_dates_iso="2026-09-05",
    )
    paper = tmp_path / "full_paper.md"
    paper.write_text("## Introduction\n\nPreserved introduction.\n\n## Methods\n\nStale methods.\n\n## Results\n\nPreserved results.\n")
    rendered = _write_review_methods(paper, pack)
    written = paper.read_text()
    assert rendered.strip() in written
    assert "example frozen query" in written and "PubMed" in written
    assert "Stale methods" not in written and written.count("## Methods\n") == 1
    assert "Preserved introduction." in written and "Preserved results." in written
    assert json.loads((tmp_path / "methods_pack.json").read_text())["screening_flow"] == {
        "n_retrieved": 120, "n_included": 8,
    }
    assert _write_review_methods(paper, pack) == rendered
    assert paper.read_text() == written


def test_methods_pack_defines_direct_indirect_and_review_evidence() -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10, n_screened=10, n_included=8, n_rejected=2,
        outcome_classes=("primary_outcome",),
        accountability_model="researka_agent_certified",
    )

    md = render_methods_md(pack, submission_id="run-0000")

    assert "### Directness coding criteria" in md
    assert "coded as direct only when it tests the topic" in md
    assert "does not establish clinical benefit" in md
    assert "coded as indirect" in md
    assert "review-level evidence" in md


def test_finalizer_methods_replacement_preserves_directness_criteria(
    tmp_path: Path,
) -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10, n_screened=10, n_included=8, n_rejected=2,
        outcome_classes=("primary_outcome",),
        source_inventory=(("PubMed", "succeeded"),),
        accountability_model="researka_agent_certified",
    )
    write_methods_pack(tmp_path, pack)

    paper = "## Methods\n\nOld methods.\n\n## Results\n\nResults body.\n"
    finalized, log = _phase_a_methods_replace(paper, tmp_path)

    assert "### Directness coding criteria" in finalized
    assert "coded as direct only when it tests the topic" in finalized
    assert "does not establish clinical benefit" in finalized
    assert "Named sources: PubMed (succeeded)" in finalized
    assert "## Results\n\nResults body." in finalized
    assert log and log[0].phase == "A_methods_replace"


def test_methods_pack_dedupes_public_outcome_aliases() -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=3,
        n_screened=3,
        n_included=3,
        n_rejected=0,
        outcome_classes=("immune", "immune_inflammation", "muscle_function"),
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "immune and inflammation, immune and inflammation" not in md
    assert md.count("immune and inflammation") == 1
    assert "muscle function" in md


def test_methods_data_items_carries_source_grounding_disclosure() -> None:
    # Describe source/extraction support without claiming every schema field
    # is populated or downgrading source-proved bundles to metadata-only.
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10, n_screened=10, n_included=8, n_rejected=2,
        outcome_classes=("primary_outcome",),
        accountability_model="researka_agent_certified",
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "traced to source excerpts and structured extraction records" in md
    assert "A schema field does not establish that every source reported it" in md
    assert "limited to reference-level metadata" not in md


def test_methods_default_rob_wording_does_not_overclaim_populated_appraisal() -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10,
        n_screened=10,
        n_included=8,
        n_rejected=2,
        outcome_classes=("primary_outcome",),
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "Per-source risk-of-bias was rated" not in md
    assert "limited to populated `risk_of_bias.json` rows" in md
    assert "risk-of-bias claims require populated assessment records" in md


def test_methods_pack_renders_receipt_admission_funnel() -> None:
    pack = build_methods_pack(
        review_type="evidence_brief",
        topic="aerobic_exercise",
        corpus_search_queries=("aerobic exercise AND aging",),
        n_retrieved=129, n_screened=129, n_included=129, n_rejected=0,
        outcome_classes=("cardiometabolic",),
        receipt_funnel={
            "classified_receipt_candidates": 188,
            "receipt_candidate_union": 339,
            "counts": {
                "admitted_receipts": 129,
                "candidate_no_claims": 9,
                "candidate_none_only": 13,
                "candidate_partial_and_none_only": 120,
                "candidate_partial_only": 4,
                "original_strict_high_confidence_receipts": 5,
            },
        },
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "pre-curated receipt-candidate set" in md
    assert "| Receipt candidate union | 339 |" in md
    assert "| Classified receipt candidates | 188 |" in md
    assert "| No extractable claims | 9 |" in md
    assert "| None-only claim binding | 13 |" in md
    assert "| Mixed partial-or-none claim-binding candidates | 120 |" in md
    assert "| Partial-only claim-binding candidates | 4 |" in md
    assert "not additive exclusion totals" in md
    assert "| Strict high-confidence receipts | 5 |" in md
    assert "| Admitted final receipts | 129 |" in md


def test_methods_exclusion_reasons_do_not_contradict_zero_excluded() -> None:
    """Reviewer-flagged contradiction: the flow reported 0 excluded while the
    'Exclusion reasons' list still enumerated population/duplicate exclusions.
    With no recorded exclusions the section must say so — no phantom reasons —
    while the required H3 marker stays present."""
    pack = build_methods_pack(
        review_type="evidence_brief",
        topic="example_topic",
        corpus_search_queries=("q",),
        n_retrieved=12, n_screened=12, n_included=12, n_rejected=0,
        outcome_classes=("primary_outcome",),
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "### Exclusion reasons" in md
    assert "0 were excluded at full-text review" in md
    assert "Source-level exclusion reasons were not recorded" in md
    assert "Wrong population" not in md
    assert "Duplicate records deduplicated" not in md


def test_methods_counts_do_not_establish_exclusion_reasons() -> None:
    pack = build_methods_pack(
        review_type="evidence_brief",
        topic="example_topic",
        corpus_search_queries=("q",),
        n_retrieved=50, n_screened=50, n_included=12, n_rejected=3,
        outcome_classes=("primary_outcome",),
    )
    md = render_methods_md(pack, submission_id="run-0000")
    assert "3 were excluded at full-text review" in md
    assert "Non-traceable findings" not in md
    assert "Off-topic or ineligible-population" not in md
    assert "Source-level exclusion reasons were not recorded" in md
    assert "No records were excluded" not in md


def test_methods_missing_stage_counts_are_not_admission_counts(tmp_path: Path) -> None:
    pack = build_methods_pack(
        review_type="evidence_brief", topic="example", corpus_search_queries=(),
        n_retrieved=None, n_screened=None, n_included=37, n_rejected=None,
        outcome_classes=("cognitive",),
        receipt_funnel={"counts": {"candidate_no_claims": 0, "admitted_receipts": 37}},
    )
    assert pack.screening_flow == {"n_included": 37, "candidate_no_claims": 0, "admitted_receipts": 37}
    md = render_methods_md(pack, submission_id="revision")
    assert "includes 37 admitted sources" in md
    assert "37 records retrieved" not in md
    assert "37 were screened" not in md
    assert "Recorded stages: none." in md
    write_methods_pack(tmp_path, pack)
    assert "not reconstructable" in _additive_screening_flow_note(tmp_path)
    (tmp_path / "methods_pack.json").write_text(json.dumps({
        "screening_flow": {"n_screened": None, "n_excluded_at_full_text": None},
    }))
    assert "not reconstructable" in _additive_screening_flow_note(tmp_path)


def test_methods_pack_legacy_model_swaps_accountability_prose() -> None:
    pack_researka = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis", topic="example",
        corpus_search_queries=(), n_retrieved=1, n_screened=1,
        n_included=1, n_rejected=0, outcome_classes=("x",),
        accountability_model="researka_agent_certified",
    )
    pack_legacy = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis", topic="example",
        corpus_search_queries=(), n_retrieved=1, n_screened=1,
        n_included=1, n_rejected=0, outcome_classes=("x",),
        accountability_model="legacy_journal_submission",
    )
    assert "human_signoff.json" not in pack_researka.human_accountability
    assert "human_signoff.json" in pack_legacy.human_accountability


# ---- Phase G: sidecar refresh ---------------------------------------------


def _make_run(tmp_path: Path, *, surface_passed: bool,
              accountability_model: str,
              old_contract_name: str,
              artifact_consistency: bool = True) -> Path:
    """Set up a minimal stale-sidecar run dir for Phase G tests."""
    run = tmp_path / "run"
    run.mkdir()
    paper = "# Stub\n\n## References\n\n- Stub 2026.\n"
    (run / "full_paper.md").write_text(paper)
    (run / "submission_package").mkdir()
    (run / "submission_package" / "final_manuscript.md").write_text(paper)
    (run / "manifest.json").write_text(json.dumps({
        "accountability_model": accountability_model,
    }))
    # Authoritative surface report (post-finalizer)
    (run / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": surface_passed,
        "issues": [] if surface_passed else [
            {"code": "STALE", "detail": "kept here for old verdict"},
        ],
    }))
    # Stale verdict — claims the OPPOSITE of the surface report
    (run / "full_paper.final_verdict.json").write_text(json.dumps({
        "verdict": "L4",
        "journal_surface_pass": not surface_passed,
        "journal_surface_issues": [
            "OLD_ISSUE: stale issue from earlier point in run",
        ],
    }))
    (run / "full_paper.consistency.json").write_text("[]")
    # Stale readiness contract — item 13 has the OLD shape
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "result": {"passed": surface_passed, "failures": []},
        "journal_readiness_contract": [
            {"id": 1, "name": "product_tiers", "status": "pass",
             "audit": "ok", "next_action": ""},
            {"id": 13, "name": old_contract_name, "status": "not_ready",
             "audit": "old hardcoded text",
             "next_action": "old next action"},
        ],
    }))
    # Spine artifacts so researka_check passes when needed
    (run / "citation_registry.json").write_text(json.dumps({
        "stub": {"body_citation": "Stub 2026"},
    }))
    if artifact_consistency:
        (run / "artifact_consistency.json").write_text(json.dumps({
            "passed": True,
        }))
    return run


def test_phase_g_refreshes_stale_verdict_surface_state(tmp_path: Path) -> None:
    """Slice 19 update: Phase G now re-evaluates the surface gate against
    the on-disk paper FIRST, then reconciles verdict to match. The stub
    paper `# Stub\n` triggers real surface issues; verdict reconciles to
    the freshly-evaluated state, not the pre-seeded `passed=True`."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    log = _phase_g_refresh_sidecars(run)
    surface = json.loads((run / "full_paper.journal_surface.json").read_text())
    verdict = json.loads((run / "full_paper.final_verdict.json").read_text())
    # After re-eval, verdict must mirror the freshly-evaluated surface.
    assert verdict["journal_surface_pass"] is bool(surface["passed"])
    assert len(verdict["journal_surface_issues"]) == len(surface["issues"])
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules
    assert "refresh_final_verdict_post_finalizer" in rules


def test_refresh_final_consistency_removes_stale_p1_before_verdict(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.md").write_text(
        "# Paper\n\n"
        "## Abstract\n\nBounded synthesis.\n\n"
        "## Introduction\n\nContext overview.\n\n"
        "## Methods\n\nSearch strategy described.\n\n"
        "## Results\n\nFindings remain limited.\n\n"
        "## Discussion\n\nInterpretation stays cautious.\n\n"
        "## References\n\n- Smith 2024."
    )
    (run / "manifest.json").write_text(json.dumps({
        "accountability_model": "researka_agent_certified",
        "n_receipts": 20,
        "n_high_confidence_claims_total": 100,
        "n_non_orthogonal_tensions": 20,
    }))
    (run / "full_paper.audit.json").write_text(json.dumps({
        "p1_pass": True,
        "score_out_of_10": 9.0,
        "checks": [{"name": "Q1", "passed": True}],
    }))
    (run / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": True,
        "issues": [],
    }))
    (run / "full_paper.consistency.json").write_text(json.dumps([{
        "id": "STALE-P1",
        "severity": "P1",
        "issue_type": "stale",
        "auto_fixable": True,
        "evidence": "text removed by finalizer",
        "suggested_fix": "Refresh consistency sidecar.",
    }]))

    assert _refresh_final_consistency_sidecar(run) is True
    refreshed = json.loads((run / "full_paper.consistency.json").read_text())
    assert refreshed == []

    _refresh_post_finalizer_verdict = importlib.import_module(
        "scripts.run_v06_synthesis",
    )._refresh_post_finalizer_verdict

    assert _refresh_post_finalizer_verdict(run) is True
    verdict = json.loads((run / "full_paper.final_verdict.json").read_text())
    assert verdict["verdict"] != "SHIP-BLOCKED"
    assert verdict["stage2_p1"] == 0


def test_phase_g_recomputes_stale_final_status_after_refresh(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "benchmark_runtime.json").write_text(json.dumps({"return_code": 0}))
    (run / "full_paper.audit.json").write_text(json.dumps({
        "n_total": 14, "n_pass": 14, "p1_pass": True,
    }))
    (run / "full_paper.journal_surface.json").write_text(json.dumps({"passed": True, "issues": []}))
    (run / "pre_submit_gate.json").write_text(json.dumps({"result": {"passed": True, "failures": []}}))
    (run / "target_journal_pack.json").write_text(json.dumps({
        "journal": "GeroScience", "declared_in_topic_pack": True,
    }))
    (run / "manifest.json").write_text(json.dumps({"accountability_model": "researka_agent_certified"}))
    (run / "citation_registry.json").write_text("{}")
    (run / "artifact_consistency.json").write_text(json.dumps({"passed": True, "checks": []}))
    (run / "final_status.json").write_text(json.dumps({
        "maturity_level": 2,
        "blocking_reasons": [{"stage": "audit", "code": "audit_check_failed"}],
    }))

    log = _phase_g_refresh_sidecars(run)
    status = json.loads((run / "final_status.json").read_text())
    assert status["dimensions"]["audit_pass"] is True
    assert all(b["stage"] != "audit" for b in status["blocking_reasons"])
    assert status["maturity_level"] >= 3
    assert "refresh_final_status_post_finalizer" in [e.rule for e in log]


def test_phase_g_rebuilds_readiness_contract_for_researka(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="human_signoff",  # stale legacy shape
    )
    log = _phase_g_refresh_sidecars(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    contract = gate["journal_readiness_contract"]
    item_13 = next(i for i in contract if i["id"] == 13)
    assert item_13["name"] == "accountability"
    assert item_13["status"] == "pass"  # spine artifacts present
    rules = [e.rule for e in log]
    # Slice 29 broadened the rule from item-13-only to a full multi-item
    # refresh (items 1/7/9/12/13). The single rule name now covers the
    # whole reconciliation pass.
    assert "reconcile_readiness_contract_items" in rules


def test_readiness_contract_refresh_updates_pre_submit_markdown(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="human_signoff",
    )
    (run / "readable").mkdir()
    (run / "pre_submit_gate.md").write_text("STALE FAIL")
    (run / "readable" / "pre_submit_gate.md").write_text("STALE FAIL")

    assert _refresh_readiness_contract_items(run) > 0

    root_md = (run / "pre_submit_gate.md").read_text()
    readable_md = (run / "readable" / "pre_submit_gate.md").read_text()
    assert "STALE FAIL" not in root_md
    assert "STALE FAIL" not in readable_md
    assert "## Journal Readiness Contract" in readable_md
    assert "| 13 | accountability | pass |" in readable_md


def test_readiness_contract_refresh_updates_stale_markdown_even_when_json_clean(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    gate["journal_readiness_contract"][1].update({
        "name": "accountability",
        "status": "pass",
        "audit": "artifact_consistency passed; citation registry present",
        "advisory": False,
        "blocks_submission": False,
    })
    (run / "pre_submit_gate.json").write_text(json.dumps(gate))
    (run / "readable").mkdir()
    (run / "readable" / "pre_submit_gate.md").write_text("STALE FAIL")

    assert _refresh_readiness_contract_items(run) >= 1
    assert "STALE FAIL" not in (run / "readable" / "pre_submit_gate.md").read_text()


def test_phase_g_writes_consistency_before_readiness_contract(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
        artifact_consistency=False,
    )

    (run / "submission_package" / "final_manuscript.md").write_text("STALE")
    log = _phase_g_refresh_sidecars(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    item_13 = next(i for i in gate["journal_readiness_contract"] if i["id"] == 13)

    assert (run / "artifact_consistency.json").is_file()
    assert (run / "submission_package" / "final_manuscript.md").read_text() == (
        run / "full_paper.md"
    ).read_text()
    assert item_13["name"] == "accountability"
    assert item_13["status"] == "pass"
    assert "refresh_submission_manuscript_post_finalizer" in [e.rule for e in log]
    assert "refresh_artifact_consistency_post_finalizer" in [e.rule for e in log]


def test_refresh_readiness_contract_makes_roadmap_partials_advisory(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    gate["journal_readiness_contract"].extend([
        {
            "id": item_id, "name": name, "status": "partial",
            "advisory": False, "blocks_submission": True,
            "audit": "stale", "next_action": "stale",
        }
        for item_id, name in (
            (3, "domain_pack"),
            (4, "journal_grade_retrieval"),
            (8, "deterministic_abstract_conclusion"),
            (10, "section_repair_loop"),
        )
    ])
    (run / "pre_submit_gate.json").write_text(json.dumps(gate))

    assert _refresh_readiness_contract_items(run) >= 4
    refreshed = json.loads((run / "pre_submit_gate.json").read_text())
    by_id = {row["id"]: row for row in refreshed["journal_readiness_contract"]}
    for item_id in (3, 4, 8, 10):
        assert by_id[item_id]["advisory"] is True
        assert by_id[item_id]["blocks_submission"] is False


def test_refresh_readiness_contract_repairs_feasibility_minimum(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["n_receipts"] = 16
    (run / "manifest.json").write_text(json.dumps(manifest))
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    gate["journal_readiness_contract"].append({
        "id": 2, "name": "feasibility_preflight", "status": "partial",
        "advisory": False, "blocks_submission": True,
        "audit": "receipts=16; recommended>=30; minimum>=12",
        "next_action": "stale",
    })
    (run / "pre_submit_gate.json").write_text(json.dumps(gate))

    assert _refresh_readiness_contract_items(run) >= 1
    refreshed = json.loads((run / "pre_submit_gate.json").read_text())
    item_2 = next(row for row in refreshed["journal_readiness_contract"] if row["id"] == 2)
    assert item_2["status"] == "pass"
    assert item_2["blocks_submission"] is False


def test_phase_g_rebuilds_readiness_contract_for_legacy(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="legacy_journal_submission",
        old_contract_name="accountability",  # stale researka shape
    )
    # Stabilize before signing; changing signed content must invalidate signoff.
    _phase_g_refresh_sidecars(run)
    from agent.human_signoff import HumanSignoff, write as write_human_signoff
    write_human_signoff(run, HumanSignoff(
        author="Test Author",
        reviewed=True,
        evidence_claims_reviewed=True,
        conflicts_declared=True,
        ready_to_submit=True,
        signature="Test Author",
    ))
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    item_13 = next(i for i in gate["journal_readiness_contract"] if i["id"] == 13)
    item_13.update({"name": "accountability", "status": "not_ready", "audit": "stale"})
    (run / "pre_submit_gate.json").write_text(json.dumps(gate))
    _phase_g_refresh_sidecars(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    item_13 = next(
        i for i in gate["journal_readiness_contract"] if i["id"] == 13
    )
    assert item_13["name"] == "human_signoff"
    assert item_13["status"] == "pass"


def test_phase_g_noop_when_already_consistent(tmp_path: Path) -> None:
    """Slice 19 update: Phase G's no-op property is now defined as
    'second call after stabilisation produces no log entries' — the
    first call re-evaluates the surface gate and reconciles verdict,
    leaving the run dir in a fixed-point state. A second invocation
    against that fixed-point state must add no log entries."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    _phase_g_refresh_sidecars(run)  # first call: stabilise
    log = _phase_g_refresh_sidecars(run)  # second call: must be quiet
    assert log == []


def test_refresh_pre_submit_gate_recomputes_numeric_coverage(tmp_path: Path) -> None:
    """When a now-fixed Q2 flips audit_gates_passed False->True, the gate's
    numeric_coverage input must be recomputed from the fresh audit (it is
    audit-derived) — not left at the stale pre-fix value that keeps the gate
    failing. Regression for the References-strip throughput unblock."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.journal_surface.json").write_text(json.dumps({"passed": True, "issues": []}))
    # Fresh audit: Q2 now traces 8/8 (post References-strip) and all gates pass.
    (run / "full_paper.audit.json").write_text(json.dumps({
        "n_total": 14, "n_pass": 14, "p1_pass": True,
        "checks": [{"name": "Q2_numeric_integrity", "passed": True,
                    "detail": "8/8 numerics trace to corpus (100%)"}],
    }))
    # Stale gate: audit_gates_passed False + numeric_coverage 0.9 (pre-fix).
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "inputs": {
            "numeric_coverage": 0.9, "audit_gates_passed": False,
            "journal_surface_passed": False, "citation_registry_complete": True,
            "rob_coverage": 1.0, "grade_coverage": 1.0, "n_tensions": 5,
            "n_receipts": 20, "unresolved_reviewer_p1_count": 0,
            "template_language_blocking": False,
        },
        "result": {"passed": False, "failures": ["numeric_coverage=0.900 < threshold 1.000"]},
    }))
    changed = _refresh_pre_submit_gate(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    assert changed is True
    assert gate["inputs"]["numeric_coverage"] == 1.0
    assert gate["inputs"]["audit_gates_passed"] is True
    assert gate["result"]["passed"] is True


def test_refresh_pre_submit_gate_uses_p1_pass_not_all_green(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.journal_surface.json").write_text(json.dumps({"passed": True, "issues": []}))
    (run / "full_paper.audit.json").write_text(json.dumps({
        "n_total": 14, "n_pass": 13, "p1_pass": True,
        "checks": [{"name": "Q2_numeric_integrity", "passed": True,
                    "detail": "8/8 numerics trace to corpus (100%)"}],
    }))
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "inputs": {
            "numeric_coverage": 1.0, "audit_gates_passed": False,
            "journal_surface_passed": True, "citation_registry_complete": True,
            "rob_coverage": 1.0, "grade_coverage": 1.0, "n_tensions": 5,
            "n_receipts": 20, "unresolved_reviewer_p1_count": 0,
            "template_language_blocking": False,
        },
        "result": {"passed": False, "failures": ["audit_gates_failed"]},
    }))
    assert _refresh_pre_submit_gate(run) is True
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    assert gate["inputs"]["audit_gates_passed"] is True
    assert gate["result"]["passed"] is True


def test_phase_g_reevaluates_surface_gate_on_post_finalizer_paper(
    tmp_path: Path,
) -> None:
    """Slice 19: pipeline writes journal_surface.json against pre-finalizer
    paper; Phase A then swaps in PRISMA-ScR Methods. Phase G must re-run
    the surface gate against the on-disk paper so the sidecar reflects
    the actual final paper state.

    Concrete scenario: pre-seed the surface sidecar as a stale `passed=True
    with 0 issues` from a hypothetical pre-finalizer evaluation. The on-
    disk paper is a stub that the gate WILL find issues with. Phase G's
    re-eval must rewrite the sidecar with the real, non-zero issue count,
    and emit a `reevaluate_journal_surface_post_finalizer` log entry."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    pre_eval = json.loads((run / "full_paper.journal_surface.json").read_text())
    assert pre_eval["passed"] is True and pre_eval["issues"] == []
    log = _phase_g_refresh_sidecars(run)
    post_eval = json.loads((run / "full_paper.journal_surface.json").read_text())
    # Re-eval against `# Stub\n` produces real issues — sidecar updated.
    assert len(post_eval["issues"]) > 0
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules


def test_phase_g_reeval_handles_missing_inputs_gracefully(
    tmp_path: Path,
) -> None:
    """Re-eval must fail-soft when its inputs (evidence_lanes.json,
    citation_registry.json) are missing — the gate should still run with
    empty animal_citations/citation_outcome_map fallbacks."""
    run = tmp_path / "minimal"
    run.mkdir()
    (run / "full_paper.md").write_text("# Minimal\n## Methods\nstub\n")
    (run / "manifest.json").write_text(json.dumps({
        "review_type": "prisma_scr_scoping_synthesis",
        "accountability_model": "researka_agent_certified",
    }))
    log = _phase_g_refresh_sidecars(run)
    # Surface sidecar must now exist (re-eval wrote it).
    assert (run / "full_paper.journal_surface.json").is_file()
    surface = json.loads((run / "full_paper.journal_surface.json").read_text())
    assert "issues" in surface
    # First-call delta is `new_issues - 0` so a log entry is expected.
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules


def test_phase_g_refreshes_pre_submit_gate_when_surface_flips(
    tmp_path: Path,
) -> None:
    """Slice 20: when Phase G's surface re-eval flips journal_surface_pass,
    the cached pre_submit_gate.result must be recomputed so the L3/L4
    ladder responds. Universal — operates on the gate inputs dict + the
    freshly-rewritten surface sidecar.

    Direction tested: pre_submit was passing with stale `surface_passed=
    True`; the re-eval against a thin stub paper produces real surface
    issues, which must propagate to flip pre_submit's result to fail."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.md").write_text("# Stub\n## Methods\nminimal\n")
    (run / "manifest.json").write_text(json.dumps({
        "review_type": "prisma_scr_scoping_synthesis",
        "accountability_model": "researka_agent_certified",
    }))
    # Pre-seed pre_submit_gate as PASSING with stale `surface_passed=True`.
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "inputs": {
            "numeric_coverage": 1.0,
            "audit_gates_passed": True,
            "journal_surface_passed": True,  # stale — re-eval will flip to False
            "citation_registry_complete": True,
            "rob_coverage": 1.0, "grade_coverage": 1.0,
            "n_tensions": 10, "n_receipts": 30,
            "unresolved_reviewer_p1_count": 0,
            "template_language_blocking": False,
        },
        "result": {"passed": True, "failures": [],
                   "warnings": [], "summary": "PASS — stale"},
    }))
    log = _phase_g_refresh_sidecars(run)
    rules = [e.rule for e in log]
    assert "refresh_pre_submit_gate_with_fresh_surface" in rules
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    # Re-eval against stub paper produces surface failures → input flips
    # → pre_submit result must reflect the flip.
    assert gate["inputs"]["journal_surface_passed"] is False
    assert gate["result"]["passed"] is False
    assert "journal_surface_failed" in gate["result"]["failures"]


def test_slice26_gate_qualifier_accepts_everyday_animal_terms() -> None:
    """Slice 26: the journal-surface gate's animal-lane qualifier check
    must accept everyday prose terms ("aged mice", "in cultured cells",
    "senior dogs") — not just the formal taxonomy ("rodent / murine /
    in vivo / canine"). Senolytics audit surfaced ≥5 false-positive
    `evidence_lane` flags because the writer routinely uses "mice" and
    "dogs"; before Slice 26 those silenced no flag."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Murray 2025 studied frailty markers. Similarly, Novais 2021 found "
        "that D+Q treatment improved physical performance in aged mice.\n"
    )
    # Without Slice 26 ("mice" missing from qualifier list), this would
    # flag Novais 2021. With Slice 26 it correctly stays silent.
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Novais 2021"])
    assert msgs == ()


def test_slice26_gate_qualifier_handles_plurals_via_word_boundary() -> None:
    """Slice 26: the regex's `s?` suffix must accept English plurals
    ("equids" → matches "equid"; "rodents" → matches "rodent"). CR
    audit caught the regression case where "obese equids" failed to
    silence the flag after switching from substring to word-boundary."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Bamford 2019, in a model of obese equids, reported "
        "cardiometabolic improvements.\n"
    )
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Bamford 2019"])
    assert msgs == ()


def test_slice26_word_boundary_avoids_false_positive_substring_matches() -> None:
    """Slice 26: switching to word-boundary regex must NOT silence the
    gate on prose that incidentally contains short substrings like
    'rate' (was previously matching the absent 'rat' qualifier via
    pure substring search — actually a non-issue pre-Slice-26 since
    'rat' wasn't in the list, but `cat`/`dog` ARE now and could
    accidentally match 'category'/'doggedly' without the boundary)."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Jones 2024 examined the rate of categorical adverse events in "
        "the dogmatic literature; doggedly tracking outcomes proved "
        "challenging.\n"
    )
    # Even though "rate"/"categorical"/"dogmatic"/"doggedly" each contain
    # an animal qualifier as substring, none should match at word
    # boundary. Jones 2024 must still be flagged when treated as animal.
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Jones 2024"])
    assert len(msgs) == 1
    assert "Jones 2024" in msgs[0]


def test_phase_b_patches_mixed_lane_paragraphs_post_slice27(
    tmp_path: Path,
) -> None:
    """Mixed-lane paragraphs name their animal context exactly once."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
        ],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    # Mixed-lane paragraph: cites the animal source AND a human source.
    # Slice 23 made Phase B skip this; Slice 27 makes Phase B patch it.
    paper = (
        "# Paper\n\n"
        "Some context. Smith 2022 reported a finding; Wilson 2023 confirmed it.\n"
    )
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    assert _unlabeled_animal_citation_issue_messages(
        paper, ["Smith 2022"],
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text != paper
    assert "Smith 2022 provides animal/preclinical context only." in new_text
    assert not new_text.startswith("Animal/preclinical context")
    assert _unlabeled_animal_citation_issue_messages(
        new_text, ["Smith 2022"],
    ) == ()
    assert len(log) == 1
    assert log[0].rule == "animal_preclinical_lead_in"

    rerendered, second_log = _phase_b_lane_qualifier(new_text, run)
    assert rerendered == new_text
    assert second_log == []
    assert rerendered.count("Smith 2022 provides animal/preclinical context only.") == 1


def test_phase_b_still_skips_paragraphs_with_existing_qualifier(
    tmp_path: Path,
) -> None:
    """Slice 27 boundary: even with the aggressive-patch reversion of
    Slice 23, Phase B must still respect an existing qualifier (avoids
    double-prepending). Universal."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
        ],
        "lanes": {"Smith 2022": "animal_preclinical"},
    }))
    paper = (
        "# Paper\n\n"
        "In animal/preclinical evidence, Smith 2022 reported a finding.\n"
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text == paper  # already qualified — no change
    assert log == []


def test_phase_b_preserves_natural_preclinical_qualifier(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {"Smith 2022": "animal_preclinical"},
    }))
    paper = "# Paper\n\nPreclinical evidence from Smith 2022 showed a bounded signal.\n"
    assert _phase_b_lane_qualifier(paper, tmp_path) == (paper, [])


def test_phase_b_replaces_repeated_generic_mixed_qualifiers(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    paper = (
        "# Paper\n\n- Additional corpus sources included animal/preclinical evidence; "
        "Additional corpus sources included animal/preclinical evidence; "
        "Smith 2022 reported context while Wilson 2023 reported human data.\n"
    )

    fixed, _log = _phase_b_lane_qualifier(paper, run)
    assert "Additional corpus sources included" not in fixed
    assert fixed.count("Smith 2022 provides animal/preclinical context only.") == 1
    assert _phase_b_lane_qualifier(fixed, run) == (fixed, [])


def test_phase_b_collapses_bundle_annotated_generated_qualifiers(
    tmp_path: Path,
) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    paper = (
        "# Paper\n\n## Framework Smith 2022 [bundle:9] provides "
        "animal/preclinical context only.\n\n"
        "Smith 2022 [bundle:9] reported context while Wilson 2023 reported "
        "human data. Smith 2022 [bundle:9] provides animal/preclinical "
        "context only. Smith 2022 [bundle:9] provides animal/preclinical "
        "context only.\n"
    )

    fixed, log = _phase_b_lane_qualifier(paper, tmp_path)

    assert len(log) == 1
    assert "## Framework\n" in fixed
    assert fixed.count("provides animal/preclinical context only.") == 1
    assert "Smith 2022 provides animal/preclinical context only." in fixed
    assert _phase_b_lane_qualifier(fixed, tmp_path) == (fixed, [])


def test_phase_b_collapses_role_flagged_bundle_qualifiers(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    marker = "[veterinary; preclinical context only; excluded from human aggregates]"
    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    paper = (
        "# Paper\n\n"
        f"Smith 2022 {marker} [bundle:9] reported context while Wilson 2023 "
        f"reported human data. Smith 2022 {marker} [bundle:9] provides "
        "animal/preclinical context only.\n"
    )

    fixed, _log = _phase_b_lane_qualifier(paper, tmp_path)

    assert fixed.count("provides animal/preclinical context only.") == 1
    assert _phase_b_lane_qualifier(fixed, tmp_path) == (fixed, [])


def test_phase_b_does_not_reclassify_human_segment_on_mixed_line(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Jorgensen 2026", "paper_id": "p2"}],
        "lanes": {
            "Human 2025": "human_interventional",
            "Jorgensen 2026": "animal_preclinical",
        },
    }))
    paper = (
        "# Paper\n\n"
        "- Human 2025 [bundle:1] (outcome=Cardiometabolic; directness=direct); "
        "Jorgensen 2026 [bundle:9] (outcome=Cardiometabolic; directness=indirect).\n"
    )

    fixed, _log = _phase_b_lane_qualifier(paper, tmp_path)

    assert "Human 2025 [bundle:1] (outcome=Cardiometabolic; directness=direct)" in fixed
    assert "Human 2025 [bundle:1] (outcome=animal/preclinical" not in fixed


def test_phase_b_reclassifies_animal_findings_map_row_as_context(
    tmp_path: Path,
) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2026", "paper_id": "p1"}],
        "lanes": {"Smith 2026": "animal_preclinical"},
    }))
    paper = (
        "### Findings Map\n\n"
        "| Outcome class | Source | Direction | Directness | Tier | Evidence role |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Cardiometabolic | Smith 2026: trial in cats | direction=positive "
        "| directness=direct | A1 | outcome=Cardiometabolic; direction=positive |\n"
    )

    fixed, log = _phase_b_lane_qualifier(paper, tmp_path)

    assert len(log) == 1
    assert "| Animal/Preclinical Context (Cardiometabolic) |" in fixed
    assert "directness=animal/preclinical context" in fixed
    assert "outcome=animal/preclinical context (Cardiometabolic)" in fixed
    assert _phase_b_lane_qualifier(fixed, tmp_path) == (
        fixed,
        [],
    )


def test_phase_b_removes_stale_generic_qualifier_without_animal_citation(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier

    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {"Smith 2022": "animal_preclinical"},
    }))
    paper = (
        "# Paper\n\nAdditional corpus sources included animal/preclinical evidence; "
        "human trials reported a bounded null result.\n"
    )

    fixed, log = _phase_b_lane_qualifier(paper, tmp_path)
    assert fixed == "# Paper\n\nHuman trials reported a bounded null result.\n"
    assert len(log) == 1
    assert _phase_b_lane_qualifier(fixed, tmp_path) == (fixed, [])


def test_finalizer_refreshes_stale_human_rct_lane_from_manifest(tmp_path: Path) -> None:
    from agent.journal_finalizer import _phase_b_lane_qualifier, _refresh_evidence_lanes

    row = {
        "receipt_id": "r1",
        "citation_token": "Smith 2024",
        "source_title": "Randomized placebo-controlled trial in older adults",
        "source_venue": "Trials",
        "population_summary": "older adults",
        "thesis_text": "Human participants were randomized; mouse work was background context.",
        "evidence_tier": "A1",
        "directness": "direct",
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [row]}))
    (tmp_path / "evidence_lanes.json").write_text(json.dumps({
        "lanes": {"Smith 2024": "animal_preclinical"},
        "animal_citations": [{"citation": "Smith 2024", "paper_id": "r1"}],
    }))

    assert _refresh_evidence_lanes(tmp_path)
    lanes = json.loads((tmp_path / "evidence_lanes.json").read_text())
    assert lanes["lanes"]["Smith 2024"] == "human_rct"
    assert lanes["animal_citations"] == []
    paper = "# Paper\n\nAnimal/preclinical context (Smith 2024): Smith 2024 reported human trial results.\n"
    fixed, log = _phase_b_lane_qualifier(paper, tmp_path)
    assert fixed == "# Paper\n\nSmith 2024 reported human trial results.\n"
    assert log and _phase_b_lane_qualifier(fixed, tmp_path) == (fixed, [])


def test_run_text_phases_repairs_late_animal_lane_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Later finalizer phases may reintroduce animal-lane citations; the
    terminal Phase B pass must clean those before the surface gate reads the
    manuscript."""
    import agent.journal_finalizer as finalizer
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages

    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [{"citation": "Smith 2022", "paper_id": "p1"}],
        "lanes": {"Smith 2022": "animal_preclinical"},
    }))

    def late_drift(text: str):
        return (
            text
            + "\n\nLate reviewer drift cites Smith 2022 without a lane label.\n",
            [finalizer.FinalizerLogEntry(
                phase="test",
                rule="late_animal_lane_drift",
                n_changes=1,
                detail="inserted synthetic drift",
            )],
        )

    monkeypatch.setattr(finalizer, "_phase_n_declare_discussion_thesis", late_drift)
    fixed, log = finalizer._run_text_phases("# Paper\n\nClean paragraph.\n", run)

    assert _unlabeled_animal_citation_issue_messages(fixed, ["Smith 2022"]) == ()
    assert any(e.rule == "late_animal_lane_drift" for e in log)
    assert any(e.rule == "animal_preclinical_lead_in" for e in log)


def test_phase_b_fires_on_exclusively_animal_lane_paragraph(
    tmp_path: Path,
) -> None:
    """Slice 23: Phase B SHOULD fire when every cited token in the
    paragraph is animal-lane. Confirms precision tightening did not
    regress the positive-trigger case. Slice 26 update: synthetic
    citation tokens MUST NOT contain animal qualifier words (the
    centralised qualifier set now includes "mouse"/"rat" — using
    those as author surnames would make the citation itself match
    the gate's qualifier regex)."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
            {"citation": "Jones 2023", "paper_id": "p2"},
        ],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Jones 2023": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    paper = (
        "# Paper\n\n"
        "Smith 2022 showed an effect that Jones 2023 replicated.\n"
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text != paper
    assert "In animal/preclinical evidence," in new_text
    assert len(log) == 1
    assert log[0].rule == "animal_preclinical_lead_in"


def test_slice31_downshift_to_thin_corpus_brief_on_few_receipts() -> None:
    """Slice 31: when n_receipts < THIN_CORPUS_MIN_RECEIPTS the
    declared review_type is downshifted to `thin_corpus_brief`,
    regardless of what the topic pack declared. Universal."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=2, n_tensions=5,
    ) == "thin_corpus_brief"


def test_slice31_downshift_on_zero_tensions() -> None:
    """Slice 31: n_tensions==0 triggers downshift even when receipt
    count is large (a paper with many receipts but no cross-claim
    tensions is still a thin-evidence artifact)."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis", n_receipts=40, n_tensions=0,
    ) == "thin_corpus_brief"


def test_slice31_no_downshift_when_corpus_is_dense() -> None:
    """Slice 31 boundary: when both receipts and tensions clear the
    thresholds the declared review_type is preserved as-is."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=30, n_tensions=5,
    ) == "systematic_review"
    # None / empty falls back to default, not thin-corpus
    assert downshift_review_type_for_thin_corpus(
        None, n_receipts=30, n_tensions=5,
    ) == "prisma_scr_scoping_synthesis"


def test_slice31_thin_corpus_brief_has_display_label() -> None:
    """Slice 31: the new review_type token must render with a journal-
    conventional display label, like the other 7 types."""
    from agent.review_type import display_label, REVIEW_TYPES
    assert "thin_corpus_brief" in REVIEW_TYPES
    assert display_label("thin_corpus_brief") == "Thin-corpus evidence brief"
    assert display_label("evidence_brief") == "Evidence brief"
    assert display_label("evidence_map") == "Evidence map"


def test_slice38_corpus_sufficiency_verdict_returns_explicit_reasons() -> None:
    """Slice 38: gate decision is structured (verdict + reasons), not
    just derived from a count comparison — auditable + transparent."""
    from agent.review_type import corpus_sufficiency_verdict
    # Sufficient: all dimensions clear
    ok, reasons = corpus_sufficiency_verdict(n_receipts=15, n_tensions=3, n_primary_tier=3)
    assert ok is True
    assert reasons == ()
    # Insufficient on each dimension yields a distinct reason string
    _, r1 = corpus_sufficiency_verdict(n_receipts=2, n_tensions=5, n_primary_tier=5)
    assert any("n_receipts" in r for r in r1)
    _, r2 = corpus_sufficiency_verdict(n_receipts=15, n_tensions=0, n_primary_tier=5)
    assert any("n_tensions" in r for r in r2)
    _, r3 = corpus_sufficiency_verdict(n_receipts=15, n_tensions=3, n_primary_tier=0)
    assert any("n_primary_tier" in r and "primary-tier" in r for r in r3)


def test_slice38_no_primary_tier_downshifts_even_with_high_count() -> None:
    """Slice 38: the case MiMo flagged — many receipts but ZERO primary-
    tier anchors must still downshift to brief. A 65-receipt corpus of
    pure review-tier (B2) evidence becomes an evidence brief."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    # 65 receipts, 12 tensions, but 0 primary-tier (all B2/C review-tier)
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=65, n_tensions=12, n_primary_tier=0,
    ) == "evidence_brief"
    # Same counts with enough primary-tier anchors → full synthesis
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=65, n_tensions=12, n_primary_tier=3,
    ) == "prisma_scr_scoping_synthesis"


def test_slice38_primary_tier_check_optional_for_backcompat() -> None:
    """Slice 38: callers that don't yet pass n_primary_tier (e.g. legacy
    callsites) get the previous count-only behavior — back-compat."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    # Default arg = -1 → primary-tier dimension skipped
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=30, n_tensions=5,
    ) == "systematic_review"
    # Explicit -1 same result
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=30, n_tensions=5, n_primary_tier=-1,
    ) == "systematic_review"


def test_broad_topic_preflight_downshifts_to_evidence_map() -> None:
    from agent.review_type import downshift_review_type_for_thin_corpus, corpus_scope_verdict
    ok, reasons = corpus_scope_verdict(n_receipts=815, n_tensions=188794, n_outcome_classes=9)
    assert ok is False
    assert any("n_receipts" in r for r in reasons)
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=815, n_tensions=188794, n_primary_tier=10, n_outcome_classes=9,
    ) == "evidence_map"


def test_real_topic_metric_routes_keep_flagships_full_and_megatopics_maps() -> None:
    from agent.review_type import downshift_review_type_for_thin_corpus

    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=815, n_tensions=188794, n_primary_tier=38, n_outcome_classes=13,
    ) == "evidence_map"
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=497, n_tensions=73864, n_primary_tier=2, n_outcome_classes=12,
    ) == "evidence_map"
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis",
        n_receipts=171, n_tensions=4684, n_primary_tier=14, n_outcome_classes=12,
    ) == "prisma_scr_scoping_synthesis"


def test_phase_i_splits_concatenated_h3_h2_heading_line() -> None:
    """Slice 30: Phase I splits a line like `### Sub Title## Next H2`
    into two heading lines separated by a blank. Universal Markdown
    structural fix — surfaced by the GLP-1 run where the writer/render
    glued `### Longevity Outcomes## Cross-Domain Synthesis` on one line."""
    from agent.journal_finalizer import _phase_i_split_concatenated_headings
    text = (
        "# Paper\n\n"
        "Some body.\n"
        "### Longevity Outcomes## Cross-Domain Synthesis\n\n"
        "Next paragraph.\n"
    )
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert "### Longevity Outcomes\n\n## Cross-Domain Synthesis" in new_text
    assert log and log[0].n_changes == 1
    assert log[0].rule == "insert_blank_line_between_headings"


def test_phase_i_splits_body_concatenated_h2_heading() -> None:
    """Writer/render glue can attach an H2 directly to prose. Split it
    before structural phases look for required sections."""
    from agent.journal_finalizer import _phase_i_split_concatenated_headings
    text = "# Paper\n\nPrior paragraph.## Discussion\n\nBody.\n"
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert "Prior paragraph.\n\n## Discussion\n\nBody." in new_text
    assert log and log[0].n_changes == 1


def test_phase_i_adds_blank_boundary_before_h2_heading() -> None:
    from agent.journal_finalizer import _phase_i_split_concatenated_headings

    text = "# Paper\n\nPrior paragraph.\n## Discussion\n\nBody.\n"
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert "Prior paragraph.\n\n## Discussion\n\nBody." in new_text
    assert log and log[0].n_changes == 1


def test_phase_i_noop_when_headings_already_separated() -> None:
    """Slice 30: clean Markdown with blank-line separators must pass
    through untouched (Phase I is a structural repair, not a reformat)."""
    from agent.journal_finalizer import _phase_i_split_concatenated_headings
    text = (
        "# Paper\n\n"
        "### Sub A\n\n"
        "Body.\n\n"
        "## Next Section\n\n"
    )
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert new_text == text
    assert log == []


def test_phase_h_substitutes_snake_case_slug_with_display_form(
    tmp_path: Path,
) -> None:
    """Slice 28: Phase H substitutes snake_case slug with display form."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "vitamin_d"}))
    paper = "# Body\n\nvitamin_d trials report mixed outcomes. The vitamin_d field is dense.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert "vitamin_d" not in new_text
    assert "vitamin D" in new_text
    assert len(log) == 1 and log[0].n_changes == 2


def test_phase_h_preserves_backtick_spans(tmp_path: Path) -> None:
    """Slice 28 boundary: file refs inside `` survive."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "glp1"}))
    paper = "# Body\n\nThe glp1 corpus loaded from `topic_packs/glp1.toml`.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert "GLP-1 corpus" in new_text
    assert "`topic_packs/glp1.toml`" in new_text


def test_phase_h_skips_plain_english_slugs(tmp_path: Path) -> None:
    """Slice 28 precision: senolytics/rapamycin slugs skip — substituting
    would damage valid English prose. Gated by _PUBLIC_SLUG_RE.fullmatch."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "senolytics"}))
    paper = "# Body\n\nTwo senolytics trials reported. The senolytics field remains preclinical-heavy.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert new_text == paper
    assert log == []


def test_phase_g_missing_sidecars_is_safe(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    # No sidecars exist — must not raise.
    log = _phase_g_refresh_sidecars(run)
    assert log == []


def test_slice35_render_full_paper_thin_brief_skips_long_form_sections() -> None:
    """Thin briefs retain bounded questions and an optional bridge slot.

    The writer only materializes that slot when reviewer feedback explicitly
    requests an inferential bridge.
    """
    from agent.paper_writer import _THIN_BRIEF_SECTION_ORDER, _FULL_PAPER_SECTION_ORDER
    skipped = set(_FULL_PAPER_SECTION_ORDER) - set(_THIN_BRIEF_SECTION_ORDER)
    assert skipped == {"introduction", "background", "cross_domain_synthesis", "novel_framework", "discussion"}
    assert set(_THIN_BRIEF_SECTION_ORDER) == {
        "abstract",
        "research_question",
        "inferential_bridge",
        "quantitative_results_table",
        "methods",
        "results",
        "limitations_full",
        "conclusion",
        "references_full",
    }


def test_phase_k_routes_immune_paragraph_to_immune_outcomes(tmp_path: Path) -> None:
    """Slice 33: paragraph cite-majority is immune → moves from ###
    Cardiometabolic Outcomes to ### Immune Outcomes. Universal — uses
    receipt outcome_class + citation registry. Surfaced in glp1 run."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "cardiometabolic"},
        {"receipt_id": "p2", "outcome_class": "immune"},
        {"receipt_id": "p3", "outcome_class": "immune"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "Jones 2023"},
        "p3": {"body_citation": "Lee 2024"},
    }))
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Smith 2022 reports weight loss and glycemic improvement.\n\n"
        "Jones 2023 and Lee 2024 found null immune-system effects across the corpus.\n\n"
        "### Immune Outcomes\n\n"
        "Placeholder.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    # The immune paragraph (Jones 2023, Lee 2024) should now live under Immune Outcomes
    immune_idx = new_text.index("### Immune Outcomes")
    cardio_idx = new_text.index("### Cardiometabolic Outcomes")
    assert new_text.index("Jones 2023 and Lee 2024") > immune_idx
    assert new_text.index("Smith 2022 reports") > cardio_idx
    assert new_text.index("Smith 2022 reports") < immune_idx
    assert log and log[0].n_changes == 1
    assert log[0].rule == "route_paragraph_by_citation_class"


def test_phase_k_noop_when_no_misclassified_paragraphs(tmp_path: Path) -> None:
    """Slice 33: paragraphs already in correct sections pass through untouched."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "cardiometabolic"},
        {"receipt_id": "p2", "outcome_class": "immune"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "Jones 2023"},
    }))
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Smith 2022 reports weight loss.\n\n"
        "### Immune Outcomes\n\n"
        "Jones 2023 found null effects.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    assert log == []


def test_phase_k_creates_missing_outcome_section_from_manifest_class(tmp_path: Path) -> None:
    """If the table/body omitted a class, citation ownership still wins.
    Phase K creates the missing section instead of leaving the paragraph
    under a junk-drawer outcome."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "contextual_other"},
        {"receipt_id": "p2", "outcome_class": "deficiency_prevalence"},
        {"receipt_id": "p3", "outcome_class": "deficiency_prevalence"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "He 2017"},
        "p3": {"body_citation": "Ilyasova 2018"},
    }))
    text = (
        "## Results\n\n"
        "### Contextual Other Outcomes\n\n"
        "Smith 2022 describes broad context. He 2017 and Ilyasova 2018 "
        "report status-linked biomarker evidence.\n\n"
        "### Immune Outcomes\n\n"
        "Jones 2020 reports immune findings.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    assert "### Deficiency Prevalence Outcomes" in new_text
    assert new_text.index("He 2017 and Ilyasova 2018") > new_text.index(
        "### Deficiency Prevalence Outcomes",
    )
    contextual = new_text.split("### Contextual Other Outcomes", 1)[1].split("###", 1)[0]
    assert "Smith 2022 describes broad context" in contextual
    assert "He 2017" not in contextual
    assert log and log[0].n_changes == 1


def test_phase_k_backfills_empty_outcome_section_after_routing(tmp_path: Path) -> None:
    """When all prose moves out of an outcome heading, keep the heading
    non-empty so the public Results contract remains parseable."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    from agent.journal_surface_gate import evaluate_journal_surface

    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "safety_comorbidity"},
        {"receipt_id": "p2", "outcome_class": "immune"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "Jones 2023"},
    }))
    text = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Safety and Comorbidity | n=1 | mixed |\n"
        "| Immune | n=1 | null |\n\n"
        "### Safety and Comorbidity Outcomes\n\n"
        "Jones 2023 reports immune findings.\n\n"
        "### Immune Outcomes\n\n"
        "Placeholder.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    safety = new_text.split("### Safety and Comorbidity Outcomes", 1)[1].split("###", 1)[0]
    assert "represented in the structured results table" in safety
    assert not any("empty heading: Safety and Comorbidity Outcomes" in i.detail for i in evaluate_journal_surface(new_text).issues)
    assert log and log[0].n_changes == 1


def test_phase_k_moves_contextual_prose_out_of_immune_outcome(tmp_path: Path) -> None:
    """Late interpretive prose can be appended under the final outcome
    heading. Citation ownership still wins and prevents journal-surface
    outcome_routing failures."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    from agent.journal_surface_gate import evaluate_journal_surface

    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "contextual_other"},
        {"receipt_id": "p2", "outcome_class": "immune_inflammation"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Wu 2025"},
        "p2": {"body_citation": "Gorabi 2021"},
    }))
    text = (
        "## Results\n\n"
        "### Contextual Adjacent Evidence Outcomes\n\n"
        "Contextual records bound interpretation.\n\n"
        "### Immune and Inflammation Outcomes\n\n"
        "Gorabi 2021 reports immune findings.\n\n"
        "The postmenopausal women's pain and symptom meta-analysis draws on a "
        "narrow contextual pool (Wu 2025).\n\n"
        "## Discussion\n"
    )

    assert any(i.code == "outcome_routing" for i in evaluate_journal_surface(
        text,
        citation_outcome_map={"Wu 2025": "contextual_other", "Gorabi 2021": "immune_inflammation"},
    ).issues)
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)

    contextual = new_text.split("### Contextual Adjacent Evidence Outcomes", 1)[1].split("###", 1)[0]
    immune = new_text.split("### Immune and Inflammation Outcomes", 1)[1].split("##", 1)[0]
    assert "Wu 2025" in contextual
    assert "Wu 2025" not in immune
    assert not any(i.code == "outcome_routing" for i in evaluate_journal_surface(
        new_text,
        citation_outcome_map={"Wu 2025": "contextual_other", "Gorabi 2021": "immune_inflammation"},
    ).issues)
    assert log and log[0].rule == "route_paragraph_by_citation_class"


def test_phase_k_routes_suffixed_author_year_citations(tmp_path: Path) -> None:
    """Author-year suffixes must route the same way the surface gate audits them."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    from agent.journal_surface_gate import evaluate_journal_surface

    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "contextual_other"},
        {"receipt_id": "p2", "outcome_class": "cardiometabolic"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Zhang 2026d"},
        "p2": {"body_citation": "Smith 2024"},
    }))
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Smith 2024 reports cardiometabolic findings.\n\n"
        "Zhang 2026d describes contextual stress biology.\n\n"
        "### Contextual Adjacent Evidence Outcomes\n\n"
        "Contextual records bound interpretation.\n\n"
        "## Discussion\n"
    )

    assert any(i.code == "outcome_routing" for i in evaluate_journal_surface(
        text,
        citation_outcome_map={"Zhang 2026d": "contextual_other", "Smith 2024": "cardiometabolic"},
    ).issues)
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)

    contextual = new_text.split("### Contextual Adjacent Evidence Outcomes", 1)[1].split("##", 1)[0]
    cardio = new_text.split("### Cardiometabolic Outcomes", 1)[1].split("###", 1)[0]
    assert "Zhang 2026d" in contextual
    assert "Zhang 2026d" not in cardio
    assert not any(i.code == "outcome_routing" for i in evaluate_journal_surface(
        new_text,
        citation_outcome_map={"Zhang 2026d": "contextual_other", "Smith 2024": "cardiometabolic"},
    ).issues)
    assert log and log[0].rule == "route_paragraph_by_citation_class"


def test_phase_k_noop_when_no_results_section(tmp_path: Path) -> None:
    """Slice 33: safe when Results section absent (e.g. Evidence Brief)."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": []}))
    (run / "citation_registry.json").write_text(json.dumps({}))
    text = "## Abstract\nA.\n\n## Methods\nM.\n"
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    assert new_text == text
    assert log == []


@pytest.mark.parametrize("retrieved", [0, 3255])
def test_methods_summary_uses_frozen_retrieval_audit_without_inventing_screening(retrieved):
    audit = {"selection_counts": {"retrieved": retrieved}, "extraction_counts": {"extracted": 117}}
    pack = build_methods_pack(review_type="curated_evidence_map", topic="resistance_training",
        corpus_search_queries=(), n_retrieved=None, n_screened=None, n_included=19,
        n_rejected=None, outcome_classes=("muscle_function",), retrieval_audit=audit)
    assert pack.screening_flow == {"n_retrieved": retrieved, "n_included": 19}
    md = render_methods_md(pack, submission_id="revision")
    assert f"Recorded stages: n_retrieved={retrieved}." in md
    assert f"| retrieved | {retrieved} |" in md
    assert "Recorded stages: none." not in md
    assert "record-linked screening path" in md
    assert "117 were screened" not in md
    assert "full-text review" not in md
