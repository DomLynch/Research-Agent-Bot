from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import l6_batch_report as l6  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(
    tmp_path: Path,
    name: str,
    *,
    topic: str = "alpha",
    maturity: int | None = 5,
    verdict: str = "AAA",
) -> Path:
    run = tmp_path / name
    run.mkdir()
    _write_json(run / "manifest.json", {"topic": topic, "generated_at": name})
    if maturity is not None:
        _write_json(
            run / "full_paper.final_verdict.json",
            {
                "topic": topic,
                "verdict": verdict,
                "maturity_level": maturity,
                "journal_surface_pass": maturity >= 5,
            },
        )
    return run


def _topic(report: dict, name: str = "alpha") -> dict:
    return next(t for t in report["topics"] if t["topic"] == name)


def test_zero_run_group_fails_closed() -> None:
    report = l6.build_batch_report({"alpha": []})
    topic = _topic(report)
    assert topic["n_runs"] == 0
    assert topic["latest_consecutive_l5"] == 0
    assert topic["l6_candidate"] is False
    assert topic["candidate_runs"] == []


def test_one_l5_run_is_not_l6_candidate(tmp_path: Path) -> None:
    report = l6.build_batch_report({"alpha": [_run(tmp_path, "r1")]})
    topic = _topic(report)
    assert topic["latest_consecutive_l5"] == 1
    assert topic["l6_candidate"] is False


def test_two_consecutive_l5_runs_surface_under_claimed_l6(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "r1"), _run(tmp_path, "r2")]
    topic = _topic(l6.build_batch_report({"alpha": runs}))
    assert topic["latest_consecutive_l5"] == 2
    assert topic["l6_candidate"] is True
    assert topic["under_claimed_l6"] is True
    assert topic["candidate_runs"] == ("r1", "r2")


def test_three_consecutive_l5_runs_keep_latest_pair(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "r1"), _run(tmp_path, "r2"), _run(tmp_path, "r3")]
    topic = _topic(l6.build_batch_report({"alpha": runs}))
    assert [r["consecutive_l5"] for r in topic["runs"]] == [1, 2, 3]
    assert topic["candidate_runs"] == ("r2", "r3")


def test_mixed_l5_l3_streak_resets(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "r1"),
        _run(tmp_path, "r2", maturity=3, verdict="Trust-Spine Pass"),
        _run(tmp_path, "r3"),
    ]
    topic = _topic(l6.build_batch_report({"alpha": runs}))
    assert [r["consecutive_l5"] for r in topic["runs"]] == [1, 0, 1]
    assert topic["l6_candidate"] is False


def test_missing_verdict_file_fails_closed(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "r1"), _run(tmp_path, "r2", maturity=None)]
    topic = _topic(l6.build_batch_report({"alpha": runs}))
    assert topic["runs"][1]["verdict"] == "unknown"
    assert topic["runs"][1]["maturity_level"] == 0
    assert topic["latest_consecutive_l5"] == 0


def test_group_run_dirs_uses_manifest_topic(tmp_path: Path) -> None:
    a = _run(tmp_path, "a1", topic="alpha")
    b = _run(tmp_path, "b1", topic="beta")
    groups = l6.group_run_dirs([b, a])
    assert sorted(groups) == ["alpha", "beta"]


def test_markdown_and_json_outputs_include_summary(tmp_path: Path, capsys) -> None:
    runs = [_run(tmp_path, "r1"), _run(tmp_path, "r2")]
    report = l6.build_batch_report(
        {"alpha": runs},
        contribution_summaries={"alpha": {"framework": "validated_scaffold"}},
    )
    md = l6.render_markdown(report)
    assert "Under-claimed L6" in md
    assert "research_contribution: alpha: framework=validated_scaffold" in md
    json_out = tmp_path / "l6.json"
    md_out = tmp_path / "l6.md"
    rc = l6.main(
        [
            str(runs[0]),
            str(runs[1]),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
            "--format",
            "md",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.startswith("# L6 Batch Report")
    assert (
        json.loads(json_out.read_text(encoding="utf-8"))["schema"]
        == "l6_batch_report.v1"
    )
    assert md_out.read_text(encoding="utf-8").startswith("# L6 Batch Report")
