"""Preserve agent evidence proof when constructing publication payloads."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Sequence
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


def ordered_source_rows(
    rows: Sequence[dict[str, Any]], receipts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    receipts = receipts or {}

    def key(row: dict[str, Any]) -> tuple[int, int, int, str]:
        receipt = receipts.get(str(row.get("receipt_id") or ""), row)
        year = int(row.get("source_year") or receipt.get("source_year") or 0)
        claims = int(receipt.get("n_claims") or row.get("n_claims") or 0)
        return -(year >= 2020), -claims, -year, str(row.get("receipt_id") or "")

    return sorted(rows, key=key)


def attach_bundle_references(paper: str, bundle: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    in_references = False
    section = ""
    for line in paper.splitlines():
        if heading := re.match(r"^##\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
            in_references = section == "references"
        if not in_references and line.strip() and not line.lstrip().startswith(("#", "|", "```")):
            line = re.sub(r"\s*\[bundle:\d+\]", "", line, flags=re.I)
            for index, row in enumerate(bundle, start=1):
                marker = f"[bundle:{index}]"
                token = str(
                    row.get("cited_as") or row.get("citation_token")
                    or row.get("body_citation") or row.get("receipt_id") or ""
                ).strip()
                if token:
                    line = _mark_citation(line, token, marker)
        lines.append(line)
    return "\n".join(lines)


def _mark_citation(line: str, token: str, marker: str) -> str:
    token_re = rf"(?<!\w){re.escape(token)}(?!\w)"
    if not re.search(token_re, line, re.I):
        return line
    line = re.sub(rf"\s*{re.escape(marker)}", "", line, flags=re.I)
    protected = re.compile(rf"\[{token_re}\](?:\([^)]+\))?", re.I)
    parts = protected.split(line)
    citations = protected.findall(line)
    marked = [re.sub(token_re, lambda match: f"{match.group(0)} {marker}", part, flags=re.I) for part in parts]
    out = marked[0]
    for citation, tail in zip(citations, marked[1:], strict=True):
        out += f"{citation} {marker}{tail}"
    return out


def attach_evidence_spans(paper: str, bundle: list[dict[str, Any]]) -> None:
    lines = [line.strip(" -*") for line in paper.splitlines()]
    for index, row in enumerate(bundle, start=1):
        marker = f"[bundle:{index}]"
        candidates = [line for line in lines if marker in line.lower() and len(line) >= 8]
        cited_as = str(row.get("cited_as") or "").lower()
        cited = [line for line in candidates if cited_as and cited_as in line.lower()]
        trace = next((
            line for line in cited
            if re.search(
                rf"\*\*Supporting source:\*\*.*?{re.escape(marker)}",
                line,
                re.I,
            )
        ), "")
        source_specific = next((
            line for line in cited
            if len(set(re.findall(r"\[bundle:\d+\]", line, re.I))) == 1
        ), "")
        span = str(row.get("evidence_span") or "").strip() or trace or source_specific or next(iter(cited), "")
        span = span or next(iter(candidates), "")
        if span:
            row["evidence_span"] = span


def _key(value: object) -> str:
    return " ".join(str(value or "").lower().split())
