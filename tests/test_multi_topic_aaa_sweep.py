"""Tests for scripts/multi_topic_aaa_sweep — L6 classifier + verdict reader."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from multi_topic_aaa_sweep import (  # type: ignore[import-not-found]  # noqa: E402
    _classify_l6, _read_verdict,
)


def _gates(verdict: str = "AAA", all_green: bool = True, **kw: object) -> dict:
    return {"verdict": verdict, "all_green": all_green, **kw}


def test_classify_l6_both_aaa_all_green() -> None:
    assert (
        _classify_l6(_gates(), _gates())
        == "L6 — REPRODUCIBLY JOURNAL-READY"
    )


def test_classify_l6_both_aaa_one_not_green() -> None:
    assert (
        _classify_l6(_gates(), _gates(all_green=False))
        == "L5 (twice) — pending all-green parity"
    )


def test_classify_l6_one_aaa() -> None:
    assert _classify_l6(_gates(), _gates(verdict="Trust-Spine Pass")) == "L5 (once)"


def test_classify_l6_neither_aaa() -> None:
    assert (
        _classify_l6(_gates(verdict="SHIP-BLOCKED", all_green=False),
                    _gates(verdict="SHIP-BLOCKED", all_green=False))
        == "below-L5"
    )


def test_classify_l6_handles_missing_keys() -> None:
    """Defensive: empty dicts shouldn't raise — they classify as below-L5."""
    assert _classify_l6({}, {}) == "below-L5"


def test_read_verdict_pulls_headline_gates(tmp_path: Path) -> None:
    """End-to-end on a synthetic run dir: every headline field maps."""
    (tmp_path / "full_paper.final_verdict.json").write_text(json.dumps({
        "verdict": "AAA",
        "stage1_pass_rate": "14/14",
        "stage1_score": 10.0,
        "stage2_p1": 0,
        "stage2_p2": 0,
        "all_green": True,
        "journal_ready": True,
        "maturity_label": "L5 — JOURNAL-READY",
        "certification_track": "AAA-CLIN",
    }))
    (tmp_path / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": True, "issues": [],
    }))
    (tmp_path / "template_language_gate.json").write_text(json.dumps({
        "summary": {"blocking": False, "total_hits": 0},
    }))
    (tmp_path / "pre_submit_gate.json").write_text(json.dumps({
        "result": {
            "paper_quality_gate": "PASS",
            "formal_sr_methods": "PARTIAL",
        },
    }))
    (tmp_path / "publication_score.json").write_text(json.dumps({
        "result": {"verdict": "accept", "rubric_total": 28},
    }))

    g = _read_verdict(tmp_path)
    assert g["verdict"] == "AAA"
    assert g["stage1_pass_rate"] == "14/14"
    assert g["all_green"] is True
    assert g["journal_surface_passed"] is True
    assert g["template_blocking"] is False
    assert g["template_total_hits"] == 0
    assert g["paper_quality_gate"] == "PASS"
    assert g["formal_sr_methods"] == "PARTIAL"
    assert g["publication_verdict"] == "accept"
    assert g["rubric_total"] == 28


def test_read_verdict_fail_soft_on_missing_files(tmp_path: Path) -> None:
    """If sidecars are missing entirely, all keys are present + None."""
    g = _read_verdict(tmp_path)
    assert g["verdict"] is None
    assert g["paper_quality_gate"] is None
    assert g["template_blocking"] is None


def test_read_verdict_fail_soft_on_corrupt_json(tmp_path: Path) -> None:
    """Corrupt JSON should not crash — degrades to None."""
    (tmp_path / "full_paper.final_verdict.json").write_text("not json")
    g = _read_verdict(tmp_path)
    assert g["verdict"] is None


def test_main_runs_topics_in_parallel_when_jobs_gt_one(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import multi_topic_aaa_sweep as sweep

    barrier = threading.Barrier(2)
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_run_topic(topic: str, **kwargs) -> dict:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        barrier.wait(timeout=2)
        with lock:
            active -= 1
        return {"passes": [{"pass": 1, "gates": {}}], "log_path": topic}

    monkeypatch.setattr(sweep, "REPO", tmp_path)
    monkeypatch.setattr(sweep, "_run_topic", fake_run_topic)

    rc = sweep.main([
        "--topics", "metformin", "rapamycin",
        "--passes", "1",
        "--jobs", "2",
    ])

    assert rc == 0
    assert max_active == 2
