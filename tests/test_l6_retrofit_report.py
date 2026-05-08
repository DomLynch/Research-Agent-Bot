from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import l6_retrofit_report as retrofit  # noqa: E402


def _run(tmp_path: Path, name: str, topic: str, maturity: int) -> Path:
    run = tmp_path / "runs" / name
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps({"topic": topic, "generated_at": name}),
        encoding="utf-8",
    )
    (run / "full_paper.final_verdict.json").write_text(
        json.dumps(
            {
                "verdict": "AAA" if maturity >= 5 else "Trust-Spine Pass",
                "maturity_level": maturity,
                "journal_surface_pass": maturity >= 5,
            }
        ),
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


def test_latest_l5_without_pair_needs_rerun(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 3), _run(tmp_path, "a2", "alpha", 5)]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["status"] == "needs_rerun"


def test_no_l5_data_is_no_data(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a1", "alpha", 3), _run(tmp_path, "a2", "alpha", 4)]
    report = retrofit.build_report(runs)
    assert _topic(report, "alpha")["status"] == "no_data"


def test_write_report_outputs_json_and_markdown(tmp_path: Path) -> None:
    report = retrofit.build_report([_run(tmp_path, "a1", "alpha", 5)])
    retrofit.write_report(report, tmp_path / "out")
    assert json.loads((tmp_path / "out" / "report.json").read_text())["schema"]
    assert "L6 Retrofit Report" in (tmp_path / "out" / "report.md").read_text()
