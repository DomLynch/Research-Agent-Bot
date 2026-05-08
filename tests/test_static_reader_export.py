from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from export_static_reader import export_static_reader, render_index  # noqa: E402


def test_static_reader_escapes_html_and_links_manifest_artifacts(tmp_path: Path) -> None:
    manifest = {
        "topic": "<beta>",
        "generated_at": "2026-05-01",
        "thesis": "A < B & C",
        "artifacts": [{"label": "Paper <md>", "path": "paper.md?x=<1>"}],
    }

    html = render_index(manifest, tmp_path)

    assert "<h1>&lt;beta&gt;</h1>" in html
    assert "A &lt; B &amp; C" in html
    assert 'href="paper.md?x=&lt;1&gt;"' in html
    assert "Paper &lt;md&gt;" in html


def test_static_reader_rejects_absolute_or_scheme_links(tmp_path: Path) -> None:
    html = render_index({
        "topic": "alpha",
        "artifacts": [
            {"label": "bad", "path": "javascript:alert(1)"},
            {"label": "abs", "path": "/tmp/paper.md"},
            {"label": "trav", "path": "../outside.txt"},
        ],
    }, tmp_path)

    assert 'href="#"' in html
    assert "javascript:alert" not in html
    assert "../outside" not in html


def test_static_reader_exports_from_run_dir(tmp_path: Path) -> None:
    run = tmp_path / "run"
    out = tmp_path / "site"
    run.mkdir()
    (run / "full_paper.md").write_text("# Paper", encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"topic": "alpha"}), encoding="utf-8")

    index = export_static_reader(run, out)

    assert index == out / "index.html"
    assert "full_paper.md" in index.read_text(encoding="utf-8")
    assert (out / "versions.html").exists()


def test_static_reader_prefers_reader_manifest(tmp_path: Path) -> None:
    run = tmp_path / "run"
    out = tmp_path / "site"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "fallback"}), encoding="utf-8")
    (run / "researka_reader_manifest.json").write_text(
        json.dumps({"topic": "reader"}),
        encoding="utf-8",
    )

    index = export_static_reader(run, out)

    assert "<h1>reader</h1>" in index.read_text(encoding="utf-8")


def test_static_reader_renders_safe_markdown_and_trust_panel(tmp_path: Path) -> None:
    run = tmp_path / "run"
    out = tmp_path / "site"
    run.mkdir()
    (run / "full_paper.md").write_text(
        "# Title <x>\n\nText **bold** `code` <script>",
        encoding="utf-8",
    )
    (run / "full_paper.audit.json").write_text(
        json.dumps({"score_out_of_10": 8.7, "p1_pass": True}),
        encoding="utf-8",
    )
    (run / "full_paper.final_verdict.md").write_text("Accept <clean>", encoding="utf-8")
    (run / "manifest.json").write_text(
        json.dumps({"topic": "alpha", "n_receipts": 2}),
        encoding="utf-8",
    )

    text = export_static_reader(run, out).read_text(encoding="utf-8")

    assert "<h1>Title &lt;x&gt;</h1>" in text
    assert "<strong>bold</strong>" in text
    assert "&lt;script&gt;" in text
    assert "Accept &lt;clean&gt;" in text
    assert "<script>" not in text


def test_static_reader_emits_json_ld_metadata(tmp_path: Path) -> None:
    html = render_index({
        "topic": "alpha",
        "generated_at": "2026-05-08T00:00:00Z",
        "thesis": "A & B </script>",
    }, tmp_path)

    assert 'application/ld+json' in html
    assert "A &amp; B" in html
    match = re.search(
        r'<script type="application/ld\+json">(.+?)</script>',
        html,
    )
    assert match is not None
    data = json.loads(match.group(1))
    assert data["@type"] == "ScholarlyArticle"
    assert data["description"] == "A & B </script>"
