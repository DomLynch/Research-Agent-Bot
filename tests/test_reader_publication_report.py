from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from reader_publication_report import summarize_exports  # noqa: E402


def test_summarize_exports_scores_static_bundle(tmp_path: Path) -> None:
    export = tmp_path / "static" / "run-a"
    export.mkdir(parents=True)
    (export / "paper.md").write_text("# Paper", encoding="utf-8")
    (export / "versions.html").write_text("versions", encoding="utf-8")
    (export / "manifest.json").write_text(
        json.dumps({"topic": "alpha", "n_receipts": 2, "n_non_orthogonal_tensions": 1}),
        encoding="utf-8",
    )
    (export / "full_paper.audit.json").write_text(
        json.dumps({"score_out_of_10": 9.0, "p1_pass": True}),
        encoding="utf-8",
    )
    (export / "quality_gate.json").write_text(
        json.dumps({"passed": True, "errors": []}),
        encoding="utf-8",
    )
    (export / "index.html").write_text(
        '<section id="trust"></section><a href="paper.md">paper</a>'
        '<a href="versions.html">versions</a>'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"ScholarlyArticle"}'
        "</script>",
        encoding="utf-8",
    )

    row = summarize_exports(tmp_path / "static")[0]

    assert row["readiness_score"] == 100
    assert row["ready_public_static"] is True
    assert row["all_link_files_exist"] is True


def test_summarize_exports_penalizes_missing_topic_and_failed_audit(tmp_path: Path) -> None:
    export = tmp_path / "static" / "run-b"
    export.mkdir(parents=True)
    (export / "manifest.json").write_text("{}", encoding="utf-8")
    (export / "full_paper.audit.json").write_text(
        json.dumps({"score_out_of_10": 6.0, "p1_pass": False}),
        encoding="utf-8",
    )
    (export / "quality_gate.json").write_text(
        json.dumps({"passed": True, "errors": []}),
        encoding="utf-8",
    )
    (export / "index.html").write_text("", encoding="utf-8")

    row = summarize_exports(tmp_path / "static")[0]

    assert row["readiness_score"] == 75
    assert row["ready_public_static"] is False


def test_summarize_exports_requires_p1_for_public_ready(tmp_path: Path) -> None:
    export = tmp_path / "static" / "run-c"
    export.mkdir(parents=True)
    (export / "manifest.json").write_text(json.dumps({"topic": "alpha"}), encoding="utf-8")
    (export / "full_paper.audit.json").write_text(
        json.dumps({"score_out_of_10": 9.3, "p1_pass": False}),
        encoding="utf-8",
    )
    (export / "quality_gate.json").write_text(
        json.dumps({"passed": True, "errors": []}),
        encoding="utf-8",
    )
    (export / "index.html").write_text("", encoding="utf-8")

    row = summarize_exports(tmp_path / "static")[0]

    assert row["readiness_score"] == 90
    assert row["ready_public_static"] is False
