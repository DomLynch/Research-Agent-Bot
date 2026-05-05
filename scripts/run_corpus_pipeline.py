"""CLI for the calibrated corpus pipeline — Slice 6 step 4c+4d.

End-to-end: TopicPack → wave retrieval → classify-before-extract →
CorpusManifest. Writes:

  docs/quality-reference/<topic>/corpus_manifest.json
    full structured manifest (entries + funnel + per_wave_stats)

  docs/quality-reference/<topic>/corpus_manifest.md
    human-readable funnel breakdown + per-class counts

Usage:
    python scripts/run_corpus_pipeline.py --topic rapamycin
    python scripts/run_corpus_pipeline.py --topic rapamycin \\
        --mode smoke           # dev / test pull (cap=100)
    python scripts/run_corpus_pipeline.py --topic rapamycin \\
        --safety-cap 50000     # tight cap for fast experiments
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.corpus_pipeline import (  # noqa: E402
    build_corpus_manifest, format_funnel_md,
)
from agent.retrieval_modes import resolve_params  # noqa: E402
from agent.topic_pack import load_topic_pack  # noqa: E402


def _entry_to_dict(entry) -> dict:
    return {
        "paper_id": entry.classification.paper_id,
        "doi": entry.hit.doi,
        "pmid": entry.hit.pmid,
        "title": entry.hit.title[:240],
        "year": entry.hit.year,
        "n_sources": entry.hit.n_sources,
        "sources": list(entry.hit.sources),
        "classification": entry.classification.classification,
        "score": entry.classification.score,
        "reason": entry.classification.reason,
        "pool": entry.pool,
        "keep_for_extraction": entry.keep_for_extraction,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument(
        "--mode",
        default="calibrated",
        choices=["smoke", "calibrated", "exhaustive", "snowball"],
        help="retrieval mode (default: calibrated)",
    )
    parser.add_argument(
        "--safety-cap", type=int, default=None,
        help="override GLOBAL_SAFETY_CAP for this run only",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help="default: docs/quality-reference/<topic>/",
    )
    args = parser.parse_args(argv)

    pack_path = REPO / "topic_packs" / f"{args.topic}.toml"
    if not pack_path.exists():
        print(
            f"[corpus-pipeline] topic pack missing: {pack_path}",
            file=sys.stderr,
        )
        return 1
    pack = load_topic_pack(pack_path)
    if pack.retrieval is None:
        print(
            f"[corpus-pipeline] topic pack '{args.topic}' has no "
            f"[retrieval] block; cannot run calibrated pipeline. "
            f"Add the schema before re-running.",
            file=sys.stderr,
        )
        return 2

    params = resolve_params(
        args.mode, safety_cap_override=args.safety_cap,
    )
    print(
        f"[corpus-pipeline] {args.topic} | {params.description}",
        file=sys.stderr,
    )

    manifest = asyncio.run(
        build_corpus_manifest(pack, params=params),
    )

    out_dir = args.out_dir or (
        REPO / "docs" / "quality-reference" / args.topic
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "corpus_manifest.json"
    json_path.write_text(json.dumps({
        "topic": manifest.topic,
        "funnel": dict(manifest.funnel),
        "per_wave_stats": [dict(s) for s in manifest.per_wave_stats],
        "entries": [_entry_to_dict(e) for e in manifest.entries],
    }, indent=2))
    md_path = out_dir / "corpus_manifest.md"
    md_path.write_text(format_funnel_md(manifest))

    f = manifest.funnel
    print(
        f"[corpus-pipeline] retrieved={f.get('retrieved',0)} | "
        f"keep={f.get('classified_keep',0)} | "
        f"core={f.get('extractable_core',0)} | "
        f"bg={f.get('extractable_background',0)} | "
        f"adj={f.get('extractable_adjacent',0)}",
        file=sys.stderr,
    )
    print(f"  json: {json_path}", file=sys.stderr)
    print(f"   md : {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
