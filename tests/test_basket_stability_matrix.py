from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from basket_stability_matrix import (  # noqa: E402
    collect_rows,
    main,
    row_from_run_dir,
    rows_to_csv,
    rows_to_json,
)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(tmp_path: Path, name: str, *, topic: str = "alpha") -> Path:
    run = tmp_path / name
    run.mkdir()
    _write_json(run / "manifest.json", {
        "topic": topic,
        "generated_at": name,
        "n_receipts": 7,
        "n_non_orthogonal_tensions": 3,
        "n_high_confidence_claims_total": 30,
    })
    return run


def test_matrix_reads_final_verdict_shape_and_missing_fields(tmp_path: Path) -> None:
    run = _run(tmp_path, "run-a")
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 5,
    })
    _write_json(run / "full_paper.audit.json", {
        "p1_pass": True,
        "score_out_of_10": 10.0,
        "checks": [{"detail": "2 rejected receipts, all properly quarantined"}],
    })
    row = row_from_run_dir(run)
    assert row["topic"] == "alpha"
    assert row["verdict"] == "AAA"
    assert row["maturity_level"] == 5
    assert row["is_l5"] is True
    assert row["quarantine_counts"] == 2


def test_matrix_falls_back_when_final_verdict_missing(tmp_path: Path) -> None:
    run = _run(tmp_path, "run-a")
    _write_json(run / "full_paper.audit.json", {
        "p1_pass": False,
        "score_out_of_10": 7.0,
    })
    row = row_from_run_dir(run)
    assert row["verdict"] == "fail"
    assert row["maturity_level"] == 0


def test_matrix_reads_journal_surface_pass_alias(tmp_path: Path) -> None:
    run = _run(tmp_path, "run-a")
    _write_json(run / "full_paper.final_verdict.json", {
        "journal_surface_pass": True,
    })

    assert row_from_run_dir(run)["js_pass"] == "true"


def test_group_runs_adds_consecutive_l5_and_l6_candidate(tmp_path: Path) -> None:
    a = _run(tmp_path, "2026-01", topic="alpha")
    b = _run(tmp_path, "2026-02", topic="alpha")
    c = _run(tmp_path, "2026-03", topic="alpha")
    for run, level in ((a, 5), (b, 5), (c, 4)):
        _write_json(run / "full_paper.final_verdict.json", {
            "verdict": "AAA",
            "maturity_level": level,
        })
    rows = collect_rows([c, b, a], group_runs=True)
    assert [row["consecutive_l5"] for row in rows] == [1, 2, 0]
    assert [row["l6_candidate"] for row in rows] == [False, True, False]


def test_baseline_comparison_flags_regression(tmp_path: Path) -> None:
    base = _run(tmp_path, "base", topic="alpha")
    new = _run(tmp_path, "new", topic="alpha")
    _write_json(base / "manifest.json", {
        "topic": "alpha", "generated_at": "base", "n_receipts": 10,
        "n_non_orthogonal_tensions": 5,
    })
    _write_json(base / "full_paper.final_verdict.json", {
        "verdict": "AAA", "maturity_level": 5,
    })
    _write_json(new / "manifest.json", {
        "topic": "alpha", "generated_at": "new", "n_receipts": 8,
        "n_non_orthogonal_tensions": 6,
    })
    _write_json(new / "full_paper.final_verdict.json", {
        "verdict": "SHIP-BLOCKED", "maturity_level": 3,
    })
    row = collect_rows([new], baseline_paths=[base])[0]
    assert row["baseline_run_dir"] == "base"
    assert row["receipt_delta"] == -2
    assert row["tension_delta"] == 1
    assert row["maturity_delta"] == -2
    assert row["regression"] is True


def test_matrix_outputs_stable_csv_json_and_files(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "run-a")
    rows = collect_rows([run])
    assert rows_to_csv(rows).splitlines()[0].startswith("topic,generated_at,run_dir")
    assert rows_to_json(rows).startswith("[\n")
    json_out = tmp_path / "matrix.json"
    csv_out = tmp_path / "matrix.csv"
    rc = main([
        str(run), "--format", "json", "--json-out", str(json_out), "--csv-out", str(csv_out),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.startswith("[\n")
    assert json_out.exists()
    assert csv_out.read_text(encoding="utf-8").splitlines()[0].startswith("topic,")
