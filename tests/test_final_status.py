"""Tests for agent.final_status — single source of truth for submission readiness.

Stdlib-only, no LLM. Each test writes minimal sidecar JSON into a tmp_path
and asserts the merged FinalStatus / on-disk final_status.json matches.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.final_status import (  # type: ignore[import-not-found]
    LABELS,
    BlockingReason,
    compute,
    compute_and_write,
)


# ---- helpers --------------------------------------------------------------


def _write(run: Path, name: str, payload: dict) -> None:
    (run / name).write_text(json.dumps(payload))


def _all_pass_sidecars(run: Path) -> None:
    _write(run, "benchmark_runtime.json", {"return_code": 0})
    _write(run, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.6,
    })
    _write(run, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(run, "pre_submit_gate.json", {"result": {"passed": True, "failures": []}})
    _write(run, "target_journal_pack.json", {"journal": "Aging Cell", "declared_in_topic_pack": True})
    # Slice 17: default accountability model is researka_agent_certified,
    # which requires citation_registry.json + artifact_consistency.json
    # (and ignores human_signoff.json). The legacy ladder test below
    # exercises the human_signoff path explicitly.
    _write(run, "manifest.json", {
        "accountability_model": "researka_agent_certified",
    })
    _write(run, "citation_registry.json", {})
    _write(run, "artifact_consistency.json", {"passed": True, "checks": []})
    _write(run, "human_signoff.json", {"ready_to_submit": True})


# ---- maturity ladder ------------------------------------------------------


def test_all_pass_yields_l5_submission_ready(tmp_path: Path) -> None:
    _all_pass_sidecars(tmp_path)
    s = compute(tmp_path)
    assert s.maturity_level == 5
    assert s.maturity_label == LABELS[5]
    assert s.submission_ready is True
    assert s.blocking_reasons == ()


def test_journal_surface_failure_blocks_l5_and_submission_ready(tmp_path: Path) -> None:
    # GPT-flagged invariant ("looks ready but refused"): a paper that fails the
    # journal-surface gate must never label L5 or report submission_ready, even
    # with every OTHER trust-spine dimension green.
    _all_pass_sidecars(tmp_path)
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": False, "issues": ["x"]})
    s = compute(tmp_path)
    assert s.journal_surface_pass is False
    assert s.maturity_level < 5
    assert s.submission_ready is False


def test_no_runtime_yields_l1(tmp_path: Path) -> None:
    # Nothing written — runtime fails first.
    s = compute(tmp_path)
    assert s.maturity_level == 1
    assert s.submission_ready is False
    # All six dimensions must have a blocking reason
    stages = {b.stage for b in s.blocking_reasons}
    assert "runtime" in stages


def test_runtime_pass_audit_fail_yields_l2(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 13, "p1_pass": False, "score_out_of_10": 8.6,
    })
    s = compute(tmp_path)
    assert s.maturity_level == 2
    assert s.audit_pass is False
    assert any(b.stage == "audit" for b in s.blocking_reasons)


def test_audit_pass_surface_fail_yields_l3(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.5,
    })
    _write(tmp_path, "full_paper.journal_surface.json", {
        "passed": False, "issues": ["missing_immune", "stale_count"],
    })
    s = compute(tmp_path)
    assert s.maturity_level == 3
    assert s.journal_surface_pass is False


def test_advisory_audit_miss_does_not_block_audit_pass(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 13, "p1_pass": True, "score_out_of_10": 9.3,
    })
    s = compute(tmp_path)
    assert s.audit_pass is True
    assert not [b for b in s.blocking_reasons if b.stage == "audit"]


def test_audit_surface_pass_pre_submit_fail_yields_l3(tmp_path: Path) -> None:
    """Wave 47 — pre-submit failure keeps the level at L3 (not L4),
    matching the user's truth-table: pre_submit_pass is required to
    promote past L3."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.5,
    })
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json", {
        "result": {"passed": False, "failures": ["audit_gates_failed"]},
    })
    s = compute(tmp_path)
    assert s.maturity_level == 3
    assert s.pre_submit_pass is False
    # The reason code should map "audit_gates_failed" specifically
    pre_blockers = [b for b in s.blocking_reasons if b.stage == "pre_submit"]
    assert pre_blockers and pre_blockers[0].code == "audit_gates_failed"


def test_readiness_contract_blocker_overrides_pre_submit_pass(tmp_path: Path) -> None:
    """A passing pre-submit summary cannot override its own blocking contract."""
    _all_pass_sidecars(tmp_path)
    _write(tmp_path, "pre_submit_gate.json", {
        "result": {"passed": True, "failures": []},
        "journal_readiness_contract": [{
            "id": 12, "name": "target_journal_finalizer",
            "status": "not_ready", "blocks_submission": True,
        }],
    })
    s = compute(tmp_path)
    assert s.pre_submit_pass is False
    assert s.submission_ready is False
    assert s.maturity_level == 3
    blockers = [b for b in s.blocking_reasons if b.stage == "pre_submit"]
    assert blockers and blockers[0].code == "readiness_contract_blocking"


def test_advisory_readiness_item_does_not_block_l4(tmp_path: Path) -> None:
    """Administrative/readiness roadmap gaps should not demote a clean paper below L4."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.5,
    })
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json", {
        "result": {"passed": True, "failures": []},
        "journal_readiness_contract": [
            {
                "id": item_id, "name": name, "status": "partial",
                "advisory": True, "blocks_submission": False,
            }
            for item_id, name in (
                (3, "domain_pack"),
                (4, "journal_grade_retrieval"),
                (8, "deterministic_abstract_conclusion"),
                (10, "section_repair_loop"),
                (12, "target_journal_finalizer"),
            )
        ],
    })
    s = compute(tmp_path)
    assert s.pre_submit_pass is True
    assert s.maturity_level == 4


def test_three_pass_no_target_journal_yields_l4(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.5,
    })
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json", {"result": {"passed": True, "failures": []}})
    # No target_journal_pack.json, no human_signoff.json
    s = compute(tmp_path)
    assert s.maturity_level == 4
    assert s.target_journal_pass is False
    assert s.human_signoff_pass is False


# ---- reason codes (universal across topics, no per-topic logic) ----------


def test_blocking_reason_codes_are_snake_case_universal(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 1})
    s = compute(tmp_path)
    runtime_blockers = [b for b in s.blocking_reasons if b.stage == "runtime"]
    assert runtime_blockers
    # Code is snake_case, no topic-specific tokens
    code = runtime_blockers[0].code
    assert " " not in code and code == code.lower()
    assert code in ("runtime_nonzero_exit", "runtime_missing", "runtime_blocked")


def test_failure_dataclass_is_immutable() -> None:
    b = BlockingReason(stage="audit", code="audit_p1_failed", detail="13/14")
    import pytest
    with pytest.raises(AttributeError):
        b.code = "other"  # type: ignore[misc]


# ---- sidecar write --------------------------------------------------------


def test_compute_and_write_emits_final_status_json(tmp_path: Path) -> None:
    _all_pass_sidecars(tmp_path)
    compute_and_write(tmp_path)
    out = tmp_path / "final_status.json"
    assert out.is_file()
    payload = json.loads(out.read_text())
    assert payload["submission_ready"] is True
    assert payload["maturity_level"] == 5
    assert payload["maturity_label"] == LABELS[5]
    # Slice 17: 6th dimension renamed to accountability_pass;
    # human_signoff_pass kept as backward-compat mirror.
    assert set(payload["dimensions"]) == {
        "runtime_pass", "audit_pass", "journal_surface_pass",
        "pre_submit_pass", "target_journal_pass",
        "accountability_pass", "human_signoff_pass",
    }
    assert payload["accountability_model"] == "researka_agent_certified"
    assert payload["blocking_reasons"] == []
    assert "benchmark_runtime.json" in payload["sidecars_read"]


def test_no_aaa_label_anywhere() -> None:
    """L1–L5 labels must NOT contain the string 'AAA' (Wave-47 label
    freeze deliberately replaces the historical 'AAA/L5' inflation)."""
    for label in LABELS.values():
        assert "AAA" not in label, f"'AAA' leaked into label: {label}"


# ---- malformed-input resilience (fail-closed) ----------------------------


def test_unreadable_sidecar_fails_closed(tmp_path: Path) -> None:
    # Truncated JSON — must NOT crash; must report stage as failing.
    (tmp_path / "benchmark_runtime.json").write_text("{not json")
    s = compute(tmp_path)
    assert s.runtime_pass is False
    assert s.maturity_level == 1


def test_audit_with_zero_total_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 0, "n_pass": 0, "p1_pass": True,
    })
    s = compute(tmp_path)
    # n_total == 0 should not count as "passed" — degenerate state.
    assert s.audit_pass is False


# ---- Slice 17: accountability-model split ---------------------------------


def test_researka_model_reaches_l5_without_human_signoff(tmp_path: Path) -> None:
    """Researka-native ladder: no human_signoff file required. L5 is
    reached on the artifact spine alone (audit + surface + pre_submit
    + artifact_consistency + citation_registry + target_journal)."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True,
    })
    _write(tmp_path, "full_paper.journal_surface.json",
           {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json",
           {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {"journal": "Aging Cell", "declared_in_topic_pack": True})
    _write(tmp_path, "manifest.json",
           {"accountability_model": "researka_agent_certified"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json",
           {"passed": True, "checks": []})
    # Deliberately NO human_signoff.json
    s = compute(tmp_path)
    assert s.maturity_level == 5
    assert s.accountability_pass is True
    assert s.accountability_model == "researka_agent_certified"


def test_legacy_model_blocks_l5_without_human_signoff(tmp_path: Path) -> None:
    """Legacy journal ladder: ICMJE/COPE compliance — still requires
    a named human-author signoff with ready_to_submit=true."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True,
    })
    _write(tmp_path, "full_paper.journal_surface.json",
           {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json",
           {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {"journal": "Aging Cell", "declared_in_topic_pack": True})
    _write(tmp_path, "manifest.json",
           {"accountability_model": "legacy_journal_submission"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json",
           {"passed": True, "checks": []})
    s = compute(tmp_path)
    # No human signoff → accountability fails → blocked at L4
    assert s.accountability_pass is False
    assert s.maturity_level == 4
    assert s.accountability_model == "legacy_journal_submission"


def test_legacy_model_reaches_l5_with_human_signoff(tmp_path: Path) -> None:
    """Legacy ladder with all artifacts + human signoff → L5."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True,
    })
    _write(tmp_path, "full_paper.journal_surface.json",
           {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json",
           {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {"journal": "Aging Cell", "declared_in_topic_pack": True})
    _write(tmp_path, "manifest.json",
           {"accountability_model": "legacy_journal_submission"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json",
           {"passed": True, "checks": []})
    _write(tmp_path, "human_signoff.json", {"ready_to_submit": True})
    s = compute(tmp_path)
    assert s.maturity_level == 5
    assert s.accountability_pass is True


def test_unknown_accountability_model_falls_back_to_researka(tmp_path: Path) -> None:
    """An unknown/typo model in manifest → defaults to researka_agent_certified
    (the conservative non-blocking default). Universal — fail-soft."""
    from agent.accountability import resolve_model
    assert resolve_model(None) == "researka_agent_certified"
    assert resolve_model("") == "researka_agent_certified"
    assert resolve_model("typo_unknown") == "researka_agent_certified"
    assert resolve_model("legacy_journal_submission") == "legacy_journal_submission"


def test_human_signoff_pass_backward_compat_mirror(tmp_path: Path) -> None:
    """Pre-Slice-17 consumers reading `status.human_signoff_pass`
    must still see the boolean (mirrors accountability_pass now)."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {
        "n_total": 14, "n_pass": 14, "p1_pass": True,
    })
    _write(tmp_path, "full_paper.journal_surface.json",
           {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json",
           {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {"journal": "Aging Cell", "declared_in_topic_pack": True})
    _write(tmp_path, "manifest.json",
           {"accountability_model": "researka_agent_certified"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json",
           {"passed": True, "checks": []})
    s = compute(tmp_path)
    assert s.human_signoff_pass == s.accountability_pass


def test_slice36_undeclared_target_journal_blocks_submission_ready(tmp_path: Path) -> None:
    """Slice 36: a target_journal_pack with declared_in_topic_pack=False
    (auto-generated fallback) must NOT count as a valid submission target.
    Previously this path quietly promoted runs to L5/submission_ready=True
    with no human-affirmed journal — the overclaim path. Universal."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {"n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.6, "checks": []})
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json", {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {
        "journal": "Open-access general scholarly journal (topic-pack target_journal not declared)",
        "declared_in_topic_pack": False,
    })
    _write(tmp_path, "manifest.json", {"accountability_model": "researka_agent_certified"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json", {"passed": True, "checks": []})
    s = compute(tmp_path)
    assert s.target_journal_pass is False
    assert s.submission_ready is False
    assert s.maturity_level == 4
    codes = {b.code for b in s.blocking_reasons}
    assert "target_journal_not_author_declared" in codes


def test_slice36_declared_target_journal_clears_l4_ceiling(tmp_path: Path) -> None:
    """Slice 36: explicit declared_in_topic_pack=True passes the guard
    (companion to the negative case above). This is the only path to L5."""
    _write(tmp_path, "benchmark_runtime.json", {"return_code": 0})
    _write(tmp_path, "full_paper.audit.json", {"n_total": 14, "n_pass": 14, "p1_pass": True, "score_out_of_10": 9.6, "checks": []})
    _write(tmp_path, "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write(tmp_path, "pre_submit_gate.json", {"result": {"passed": True, "failures": []}})
    _write(tmp_path, "target_journal_pack.json", {
        "journal": "Journal of Climate Modelling", "declared_in_topic_pack": True,
    })
    _write(tmp_path, "manifest.json", {"accountability_model": "researka_agent_certified"})
    _write(tmp_path, "citation_registry.json", {})
    _write(tmp_path, "artifact_consistency.json", {"passed": True, "checks": []})
    s = compute(tmp_path)
    assert s.target_journal_pass is True
    assert s.submission_ready is True
    assert s.maturity_level == 5
