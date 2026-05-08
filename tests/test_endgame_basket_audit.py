from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from endgame_basket_audit import audit, main, rows_to_json, rows_to_markdown  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(
    tmp_path: Path,
    name: str,
    *,
    topic: str = "alpha",
    receipts: int = 20,
    maturity: int = 5,
) -> Path:
    run = tmp_path / name
    run.mkdir()
    _write_json(run / "manifest.json", {
        "topic": topic,
        "generated_at": name,
        "n_receipts": receipts,
        "n_non_orthogonal_tensions": 3,
        "n_high_confidence_claims_total": 30,
    })
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "AAA" if maturity >= 5 else "SHIP-BLOCKED",
        "maturity_level": maturity,
        "journal_surface_pass": True,
    })
    return run


def test_audit_marks_weakest_run_and_repeated_classifier_signal(tmp_path: Path) -> None:
    js = _run(tmp_path, "2026-01", topic="alpha")
    grok_a = _run(tmp_path, "2026-02", topic="beta")
    grok_b = _run(tmp_path, "2026-03", topic="gamma")
    _write_json(js / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 5,
        "journal_surface_pass": False,
    })
    _write_json(grok_a / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 5,
        "grok_unresolved_p1": 1,
        "journal_surface_pass": True,
    })
    _write_json(grok_b / "full_paper.final_verdict.json", {
        "verdict": "AAA",
        "maturity_level": 5,
        "grok_unresolved_p1": 2,
        "journal_surface_pass": True,
    })

    data = audit([grok_b, js, grok_a])

    assert data["weakest"]["failure_class"] == "js"
    assert data["universal_classifier_fix_indicated"] is True
    assert "grok" in data["universal_classifier_fix_reason"]


def test_audit_marks_l5_not_l6_and_cert_regression(tmp_path: Path) -> None:
    base = _run(tmp_path, "base", topic="alpha", receipts=24, maturity=5)
    new = _run(tmp_path, "new", topic="alpha", receipts=18, maturity=4)

    data = audit([new], baseline_paths=[base])

    assert data["runs"][0]["regression"] is True
    assert data["cert_regressed"][0]["run_dir"] == "new"
    assert data["l5_not_l6"] == []


def test_audit_marks_l5_without_l6(tmp_path: Path) -> None:
    run = _run(tmp_path, "single-l5", topic="alpha", receipts=20, maturity=5)

    data = audit([run])

    assert data["l5_not_l6"][0]["run_dir"] == "single-l5"
    assert data["runs"][0]["l6_candidate"] is False


def test_audit_does_not_mark_thin_false_positive_for_missing_high_claims(
    tmp_path: Path,
) -> None:
    run = tmp_path / "not-thin"
    run.mkdir()
    _write_json(run / "manifest.json", {
        "topic": "alpha",
        "generated_at": "not-thin",
        "n_receipts": 20,
    })
    _write_json(run / "full_paper.final_verdict.json", {
        "verdict": "SHIP-BLOCKED",
        "maturity_level": 4,
        "journal_surface_pass": True,
    })

    data = audit([run])

    assert data["runs"][0]["failure_class"] == "verdict"
    assert data["thin_false_positive_suspects"] == []


def test_audit_outputs_json_and_markdown_files(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "pass", topic="alpha")
    json_out = tmp_path / "audit.json"
    md_out = tmp_path / "audit.md"

    rc = main([
        str(run),
        "--format",
        "json",
        "--json-out",
        str(json_out),
        "--markdown-out",
        str(md_out),
    ])
    captured = capsys.readouterr()
    data = json.loads(json_out.read_text(encoding="utf-8"))

    assert rc == 0
    assert captured.out.startswith("{\n")
    assert rows_to_json(data).startswith("{\n")
    assert rows_to_markdown(data).startswith("# Endgame Basket Audit")
    assert md_out.read_text(encoding="utf-8").startswith("# Endgame Basket Audit")
