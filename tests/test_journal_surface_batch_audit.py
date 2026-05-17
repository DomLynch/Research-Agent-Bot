from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import journal_surface_batch_audit as audit  # noqa: E402


def _run(tmp_path: Path, body: str) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "full_paper.md").write_text(body, encoding="utf-8")
    return run_dir


def _words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_appendix_boundary_excludes_forbidden_meta(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        "## Abstract\n\nClean public text.\n\n"
        "## Publication Appendix\n\n"
        "LLM proposes, code disposes.\n\n"
        "[citation needed]\n\n"
        "## Quantitative Evidence Index\n\n"
        "| Kell 2026 | mTOR signaling | placebo | p<0.001 |\n",
    )

    report = audit.build_report([run_dir])

    assert report["passed"]


def test_ai_use_boundary_excludes_disclosure_meta(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        "## Abstract\n\nClean public text.\n\n"
        "## AI-Use Disclosure\n\nfinal-layer reviewer and SPAR are documented here.\n",
    )

    report = audit.build_report([run_dir])

    assert report["passed"]


def test_forbidden_meta_in_public_body_fails(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "## Discussion\n\nThe run manifest is visible.\n")

    report = audit.build_report([run_dir])

    assert not report["passed"]
    assert report["runs"][0]["issues"][0]["issue_type"] == "audit_meta"


def test_deterministic_backfill_and_placeholder_prose_fail(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        "## Background\n\n"
        "This paper evaluates the topic through accepted receipts.\n\n"
        "## Conclusion\n\nDeterministic evidence summary.\n",
    )

    issues = audit.build_report([run_dir])["runs"][0]["issues"]

    assert {issue["issue_type"] for issue in issues} == {"placeholder"}
    assert len(issues) == 2


def test_duplicate_paragraph_threshold(tmp_path: Path) -> None:
    paragraph = _words("alpha", 35)
    near_duplicate = paragraph + " extra_token"
    distinct = _words("beta", 35)
    run_dir = _run(tmp_path, f"{paragraph}\n\n{near_duplicate}\n\n{distinct}\n")

    issues = audit.build_report([run_dir])["runs"][0]["issues"]

    assert [issue["issue_type"] for issue in issues] == ["duplicate_paragraph"]
    assert issues[0]["detail"] == "token_overlap=1.00"


def test_citation_qei_and_hedge_fragments_fail(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        "## Results\n\n[citation needed]\n\nMay.\n\n"
        "## Quantitative Evidence Index\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Palmer 2021ucos | fasting glucose | control | — | — | — |\n"
        "| Kell 2026 | mTOR signaling | placebo | p<0.001 |\n",
    )

    issue_types = [
        issue["issue_type"]
        for issue in audit.build_report([run_dir])["runs"][0]["issues"]
    ]

    assert "citation_artifact" in issue_types
    assert "standalone_hedge_fragment" in issue_types
    assert issue_types.count("malformed_qei_row") == 3


def test_outputs_json_csv_and_markdown(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "## Abstract\n\nClean public text.\n")
    json_out = tmp_path / "report.json"
    csv_out = tmp_path / "report.csv"
    md_out = tmp_path / "report.md"

    code = audit.main([
        str(run_dir),
        "--json-out", str(json_out),
        "--csv-out", str(csv_out),
        "--md-out", str(md_out),
    ])

    assert code == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["passed"]
    assert csv_out.read_text(encoding="utf-8").startswith("run_dir,manuscript")
    assert "# Journal Surface Batch Audit" in md_out.read_text(encoding="utf-8")


def test_missing_manuscript_fails_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    report = audit.build_report([run_dir])

    assert not report["passed"]
    assert report["runs"][0]["issues"][0]["issue_type"] == "missing_or_unreadable"
