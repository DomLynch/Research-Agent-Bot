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
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    log = _phase_g_refresh_sidecars(run)
    verdict = json.loads((run / "full_paper.final_verdict.json").read_text())
    assert verdict["journal_surface_pass"] is True
    assert verdict["journal_surface_issues"] == []
    rules = [e.rule for e in log]
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
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    # Pre-align the verdict so refresh has nothing to do
    verdict = json.loads((run / "full_paper.final_verdict.json").read_text())
    verdict["journal_surface_pass"] = True
    verdict["journal_surface_issues"] = []
    (run / "full_paper.final_verdict.json").write_text(json.dumps(verdict))
    log = _phase_g_refresh_sidecars(run)
    assert log == []  # already consistent — Phase G is a quiet no-op


def test_phase_g_missing_sidecars_is_safe(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    # No sidecars exist — must not raise.
    log = _phase_g_refresh_sidecars(run)
    assert log == []
