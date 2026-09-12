"""Function API for the template-language gate and its shared report serializers."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from agent.template_language import (
    Hit,
    detect_template_language,
)

__all__ = ["TemplateGateReport", "evaluate_template_gate"]


@dataclass(frozen=True, slots=True)
class TemplateGateReport:
    """Severity counts, frozen hits and rendered reports for the final trust gate."""

    template_language_blocking: bool
    p1_count: int
    p2_count: int
    p3_count: int
    total_hits: int
    hits: tuple[Hit, ...]
    markdown_report: str
    json_report: str


def _build_summary(hits: tuple[Hit, ...]) -> dict[str, object]:
    return import_module("scripts.template_language_gate")._build_summary(hits, gate=True)


def _render_markdown_report(
    hits: tuple[Hit, ...], summary: dict[str, object], source: str
) -> str:
    return import_module("scripts.template_language_gate")._render_markdown(hits, source, summary, gate=True)


def _render_json_report(
    hits: tuple[Hit, ...], summary: dict[str, object], source: str
) -> str:
    return import_module("scripts.template_language_gate")._render_json_report(hits, summary, source)


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
