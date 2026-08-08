"""Preserve agent evidence proof when constructing publication payloads."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent.revision_evidence import RevisionEvidenceLock
from agent.source_hygiene import is_notice_only_source_title

SOURCE_PROOF_ORIGINS = frozenset({"pubmed", "publisher", "full_text"})
SOURCE_IDENTITY_FIELDS = (
    "source_type", "id", "title", "url", "doi", "pmid", "openalex_id", "registry_id",
    "source_record_locator",
)


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_identity_hash(row: dict[str, Any], *, origin: str) -> str:
    material = {
        key: value for key in SOURCE_IDENTITY_FIELDS
        if (value := _normalized_text(row.get(key)))
    }
    if origin not in SOURCE_PROOF_ORIGINS or not material:
        return ""
    material["evidence_origin"] = origin
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return _sha256_text(encoded)


def exact_source_quote(candidate: object, source_text: object) -> str | None:
    quote = _normalized_text(candidate)
    source = _normalized_text(source_text)
    return quote if len(quote) >= 20 and quote in source else None


def _record_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_record_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_record_text(item) for item in value)
    return str(value) if isinstance(value, str) else ""


def source_proof_fields(
    row: dict[str, Any], *, origin: str, evidence: RevisionEvidenceLock | None = None,
    topic: str = "", receipt_id: str = "",
) -> dict[str, Any]:
    if evidence is None or evidence.mode != "snapshot" or evidence.errors:
        return {}
    if not topic or not receipt_id or receipt_id not in evidence.receipt_rows:
        return {}
    frozen_topic = _normalized_text(evidence.receipt_rows[receipt_id].get("topic"))
    if frozen_topic and frozen_topic != topic:
        return {}
    source_path = evidence.parsed_dir / f"{receipt_id}.paper_sections.json"
    try:
        raw = source_path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    excerpt = _normalized_text(row.get("excerpt"))
    source_run = evidence.source_run.name if evidence.source_run else "unknown"
    locator = f"revision-snapshot:{source_run}:{topic}:{receipt_id}"
    identity_hash = source_identity_hash(
        {**row, "source_record_locator": locator}, origin=origin,
    )
    if not excerpt or not exact_source_quote(excerpt, _record_text(record)) or not identity_hash:
        return {}
    quote = _normalized_text(row.get("quote"))
    return {
        "evidence_origin": origin,
        "source_record_locator": locator,
        "source_record_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "source_content_hash": _sha256_text(excerpt),
        "source_identity_hash": identity_hash,
        "quote_verified": bool(quote and exact_source_quote(quote, excerpt)),
    }


def source_proof_is_valid(row: dict[str, Any]) -> bool:
    origin = _normalized_text(row.get("evidence_origin"))
    excerpt = _normalized_text(row.get("excerpt"))
    locator = _normalized_text(row.get("source_record_locator"))
    if (
        origin not in SOURCE_PROOF_ORIGINS
        or not excerpt
        or not locator
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(row.get("source_record_hash") or ""))
        or row.get("source_content_hash") != _sha256_text(excerpt)
        or row.get("source_identity_hash") != source_identity_hash(row, origin=origin)
    ):
        return False
    quote = _normalized_text(row.get("quote"))
    evidence_span = _normalized_text(row.get("evidence_span"))
    quote_ok = not quote or row.get("quote_verified") is True and exact_source_quote(quote, excerpt)
    return bool(quote_ok and (not evidence_span or exact_source_quote(evidence_span, excerpt)))


def verified_source_span(row: dict[str, Any]) -> str:
    excerpt = _normalized_text(row.get("excerpt"))
    if not source_proof_is_valid(row) or len(excerpt.split()) < 12:
        return ""
    quote = _normalized_text(row.get("quote"))
    return quote if quote and len(quote.split()) >= 12 else excerpt


def source_rows(registry: dict[str, Any], receipts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in registry.values() if isinstance(row, dict)
        and not is_notice_only_source_title(
            row.get("title") or receipts.get(str(row.get("receipt_id")), {}).get("source_title")
        )
    ]


def parsed_source_url(
    root: Path, topic: str, receipt_id: str, *, parsed_dir: Path | None = None,
) -> str | None:
    path = (parsed_dir or root / "docs" / "quality-reference" / topic / "parsed") / f"{receipt_id}.paper_sections.json"
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

    def append_marker(match: re.Match[str]) -> str:
        return f"{match.group(0)} {marker}"

    marked = [re.sub(token_re, append_marker, part, flags=re.I) for part in parts]
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
        span = str(row.get("claim_span") or "").strip() or trace or source_specific or next(iter(cited), "")
        span = span or next(iter(candidates), "")
        if span:
            row["claim_span"] = span


def _key(value: object) -> str:
    return " ".join(str(value or "").lower().split())
