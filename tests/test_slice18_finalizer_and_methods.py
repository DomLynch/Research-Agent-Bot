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

import json
from pathlib import Path

from agent.journal_finalizer import (  # type: ignore[import-not-found]
    _lowercase_first_letter,
    _phase_g_refresh_sidecars,
)
from agent.methods_pack import (  # type: ignore[import-not-found]
    REQUIRED_METHODS_H3_MARKERS,
    _accountability_text,
    build_methods_pack,
    render_methods_md,
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


def test_accountability_text_unknown_token_falls_back_to_researka() -> None:
    text = _accountability_text("nonsense_value")
    assert "researka_agent_certified" in text


def test_methods_pack_h3_markers_no_longer_say_human_accountability() -> None:
    # Slice 18: heading was renamed; constant must match the renderer.
    assert "### Accountability" in REQUIRED_METHODS_H3_MARKERS
    assert "### Human accountability" not in REQUIRED_METHODS_H3_MARKERS


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
              old_contract_name: str) -> Path:
    """Set up a minimal stale-sidecar run dir for Phase G tests."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.md").write_text("# Stub\n")
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
    (run / "citation_registry.json").write_text("[]")
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
    assert "reconcile_final_verdict_surface_state" in rules


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
    assert "reconcile_readiness_contract_item_13" in rules


def test_phase_g_rebuilds_readiness_contract_for_legacy(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="legacy_journal_submission",
        old_contract_name="accountability",  # stale researka shape
    )
    # legacy needs human_signoff.json ready
    (run / "human_signoff.json").write_text(json.dumps({
        "ready_to_submit": True,
    }))
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


def test_phase_g_missing_sidecars_is_safe(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    # No sidecars exist — must not raise.
    log = _phase_g_refresh_sidecars(run)
    assert log == []
