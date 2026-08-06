#!/usr/bin/env python3
"""Read-only per-source evidence funnel: where does the corpus disappear?

Publication needs 12 receipts / 3 primary-tier / 4 direct. Topics with large
corpora were failing all three, so the question is not "is the corpus big
enough" but "at which stage does each source die". This reports that per topic
without touching the pipeline.

It also reports structured-metadata coverage. Tier and directness are assigned
downstream, but the extracted claim records carry no study_design/species/
population/intervention/comparator/endpoint fields, so the classifier can only
fall back to title/abstract matching. Low coverage here is the upstream cause
of a low primary-tier count — fix that before adding classifier rules.

Universal: no topic, domain, or source is special-cased.

  python3 scripts/evidence_funnel.py --topic resistance_training
  python3 scripts/evidence_funnel.py --all --limit 15
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
QUALITY_REF = REPO_ROOT / "docs" / "quality-reference"
RUNS = REPO_ROOT / "runs"

# Fields a tier/directness classifier needs to work structurally rather than
# by regex over prose.
DESIGN_FIELDS = (
    "study_design", "species", "population",
    "intervention", "comparator", "endpoint",
)


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _claim_records(doc: dict[str, Any]) -> list[dict[str, Any]]:
    claims = doc.get("claims")
    return [c for c in claims if isinstance(c, dict)] if isinstance(claims, list) else []


def topic_funnel(topic: str) -> dict[str, Any] | None:
    quant_dir = QUALITY_REF / topic / "quant_claims"
    if not quant_dir.is_dir():
        return None

    papers = sorted(quant_dir.glob("*.json"))
    with_claims = 0
    total_claims = 0
    design_hits = dict.fromkeys(DESIGN_FIELDS, 0)

    for path in papers:
        doc = _load(path)
        records = _claim_records(doc)
        if records:
            with_claims += 1
            total_claims += len(records)
        # A field counts as present if the paper doc or any claim carries it.
        for field in DESIGN_FIELDS:
            if doc.get(field) or any(r.get(field) for r in records):
                design_hits[field] += 1

    # Latest observed admission counts for this topic, if any run recorded them.
    counts: dict[str, Any] = {}
    runs = sorted(
        RUNS.glob(f"synthesis-{topic}-v06-*"),
        key=lambda p: p.name,
        reverse=True,
    )
    for run in runs:
        funnel = _load(run / "receipt_funnel.json")
        if isinstance(funnel.get("counts"), dict):
            counts = funnel["counts"]
            break

    return {
        "topic": topic,
        "papers": len(papers),
        "papers_with_claims": with_claims,
        "claims": total_claims,
        "design_coverage": design_hits,
        "counts": counts,
    }


def render(f: dict[str, Any]) -> str:
    papers = f["papers"]
    counts = f["counts"]
    admitted = counts.get("admitted_receipts")
    lines = [
        f"topic: {f['topic']}",
        f"  corpus papers          {papers}",
        f"  papers with claims     {f['papers_with_claims']}",
        f"  extracted claims       {f['claims']}",
    ]
    if admitted is not None:
        lost = papers - admitted
        pct = (lost / papers * 100) if papers else 0.0
        lines += [
            f"  receipts admitted      {admitted}"
            f"   ({lost} of {papers} sources dropped, {pct:.0f}%)",
            f"  primary-tier           {counts.get('primary_tier_receipts')}",
            f"  direct                 {counts.get('direct_receipts')}",
        ]
    else:
        lines.append("  receipts admitted      <no run recorded a funnel>")
    lines.append("  structured design-field coverage (drives tier/directness):")
    for field, n in f["design_coverage"].items():
        pct = (n / papers * 100) if papers else 0.0
        flag = "" if pct else "   <- absent; classifier falls back to prose"
        lines.append(f"    {field:<13} {n:>5}/{papers} ({pct:.0f}%){flag}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", action="append", default=[])
    ap.add_argument("--all", action="store_true", help="every topic with a corpus")
    ap.add_argument("--limit", type=int, default=0, help="cap --all output")
    args = ap.parse_args()

    topics = list(args.topic)
    if args.all or not topics:
        topics = sorted(
            p.name for p in QUALITY_REF.iterdir()
            if (p / "quant_claims").is_dir()
        )
        if args.limit:
            topics = topics[: args.limit]

    for topic in topics:
        funnel = topic_funnel(topic)
        print(render(funnel) if funnel else f"topic: {topic}\n  <no corpus>")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
