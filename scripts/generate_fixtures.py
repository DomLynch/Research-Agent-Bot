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
    """Run the REAL production path for one topic, return draft artifact + telemetry.

    Uses run_agent() directly so fixtures match production behaviour:
    all 5 sources (pubmed/openalex/rxiv/clinicaltrials/chembl) fire per
    the _should_use_* gates, quality gates apply, telemetry is captured.
    """
    try:
        from agent.cli import run_agent
    except ImportError as e:
        print(f"Import error: {e}")
        return None

    # Use a temporary run_dir so we don't pollute runs/ with fixtures
    run_log = run_agent(
        topic=topic,
        domain=domain,
        criteria=criteria,
        per_source_limit=20,  # match brief's original "limit=20" behaviour
        run_dir="tests/golden/fixture_runs",
    )

    if run_log.get("error"):
        print(f"  ERROR: {run_log['error']}")
        return None

    # Strip fields that don't belong in a scored fixture artifact
    artifact = {
        k: v for k, v in run_log.items()
        if k not in {"run_log", "started_at", "topic", "domain_slug", "criteria",
                     "queries", "scope_signals", "source_errors",
                     "evidence_retrieved", "evidence_selected",
                     "submission", "submission_id", "submission_status",
                     "submission_error", "fingerprint", "markdown_file"}
    }
    # Keep telemetry for transparency
    artifact["_telemetry"] = {
        "source_counts": run_log.get("source_counts", {}),
        "bundle_stages": run_log.get("bundle_stages", {}),
        "evidence_retrieved": run_log.get("evidence_retrieved"),
        "evidence_selected": run_log.get("evidence_selected"),
    }
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