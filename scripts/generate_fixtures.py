#!/usr/bin/env python3
"""Generate fixture drafts for gold topics by running the live bot.

Usage:
    python scripts/generate_fixtures.py [--topics rapamycin,nad_precursors] [--all]

Requires: MIMO_API_KEY, httpx

Each fixture draft is saved to tests/golden/fixtures/<slug>_draft.json
and contains the real bot output with verified DOIs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REQUIRED_ENV = ["MIMO_API_KEY"]


def check_env():
    missing = [v for v in REQUIRED_ENV if not os.getenv(v)]
    if missing:
        print(f"ERROR: Missing env vars: {missing}")
        sys.exit(1)


def generate_fixture(slug: str, topic: str, domain: str, criteria: str) -> dict | None:
    """Run the bot pipeline for one topic, return draft artifact."""
    try:
        from agent.planner import QueryPlanner
        from agent.sources.pubmed import PubMedClient
        from agent.sources.openalex import OpenAlexClient
        from agent.drafter import RapidEvidenceDrafter
        from agent.provider import MimoClient
    except ImportError as e:
        print(f"Import error: {e}")
        return None

    provider = MimoClient.from_env()
    planner = QueryPlanner()
    drafter = RapidEvidenceDrafter(provider=provider)

    plan = planner.build(topic=topic, domain_slug=domain, criteria=criteria)

    evidence = []
    for source_name, client_cls in [("pubmed", PubMedClient), ("openalex", OpenAlexClient)]:
        client = client_cls()
        for query in plan.primary_queries():
            try:
                results = client.search(query, limit=20)
                evidence.extend(results)
            except Exception as e:
                print(f"  [{source_name}] {query[:50]}: {e}", file=sys.stderr)

    artifact, raw = drafter.draft(
        topic=topic,
        domain_slug=domain,
        criteria=criteria,
        queries=plan.queries,
        evidence=evidence,
        all_evidence=evidence,
    )

    if artifact.get("error"):
        print(f"  ERROR: {artifact['error']}")
        return None

    return artifact


def main():
    parser = argparse.ArgumentParser(description="Generate fixture drafts for gold topics")
    parser.add_argument("--topics", default="", help="Comma-separated slugs, or empty for all")
    parser.add_argument("--all", action="store_true", help="Generate all topics")
    args = parser.parse_args()

    check_env()

    topics_dir = Path("tests/golden/topics")
    fixture_dir = Path("tests/golden/fixtures")
    fixture_dir.mkdir(parents=True, exist_ok=True)

    slugs = []
    if args.topics:
        slugs = args.topics.split(",")
    elif args.all:
        slugs = [f.stem for f in topics_dir.glob("*.json")]
    else:
        print("Use --topics <slug1,slug2> or --all")
        print("Available slugs:")
        for f in sorted(topics_dir.glob("*.json")):
            print(f"  {f.stem}")
        return

    print(f"Generating fixtures for: {', '.join(slugs)}")
    print()

    for slug in slugs:
        topic_file = topics_dir / f"{slug}.json"
        if not topic_file.exists():
            print(f"[SKIP] {slug}: no topic file")
            continue

        with open(topic_file) as f:
            topic_data = json.load(f)

        topic = topic_data["topic"]
        domain = topic_data.get("domain", "longevity")
        criteria = topic_data.get("criteria", "")

        print(f"=== {slug} ===")
        print(f"Topic: {topic}")
        print(f"Domain: {domain}")

        fixture_path = fixture_dir / f"{slug}_draft.json"
        if fixture_path.exists():
            print(f"  [EXISTS] {fixture_path} — skipping (delete to regenerate)")
        else:
            artifact = generate_fixture(slug, topic, domain, criteria)
            if artifact:
                with open(fixture_path, "w") as f:
                    json.dump(artifact, f, indent=2)
                bundle_size = len(artifact.get("source_bundle", []))
                print(f"  [OK] Saved {fixture_path} ({bundle_size} sources)")
            else:
                print("  [FAIL] Could not generate fixture")
            time.sleep(2)

        print()


if __name__ == "__main__":
    main()