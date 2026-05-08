from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import journal_surface_root_cause as root_cause  # noqa: E402


def test_excerpt_report_maps_phrase_and_duplicate_lines(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    paragraph = " ".join(f"alpha{i}" for i in range(35))
    paper = run / "full_paper.md"
    paper.write_text(
        "## Methods\n\n"
        "This synthesis was produced by a demo pipeline.\n\n"
        f"{paragraph}\n\n{paragraph}\n",
        encoding="utf-8",
    )
    audit_json = tmp_path / "audit.json"
    audit_json.write_text(json.dumps({
        "runs": [{
            "run_dir": str(run),
            "manuscript": str(paper),
            "issues": [
                {
                    "issue_type": "template_meta",
                    "location": "body",
                    "detail": "this synthesis was produced by",
                },
                {
                    "issue_type": "duplicate_paragraph",
                    "location": "paragraphs 1,2",
                    "detail": "token_overlap=1.00",
                },
            ],
        }],
    }), encoding="utf-8")

    report = root_cause.excerpt_report(audit_json)

    assert report["rows"][0]["hits"][0]["line"] == 3
    assert [hit["line"] for hit in report["rows"][1]["hits"]] == [5, 7]
