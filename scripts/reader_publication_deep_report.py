"""Deep readiness report for static reader publication exports."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReaderRow:
    run: str
    topic: str
    gate_passed: bool
    trust_panel: bool
    audit_p1_pass: bool
    json_ld: bool
    safe_links: bool
    files_exist: bool
    has_citation_export: bool
    has_bundle_hashes: bool
    has_topic_index: bool
    has_version_index: bool
    issues: tuple[str, ...]
    readiness_score: int


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.scripts: list[tuple[str, str]] = []
        self._script_type: str | None = None
        self._body: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if data.get("id"):
            self.ids.add(str(data["id"]))
        if tag == "a" and data.get("href"):
            self.links.append(str(data["href"]))
        if tag == "script":
            self._script_type = str(data.get("type") or "")
            self._body = []

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._body.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script_type is not None:
            self.scripts.append((self._script_type, "".join(self._body)))
            self._script_type = None


def build_report(static_root: Path) -> dict[str, Any]:
    rows = [
        _row(path, static_root)
        for path in sorted(static_root.iterdir())
        if path.is_dir() and (path / "index.html").exists() and (path / "manifest.json").exists()
    ]
    by_topic: dict[str, list[str]] = {}
    for row in rows:
        by_topic.setdefault(row.topic, []).append(row.run)
    return {
        "readers": [asdict(row) for row in rows],
        "topics": {topic: sorted(runs) for topic, runs in sorted(by_topic.items())},
        "foundation_candidates": [
            row.run for row in rows
            if row.gate_passed and row.trust_panel and row.json_ld
            and row.safe_links and row.files_exist and row.audit_p1_pass
        ],
        "v2_public_candidates": [
            row.run for row in rows if row.readiness_score >= 90 and not row.issues
        ],
        "blocked": {row.run: row.issues for row in rows if row.issues},
        "missing_v2_pieces": sorted({
            issue for row in rows for issue in row.issues
            if issue != "audit_p1_pass"
        }),
    }


def write_report(static_root: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(static_root)
    json_path = out_dir / "deep_report.json"
    md_path = out_dir / "deep_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(_to_markdown(report))
    return json_path, md_path


def build_run_bundle_report(run_dirs: list[Path]) -> dict[str, Any]:
    rows = [_run_bundle_row(path) for path in sorted(run_dirs)]
    return {
        "runs": rows,
        "must_build": sorted({item for row in rows for item in row["missing"]}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("static_root", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    json_path, _ = write_report(args.static_root, args.out_dir)
    print(json_path)
    return 0


def _row(path: Path, static_root: Path) -> ReaderRow:
    manifest = _read_json(path / "manifest.json")
    audit = _read_json(path / "full_paper.audit.json")
    gate = _read_json(path / "quality_gate.json")
    parser = _parse(path / "index.html")
    topic = str(manifest.get("topic") or manifest.get("title") or "unknown")
    checks = {
        "gate_passed": gate.get("passed") is True,
        "trust_panel": "trust" in parser.ids,
        "audit_p1_pass": audit.get("p1_pass") is True,
        "json_ld": _valid_json_ld(parser.scripts),
        "safe_links": all(_safe_href(href) for href in parser.links),
        "files_exist": all(_file_exists(path, href) for href in parser.links),
        "has_citation_export": _has_citation_export(path),
        "has_bundle_hashes": _has_bundle_hashes(path),
        "has_topic_index": (static_root / "topics" / topic / "index.html").exists(),
        "has_version_index": _version_index_has_run(path / "versions.html", path.name),
    }
    issues = tuple(name for name, ok in checks.items() if not ok)
    score = max(0, 100 - (10 * len(issues)))
    return ReaderRow(
        run=path.name,
        topic=topic,
        issues=issues,
        readiness_score=score,
        **checks,
    )


def _run_bundle_row(path: Path) -> dict[str, Any]:
    manifest = _read_json(path / "manifest.json")
    audit = _read_json(path / "full_paper.audit.json")
    required = {
        "topic": bool(manifest.get("topic")),
        "title_or_thesis": bool(manifest.get("title") or manifest.get("thesis")),
        "generated_at": bool(manifest.get("generated_at")),
        "paper": (path / "full_paper.md").exists(),
        "audit": bool(audit),
        "audit_p1_pass": audit.get("p1_pass") is True,
        "receipt_count": isinstance(manifest.get("n_receipts"), int),
        "tension_count": isinstance(manifest.get("n_non_orthogonal_tensions"), int),
        "verdict": (path / "full_paper.final_verdict.md").exists(),
        "certification": (path / "full_paper.certification.md").exists(),
    }
    missing = tuple(name for name, ok in required.items() if not ok)
    return {
        "run": path.name,
        "topic": manifest.get("topic") or "",
        "ready_for_reader_export": not missing,
        "missing": missing,
    }


def _parse(path: Path) -> _Parser:
    parser = _Parser()
    if path.exists():
        parser.feed(path.read_text(encoding="utf-8"))
    return parser


def _valid_json_ld(scripts: list[tuple[str, str]]) -> bool:
    for kind, body in scripts:
        if kind != "application/ld+json":
            continue
        data = _loads(body)
        return data.get("@context") == "https://schema.org" and bool(data.get("name"))
    return False


def _safe_href(href: str) -> bool:
    if href == "#":
        return True
    if href.startswith(("/", "//")) or ":" in href.split("/", 1)[0]:
        return False
    return ".." not in Path(href.split("?", 1)[0]).parts


def _file_exists(base: Path, href: str) -> bool:
    if href == "#":
        return True
    rel = href.split("#", 1)[0].split("?", 1)[0]
    return bool(rel) and (base / rel).exists()


def _has_citation_export(path: Path) -> bool:
    return (path / "citation.bib").exists() and (path / "citation.csl.json").exists()


def _has_bundle_hashes(path: Path) -> bool:
    bundle = _read_json(path / "bundle_manifest.json")
    files = bundle.get("files")
    if not isinstance(files, list) or not files:
        return False
    for item in files:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            return False
        target = path / str(item["path"])
        if not target.exists() or _sha256(target) != item["sha256"]:
            return False
    return True


def _version_index_has_run(path: Path, run: str) -> bool:
    return path.exists() and run in path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Deep Reader Publication Report",
        "",
        "| Run | Topic | Score | Issues |",
        "|---|---:|---:|---|",
    ]
    for row in report["readers"]:
        issues = ", ".join(row["issues"]) or "none"
        lines.append(f"| {row['run']} | {row['topic']} | {row['readiness_score']} | {issues} |")
    lines += [
        "",
        "## Safe Candidates",
        "",
        "\n".join(f"- {run}" for run in report["foundation_candidates"]) or "- none",
        "",
        "## V2 Public Candidates",
        "",
        "\n".join(f"- {run}" for run in report["v2_public_candidates"]) or "- none",
        "",
        "## Missing V2 Pieces",
        "",
        "\n".join(f"- {item}" for item in report["missing_v2_pieces"]) or "- none",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
