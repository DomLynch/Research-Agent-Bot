"""Phase 6 template-language gate adapter.

Function-API wrapper over `agent.template_language.detect_template_language`
for use by the writer post-render hook. Returns a structured report with
both markdown and JSON serialisations the orchestrator can persist
alongside the audit / cert artifacts.

Stdlib-only. The detector handles section-skipping (code fences, tables,
references, audit metadata) already; this adapter only assembles counts +
serialisations + the blocking verdict.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from agent.template_language import (
    Hit,
    detect_template_language,
    has_blocking_severity,
    hit_to_dict,
)

__all__ = [
    "TemplateGateReport",
    "evaluate_template_gate",
]


@dataclass(frozen=True, slots=True)
class TemplateGateReport:
    """Structured verdict from the template-language gate.

    template_language_blocking — True if any P1 or P2 hit. Wired directly
                                 into `agent.final_gate.GateInputs`.
    p1_count, p2_count, p3_count — per-severity counts.
    total_hits                  — sum across severities.
    hits                        — frozen tuple of Hit records.
    markdown_report             — human-readable markdown audit.
    json_report                 — JSON-serialised dict (str) with summary +
                                  hits, suitable for persistence next to
                                  audit.json / consistency.json.
    """

    template_language_blocking: bool
    p1_count: int
    p2_count: int
    p3_count: int
    total_hits: int
    hits: tuple[Hit, ...]
    markdown_report: str
    json_report: str


def _build_summary(hits: tuple[Hit, ...]) -> dict[str, object]:
    severity_counts = Counter(h.severity for h in hits)
    category_counts = Counter(h.category for h in hits)
    return {
        "total_hits": len(hits),
        "by_severity": {
            "P1": severity_counts.get("P1", 0),
            "P2": severity_counts.get("P2", 0),
            "P3": severity_counts.get("P3", 0),
        },
        "by_category": dict(sorted(category_counts.items())),
        "blocking": has_blocking_severity(hits),
    }


def _render_markdown_report(
    hits: tuple[Hit, ...], summary: dict[str, object], source: str
) -> str:
    lines: list[str] = []
    lines.append(f"# Template-Language Gate — {source}")
    lines.append("")
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
            lines.append(f"| {sev} | {by_sev.get(sev, 0)} |")
    lines.append("")
    lines.append("## Counts by category")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("| --- | --- |")
    by_cat = summary["by_category"]
    if isinstance(by_cat, dict):
        if not by_cat:
            lines.append("| _none_ | 0 |")
        else:
            for cat, count in by_cat.items():
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
    return "\n".join(lines)


def _render_json_report(
    hits: tuple[Hit, ...], summary: dict[str, object], source: str
) -> str:
    payload = {
        "source": source,
        "summary": summary,
        "hits": [hit_to_dict(h) for h in hits],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def evaluate_template_gate(
    paper_text: str, *, source: str = "<paper>"
) -> TemplateGateReport:
    """Run the deterministic detector over `paper_text` and bundle the
    result. `source` is a label included in the markdown/JSON reports
    (typically the file path or run ID)."""
    if not isinstance(paper_text, str):
        raise TypeError(f"paper_text must be str, got {type(paper_text).__name__}")
    hits_tuple: tuple[Hit, ...] = tuple(detect_template_language(paper_text))
    summary = _build_summary(hits_tuple)
    by_sev = summary["by_severity"]
    if not isinstance(by_sev, dict):
        raise RuntimeError("internal: summary.by_severity must be dict")
    p1 = int(by_sev.get("P1", 0))
    p2 = int(by_sev.get("P2", 0))
    p3 = int(by_sev.get("P3", 0))
    total_hits = summary.get("total_hits", 0)
    if not isinstance(total_hits, (str, int, float)):
        total_hits = 0
    return TemplateGateReport(
        template_language_blocking=bool(summary["blocking"]),
        p1_count=p1,
        p2_count=p2,
        p3_count=p3,
        total_hits=int(total_hits),
        hits=hits_tuple,
        markdown_report=_render_markdown_report(hits_tuple, summary, source),
        json_report=_render_json_report(hits_tuple, summary, source),
    )
