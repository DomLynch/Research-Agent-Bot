"""Capture real adapter output for the 5 golden topics.

Run once when adapters change shape, or to refresh the corpus. Output is
stable, sorted JSON committed under tests/fixtures/<topic>/<source>.json so
test_bundle.py and test_sources.py can replay without burning API quota.

Usage:
    python scripts/capture_fixtures.py
    python scripts/capture_fixtures.py --topic rapamycin
    python scripts/capture_fixtures.py --limit 12
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Make `agent.*` importable when this script is invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from agent.sources._base import USER_AGENT  # noqa: E402
from agent.sources.clinicaltrials import ClinicalTrialsClient  # noqa: E402
from agent.sources.europepmc import EuropePMCClient  # noqa: E402
from agent.sources.openalex import OpenAlexClient  # noqa: E402
from agent.sources.pubmed import PubMedClient  # noqa: E402
from agent.types import RawHit  # noqa: E402

TOPICS: list[tuple[str, str]] = [
    # Each query is tuned to surface the published+protocol pair we want the
    # classifier to distinguish. "rapamycin aging" missed RAPA-EX entirely;
    # "rapamycin older adults" returns both PMID 41985884 (results, 2026)
    # and PMID 39354527 (protocol, 2024) — exactly the V0 contradiction case.
    ("rapamycin", "rapamycin older adults"),
    ("metformin", "metformin aging older adults"),
    ("senolytics", "senolytics dasatinib quercetin older adults"),
    ("semaglutide_weight", "semaglutide weight loss adults"),
    ("vitamin_d_mortality", "vitamin D supplementation mortality elderly"),
]

CLIENTS = [
    PubMedClient(),
    OpenAlexClient(),
    EuropePMCClient(),
    ClinicalTrialsClient(),
]

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _serialize(hit: RawHit) -> dict:
    return asdict(hit)


async def capture(*, limit: int, polite_delay_sec: float, only_topic: str | None) -> None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
        for slug, query in TOPICS:
            if only_topic and slug != only_topic:
                continue
            topic_dir = OUT_DIR / slug
            topic_dir.mkdir(parents=True, exist_ok=True)
            for adapter in CLIENTS:
                print(f"  {slug:22s} {adapter.name:16s}", end=" ", flush=True)
                try:
                    hits = await adapter.search(client, query, limit=limit)
                except Exception as exc:  # noqa: BLE001 — capture script, log + continue
                    print(f"FAILED: {type(exc).__name__}: {exc}")
                    continue
                payload = [_serialize(h) for h in hits]
                path = topic_dir / f"{adapter.name}.json"
                path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                print(f"{len(hits):>2} hits -> {path.relative_to(OUT_DIR.parent.parent)}")
                await asyncio.sleep(polite_delay_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8, help="hits per source per topic")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds to sleep between calls (be polite)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="capture only this topic slug (default: all)",
    )
    args = parser.parse_args()
    asyncio.run(
        capture(limit=args.limit, polite_delay_sec=args.delay, only_topic=args.topic)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
