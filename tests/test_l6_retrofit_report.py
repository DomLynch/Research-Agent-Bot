from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import l6_retrofit_report as retrofit  # type: ignore[import-not-found]  # noqa: E402


def _run(
    tmp_path: Path,
    name: str,
    topic: str,
    maturity: int,
    *,
    receipt_id: str = "same",
    extractor: str = "v1",
    flagged: int = 0,
    auto_stripped: int = 0,
    generated_at: str | None = None,
) -> Path:
    run = tmp_path / "runs" / name
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "topic": topic,
                "generated_at": generated_at or name,
                "extractor_version": extractor,
                "writer_path": "writer",
                "receipts": [{"receipt_id": receipt_id}],
            }
        ),
        encoding="utf-8",
    )
    (run / "full_paper.final_verdict.json").write_text(
        json.dumps(
            {
                "verdict": "AAA" if maturity >= 5 else "Trust-Spine Pass",
                "maturity_level": maturity,
                "journal_surface_pass": maturity >= 5,
                "grok_unresolved_p1": flagged,
                "auto_stripped_count": auto_stripped,
            }
        ),
        encoding="utf-8",
    )
    (run / "full_paper.review_patch_log.json").write_text(
        json.dumps({"n_flagged": flagged, "n_auto_stripped": auto_stripped}),
        encoding="utf-8",
    )
    (run / "full_paper.md").write_text("# Paper\n", encoding="utf-8")
    return run


def _cert_runner(l6_ready: bool) -> retrofit.CertRunner:
    def run(paths: tuple[Path, Path], output_dir: Path, timeout_s: int) -> dict:
        assert paths[0].name == "full_paper.md"
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "cert.json"
        out.write_text("{}", encoding="utf-8")
        return {
            "returncode": 0 if l6_ready else 1,
            "stdout_path": str(out),
            "stderr_path": "",
            "parsed": {
                "l6_reproducibly_journal_ready": l6_ready,
                "certified": True,
                "maturity_level": 6 if l6_ready else 5,
                "l6_blockers": [] if l6_ready else ["flagged patches"],
                "selected_pair": [paths[0].parent.name, paths[1].parent.name],
                "runs": [
                    _cert_run(paths[0].parent.name, flagged=0),
                    _cert_run(paths[1].parent.name, flagged=0 if l6_ready else 1),
                ],
            },
        }

    return run


def _wrong_pair_cert_runner() -> retrofit.CertRunner:
    def run(paths: tuple[Path, Path], output_dir: Path, timeout_s: int) -> dict:
        return {
            "returncode": 0,
            "stdout_path": "",
            "stderr_path": "",
            "parsed": {
                "l6_reproducibly_journal_ready": True,
                "certified": True,
                "maturity_level": 6,
                "selected_pair": ["different-a", "different-b"],
                "runs": [
                    _cert_run(paths[0].parent.name, flagged=0),
                    _cert_run(paths[1].parent.name, flagged=0),
                ],
            },
        }

    return run


def _cert_run(run_id: str, *, flagged: int) -> dict:
    return {
        "run_id": run_id,
        "aaa_pass": True,
        "q2_full": True,
        "stage2_clean": True,
        "grok_clean": True,
        "no_regression_pass": True,
        "old_defect_scan_clean": True,
        "flagged_patches": flagged,
        "auto_stripped_patches": 0,
        "journal_surface_pass": True,
    }


def _topic(report: dict, topic: str) -> dict:
    return next(t for t in report["topics"] if t["topic"] == topic)


def test_adjacent_l5_pair_is_candidate_only_without_real_gate(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(runs)
    topic = _topic(report, "alpha")
    assert topic["status"] == "candidate_only"
    assert topic["candidate_pairs"] == [["a1", "a2"]]


def test_same_topic_different_corpus_does_not_form_l6_pair(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "a1", "alpha", 5, receipt_id="corpus-a"),
        _run(tmp_path, "a2", "alpha", 5, receipt_id="corpus-b"),
    ]
    report = retrofit.build_report(runs)
    assert report["counts"]["needs_rerun"] == 2
    assert all(t["candidate_pairs"] == [] for t in report["topics"])


def test_same_topic_different_code_does_not_form_l6_pair(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "a1", "alpha", 5, extractor="v1"),
        _run(tmp_path, "a2", "alpha", 5, extractor="v2"),
    ]
    report = retrofit.build_report(runs)
    assert report["counts"]["needs_rerun"] == 2
    assert all(t["candidate_pairs"] == [] for t in report["topics"])


def test_mixed_topic_pairs_are_never_candidates(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "b1", "beta", 5)]
    report = retrofit.build_report(runs)
    assert {t["topic"] for t in report["topics"]} == {"alpha", "beta"}
    assert all(t["candidate_pairs"] == [] for t in report["topics"])


def test_real_gate_can_confirm_l6(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(
        runs,
        run_cert=True,
        output_dir=tmp_path / "out",
        cert_runner=_cert_runner(True),
    )
    topic = _topic(report, "alpha")
    assert topic["status"] == "confirmed_l6"
    assert topic["confirmed_pair"] == ["a1", "a2"]


def test_real_gate_blocks_candidate_pair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(
        runs,
        run_cert=True,
        output_dir=tmp_path / "out",
        cert_runner=_cert_runner(False),
    )
    topic = _topic(report, "alpha")
    assert topic["status"] == "blocked"
    assert topic["certifications"][0]["blockers"] == ["flagged patches"]
    assert "flagged_patches=1" in topic["certifications"][0]["eligibility_blockers"][0]


def test_wrong_selected_pair_cannot_confirm_l6(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(
        runs,
        run_cert=True,
        output_dir=tmp_path / "out",
        cert_runner=_wrong_pair_cert_runner(),
    )
    topic = _topic(report, "alpha")
    cert = topic["certifications"][0]
    assert topic["status"] == "blocked"
    assert cert["l6_confirmed"] is False
    assert cert["selected_pair_matches"] is False
    assert "cert selected_pair does not match evaluated pair" in cert["eligibility_blockers"]


def test_latest_l5_without_pair_needs_rerun(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 3), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["status"] == "needs_rerun"


def test_three_run_sequence_tracks_two_adjacent_pairs(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "a1", "alpha", 5),
        _run(tmp_path, "a2", "alpha", 5),
        _run(tmp_path, "a3", "alpha", 5),
    ]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["candidate_pairs"] == [["a1", "a2"], ["a2", "a3"]]


def test_broken_sequence_resets_candidate_pairs(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "a1", "alpha", 5),
        _run(tmp_path, "a2", "alpha", 3),
        _run(tmp_path, "a3", "alpha", 5),
    ]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["status"] == "needs_rerun"
    assert _topic(report, "alpha")["candidate_pairs"] == []


def test_non_consecutive_l5_runs_separated_by_dirty_run_do_not_pair(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "a1", "alpha", 5, generated_at="2026-05-08T00:00:00Z"),
        _run(tmp_path, "a2", "alpha", 5, flagged=1, generated_at="2026-05-08T00:01:00Z"),
        _run(tmp_path, "a3", "alpha", 5, generated_at="2026-05-08T00:02:00Z"),
    ]
    report = retrofit.build_report(runs)
    topic = _topic(report, "alpha")
    assert topic["candidate_pairs"] == []
    assert topic["status"] == "needs_rerun"


def test_flagged_or_auto_stripped_runs_are_not_l6_candidates(tmp_path: Path) -> None:
    flagged = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5, flagged=1)]
    stripped = [_run(tmp_path, "b1", "beta", 5), _run(tmp_path, "b2", "beta", 5, auto_stripped=1)]
    report = retrofit.build_report(flagged + stripped)
    assert _topic(report, "alpha")["candidate_pairs"] == []
    assert _topic(report, "beta")["candidate_pairs"] == []


def test_no_l5_data_is_no_data(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 3), _run(tmp_path, "a2", "alpha", 4)]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["status"] == "no_data"


def test_write_report_outputs_json_and_markdown(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 5), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(runs)
    retrofit.write_report(report, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "report.json").read_text())["schema"]
    markdown = (tmp_path / "out" / "report.md").read_text()
    assert "L6 Retrofit Report" in markdown
    assert "## Next Reruns\n\n- None;" in markdown
