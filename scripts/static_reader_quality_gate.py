"""Quality gate for exported static reader HTML."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    checks: dict[str, bool]
    errors: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class _ReaderParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.headings: list[str] = []
        self.links: list[str] = []
        self.scripts: list[tuple[str, str]] = []
        self._tag: str | None = None
        self._in_script = False
        self._script_type = ""
        self._script_body: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if attrs_map.get("id"):
            self.ids.add(str(attrs_map["id"]))
        if tag in {"h1", "h2"}:
            self._tag = tag
        if tag == "a" and attrs_map.get("href"):
            self.links.append(str(attrs_map["href"]))
        if tag == "script":
            self._in_script = True
            self._script_type = str(attrs_map.get("type") or "")
            self._script_body = []

    def handle_data(self, data: str) -> None:
        if self._tag in {"h1", "h2"}:
            self.headings.append(data.strip())
        if self._in_script:
            self._script_body.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._tag:
            self._tag = None
        if tag == "script" and self._in_script:
            self.scripts.append((self._script_type, "".join(self._script_body)))
            self._in_script = False
            self._script_type = ""


def validate_static_reader(index: Path) -> GateResult:
    text = index.read_text(encoding="utf-8")
    parser = _ReaderParser()
    parser.feed(text)
    checks = {
        "trust_panel": "trust" in parser.ids,
        "artifacts_section": any(h == "Artifacts" for h in parser.headings),
        "json_ld": _has_valid_json_ld(parser.scripts),
        "no_raw_script_from_markdown": _no_raw_script_from_markdown(parser.scripts),
        "safe_links": all(_safe_href(href) for href in parser.links),
        "referenced_files_exist": all(_exists(index.parent, href) for href in parser.links),
        "version_index": "versions.html" in parser.links
        and (index.parent / "versions.html").exists(),
    }
    errors = tuple(name for name, passed in checks.items() if not passed)
    return GateResult(passed=not errors, checks=checks, errors=errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    args = parser.parse_args(argv)
    result = validate_static_reader(args.index)
    print(result.to_json())
    return 0 if result.passed else 1


def _has_valid_json_ld(scripts: list[tuple[str, str]]) -> bool:
    for script_type, body in scripts:
        if script_type == "application/ld+json":
            try:
                data: Any = json.loads(body)
            except json.JSONDecodeError:
                return False
            return isinstance(data, dict) and data.get("@context") == "https://schema.org"
    return False


def _no_raw_script_from_markdown(scripts: list[tuple[str, str]]) -> bool:
    return all(script_type == "application/ld+json" for script_type, _ in scripts)


def _safe_href(href: str) -> bool:
    if href == "#":
        return True
    if href.startswith(("/", "//")) or ":" in href.split("/", 1)[0]:
        return False
    return ".." not in Path(href.split("?", 1)[0]).parts


def _exists(base: Path, href: str) -> bool:
    if href in {"#", "versions.html"}:
        return True
    target = (base / href.split("#", 1)[0].split("?", 1)[0]).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return False
    return target.exists()


if __name__ == "__main__":
    raise SystemExit(main())
