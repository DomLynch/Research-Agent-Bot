"""Quality Evidence Map renderer — single deterministic markdown summary
combining manifest + RoB + GRADE + top tensions.

Phase 4/5/7 sibling tooling. Stdlib-only; reuses existing renderers from
scripts/render_quality_tables.py and the tension selector from
agent/tension_elaboration.py.

CLI:
    python scripts/quality_evidence_map.py \\
        [--manifest m.json] [--rob rob.json] \\
        [--grade grade.json] [--tensions t.json] \\
        --out evidence_map.md [--top-n 5]

Any of --manifest / --rob / --grade / --tensions may be omitted; the
renderer emits an explicit "_No data provided._" stub for missing
sections rather than failing closed (this is a renderer, not a gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.tension_elaboration import (  # noqa: E402
    TensionRecord,
    select_top_tensions,
)
from scripts.render_quality_tables import (  # noqa: E402
    grades_from_json,
    render_grade_table,
    render_rob_table,
    studies_from_json,
)

__all__ = [
    "render_quality_evidence_map",
    "render_corpus_summary",
    "render_top_tensions_section",
    "tensions_from_json",
]


def _md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_corpus_summary(manifest: dict | None) -> str:
    """Render the receipts table from a manifest dict. None / empty manifest
    emits the placeholder."""
    out: list[str] = []
    out.append("## Corpus Summary")
    out.append("")
    if not manifest:
        out.append("_No manifest provided._")
        return "\n".join(out)
    receipts = manifest.get("receipts") or []
    n = manifest.get("n_receipts", len(receipts))
    out.append(f"**Receipts:** {n}")
    if "thesis" in manifest:
        out.append("")
        out.append(f"**Thesis:** {_md_escape(str(manifest['thesis']))}")
    out.append("")
    if not receipts:
        out.append("_No receipts in manifest._")
        return "\n".join(out)
    out.append("| Receipt | Outcome class | Effect direction | Evidence tier | Directness |")
    out.append("| --- | --- | --- | --- | --- |")
    for r in receipts:
        out.append(
            "| "
            + " | ".join([
                _md_escape(str(r.get("receipt_id", "?"))),
                _md_escape(str(r.get("outcome_class", "?"))),
                _md_escape(str(r.get("effect_direction", "?"))),
                _md_escape(str(r.get("evidence_tier", "?"))),
                _md_escape(str(r.get("directness", "?"))),
            ])
            + " |"
        )
    return "\n".join(out)


def tensions_from_json(payload: list[dict]) -> list[TensionRecord]:
    """Parse a JSON list into TensionRecord instances."""
    records: list[TensionRecord] = []
    for raw in payload:
        records.append(TensionRecord(
            tension_id=str(raw["tension_id"]),
            paper_a=str(raw["paper_a"]),
            paper_b=str(raw["paper_b"]),
            conflict_type=str(raw["conflict_type"]),
            outcome_class=str(raw["outcome_class"]),
            severity=int(raw["severity"]),
            weight_a=float(raw.get("weight_a", 1.0)),
            weight_b=float(raw.get("weight_b", 1.0)),
            directness_a=str(raw.get("directness_a", "direct")),
            directness_b=str(raw.get("directness_b", "direct")),
            numeric_anchors_a=tuple(raw.get("numeric_anchors_a", ())),
            numeric_anchors_b=tuple(raw.get("numeric_anchors_b", ())),
        ))
    return records


def render_top_tensions_section(
    records: Sequence[TensionRecord], *, top_n: int = 5
) -> str:
    out: list[str] = []
    out.append("## Top Tensions")
    out.append("")
    if not records:
        out.append("_No tension records provided._")
        return "\n".join(out)
    plans = select_top_tensions(records, top_n=top_n)
    for plan in plans:
        out.append(f"### {plan.tension_id}: {plan.paper_a} vs {plan.paper_b}")
        out.append("")
        out.append(f"- **Conflict type:** {plan.conflict_type}")
        out.append(f"- **Outcome class:** {plan.outcome_class}")
        out.append(f"- **Severity:** {plan.severity}/5")
        anchors_text = ", ".join(plan.numeric_anchors) if plan.numeric_anchors else "—"
        out.append(f"- **Numeric anchors:** {anchors_text}")
        out.append(f"- **Corpus-weight winner:** {plan.corpus_weight_winner}")
        out.append("- **Plausible hypotheses:**")
        out.append(f"  1. {plan.hypotheses[0]}")
        out.append(f"  2. {plan.hypotheses[1]}")
        out.append("")
    return "\n".join(out)


def render_quality_evidence_map(
    *,
    manifest: dict | None = None,
    rob_payload: list[dict] | None = None,
    grade_payload: list[dict] | None = None,
    tension_payload: list[dict] | None = None,
    top_n: int = 5,
) -> str:
    """Render the complete Quality Evidence Map markdown."""
    sections: list[str] = []
    title = "Quality Evidence Map"
    if manifest and "topic" in manifest:
        title = f"Quality Evidence Map — {manifest['topic']}"
    sections.append(f"# {title}")
    sections.append("")
    sections.append(render_corpus_summary(manifest))
    sections.append("")
    if rob_payload:
        sections.append(render_rob_table(studies_from_json(rob_payload)))
    else:
        sections.append("# Risk-of-Bias Summary\n\n_No RoB data provided._")
    sections.append("")
    if grade_payload:
        sections.append(render_grade_table(grades_from_json(grade_payload)))
    else:
        sections.append("# GRADE Certainty Summary\n\n_No GRADE data provided._")
    sections.append("")
    sections.append(render_top_tensions_section(
        tensions_from_json(tension_payload) if tension_payload else [],
        top_n=top_n,
    ))
    return "\n".join(sections)


def _load_json(path: str | None) -> object:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a unified Quality Evidence Map (manifest + RoB + GRADE + tensions)."
    )
    parser.add_argument("--manifest", help="Path to manifest.json.")
    parser.add_argument("--rob", help="Path to RoB JSON list.")
    parser.add_argument("--grade", help="Path to GRADE JSON list.")
    parser.add_argument("--tensions", help="Path to tensions JSON list.")
    parser.add_argument("--out", required=True, help="Output markdown path.")
    parser.add_argument("--top-n", type=int, default=5, help="Top-N tensions (default 5).")
    args = parser.parse_args(argv)
    manifest = _load_json(args.manifest)
    rob = _load_json(args.rob)
    grade = _load_json(args.grade)
    tensions = _load_json(args.tensions)
    md = render_quality_evidence_map(
        manifest=manifest if isinstance(manifest, dict) else None,
        rob_payload=rob if isinstance(rob, list) else None,
        grade_payload=grade if isinstance(grade, list) else None,
        tension_payload=tensions if isinstance(tensions, list) else None,
        top_n=args.top_n,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"quality evidence map: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
