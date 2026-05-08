"""Minimal static HTML reader export for a run directory or reader manifest."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


def export_static_reader(source: Path, out_dir: Path) -> Path:
    manifest, base = _load_manifest(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render_index(manifest, base), encoding="utf-8")
    (out_dir / "versions.html").write_text(render_versions([manifest]), encoding="utf-8")
    return index


def render_index(manifest: dict[str, Any], base: Path) -> str:
    topic = _escape(str(manifest.get("topic") or manifest.get("title") or "Untitled run"))
    generated = _escape(str(manifest.get("generated_at") or manifest.get("finished_at") or ""))
    thesis = _escape(str(manifest.get("thesis") or ""))
    links = _links(manifest, base)
    items = "\n".join(
        f'<li><a href="{_escape(_safe_href(href))}">{_escape(label)}</a></li>'
        for label, href in links
    )
    paper = _render_paper(base)
    trust = _render_trust_panel(base)
    json_ld = _json_ld(manifest)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head><meta charset="utf-8">'
        f"<title>{topic}</title>"
        f'<script type="application/ld+json">{json_ld}</script></head>\n<body>\n'
        f"<h1>{topic}</h1>\n"
        f"<p><strong>Generated:</strong> {generated}</p>\n"
        f"<p>{thesis}</p>\n"
        f"{trust}\n"
        "<h2>Artifacts</h2>\n"
        f"<ul>\n{items}\n</ul>\n"
        "<p><a href=\"versions.html\">Version index</a></p>\n"
        f"{paper}\n"
        "</body>\n</html>\n"
    )


def render_versions(manifests: list[dict[str, Any]]) -> str:
    rows = []
    for manifest in sorted(manifests, key=lambda m: str(m.get("generated_at", ""))):
        topic = _escape(str(manifest.get("topic") or manifest.get("title") or "Untitled"))
        generated = _escape(str(manifest.get("generated_at") or manifest.get("finished_at") or ""))
        rows.append(f"<li>{topic} {generated}</li>")
    return "<!doctype html>\n<html><body><h1>Versions</h1><ul>\n" + "\n".join(rows) + "\n</ul></body></html>\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    print(export_static_reader(args.source, args.out_dir))
    return 0


def _load_manifest(source: Path) -> tuple[dict[str, Any], Path]:
    if source.is_dir():
        for name in ("researka_reader_manifest.json", "manifest.json"):
            candidate = source / name
            if candidate.exists():
                return _read_json(candidate), source
        return {}, source
    return _read_json(source), source.parent


def _links(manifest: dict[str, Any], base: Path) -> list[tuple[str, str]]:
    raw = manifest.get("artifacts")
    if isinstance(raw, list):
        return [
            (str(item.get("label") or item.get("path") or "artifact"), str(item.get("path")))
            for item in raw
            if isinstance(item, dict) and item.get("path")
        ]
    names = (
        "full_paper.md",
        "full_paper.audit.json",
        "full_paper.final_verdict.md",
        "full_paper.certification.md",
        "manifest.json",
    )
    return [(name, name) for name in names if (base / name).exists()]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _safe_href(value: str) -> str:
    if (
        value.startswith(("/", "//"))
        or ":" in value.split("/", 1)[0]
        or ".." in Path(value.split("?", 1)[0]).parts
    ):
        return "#"
    return value


def _safe_child(base: Path, name: str) -> Path | None:
    path = (base / name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path


def _render_paper(base: Path) -> str:
    path = _safe_child(base, "full_paper.md")
    if path is None or not path.exists():
        return ""
    return '<article id="paper">\n' + _markdown_to_html(path.read_text(encoding="utf-8")) + "\n</article>"


def _markdown_to_html(markdown: str) -> str:
    lines = []
    for raw in markdown.splitlines():
        text = raw.strip()
        if not text:
            continue
        if text.startswith("#"):
            level = min(len(text) - len(text.lstrip("#")), 3)
            body = _escape(text[level:].strip())
            lines.append(f"<h{level}>{body}</h{level}>")
        else:
            body = _escape(text)
            body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
            body = re.sub(r"`(.+?)`", r"<code>\1</code>", body)
            lines.append(f"<p>{body}</p>")
    return "\n".join(lines)


def _render_trust_panel(base: Path) -> str:
    audit = _read_json(base / "full_paper.audit.json")
    manifest = _read_json(base / "manifest.json")
    verdict = _read_text(base / "full_paper.final_verdict.md")
    cert = _read_text(base / "full_paper.certification.md")
    bits = [
        ("Verdict", verdict.splitlines()[0] if verdict else _verdict_from_audit(audit)),
        ("Audit score", str(audit.get("score_out_of_10", "unknown"))),
        ("P1 pass", str(audit.get("p1_pass", "unknown")).lower()),
        ("Receipts", str(manifest.get("n_receipts", "unknown"))),
        ("Certification", cert.splitlines()[0] if cert else "not provided"),
    ]
    items = "".join(f"<li><strong>{_escape(k)}:</strong> {_escape(v)}</li>" for k, v in bits)
    return f"<section id=\"trust\"><h2>Trust panel</h2><ul>{items}</ul></section>"


def _json_ld(manifest: dict[str, Any]) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "name": manifest.get("topic") or manifest.get("title") or "Untitled run",
        "dateCreated": manifest.get("generated_at") or manifest.get("finished_at"),
        "description": manifest.get("thesis", ""),
    }
    return (
        json.dumps(data, ensure_ascii=True, sort_keys=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _verdict_from_audit(audit: dict[str, Any]) -> str:
    if not audit:
        return "unknown"
    return "pass" if audit.get("p1_pass") is True else "fail"


if __name__ == "__main__":
    raise SystemExit(main())
