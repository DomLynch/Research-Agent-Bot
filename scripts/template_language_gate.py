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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.template_language import (  # noqa: E402
    Hit,
    detect_template_language,
    has_blocking_severity,
    hit_to_dict,
)


def _build_summary(hits: list[Hit]) -> dict[str, object]:
    """Compute counts per severity and per category."""
    severity_counts = Counter(h.severity for h in hits)
    category_counts = Counter(h.category for h in hits)
    return {
        "total_hits": len(hits),
        "by_severity": dict(severity_counts),
        "by_category": dict(category_counts),
        "blocking": has_blocking_severity(hits),
    }


def _render_markdown(hits: list[Hit], source_path: Path, summary: dict[str, object]) -> str:
    """Render a markdown audit report. Sorted by line_number then severity."""
    lines: list[str] = []
    lines.append(f"# Template-Language Audit — {source_path.name}")
    lines.append("")
    lines.append(f"**Source:** `{source_path}`")
    lines.append(f"**Total hits:** {summary['total_hits']}")
    lines.append(f"**Blocking (P1/P2):** {summary['blocking']}")
    lines.append("")
    lines.append("## Counts by severity")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("| --- | --- |")
    by_sev = summary["by_severity"]
    if isinstance(by_sev, dict):
        for sev in ("P1", "P2", "P3"):
            count = by_sev.get(sev, 0)
            lines.append(f"| {sev} | {count} |")
    lines.append("")
    lines.append("## Counts by category")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("| --- | --- |")
    by_cat = summary["by_category"]
    if isinstance(by_cat, dict):
        for cat, count in sorted(by_cat.items()):
            lines.append(f"| {cat} | {count} |")
    lines.append("")
    lines.append("## Hits")
    lines.append("")
    if not hits:
        lines.append("_No template-language hits detected._")
    else:
        lines.append("| Line | Severity | Category | Phrase | Sentence |")
        lines.append("| ---: | --- | --- | --- | --- |")
        sorted_hits = sorted(hits, key=lambda h: (h.line_number, h.severity, h.category))
        for h in sorted_hits:
            sentence = h.sentence.replace("|", "\\|").replace("\n", " ")
            phrase = h.phrase.replace("|", "\\|")
            lines.append(
                f"| {h.line_number} | {h.severity} | {h.category} | "
                f"`{phrase}` | {sentence} |"
            )
    lines.append("")
    return "\n".join(lines)


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
    json_payload = {
        "source": str(source),
        "summary": summary,
        "hits": [hit_to_dict(h) for h in hits],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

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
