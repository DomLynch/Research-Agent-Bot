"""CLI for the 5-class corpus classifier — Wave 7 slice 2 full.

Reads `docs/quality-reference/<topic>/parsed/*.paper_sections.json`,
classifies every paper into one of the 5 classes (core_on_thesis,
background_mechanism, adjacent_clinical, off_thesis, reject), and
writes:

  docs/quality-reference/<topic>/corpus_classification.json
    [{paper_id, classification, score, reason, signals: [...]}, ...]

  docs/quality-reference/<topic>/corpus_classification.md
    Human-readable summary grouped by class.

This is the "rejected-paper reason log" deliverable (Corpus Factory
v1). Universal across topics — the classifier and CLI take topic
aliases from the topic_pack and contain no per-topic logic.

Usage:
    python scripts/run_corpus_classifier.py --topic statins
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.corpus_classifier import classify_corpus  # noqa: E402


def _load_topic_aliases(topic: str) -> tuple[str, ...]:
    pack_path = REPO / "topic_packs" / f"{topic}.toml"
    if not pack_path.exists():
        return (topic,)
    pack = tomllib.loads(pack_path.read_text(encoding="utf-8"))
    aliases = pack.get("aliases", []) or []
    aliases = [a.lower() for a in aliases if isinstance(a, str)]
    if topic.lower() not in aliases:
        aliases.append(topic.lower())
    return tuple(aliases)


def _load_papers(parsed_dir: Path) -> list[dict]:
    out: list[dict] = []
    for p in sorted(parsed_dir.glob("*.paper_sections.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if "paper_id" not in data:
            data["paper_id"] = p.stem.replace(".paper_sections", "")
        out.append(data)
    return out


def _render_md(
    classifications: list, *, topic: str, parsed_dir: Path,
) -> str:
    counts = Counter(c.classification for c in classifications)
    n_total = len(classifications)
    lines = [
        f"# Corpus Classification — {topic}", "",
        f"**Source:** `{parsed_dir.relative_to(REPO)}` ({n_total} papers)",
        "", "## Class distribution", "",
        "| Class | Count | Pct |",
        "|---|---|---|",
    ]
    for cls in (
        "core_on_thesis", "background_mechanism", "adjacent_clinical",
        "off_thesis", "reject",
    ):
        n = counts.get(cls, 0)
        pct = (100.0 * n / n_total) if n_total else 0.0
        lines.append(f"| {cls} | {n} | {pct:.1f}% |")
    lines += ["", "## Per-paper detail", ""]
    for cls in (
        "core_on_thesis", "background_mechanism", "adjacent_clinical",
        "off_thesis", "reject",
    ):
        rows = [c for c in classifications if c.classification == cls]
        if not rows:
            continue
        lines.append(f"### {cls} ({len(rows)})")
        lines.append("")
        for c in sorted(rows, key=lambda r: -r.score)[:25]:
            lines.append(
                f"- `{c.paper_id}` (score {c.score}) — {c.reason}"
            )
        if len(rows) > 25:
            lines.append(f"- … {len(rows) - 25} more")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help="default: docs/quality-reference/<topic>/",
    )
    args = parser.parse_args(argv)
    out_dir = args.out_dir or (
        REPO / "docs" / "quality-reference" / args.topic
    )
    parsed_dir = out_dir / "parsed"
    if not parsed_dir.exists():
        print(
            f"[classifier] parsed dir missing: {parsed_dir}",
            file=sys.stderr,
        )
        return 1
    aliases = _load_topic_aliases(args.topic)
    papers = _load_papers(parsed_dir)
    classifications = classify_corpus(
        papers, topic_aliases=aliases,
    )
    json_path = out_dir / "corpus_classification.json"
    json_path.write_text(json.dumps(
        [asdict(c) for c in classifications], indent=2,
    ))
    md_path = out_dir / "corpus_classification.md"
    md_path.write_text(_render_md(
        classifications, topic=args.topic, parsed_dir=parsed_dir,
    ))
    counts = Counter(c.classification for c in classifications)
    print(
        f"[classifier] {args.topic}: {len(papers)} papers → "
        + ", ".join(f"{k}={v}" for k, v in counts.most_common()),
        file=sys.stderr,
    )
    print(f"  json: {json_path}", file=sys.stderr)
    print(f"   md : {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
