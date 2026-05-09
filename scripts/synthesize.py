"""Generate a topic pack from a free-text topic.

This is the safe V1 front door for "synthesize by topic": it creates the
versioned generated pack record. Full synthesis remains gated by corpus
availability and the existing run_v06_synthesis.py path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.topic_pack_generator import (
    RetrievalCounts,
    generate_candidate_topic_pack,
    run_adaptive_expansion,
)
from agent.topic_pack_store import persist_generated_pack

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_topic_flow(
    topic: str,
    *,
    candidate_counts: tuple[int, ...] = (),
    db_dir: Path = REPO_ROOT / "topic_packs_db",
    persist: bool = False,
) -> dict[str, Any]:
    pack = generate_candidate_topic_pack(topic)
    if candidate_counts:
        counts = tuple(RetrievalCounts(unique_candidates=n) for n in candidate_counts)
        pack = run_adaptive_expansion(pack, counts).pack
    result: dict[str, Any] = {
        "topic": pack.topic,
        "slug": pack.slug,
        "domain": pack.domain,
        "tier": pack.tier,
        "status": "rejected" if pack.status == "stop" else "pack_ready",
        "stop_reason": pack.stop_reason,
        "candidate_cap": pack.candidate_cap,
        "topic_terms": list(pack.topic_terms),
        "corpus_search_queries": list(pack.corpus_search_queries),
        "validation_errors": list(pack.validation_errors),
    }
    if persist and pack.status == "proceed":
        record = persist_generated_pack(
            pack,
            db_dir,
            candidate_count=candidate_counts[-1] if candidate_counts else 0,
        )
        result["topic_pack_id"] = record.topic_pack_id
        result["topic_pack_version"] = record.version
        result["topic_pack_hash"] = record.pack_hash
        result["topic_pack_path"] = str(db_dir / pack.slug / f"v{record.version}.json")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Researka topic pack")
    parser.add_argument("--topic", required=True, help="Free-text topic name")
    parser.add_argument(
        "--candidate-count",
        type=int,
        action="append",
        default=[],
        help="Observed dry-run candidate count; repeat to simulate expansion rounds",
    )
    parser.add_argument(
        "--db-dir",
        type=Path,
        default=REPO_ROOT / "topic_packs_db",
        help="Generated topic-pack DB directory",
    )
    parser.add_argument("--persist", action="store_true", help="Write versioned pack")
    args = parser.parse_args(argv)
    result = build_topic_flow(
        args.topic,
        candidate_counts=tuple(args.candidate_count),
        db_dir=args.db_dir,
        persist=args.persist,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
