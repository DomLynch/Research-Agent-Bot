#!/usr/bin/env python3
"""Verify every DOI in every gold topic file resolves via doi.org.

Removes unresolvable DOIs and sets doi_verified=true + doi_verified_at on success.

Usage:
    python scripts/verify_dois.py [--dry-run]

Exits 1 if any source_review.doi fails to resolve (that's the ground-truth anchor
— we tolerate a few dead included_dois, but a missing systematic review is fatal).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

UA = "research-agent-bot/verify-dois (mailto:dom@domlynch.com)"
CROSSREF = "https://api.crossref.org/works"


def _resolves(client: httpx.Client, doi: str) -> bool:
    """A DOI 'resolves' iff it's registered in the CrossRef canonical registry.

    CrossRef is the authority for every DOI: registration = real citable work.
    Bypasses publisher CDN quirks (403s on HEAD, bot-UA blocking) that give
    false negatives for legitimate DOIs when hitting doi.org directly.
    """
    if not doi:
        return False
    try:
        r = client.get(f"{CROSSREF}/{doi}", timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def verify_topic(client: httpx.Client, topic_file: Path, dry_run: bool = False) -> dict:
    with topic_file.open() as f:
        gold = json.load(f)

    source_doi = (gold.get("source_review") or {}).get("doi", "")
    included = list(gold.get("included_dois", []))

    source_ok = _resolves(client, source_doi)
    time.sleep(0.15)

    kept: list[str] = []
    dropped: list[str] = []
    for doi in included:
        if _resolves(client, doi):
            kept.append(doi)
        else:
            dropped.append(doi)
        time.sleep(0.15)

    print(f"{topic_file.stem:28} source={'OK' if source_ok else 'DEAD'}  kept={len(kept)}/{len(included)}  dropped={len(dropped)}")

    gold["included_dois"] = kept
    gold["doi_verified"] = source_ok
    gold["doi_verified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if dropped:
        gold.setdefault("verification_notes", {})["dropped_dois"] = dropped

    if not dry_run:
        with topic_file.open("w") as f:
            json.dump(gold, f, indent=2)
            f.write("\n")

    return {"slug": topic_file.stem, "source_ok": source_ok, "kept": len(kept), "dropped": len(dropped)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    topics_dir = repo / "tests" / "golden" / "topics"

    rows = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for f in sorted(topics_dir.glob("*.json")):
            rows.append(verify_topic(client, f, dry_run=args.dry_run))

    dead_sources = [r for r in rows if not r["source_ok"]]
    total_kept = sum(r["kept"] for r in rows)
    total_dropped = sum(r["dropped"] for r in rows)
    print(f"\n=== SUMMARY ===  topics={len(rows)}  dead_source_dois={len(dead_sources)}  kept_included={total_kept}  dropped={total_dropped}")

    return 1 if dead_sources else 0


if __name__ == "__main__":
    sys.exit(main())
