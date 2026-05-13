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
    _write(run, "target_journal_pack.json", {"journal": "Aging Cell"})
    _write(run, "human_signoff.json", {"ready_to_submit": True})


# ---- maturity ladder ------------------------------------------------------


def test_all_pass_yields_l5_submission_ready(tmp_path: Path) -> None:
    _all_pass_sidecars(tmp_path)
    s = compute(tmp_path)
    assert s.maturity_level == 5
    assert s.maturity_label == LABELS[5]
    assert s.submission_ready is True
    assert s.blocking_reasons == ()


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
    assert set(payload["dimensions"]) == {
        "runtime_pass", "audit_pass", "journal_surface_pass",
        "pre_submit_pass", "target_journal_pass", "human_signoff_pass",
    }
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
