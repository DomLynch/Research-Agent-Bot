#!/usr/bin/env python3
"""Populate gold topic files with real ground truth from OpenAlex.

For each gold topic:
1. Search OpenAlex for top systematic review / meta-analysis on the topic
2. Write its DOI into source_review
3. Fetch referenced_works, extract real DOIs, write into included_dois

This replaces hand-curation with programmatic ground truth — same data a
human curator would extract, no hallucination risk.

Usage:
    python scripts/curate_gold.py [--dry-run] [--topic <slug>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


OPENALEX = "https://api.openalex.org"
UA = "research-agent-bot/curate-gold (+https://research-agent.domlynch.com)"
MAX_REFS = 15


def _doi(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("https://doi.org/", "").replace("http://doi.org/", "").strip().lower() or None


_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an", "or", "vs"}


def _topic_tokens(topic: str) -> list[str]:
    return [t.lower() for t in topic.replace("-", " ").split() if t.lower() not in _STOPWORDS and len(t) > 2]


def _title_matches_topic(title: str | None, tokens: list[str]) -> bool:
    """Require at least one non-stopword topic token to appear in the title."""
    if not title or not tokens:
        return False
    tl = title.lower()
    return any(tok in tl for tok in tokens)


def _fetch_review(client: httpx.Client, topic: str) -> dict | None:
    """Search OpenAlex for top review on topic since 2022 with topic-token in title."""
    tokens = _topic_tokens(topic)
    for review_filter in ("type:review", "type:review,has_abstract:true"):
        params = {
            "search": topic,
            "filter": f"{review_filter},from_publication_date:2022-01-01",
            "per-page": 15,
            "select": "id,doi,title,publication_year,primary_location,referenced_works,abstract_inverted_index",
        }
        r = client.get(f"{OPENALEX}/works", params=params, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])
        # Require topic-token in title — otherwise OpenAlex sometimes routes to
        # tangentially-relevant top-cited papers on related topics.
        for work in results:
            if (
                work.get("doi")
                and work.get("referenced_works")
                and _title_matches_topic(work.get("title"), tokens)
            ):
                return work
    return None


def _fetch_ref_doi(client: httpx.Client, ref_url: str) -> str | None:
    """Given an OpenAlex work URL, return its DOI (or None)."""
    oa_id = ref_url.rsplit("/", 1)[-1]
    try:
        r = client.get(f"{OPENALEX}/works/{oa_id}", params={"select": "doi"}, timeout=15)
        r.raise_for_status()
        return _doi(r.json().get("doi"))
    except Exception:
        return None


def _conclusion_from_abstract(inverted_index: dict | None) -> str:
    if not isinstance(inverted_index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for i in indexes:
            try:
                positions[int(i)] = str(word)
            except (TypeError, ValueError):
                continue
    text = " ".join(positions[i] for i in sorted(positions))
    # Take last 2 sentences as conclusion-ish summary
    sentences = [s.strip() for s in text.replace("!", ".").split(".") if s.strip()]
    return ". ".join(sentences[-2:])[:400] if sentences else ""


def curate_topic(client: httpx.Client, topic_file: Path, dry_run: bool = False) -> dict:
    with topic_file.open() as f:
        gold = json.load(f)

    topic = gold.get("topic", "")
    print(f"=== {topic_file.stem} === '{topic}'")

    review = _fetch_review(client, topic)
    if not review:
        print("  [SKIP] no systematic review with DOI + references found")
        return {"slug": topic_file.stem, "status": "no_review_found"}

    source_doi = _doi(review.get("doi"))
    source_title = review.get("title", "")[:300]
    source_year = review.get("publication_year")
    location = review.get("primary_location") or {}
    source_journal = (location.get("source") or {}).get("display_name", "") if isinstance(location.get("source"), dict) else ""
    refs = review.get("referenced_works", []) or []
    print(f"  review: {source_title[:70]}...")
    print(f"  doi: {source_doi}  year: {source_year}  refs_available: {len(refs)}")

    included_dois: list[str] = []
    for ref_url in refs[:MAX_REFS]:
        d = _fetch_ref_doi(client, ref_url)
        if d:
            included_dois.append(d)
        time.sleep(0.12)  # polite pool ≤10/sec
    print(f"  resolved {len(included_dois)} DOIs from {min(len(refs), MAX_REFS)} references")

    new_summary = _conclusion_from_abstract(review.get("abstract_inverted_index"))

    gold["source_review"] = {
        "doi": source_doi or gold.get("source_review", {}).get("doi", ""),
        "title": source_title,
        "year": source_year,
        "journal": source_journal,
        "url": f"https://doi.org/{source_doi}" if source_doi else "",
    }
    gold["included_dois"] = included_dois
    if new_summary and not gold.get("conclusion_summary", "").strip():
        gold["conclusion_summary"] = new_summary
    gold["last_validated"] = datetime.now(timezone.utc).date().isoformat()
    gold["curator"] = "openalex-programmatic"
    gold["doi_verified"] = False  # set true by verify_dois.py

    if dry_run:
        print("  [DRY RUN] would write", topic_file)
    else:
        with topic_file.open("w") as f:
            json.dump(gold, f, indent=2)
            f.write("\n")
        print(f"  [OK] wrote {topic_file}")

    return {
        "slug": topic_file.stem,
        "status": "ok",
        "source_doi": source_doi,
        "included_count": len(included_dois),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--topic", help="Single topic slug to curate")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    topics_dir = repo / "tests" / "golden" / "topics"

    files = sorted(topics_dir.glob("*.json"))
    if args.topic:
        files = [f for f in files if f.stem == args.topic]
        if not files:
            print(f"no topic {args.topic}", file=sys.stderr)
            return 1

    summary = []
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        for f in files:
            try:
                summary.append(curate_topic(client, f, dry_run=args.dry_run))
            except Exception as exc:
                print(f"  [ERROR] {f.stem}: {exc}")
                summary.append({"slug": f.stem, "status": "error", "error": str(exc)})

    print("\n=== SUMMARY ===")
    for row in summary:
        if row.get("status") == "ok":
            print(f"  {row['slug']:30}  DOI={row['source_doi'][:50] if row['source_doi'] else 'NONE':50}  refs={row['included_count']}")
        else:
            print(f"  {row['slug']:30}  {row['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
