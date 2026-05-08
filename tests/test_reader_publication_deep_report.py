from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from reader_publication_deep_report import build_report, write_report  # noqa: E402


def _reader(root: Path, run: str, topic: str = "alpha") -> Path:
    path = root / run
    path.mkdir(parents=True)
    (path / "paper.md").write_text("# Paper", encoding="utf-8")
    (path / "versions.html").write_text(f"<li>{run}</li>", encoding="utf-8")
    (path / "manifest.json").write_text(json.dumps({"topic": topic}), encoding="utf-8")
    (path / "quality_gate.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (path / "full_paper.audit.json").write_text(
        json.dumps({"p1_pass": True}),
        encoding="utf-8",
    )
    (path / "citation.bib").write_text("@article{x}", encoding="utf-8")
    (path / "citation.csl.json").write_text("[]", encoding="utf-8")
    digest = hashlib.sha256((path / "paper.md").read_bytes()).hexdigest()
    (path / "bundle_manifest.json").write_text(
        json.dumps({"files": [{"path": "paper.md", "sha256": digest}]}),
        encoding="utf-8",
    )
    (path / "index.html").write_text(
        '<section id="trust"></section><a href="paper.md">paper</a>'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","name":"Alpha"}'
        "</script>",
        encoding="utf-8",
    )
    return path


def test_deep_report_groups_multiple_versions_per_topic(tmp_path: Path) -> None:
    root = tmp_path / "static"
    _reader(root, "run-1", "alpha")
    _reader(root, "run-2", "alpha")
    (root / "topics" / "alpha").mkdir(parents=True)
    (root / "topics" / "alpha" / "index.html").write_text("alpha", encoding="utf-8")

    report = build_report(root)

    assert report["topics"]["alpha"] == ["run-1", "run-2"]
    assert not report["blocked"]
    assert report["v2_public_candidates"] == ["run-1", "run-2"]


def test_deep_report_flags_missing_links_json_ld_and_trust(tmp_path: Path) -> None:
    root = tmp_path / "static"
    path = _reader(root, "run-1")
    (path / "index.html").write_text('<a href="missing.md">missing</a>', encoding="utf-8")

    row = build_report(root)["readers"][0]

    assert "trust_panel" in row["issues"]
    assert "json_ld" in row["issues"]
    assert "files_exist" in row["issues"]
    assert "run-1" not in build_report(root)["v2_public_candidates"]


def test_deep_report_flags_invalid_citation_and_bundle_metadata(tmp_path: Path) -> None:
    root = tmp_path / "static"
    path = _reader(root, "run-1")
    (path / "citation.bib").unlink()
    (path / "bundle_manifest.json").write_text(
        json.dumps({"files": [{"path": "paper.md", "sha256": "bad"}]}),
        encoding="utf-8",
    )

    row = build_report(root)["readers"][0]

    assert "has_citation_export" in row["issues"]
    assert "has_bundle_hashes" in row["issues"]


def test_deep_report_blocks_failed_audit_p1(tmp_path: Path) -> None:
    root = tmp_path / "static"
    path = _reader(root, "run-1")
    (path / "full_paper.audit.json").write_text(
        json.dumps({"p1_pass": False}),
        encoding="utf-8",
    )

    report = build_report(root)

    assert "audit_p1_pass" in report["readers"][0]["issues"]
    assert report["foundation_candidates"] == []


def test_write_report_outputs_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "static"
    _reader(root, "run-1")

    json_path, md_path = write_report(root, tmp_path / "out")

    assert json.loads(json_path.read_text())["readers"][0]["run"] == "run-1"
    assert "Deep Reader Publication Report" in md_path.read_text()
