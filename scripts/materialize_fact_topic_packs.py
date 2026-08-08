"""Materialize fact-backed generated topic packs.

Turns validated Tier 2 fact groups into versioned topic_packs_db records. This
expands publishable topic capacity without weakening synthesis gates: generated
topics still have to seed a corpus, pass source precision, render, and submit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.topic_pack_generator import generate_candidate_topic_pack  # noqa: E402
from agent.topic_pack_store import pack_hash, persist_generated_pack  # noqa: E402
from source_topic_specificity import generated_pack_publishable, topic_tokens  # noqa: E402

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

FACT_FIELD_CROSS_SQL = """
WITH expanded AS (
    SELECT
        COALESCE(NULLIF(ft.fact_json->>'topic', ''), 'unknown') AS topic,
        CASE
            WHEN kv.key = 'sub_topic' THEN kv.value
            ELSE concat(kv.key, ' ', kv.value)
        END AS sub_topic,
        COALESCE(NULLIF(ft.claim_type, ''), 'claim') AS claim_type,
        count(*) AS facts,
        count(DISTINCT ft.paper_id) AS papers,
        count(*) FILTER (WHERE fv.status = 'exact') AS exact_facts
    FROM facts_tier2 ft
    LEFT JOIN fact_validations fv ON fv.fact_id = ft.id
    CROSS JOIN LATERAL jsonb_each_text(ft.fact_json::jsonb) AS kv(key, value)
    WHERE ft.numeric_value IS NOT NULL
      AND kv.key IN ('sub_topic', 'population', 'intervention', 'outcome', 'endpoint', 'condition', 'species')
      AND (kv.key != 'intervention' OR lower(trim(kv.value)) != lower(COALESCE(NULLIF(ft.fact_json->>'topic', ''), '')))
      AND lower(trim(kv.value)) NOT IN ('', 'other', 'unknown', 'none', 'false', 'true', 'global', 'baseline', 'control', 'control group', 'placebo', 'healthy controls', 'methodology')
      AND length(trim(kv.value)) BETWEEN 3 AND 80
    GROUP BY 1, 2, 3
)
SELECT topic, sub_topic, claim_type, facts, papers, exact_facts
FROM expanded
WHERE topic NOT IN ('', 'other', 'unknown')
  AND exact_facts >= %(min_exact_facts)s
  AND papers >= %(min_papers)s
ORDER BY exact_facts DESC, papers DESC, facts DESC, topic, sub_topic, claim_type
LIMIT %(limit)s;
"""

FACT_PAIR_CROSS_SQL = """
WITH expanded AS (
    SELECT
        COALESCE(NULLIF(ft.fact_json->>'topic', ''), 'unknown') AS topic,
        concat(trim(ft.fact_json->>'intervention'), ' in ', trim(ft.fact_json->>'population')) AS sub_topic,
        COALESCE(NULLIF(ft.claim_type, ''), 'claim') AS claim_type,
        count(*) AS facts,
        count(DISTINCT ft.paper_id) AS papers,
        count(*) FILTER (WHERE fv.status = 'exact') AS exact_facts
    FROM facts_tier2 ft
    LEFT JOIN fact_validations fv ON fv.fact_id = ft.id
    WHERE ft.numeric_value IS NOT NULL
      AND length(trim(COALESCE(ft.fact_json->>'intervention', ''))) BETWEEN 3 AND 80
      AND length(trim(COALESCE(ft.fact_json->>'population', ''))) BETWEEN 3 AND 80
    GROUP BY 1, 2, 3
)
SELECT topic, sub_topic, claim_type, facts, papers, exact_facts
FROM expanded
WHERE topic NOT IN ('', 'other', 'unknown')
  AND lower(split_part(sub_topic, ' in ', 1)) NOT IN ('', 'other', 'unknown', 'none', 'false', 'true', 'global', 'baseline', 'control', 'control group', 'placebo', 'healthy controls', 'methodology', 'n/a', 'na')
  AND lower(split_part(sub_topic, ' in ', 2)) NOT IN ('', 'other', 'unknown', 'none', 'false', 'true', 'global', 'baseline', 'control', 'control group', 'placebo', 'healthy controls', 'methodology', 'n/a', 'na')
  AND lower(split_part(sub_topic, ' in ', 1)) != lower(topic)
  AND exact_facts >= %(min_exact_facts)s
  AND papers >= %(min_papers)s
ORDER BY exact_facts DESC, papers DESC, facts DESC, topic, sub_topic, claim_type
LIMIT %(limit)s;
"""

FACT_INTERVENTION_CROSS_SQL = """
WITH expanded AS (
    SELECT
        trim(ft.fact_json->>'intervention') AS topic,
        COALESCE(NULLIF(ft.fact_json->>'topic', ''), 'general') AS sub_topic,
        COALESCE(NULLIF(ft.claim_type, ''), 'claim') AS claim_type,
        count(*) AS facts,
        count(DISTINCT ft.paper_id) AS papers,
        count(*) FILTER (WHERE fv.status = 'exact') AS exact_facts
    FROM facts_tier2 ft
    LEFT JOIN fact_validations fv ON fv.fact_id = ft.id
    WHERE ft.numeric_value IS NOT NULL
      AND length(trim(COALESCE(ft.fact_json->>'intervention', ''))) BETWEEN 3 AND 80
    GROUP BY 1, 2, 3
)
SELECT topic, sub_topic, claim_type, facts, papers, exact_facts
FROM expanded
WHERE lower(topic) NOT IN ('', 'other', 'unknown', 'none', 'false', 'true', 'global', 'baseline', 'control', 'control group', 'placebo', 'healthy controls', 'methodology', 'n/a', 'na')
  AND lower(topic) NOT LIKE 'none%%'
  AND lower(topic) != lower(sub_topic)
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
HIGH_PRECISION_ACTION_TERMS = {
    "agonist", "agonists", "antagonist", "antagonists", "fasting",
    "inhibitor", "inhibitors", "rehabilitation", "restriction", "supplementation",
    "vaccination", "vaccine",
}
DSN_ENV_NAMES = ("RESEARKA_DATABASE_DSN", "DATABASE_URL", "POSTGRES_DSN", "POSTGRES_URL")
HTTP_URL_ENV = "RESEARKA_DATABASE_URL"
HTTP_TOKEN_ENV = "RESEARKA_DATABASE_TOKEN"
TOPIC_GROUPS_PATH = "/api/v1/tier2/facts/topic-groups"


def dsn_from_env() -> str:
    for name in DSN_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value.startswith(("postgres://", "postgresql://")):
            return value
    return ""


def http_credentials_from_env() -> tuple[str, str]:
    return os.getenv(HTTP_URL_ENV, "").strip(), os.getenv(HTTP_TOKEN_ENV, "").strip()


def build_topic_name(row: dict[str, Any]) -> str:
    topic = _label(row.get("topic"))
    sub_topic = _label(row.get("sub_topic"))
    claim = CLAIM_LABELS.get(str(row.get("claim_type") or "").strip(), _label(row.get("claim_type")) or "evidence")
    if sub_topic.lower() in GENERIC_SUBTOPICS:
        return f"{topic} {claim}"
    parts = [topic]
    topic_s = _singular_label(topic).lower()
    sub_topic_s = _singular_label(sub_topic).lower()
    if sub_topic_s != topic_s and sub_topic_s not in topic_s and topic_s not in sub_topic_s:
        parts.append(sub_topic)
    if _singular_label(claim).lower() not in _singular_label(" ".join(parts)).lower():
        parts.append(claim)
    return " ".join(parts)


def materialize_rows(
    rows: list[dict[str, Any]],
    *,
    db_dir: Path,
    persist: bool,
    quality_mode: str = "standard",
    max_created: int | None = None,
    skip_slugs: set[str] | None = None,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    skip_slugs = skip_slugs or set()
    candidates = []
    for row in rows:
        seed_terms = tuple(
            term for term in (_label(row.get("topic")), _label(row.get("sub_topic")))
            if term and term.lower() not in GENERIC_SUBTOPICS
        )
        pack = generate_candidate_topic_pack(build_topic_name(row), seed_terms=seed_terms, query_anchor=_label(row.get("topic")))
        candidates.append((row, pack, {
            "pack_data": pack.to_topic_pack_dict(),
            "candidate_count": int(row.get("exact_facts") or row.get("facts") or 0),
        }))
    peer_records = [record for record in _existing_records(db_dir) + [
        record for row, pack, record in candidates
        if quality_mode != "high-precision" or _high_precision_pack(row, pack)
    ] if generated_pack_publishable(record, peer_records=())]
    batch_slugs: set[str] = set()
    for row, pack, record in candidates:
        if pack.status != "proceed" or pack.validation_errors:
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": pack.stop_reason or pack.validation_errors})
            continue
        if pack.slug in skip_slugs:
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "excluded_topic"})
            continue
        if pack.slug in batch_slugs:
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "duplicate_batch_slug"})
            continue
        candidate_count = int(row.get("exact_facts") or row.get("facts") or 0)
        if not generated_pack_publishable(record, peer_records=peer_records):
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "low_information_topic"})
            continue
        if quality_mode == "high-precision" and not _high_precision_pack(row, pack):
            skipped.append({"topic": pack.topic, "slug": pack.slug, "reason": "quality_filter_failed"})
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
        persisted = None
        if persist:
            persisted = persist_generated_pack(
                pack,
                db_dir,
                candidate_count=candidate_count,
                generated_by=f"fact-topic-materializer-v1:{quality_mode}",
            )
        created.append({
            "topic": pack.topic,
            "slug": pack.slug,
            "facts": int(row.get("facts") or 0),
            "exact_facts": int(row.get("exact_facts") or 0),
            "papers": int(row.get("papers") or 0),
            "path": str(path if persisted is None else db_dir / pack.slug / f"v{persisted.version}.json"),
        })
        batch_slugs.add(pack.slug)
        if max_created is not None and len(created) >= max_created:
            break
    return {"created": created, "skipped": skipped}


def _existing_records(db_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(db_dir.glob("*/latest.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def fetch_rows(
    *,
    dsn: str,
    min_exact_facts: int,
    min_papers: int,
    limit: int,
    strategy: str = "grouped",
) -> list[dict[str, Any]]:
    try:
        import psycopg2  # type: ignore[import-untyped]
        from psycopg2.extras import RealDictCursor  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - runtime environment check
        raise RuntimeError("psycopg2 is required for live DB materialization") from exc
    with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        sql = {
            "grouped": FACT_TOPIC_SQL,
            "fact-field-cross": FACT_FIELD_CROSS_SQL,
            "fact-pair-cross": FACT_PAIR_CROSS_SQL,
            "fact-intervention-cross": FACT_INTERVENTION_CROSS_SQL,
        }[strategy]
        cur.execute(sql, {"min_exact_facts": min_exact_facts, "min_papers": min_papers, "limit": limit})
        return [dict(row) for row in cur.fetchall()]


def fetch_rows_http(
    *,
    base_url: str,
    token: str,
    min_exact_facts: int,
    min_papers: int,
    limit: int,
    strategy: str = "grouped",
) -> list[dict[str, Any]]:
    rows = _post_json(
        base_url.rstrip("/") + TOPIC_GROUPS_PATH,
        token,
        {
            "strategy": strategy,
            "limit": limit,
            "min_exact_facts": min_exact_facts,
            "min_papers": min_papers,
        },
    )
    if not isinstance(rows, list):
        raise RuntimeError("topic-groups endpoint returned non-list payload")
    return [dict(row) for row in rows if isinstance(row, dict)]


def _post_json(url: str, token: str, payload: dict[str, object]) -> object:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Researka-Token": token,
            "User-Agent": "research-agent-bot-topic-materializer/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"topic-groups endpoint failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"topic-groups endpoint unavailable: {exc.reason}") from exc


def _label(value: object) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


def _singular_label(value: str) -> str:
    return " ".join(token[:-1] if token.endswith("s") and len(token) > 4 else token for token in value.split())


def _high_precision_pack(row: dict[str, Any], pack: object) -> bool:
    if not topic_tokens(_label(row.get("topic"))) or set(_singular_label(_label(row.get("claim_type"))).lower().split()) & {"method", "methodology", "rate", "technique", "threshold"}:
        return False
    sub_topic = _singular_label(_label(row.get("sub_topic"))).lower()
    if set(sub_topic.split()) & {"method", "rate", "technique", "threshold"}:
        return False
    tier = str(getattr(pack, "tier", ""))
    if tier in {"mainstream", "emerging", "contested"}:
        return True
    raw_terms = " ".join(str(term) for term in getattr(pack, "aliases", ()))
    tokens = set(re.findall(r"[a-z0-9]+", raw_terms.lower()))
    return bool(tokens & HIGH_PRECISION_ACTION_TERMS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-dir", type=Path, default=REPO_ROOT / "topic_packs_db")
    parser.add_argument("--dsn", default=dsn_from_env())
    parser.add_argument("--rows-json", type=Path, help="Use exported rows instead of live Postgres")
    parser.add_argument("--min-exact-facts", type=int, default=2)
    parser.add_argument("--min-papers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--strategy",
        choices=("grouped", "fact-field-cross", "fact-pair-cross", "fact-intervention-cross"),
        default="grouped",
    )
    parser.add_argument("--quality-mode", choices=("standard", "high-precision"), default="standard")
    parser.add_argument("--max-created", type=int, help="Stop after creating this many packs")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    if args.rows_json:
        rows = json.loads(args.rows_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("--rows-json must contain a JSON list")
    else:
        if args.dsn:
            rows = fetch_rows(
                dsn=args.dsn,
                min_exact_facts=args.min_exact_facts,
                min_papers=args.min_papers,
                limit=args.limit,
                strategy=args.strategy,
            )
        else:
            base_url, token = http_credentials_from_env()
            if not base_url or not token:
                raise SystemExit(
                    "Provide --dsn, one Postgres DSN env "
                    f"({', '.join(DSN_ENV_NAMES)}), {HTTP_URL_ENV}+{HTTP_TOKEN_ENV}, or --rows-json"
                )
            rows = fetch_rows_http(
                base_url=base_url,
                token=token,
                min_exact_facts=args.min_exact_facts,
                min_papers=args.min_papers,
                limit=args.limit,
                strategy=args.strategy,
            )
    result = materialize_rows(
        rows,
        db_dir=args.db_dir,
        persist=args.persist,
        quality_mode=args.quality_mode,
        max_created=args.max_created,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
