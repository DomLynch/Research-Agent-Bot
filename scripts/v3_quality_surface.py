"""Surface v3 paper-quality artifacts in the main manuscript.

The v3 pipeline already writes RoB/GRADE, meta-analysis, and cross-paper
tension artifacts, but historical runs can leave those signals in sidecars or
supplement-only markdown. This module deterministically inserts the existing
artifact text into `full_paper.md` without creating new scientific claims.

It is intentionally post-render and idempotent: the input artifacts remain the
source of truth, and repeated calls do not duplicate sections.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts import paper_quality_runtime as _pqr

__all__ = [
    "apply_quality_surface_markdown",
    "apply_quality_surface_sections",
    "apply_quality_surface_to_run",
    "main",
]

_ANCHOR_HEADINGS = (
    "## Discussion",
    "## Limitations",
    "## Conclusion",
    "## Structured Evidence Tables",
    "## Search Provenance",
    "## References",
)

_RUN_ARTIFACT_LOCATIONS = (
    "{name}",
    "readable/{name}",
)


def apply_quality_surface_sections(
    paper_md: str,
    *,
    quality_bundle: Any | None = None,
    meta_analysis: dict[str, Any] | None = None,
    tension_payload: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Insert live in-memory v3 quality artifacts into manuscript markdown.

    This is the runner-facing API. It accepts the same structured objects that
    `scripts.paper_quality_runtime` already creates and returns the updated
    manuscript plus a compact insertion log.
    """
    quality_md = (
        _pqr.render_quality_section_for_paper(quality_bundle)
        if quality_bundle is not None else ""
    )
    meta_md = (
        _pqr.render_meta_analysis_section(meta_analysis)
        if isinstance(meta_analysis, dict) else ""
    )
    tension_md = (
        _pqr.render_tension_section(tension_payload)
        if isinstance(tension_payload, dict) else ""
    )
    return apply_quality_surface_markdown(
        paper_md,
        quality_md=quality_md,
        meta_md=meta_md,
        tension_md=tension_md,
    )


def apply_quality_surface_markdown(
    paper_md: str,
    *,
    quality_md: str = "",
    meta_md: str = "",
    tension_md: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Insert already-rendered quality sections into the public manuscript.

    The operation is deterministic and idempotent. The first H2 of each normalized
    section is the duplication guard.
    """
    out = paper_md
    log: list[dict[str, str]] = []
    ordered_sections = (
        ("risk_of_bias_and_grade", _normalize_quality_markdown(quality_md)),
        ("meta_analysis_results", _normalize_meta_markdown(meta_md)),
        ("cross_paper_tensions", _normalize_tension_markdown(tension_md)),
    )
    for section_name, section in ordered_sections:
        if not section:
            continue
        before = out
        out = _insert_before_first_anchor(out, section)
        if out != before:
            log.append({
                "section": section_name,
                "heading": section.splitlines()[0].strip(),
            })
    return out, log


def apply_quality_surface_to_run(run_dir: Path) -> dict[str, Any]:
    """Patch a v3 run folder in place.

    Reads `full_paper.md` plus quality sidecars from either the run root or the
    post-organization `readable/` folder. Writes `quality_surface_log.json` even
    when no change was required so a run has an auditable no-op record.
    """
    paper_path = run_dir / "full_paper.md"
    if not paper_path.exists():
        raise FileNotFoundError(f"missing full_paper.md in {run_dir}")
    paper_md = paper_path.read_text(encoding="utf-8")
    out, insertions = apply_quality_surface_markdown(
        paper_md,
        quality_md=_read_run_artifact(run_dir, "quality_methods.md"),
        meta_md=_read_run_artifact(run_dir, "meta_analysis_results.md"),
        tension_md=_read_run_artifact(run_dir, "tension_elaboration_plans.md"),
    )
    changed = out != paper_md
    if changed:
        paper_path.write_text(out, encoding="utf-8")
    payload = {
        "changed": changed,
        "insertions": insertions,
        "source_artifacts": {
            "quality_methods": _artifact_exists(run_dir, "quality_methods.md"),
            "meta_analysis_results": _artifact_exists(run_dir, "meta_analysis_results.md"),
            "tension_elaboration_plans": _artifact_exists(run_dir, "tension_elaboration_plans.md"),
        },
        "method": "scripts.v3_quality_surface.apply_quality_surface_to_run",
    }
    (run_dir / "quality_surface_log.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _normalize_quality_markdown(markdown: str) -> str:
    text = _clean_section(markdown)
    if not text:
        return ""
    if _first_heading(text) == "## Risk of Bias and GRADE":
        return text
    text = _drop_h1(text)
    return (
        "## Risk of Bias and GRADE\n\n"
        "The following study-level risk-of-bias and outcome-level certainty "
        "summaries are rendered from the run's structured RoB/GRADE sidecars. "
        "They are screening outputs, not new source claims.\n\n"
        + text.lstrip()
    ).rstrip()


def _normalize_meta_markdown(markdown: str) -> str:
    text = _clean_section(markdown)
    if not text:
        return ""
    if _first_heading(text) == "## Meta-Analysis Results":
        return text
    text = _drop_h1(text)
    return "## Meta-Analysis Results\n\n" + text.lstrip()


def _normalize_tension_markdown(markdown: str) -> str:
    text = _clean_section(markdown)
    if not text:
        return ""
    text = text.replace("## Cross-Paper Tension Plans", "## Cross-Paper Tensions", 1)
    if _first_heading(text) == "## Cross-Paper Tensions":
        return text
    text = _drop_h1(text)
    return "## Cross-Paper Tensions\n\n" + text.lstrip()


def _insert_before_first_anchor(markdown: str, section: str) -> str:
    heading = _first_heading(section)
    if not heading or _has_heading(markdown, heading):
        return markdown
    anchor = _first_existing_anchor(markdown)
    return _pqr.insert_before_heading(markdown, anchor, section)


def _first_existing_anchor(markdown: str) -> str:
    candidates = [
        (heading, _heading_position(markdown, heading))
        for heading in _ANCHOR_HEADINGS
    ]
    present = [(heading, pos) for heading, pos in candidates if pos >= 0]
    if not present:
        return "## References"
    return min(present, key=lambda item: item[1])[0]


def _heading_position(markdown: str, heading: str) -> int:
    match = re.search(rf"^{re.escape(heading)}\b", markdown, flags=re.MULTILINE)
    return -1 if match is None else match.start()


def _has_heading(markdown: str, heading: str) -> bool:
    return _heading_position(markdown, heading) >= 0


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return stripped
        if stripped.startswith("# "):
            continue
        if stripped:
            break
    return ""


def _drop_h1(markdown: str) -> str:
    lines = markdown.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def _clean_section(markdown: str) -> str:
    return markdown.strip()


def _read_run_artifact(run_dir: Path, name: str) -> str:
    for template in _RUN_ARTIFACT_LOCATIONS:
        path = run_dir / template.format(name=name)
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _artifact_exists(run_dir: Path, name: str) -> bool:
    return any((run_dir / template.format(name=name)).exists() for template in _RUN_ARTIFACT_LOCATIONS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Insert v3 quality-method, meta-analysis, and tension artifacts into full_paper.md.",
    )
    parser.add_argument("run_dir", type=Path, help="Path to a v3 synthesis run folder")
    args = parser.parse_args(argv)
    payload = apply_quality_surface_to_run(args.run_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
