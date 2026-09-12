"""CLI gate for template-language detection.

Phase 6 of the WORLDCLASS rapamycin sprint. Stdlib-only.

Usage:
    python scripts/template_language_gate.py path/to/full_paper.md \\
        --json out.json [--md out.md]

Exit code:
    0 — no P1/P2 hits (gate clean)
    1 — at least one P1 or P2 hit (gate blocked)
    2 — input error (file not found, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.template_language import (  # noqa: E402
    Hit,
    detect_template_language,
    has_blocking_severity,
    hit_to_dict,
)


def _build_summary(hits: Sequence[Hit], *, gate: bool = False) -> dict[str, object]:
    """Compute counts per severity and per category."""
    severity_counts: Counter[str] = Counter(h.severity for h in hits)
    category_counts = Counter(h.category for h in hits)
    return {
        "total_hits": len(hits),
        "by_severity": {severity: severity_counts.get(severity, 0) for severity in ("P1", "P2", "P3")} if gate else dict(severity_counts),
        "by_category": dict(sorted(category_counts.items())) if gate else dict(category_counts),
        "blocking": has_blocking_severity(hits),
    }


def _render_markdown(hits: Sequence[Hit], source_path: Path | str, summary: dict[str, object], *, gate: bool = False) -> str:
    """Render a markdown audit report. Sorted by line_number then severity."""
    title = f"Gate — {source_path}" if gate else f"Audit — {Path(source_path).name}"
    lines = [f"# Template-Language {title}", ""]
    if not gate:
        lines.append(f"**Source:** `{source_path}`")
    lines.extend([f"**Total hits:** {summary['total_hits']}", f"**Blocking (P1/P2):** {summary['blocking']}"])
    for group in ("severity", "category"):
        label = group.capitalize()
        lines.extend(["", f"## Counts by {group}", "", f"| {label} | Count |", "| --- | --- |"])
        counts = summary[f"by_{group}"]
        if isinstance(counts, dict):
            rows = [(key, counts.get(key, 0)) for key in ("P1", "P2", "P3")] if group == "severity" else sorted(counts.items())
            if gate and group == "category" and not rows:
                rows = [("_none_", 0)]
            lines.extend(f"| {key} | {count} |" for key, count in rows)
    lines.extend(["", "## Hits", ""])
    if not hits:
        lines.append("_No template-language hits detected._")
    else:
        lines.extend(["| Line | Severity | Category | Phrase | Sentence |", "| ---: | --- | --- | --- | --- |"])
        for hit in sorted(hits, key=lambda h: (h.line_number, h.severity, h.category)):
            sentence = hit.sentence.replace("|", "\\|").replace("\n", " ")
            phrase = hit.phrase.replace("|", "\\|")
            lines.append(f"| {hit.line_number} | {hit.severity} | {hit.category} | `{phrase}` | {sentence} |")
    return "\n".join(lines) + ("" if gate else "\n")


def _render_json_report(hits: Sequence[Hit], summary: dict[str, object], source: str, *, sort_keys: bool = True) -> str:
    return json.dumps({"source": source, "summary": summary, "hits": [hit_to_dict(hit) for hit in hits]}, indent=2, sort_keys=sort_keys)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 (clean), 1 (blocking hits), or 2 (input error)."""
    parser = argparse.ArgumentParser(
        description="Deterministic template-language detector for paper renders.",
    )
    parser.add_argument(
        "input",
        help="Path to markdown paper file to audit.",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        required=True,
        help="Path to write the JSON report.",
    )
    parser.add_argument(
        "--md",
        dest="md_out",
        default=None,
        help="Optional path to write a markdown audit report.",
    )
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.is_file():
        print(f"error: input file not found: {source}", file=sys.stderr)
        return 2

    text = source.read_text(encoding="utf-8")
    hits = detect_template_language(text)
    summary = _build_summary(hits)

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(_render_json_report(hits, summary, str(source), sort_keys=False), encoding="utf-8")

    if args.md_out:
        md_path = Path(args.md_out)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(_render_markdown(hits, source, summary), encoding="utf-8")

    blocking = bool(summary["blocking"])
    print(
        f"template-language gate: {summary['total_hits']} hit(s); "
        f"blocking={blocking}; json={json_path}"
        + (f"; md={args.md_out}" if args.md_out else "")
    )
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
