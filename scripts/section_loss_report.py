#!/usr/bin/env python3
"""Compare per-section word counts as BUILT vs as RENDERED, per run.

Reads manifest.json section_words (written at render time) against the
section body in full_paper.md, for the SAME run. Comparing across runs or
against already-finalized files produced four wrong conclusions on
2026-08-08; this pins both numbers to one run id.

Measured over 735 completed runs: rendered normally EXCEEDS built (median
+52, the finalizer adds deterministic content). The failure mode is bimodal --
64/735 runs render the section as 0 words, i.e. the section is absent despite
being built. That total loss, not gradual erosion, is what fails the surface
gate. Read-only.
"""
import glob
import json
import os
import re

SECTION = "cross_domain_synthesis"
HEADING = "Cross-Domain Synthesis"


def rendered_words(paper: str, heading: str) -> int:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\b.*?\n(.*?)(?=^##\s+|\Z)", paper, re.M | re.S,
    )
    return len(re.findall(r"\b\w+\b", match.group(1))) if match else 0


def main() -> int:
    rows: list[tuple[int, int, int, str]] = []
    for manifest in glob.glob("runs/synthesis-*/manifest.json"):
        run_dir = os.path.dirname(manifest)
        paper_path = os.path.join(run_dir, "full_paper.md")
        if not os.path.exists(paper_path):
            continue
        try:
            section_words = (json.load(open(manifest)) or {}).get("section_words") or {}
        except (OSError, ValueError):
            continue
        built = section_words.get(SECTION)
        if not built:
            continue
        paper = open(paper_path, errors="replace").read()
        rendered = rendered_words(paper, HEADING)
        rows.append((built - rendered, built, rendered, os.path.basename(run_dir)[:44]))

    rows.sort(reverse=True)
    print(f"completed runs with both artifacts: {len(rows)}")
    if not rows:
        return 0
    losses = [row[0] for row in rows]
    absent = [row for row in rows if row[2] == 0]
    print(f"  runs where rendered < built: {sum(1 for x in losses if x > 0)}/{len(rows)}")
    print(f"  runs where section is ABSENT (rendered=0): {len(absent)}")
    print(f"  median delta (negative = finalizer added): {sorted(losses)[len(losses) // 2]}")
    print("  largest losses:")
    for loss, built, rendered, name in rows[:4]:
        print(f"    -{loss:<5} built={built:<5} rendered={rendered:<5} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
