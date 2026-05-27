from __future__ import annotations

import json
import re
from pathlib import Path

Change = tuple[str, int, str]


def apply_review_noise_control(text: str, out_dir: Path) -> tuple[str, list[Change]]:
    changes: list[Change] = []
    text, n = re.subn(r"\bContextual Other\b", "Contextual Adjacent Evidence", text)
    if n:
        changes.append(("rename_contextual_other", n, "renamed broad contextual bucket"))
    if "Contextual Adjacent Evidence" in text and "not pooled with direct outcome evidence" not in text:
        note = (
            "\n\n**Outcome-class note:** Contextual Adjacent Evidence denotes "
            "background, boundary-condition, or adjacent-outcome sources. It is "
            "not pooled with direct outcome evidence.\n"
        )
        text, n = re.subn(r"(^## Results\b)", r"\1" + note, text, count=1, flags=re.M)
        if n:
            changes.append(("explain_contextual_adjacent_evidence", 1, "defined broad adjacent-evidence bucket"))
    text, n = _dedupe_repeated_blocks(text)
    if n:
        changes.append(("dedupe_repeated_blocks", n, f"removed {n} repeated prose/table block(s)"))
    text, n = _trim_cross_domain_tables(text)
    if n:
        changes.append(("trim_low_value_cross_domain_rows", n, f"removed {n} low-severity agreement row(s)"))
    if _has_verification_limited_sources(out_dir) and "verification-limited context" not in text:
        note = (
            "\n\n**Verification note:** Reference-only or no-abstract records "
            "are treated as verification-limited context, not as equal-weight "
            "support for the main claim.\n"
        )
        text, n = re.subn(r"(^## Limitations\b)", r"\1" + note, text, count=1, flags=re.M)
        if n:
            changes.append(("flag_verification_limited_sources", 1, "flagged lower-weight context sources"))
    return text, changes


def _dedupe_repeated_blocks(text: str) -> tuple[str, int]:
    parts = re.split(r"(^## References\b.*)", text, maxsplit=1, flags=re.M | re.S)
    body, tail = parts[0], "".join(parts[1:])
    chunks = re.split(r"(\n{2,})", body)
    seen: set[str] = set()
    removed = 0
    for i in range(0, len(chunks), 2):
        block = chunks[i]
        norm = re.sub(r"\s+", " ", block.strip())
        words = norm.split()
        if not norm:
            continue
        table_like = block.lstrip().startswith("|") and block.count("\n|") >= 1
        if norm in seen and (table_like or len(words) >= 18):
            chunks[i] = ""
            removed += 1
        else:
            seen.add(norm)
    return "".join(chunks) + tail, removed


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _separator_row(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", line))


def _trim_cross_domain_tables(text: str) -> tuple[str, int]:
    match = re.search(r"^## Cross-Domain Synthesis\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match:
        return text, 0
    lines = match.group(0).splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            i += 1
        table = lines[start:i]
        if len(table) < 3 or not _separator_row(table[1]):
            out.extend(table)
            continue
        header = [c.lower() for c in _cells(table[0])]
        sev_idx = next((j for j, c in enumerate(header) if "severity" in c), -1)
        kind_idx = next((j for j, c in enumerate(header) if any(k in c for k in ("kind", "type", "tension", "conflict"))), -1)
        kept = table[:2]
        for row in table[2:]:
            cells = _cells(row)
            kind = cells[kind_idx].lower() if 0 <= kind_idx < len(cells) else ""
            m = re.search(r"\b([0-5])\b", cells[sev_idx]) if 0 <= sev_idx < len(cells) else None
            severity = int(m.group(1)) if m else None
            if (severity is not None and severity <= 1) or ("agreement" in kind and "disagreement" not in kind):
                removed += 1
            else:
                kept.append(row)
        out.extend(kept)
    return text[:match.start()] + "\n".join(out) + text[match.end():], removed


def _has_verification_limited_sources(out_dir: Path) -> bool:
    try:
        data = json.loads((out_dir / "citation_registry.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return any(isinstance(row, dict) and not row.get("title") and not row.get("source_journal") for row in data.values())
