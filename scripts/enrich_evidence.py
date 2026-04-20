#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrichment import enrich_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich evidence receipts via MiniMax")
    parser.add_argument("input", type=Path, help="JSON file with list of evidence receipts")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: runs/<stem>.evidence.json)")
    args = parser.parse_args()

    evidence = json.loads(args.input.read_text())
    if not isinstance(evidence, list):
        evidence = [evidence]

    output_path = args.output
    if output_path is None:
        stem = args.input.stem
        runs_dir = Path("runs")
        runs_dir.mkdir(exist_ok=True)
        output_path = runs_dir / f"{stem}.evidence.json"

    results = enrich_batch(evidence, output_path)
    print(f"Enriched {len(results)} items -> {output_path}")


if __name__ == "__main__":
    main()
