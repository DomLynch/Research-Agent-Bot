"""Preserve agent evidence proof when constructing publication payloads."""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from agent.source_hygiene import is_notice_only_source_title

def source_rows(registry: dict[str, Any], receipts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in registry.values() if isinstance(row, dict)
        and not is_notice_only_source_title(
            row.get("title") or receipts.get(str(row.get("receipt_id")), {}).get("source_title")
        )
    ]


def parsed_source_url(root: Path, topic: str, receipt_id: str) -> str | None:
    path = root / "docs" / "quality-reference" / topic / "parsed" / f"{receipt_id}.paper_sections.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(data.get("source_pdf") or data.get("url") or "").strip() if isinstance(data, dict) else ""
    parsed = urllib.parse.urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def risk_of_bias_ratings(run: Path) -> dict[str, str]:
    for path in (run / "risk_of_bias.json", run / "audit" / "risk_of_bias.json"):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rows, list):
            return {
                _key(row.get("study_id")): str(row.get("overall_rating") or "")
                for row in rows
                if isinstance(row, dict) and row.get("study_id") and row.get("overall_rating")
            }
    return {}


def risk_of_bias_rating(ratings: dict[str, str], *keys: object) -> str | None:
    return next((ratings.get(_key(key)) for key in keys if ratings.get(_key(key))), None)


def attach_bundle_references(paper: str, bundle: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    in_references = False
    section = ""
    for line in paper.splitlines():
        if heading := re.match(r"^##\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
            in_references = section == "references"
        markers = [] if in_references or not line.strip() or line.lstrip().startswith("#") else [
            f"[bundle:{index}]"
            for index, row in enumerate(bundle, start=1)
            if (token := str(row.get("cited_as") or "").strip())
            and re.search(rf"(?<!\w){re.escape(token)}(?!\w)", line, re.I)
            and f"[bundle:{index}]" not in line.lower()
        ]
        lines.append(f"{line.rstrip()} {' '.join(markers)}" if markers else line)
    return "\n".join(lines)


def attach_evidence_spans(paper: str, bundle: list[dict[str, Any]]) -> None:
    lines = [line.strip(" -*") for line in paper.splitlines()]
    for index, row in enumerate(bundle, start=1):
        marker = f"[bundle:{index}]"
        candidates = [line for line in lines if marker in line.lower() and len(line) >= 8]
        cited_as = str(row.get("cited_as") or "").lower()
        span = next((line for line in candidates if cited_as and cited_as in line.lower()), "")
        span = span or next(iter(candidates), "")
        if span:
            row["evidence_span"] = span


def _key(value: object) -> str:
    return " ".join(str(value or "").lower().split())
