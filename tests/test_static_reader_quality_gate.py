from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from export_static_reader import export_static_reader  # noqa: E402
from static_reader_quality_gate import main, validate_static_reader  # noqa: E402


def _write_reader(tmp_path: Path, *, href: str = "paper.md", extra: str = "") -> Path:
    (tmp_path / "paper.md").write_text("# Paper", encoding="utf-8")
    (tmp_path / "versions.html").write_text("versions", encoding="utf-8")
    index = tmp_path / "index.html"
    index.write_text(
        "<!doctype html><html><head>"
        '<script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@type": "ScholarlyArticle"})
        + "</script></head><body>"
        '<section id="trust"><h2>Trust panel</h2></section>'
        "<h2>Artifacts</h2>"
        f'<a href="{href}">paper</a>'
        '<a href="versions.html">versions</a>'
        f"{extra}</body></html>",
        encoding="utf-8",
    )
    return index


def test_quality_gate_passes_valid_static_reader(tmp_path: Path) -> None:
    result = validate_static_reader(_write_reader(tmp_path))

    assert result.passed
    assert result.checks["json_ld"]
    assert result.checks["version_index"]


def test_quality_gate_fails_missing_referenced_file(tmp_path: Path) -> None:
    result = validate_static_reader(_write_reader(tmp_path, href="missing.md"))

    assert not result.passed
    assert "referenced_files_exist" in result.errors


def test_quality_gate_fails_unsafe_links(tmp_path: Path) -> None:
    result = validate_static_reader(_write_reader(tmp_path, href="../outside.md"))

    assert not result.passed
    assert "safe_links" in result.errors


def test_quality_gate_fails_raw_script_from_markdown(tmp_path: Path) -> None:
    result = validate_static_reader(
        _write_reader(tmp_path, extra="<script>alert(1)</script>")
    )

    assert not result.passed
    assert "no_raw_script_from_markdown" in result.errors


def test_quality_gate_reports_json_failure(tmp_path: Path) -> None:
    index = _write_reader(tmp_path)
    text = index.read_text(encoding="utf-8").replace(
        '{"@context": "https://schema.org", "@type": "ScholarlyArticle"}',
        "{bad",
    )
    index.write_text(text, encoding="utf-8")

    result = validate_static_reader(index)

    assert not result.passed
    assert "json_ld" in result.errors
    assert json.loads(result.to_json())["passed"] is False


def test_quality_gate_fails_missing_version_index(tmp_path: Path) -> None:
    index = _write_reader(tmp_path)
    (tmp_path / "versions.html").unlink()

    result = validate_static_reader(index)

    assert not result.passed
    assert "version_index" in result.errors


def test_quality_gate_cli_reports_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    index = _write_reader(tmp_path)

    assert main([str(index)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True


def test_quality_gate_real_run_export_smoke(tmp_path: Path) -> None:
    run = REPO / "runs" / "synthesis-metformin-v06-FINAL-2026-05-05T21-15-00Z"
    if not run.exists():
        pytest.skip("real synthesis run fixture not present")

    index = export_static_reader(run, tmp_path / "site")
    result = validate_static_reader(index)

    assert result.passed, result.errors
