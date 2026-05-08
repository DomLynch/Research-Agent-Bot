"""Read-only summary for exported static-reader campaign dirs."""
from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()
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


def summarize_exports(static_root: Path) -> list[dict[str, Any]]:
    rows = [_summarize_one(path) for path in sorted(static_root.iterdir()) if path.is_dir()]
    return sorted(rows, key=lambda row: str(row["run"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("static_root", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(summarize_exports(args.static_root), indent=2, sort_keys=True))
    return 0


def _summarize_one(path: Path) -> dict[str, Any]:
    manifest = _read_json(path / "manifest.json")
    audit = _read_json(path / "full_paper.audit.json")
    gate = _read_json(path / "quality_gate.json")
    parser = _Parser()
    parser.feed((path / "index.html").read_text(encoding="utf-8"))
    json_ld = [_loads(body) for kind, body in parser.scripts if kind == "application/ld+json"]
    files_ok = all(_file_exists(path, href) for href in parser.links)
    score = _score(gate, audit, manifest, files_ok)
    return {
        "run": path.name,
        "topic": manifest.get("topic") or manifest.get("title") or "",
        "passed_gate": gate.get("passed") is True,
        "gate_errors": gate.get("errors", []),
        "audit_score": audit.get("score_out_of_10"),
        "p1_pass": audit.get("p1_pass"),
        "receipts": manifest.get("n_receipts"),
        "tensions": manifest.get("n_non_orthogonal_tensions"),
        "link_count": len(parser.links),
        "all_link_files_exist": files_ok,
        "trust_panel": "trust" in parser.ids,
        "json_ld_type": json_ld[0].get("@type") if json_ld else "",
        "readiness_score": score,
        "ready_public_static": score >= 90
        and gate.get("passed") is True
        and audit.get("p1_pass") is True,
    }


def _score(
    gate: dict[str, Any], audit: dict[str, Any], manifest: dict[str, Any], files_ok: bool
) -> int:
    score = 100 if gate.get("passed") is True and files_ok else 60
    if audit.get("p1_pass") is not True:
        score -= 10
    if (audit.get("score_out_of_10") or 0) < 8.5:
        score -= 10
    if not (manifest.get("topic") or manifest.get("title")):
        score -= 5
    return max(score, 0)


def _file_exists(base: Path, href: str) -> bool:
    if href == "#":
        return True
    rel = href.split("?", 1)[0].split("#", 1)[0]
    return bool(rel) and (base / rel).exists()


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


if __name__ == "__main__":
    raise SystemExit(main())
