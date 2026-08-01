"""Topic discovery and bounded generated-pack materialization."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .io import AtomicJsonState, CorruptJsonState, JsonStateStatus

Publishable = Callable[..., bool]


def _generated_record(path: Path) -> dict[str, Any] | None:
    state = AtomicJsonState[dict[str, Any]](path, dict).read()
    if state.status is JsonStateStatus.CORRUPT:
        raise CorruptJsonState(f"{path}: {state.error}")
    return state.value


def discover_topics(
    topic_packs: Path,
    topic_pack_db: Path,
    *,
    generated_pack_publishable: Publishable,
) -> list[str]:
    topics = {
        path.stem
        for path in topic_packs.glob("*.toml")
        if not path.stem.startswith("_")
    }
    peer_records = generated_pack_records(topic_pack_db)
    for path in topic_pack_db.glob("*/latest.json"):
        record = _generated_record(path)
        if (
            not path.parent.name.startswith("_")
            and record is not None
            and isinstance(record.get("pack_data"), dict)
            and generated_pack_publishable(record, peer_records=peer_records)
        ):
            topics.add(path.parent.name)
    return sorted(topics)


def generated_pack_records(topic_pack_db: Path) -> list[dict[str, Any]]:
    return [
        record
        for path in sorted(topic_pack_db.glob("*/latest.json"))
        if (record := _generated_record(path))
    ]


def ordered_strategies(configured: str, strategies: Sequence[str]) -> list[str]:
    first = configured if configured in strategies else strategies[0]
    return [first, *(strategy for strategy in strategies if strategy != first)]


def refresh_topic_supply(
    *,
    materializer: Any,
    topic_pack_db: Path,
    skip_slugs: set[str] | None,
    quality_mode: str,
    scan_limits: Sequence[int],
    max_created: int,
    strategies: Sequence[str],
    dsn: str | None,
    base_url: str | None,
    token: str | None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    skipped: list[dict[str, Any]] = []
    for scan_limit in scan_limits:
        pass_attempts = 0
        for strategy in strategies:
            try:
                rows = (
                    materializer.fetch_rows(
                        dsn=dsn,
                        min_exact_facts=2,
                        min_papers=2,
                        limit=scan_limit,
                        strategy=strategy,
                    )
                    if dsn
                    else materializer.fetch_rows_http(
                        base_url=base_url,
                        token=token,
                        min_exact_facts=2,
                        min_papers=2,
                        limit=scan_limit,
                        strategy=strategy,
                    )
                )
                result = materializer.materialize_rows(
                    rows,
                    db_dir=topic_pack_db,
                    persist=True,
                    quality_mode=quality_mode,
                    max_created=max_created,
                    skip_slugs=skip_slugs,
                )
            except Exception as exc:
                errors[f"{strategy}:{scan_limit}"] = str(exc)
                continue
            created = result.get("created", [])
            result_skipped = result.get("skipped", []) or []
            skipped.extend(result_skipped)
            pass_attempts += len(rows)
            attempts.append({
                "strategy": strategy,
                "limit": scan_limit,
                "rows": len(rows),
                "created": len(created),
                "skipped": len(result_skipped),
            })
            if created:
                return {
                    **result,
                    "skipped": skipped,
                    "status": "topic_supply_refreshed",
                    "strategy": strategy,
                    "strategies_attempted": attempts,
                    "quality_mode": quality_mode,
                }
        if pass_attempts == 0:
            break
    if attempts:
        return {
            "created": [],
            "skipped": skipped,
            "status": "topic_supply_no_new_packs",
            "strategy": attempts[-1]["strategy"],
            "strategies_attempted": attempts,
            "quality_mode": quality_mode,
            **({"strategy_errors": errors} if errors else {}),
        }
    return {"status": "topic_supply_refresh_failed", "errors": errors, "created": []}


def created_topic_slugs(refresh: Mapping[str, Any]) -> set[str]:
    return {
        str(row.get("slug") or "")
        for row in refresh.get("created", [])
        if isinstance(row, dict)
    }
