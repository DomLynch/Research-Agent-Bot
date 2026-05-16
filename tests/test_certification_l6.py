from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import certification_report as cert  # type: ignore[import-not-found]  # noqa: E402


def _paper(run_id: str) -> Path:
    return Path(run_id) / "full_paper.md"


def _verdict(
    run_id: str,
    *,
    topic: str = "metformin",
    aaa: bool = True,
    auto_stripped: int = 0,
    journal_surface: bool = True,
) -> cert.CertificationVerdict:
    return cert.CertificationVerdict(
        run_id=run_id,
        git_sha="deadbeef",
        timestamp_iso="2026-01-01T00:00:00Z",
        final_verdict="AAA" if aaa else "SHIP-BLOCKED",
        aaa_pass=aaa,
        q2_traceability_pct=100.0 if aaa else 0.0,
        q2_full=aaa,
        stage1_pass_rate="13/13",
        stage2_p1=0,
        stage2_p2=0,
        stage2_clean=True,
        grok_unresolved_p1=0,
        grok_clean=True,
        no_regression_pass=True,
        old_defect_scan_clean=True,
        auto_stripped_patches=auto_stripped,
        topic=topic,
        journal_surface_pass=journal_surface,
    )


def _patch_certify(monkeypatch, verdicts: dict[str, cert.CertificationVerdict]):
    monkeypatch.setattr(
        cert, "certify_run", lambda p: verdicts[p.parent.name],
    )


def test_l6_empty_fails_closed(monkeypatch) -> None:
    _patch_certify(monkeypatch, {})
    result = cert.certify_consecutive([])
    assert result["l6_reproducibly_journal_ready"] is False
    assert result["selected_pair"] == []
    assert result["l6_blockers"]


def test_l6_one_run_fails_closed(monkeypatch) -> None:
    run = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    _patch_certify(monkeypatch, {run: _verdict(run)})
    result = cert.certify_consecutive([_paper(run)])
    assert result["l6_reproducibly_journal_ready"] is False
    assert "need >=2" in result["l6_blockers"][0]


def test_l6_clean_latest_two_same_topic_pass(monkeypatch) -> None:
    a = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    b = "synthesis-metformin-v06-B-2026-05-02T00-00-00Z"
    _patch_certify(monkeypatch, {a: _verdict(a), b: _verdict(b)})
    result = cert.certify_consecutive([_paper(a), _paper(b)])
    assert result["l6_reproducibly_journal_ready"] is True
    assert result["selected_pair"] == [a, b]
    assert result["consecutive_aaa_count"] == 2
    assert result["consecutive_aaa_run_ids"] == [a, b]
    assert result["consecutive_l5_count"] == 2
    assert result["consecutive_l5_run_ids"] == [a, b]
    assert result["l6_evidence"] == {
        "gate": cert.CERTIFICATION_GATE_VERSION,
        "selected_pair": [a, b],
        "consecutive_aaa_count": 2,
        "consecutive_aaa_run_ids": [a, b],
        "consecutive_l5_count": 2,
        "consecutive_l5_run_ids": [a, b],
        "selected_pair_clean_l5": True,
        "blockers": [],
    }
    assert result["certification_gate_version"] == cert.CERTIFICATION_GATE_VERSION


def test_l6_mixed_topic_fails_closed(monkeypatch) -> None:
    a = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    b = "synthesis-rapamycin-v06-B-2026-05-02T00-00-00Z"
    _patch_certify(
        monkeypatch, {a: _verdict(a), b: _verdict(b, topic="rapamycin")},
    )
    result = cert.certify_consecutive([_paper(a), _paper(b)])
    assert result["l6_reproducibly_journal_ready"] is False
    assert any("mixed topics" in b for b in result["l6_blockers"])


def test_l6_uses_latest_adjacent_pair(monkeypatch) -> None:
    old = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    mid = "synthesis-metformin-v06-B-2026-05-02T00-00-00Z"
    new = "synthesis-metformin-v06-C-2026-05-03T00-00-00Z"
    _patch_certify(
        monkeypatch,
        {old: _verdict(old), mid: _verdict(mid), new: _verdict(new, aaa=False)},
    )
    result = cert.certify_consecutive([_paper(old), _paper(mid), _paper(new)])
    assert result["selected_pair"] == [mid, new]
    assert result["l6_reproducibly_journal_ready"] is False
    assert result["consecutive_aaa_count"] == 0
    assert result["consecutive_aaa_run_ids"] == []
    assert result["l6_evidence"]["selected_pair_clean_l5"] is False
    assert any(new in b for b in result["l6_blockers"])


def test_l6_auto_strip_blocks_reproducibility(monkeypatch) -> None:
    a = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    b = "synthesis-metformin-v06-B-2026-05-02T00-00-00Z"
    _patch_certify(
        monkeypatch, {a: _verdict(a), b: _verdict(b, auto_stripped=1)},
    )
    result = cert.certify_consecutive([_paper(a), _paper(b)])
    assert result["certified"] is True
    assert result["l6_reproducibly_journal_ready"] is False
    assert any("auto-stripped" in b for b in result["l6_blockers"])


def test_l6_journal_surface_failure_blocks_reproducibility(monkeypatch) -> None:
    a = "synthesis-metformin-v06-A-2026-05-01T00-00-00Z"
    b = "synthesis-metformin-v06-B-2026-05-02T00-00-00Z"
    _patch_certify(
        monkeypatch, {a: _verdict(a), b: _verdict(b, journal_surface=False)},
    )
    result = cert.certify_consecutive([_paper(a), _paper(b)])
    assert result["certified"] is True
    assert result["l6_reproducibly_journal_ready"] is False
    assert any("journal surface failed" in b for b in result["l6_blockers"])


def test_rapamycin_patha_l6_verdicts_are_self_contained() -> None:
    runs = [
        "synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z",
        "synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z",
        "synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z",
    ]
    selected_pair = runs[1:]
    for run_id in runs:
        path = (
            REPO / "tests" / "fixtures" / "certification_l6_patha"
            / f"{run_id}.final_verdict.json"
        )
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["maturity_level"] == 6
        assert doc["l6_reproducibly_journal_ready"] is True
        assert doc["consecutive_aaa_count"] == 3
        assert doc["consecutive_aaa_run_ids"] == runs
        assert doc["l6_selected_pair"] == selected_pair
        assert doc["arbitration_count"] == 0
        assert doc["arbitration_log_path"] is None
        assert doc["l6_evidence"] == {
            "blockers": [],
            "consecutive_aaa_count": 3,
            "consecutive_aaa_run_ids": runs,
            "consecutive_l5_count": 3,
            "consecutive_l5_run_ids": runs,
            "gate": cert.CERTIFICATION_GATE_VERSION,
            "selected_pair": selected_pair,
            "selected_pair_clean_l5": True,
        }
