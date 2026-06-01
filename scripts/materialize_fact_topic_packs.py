"""Materialize fact-backed generated topic packs.

Turns validated Tier 2 fact groups into versioned topic_packs_db records. This
expands publishable topic capacity without weakening synthesis gates: generated
topics still have to seed a corpus, pass source precision, render, and submit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.topic_pack_generator import generate_candidate_topic_pack  # noqa: E402
from agent.topic_pack_store import (  # noqa: E402
    generated_pack_publishable,
    pack_hash,
    persist_generated_pack,
)

FACT_TOPIC_SQL = """
WITH grouped AS (
    SELECT
        COALESCE(NULLIF(ft.fact_json->>'topic', ''), 'unknown') AS topic,
        COALESCE(NULLIF(ft.fact_json->>'sub_topic', ''), 'general') AS sub_topic,
        COALESCE(NULLIF(ft.claim_type, ''), 'claim') AS claim_type,
        count(*) AS facts,
        count(DISTINCT ft.paper_id) AS papers,
        count(*) FILTER (WHERE fv.status = 'exact') AS exact_facts
    FROM facts_tier2 ft
    LEFT JOIN fact_validations fv ON fv.fact_id = ft.id
    WHERE ft.numeric_value IS NOT NULL
    GROUP BY 1, 2, 3
)
SELECT topic, sub_topic, claim_type, facts, papers, exact_facts
FROM grouped
WHERE topic NOT IN ('', 'other', 'unknown')
  AND exact_facts >= %(min_exact_facts)s
  AND papers >= %(min_papers)s
ORDER BY exact_facts DESC, papers DESC, facts DESC, topic, sub_topic, claim_type
LIMIT %(limit)s;
"""

CLAIM_LABELS = {
    "effect_size": "effects",
    "rate": "rates",
    "threshold": "thresholds",
    "regimen": "regimens",
    "duration": "durations",
    "adverse": "safety",
    "subgroup": "subgroups",
    "methodology": "measurement methods",
}
GENERIC_SUBTOPICS = {"", "general", "other", "unknown"}


def build_topic_name(row: dict[str, Any]) -> str:
    topic = _label(row.get("topic"))
    sub_topic = _label(row.get("sub_topic"))
    claim = CLAIM_LABELS.get(str(row.get("claim_type") or "").strip(), _label(row.get("claim_type")) or "evidence")
    if sub_topic.lower() in GENERIC_SUBTOPICS:
        return f"{topic} {claim} aging evidence"
    parts = [topic]
    if sub_topic.lower() != topic.lower():
        parts.append(sub_topic)
    if claim.lower() not in " ".join(parts).lower():
        parts.append(claim)
    return " ".join(parts)


def materialize_rows(
    rows: list[dict[str, Any]],
    *,
    db_dir: Path,
    persist: bool,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        pack = generate_candidate_topic_pack(
            build_topic_name(row),
            seed_terms=tuple(
                term for term in (_label(row.get("topic")), _label(row.get("sub_topic"))) if term
            ),
        )
        if pack.status != "proceed" or pack.validation_errors:
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": pack.stop_reason or pack.validation_errors})
            continue
        if not generated_pack_publishable(pack.to_topic_pack_dict()):
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "low_information_topic"})
            continue
        path = db_dir / pack.slug / "latest.json"
        digest = pack_hash(pack.to_topic_pack_dict())
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
            if current.get("pack_hash") == digest:
                skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "unchanged"})
                continue
        record = None
        if persist:
            record = persist_generated_pack(
                pack,
                db_dir,
                candidate_count=int(row.get("exact_facts") or row.get("facts") or 0),
                generated_by="fact-topic-materializer-v1",
            )
        created.append({
            "topic": pack.topic,
            "slug": pack.slug,
            "facts": int(row.get("facts") or 0),
            "exact_facts": int(row.get("exact_facts") or 0),
            "papers": int(row.get("papers") or 0),
            "path": str(path if record is None else db_dir / pack.slug / f"v{record.version}.json"),
        })
    return {"created": created, "skipped": skipped}


def fetch_rows(*, dsn: str, min_exact_facts: int, min_papers: int, limit: int) -> list[dict[str, Any]]:
    try:
        import psycopg2  # type: ignore[import-untyped]
        from psycopg2.extras import RealDictCursor  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - runtime environment check
        raise RuntimeError("psycopg2 is required for live DB materialization") from exc
    with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            FACT_TOPIC_SQL,
            {"min_exact_facts": min_exact_facts, "min_papers": min_papers, "limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]


def _label(value: object) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-dir", type=Path, default=REPO_ROOT / "topic_packs_db")
    parser.add_argument("--dsn", default=os.getenv("RESEARKA_DATABASE_DSN", ""))
    parser.add_argument("--rows-json", type=Path, help="Use exported rows instead of live Postgres")
    parser.add_argument("--min-exact-facts", type=int, default=2)
    parser.add_argument("--min-papers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    if args.rows_json:
        rows = json.loads(args.rows_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("--rows-json must contain a JSON list")
    else:
        if not args.dsn:
            raise SystemExit("Provide --dsn/RESEARKA_DATABASE_DSN or --rows-json")
        rows = fetch_rows(
            dsn=args.dsn,
            min_exact_facts=args.min_exact_facts,
            min_papers=args.min_papers,
            limit=args.limit,
        )
    result = materialize_rows(rows, db_dir=args.db_dir, persist=args.persist)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
