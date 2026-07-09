#!/usr/bin/env python3
"""Report when Researka has no recent public publication."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_PUBLICATIONS_URL = "https://researka.org/api/publications"
DEFAULT_RUNS_ROOT = Path("runs")
DEFAULT_REPORT_PATH = Path("reports/publish_drought_guard.json")
TIMESTAMP_KEYS = (
    "publishedAt",
    "published_at",
    "createdAt",
    "created_at",
    "updatedAt",
    "updated_at",
)


@dataclass(frozen=True)
class DroughtStatus:
    passed: bool
    status: str
    reason: str
    total: int
    latest_at: str | None
    age_hours: float | None
    max_age_hours: float
    triage: dict[str, Any]


def publication_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("publications", "items", "rows", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for value in payload.values():
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            if rows:
                return rows
    return []


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def latest_publication_at(rows: list[dict[str, Any]]) -> dt.datetime | None:
    seen: list[dt.datetime] = []
    for row in rows:
        for key in TIMESTAMP_KEYS:
            parsed = parse_timestamp(row.get(key))
            if parsed is not None:
                seen.append(parsed.astimezone(dt.UTC))
                break
    return max(seen) if seen else None


def evaluate_drought(
    rows: list[dict[str, Any]],
    *,
    now: dt.datetime,
    max_age_hours: float,
    triage: dict[str, Any] | None = None,
) -> DroughtStatus:
    now_utc = now.astimezone(dt.UTC) if now.tzinfo else now.replace(tzinfo=dt.UTC)
    latest = latest_publication_at(rows)
    if latest is None:
        return DroughtStatus(
            passed=False,
            status="fail",
            reason="no_publication_timestamps",
            total=len(rows),
            latest_at=None,
            age_hours=None,
            max_age_hours=max_age_hours,
            triage=triage or {},
        )
    age_hours = (now_utc - latest).total_seconds() / 3600
    passed = age_hours <= max_age_hours
    return DroughtStatus(
        passed=passed,
        status="pass" if passed else "fail",
        reason="recent_publication" if passed else "publish_drought",
        total=len(rows),
        latest_at=latest.isoformat(),
        age_hours=round(age_hours, 2),
        max_age_hours=max_age_hours,
        triage=triage or {},
    )


def recent_lane_ledgers(runs_root: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    ledgers: list[dict[str, Any]] = []
    for subdir in ("_daily_research_paper_cycle_ledger", "_daily_research_paper_ledger"):
        for path in sorted((runs_root / subdir).glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            ledgers.append({
                "ledger": str(path),
                "mode": data.get("mode") or ("daily-submit" if subdir.endswith("_ledger") else None),
                "status": data.get("status"),
                "topic": data.get("attempted_topic") or data.get("topic_slug") or data.get("topic"),
                "submitted": data.get("submitted"),
                "published": data.get("published"),
                "reason": (
                    data.get("no_submission_reason")
                    or data.get("reason")
                    or data.get("gate_reason")
                    or data.get("reviewer_decision")
                ),
                "submission_id": data.get("submission_id") or data.get("researka_submission_id"),
            })
    return sorted(ledgers, key=lambda row: str(row["ledger"]), reverse=True)[:limit]


def build_triage(runs_root: Path) -> dict[str, Any]:
    ledgers = recent_lane_ledgers(runs_root)
    submitted_not_public = [
        row for row in ledgers if row.get("submitted") and not row.get("published")
    ][:5]
    blockers: dict[str, int] = {}
    for row in ledgers:
        reason = str(row.get("reason") or row.get("status") or "unknown")
        blockers[reason] = blockers.get(reason, 0) + 1
    top_blocker_items = sorted(blockers.items(), key=lambda item: (-item[1], item[0]))
    return {
        "runs_root": str(runs_root),
        "recent_ledgers": ledgers,
        "submitted_not_public": submitted_not_public,
        "top_blockers": [
            {"reason": reason, "count": count}
            for reason, count in top_blocker_items[:8]
        ],
    }


def fetch_publications(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_payload(path: Path | None) -> Any:
    if path is None:
        return fetch_publications(DEFAULT_PUBLICATIONS_URL)
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    return json.loads(text)


def render_status(status: DroughtStatus, *, as_json: bool) -> str:
    payload = asdict(status)
    if as_json:
        return json.dumps(payload, sort_keys=True)
    fields = [f"{key}={value}" for key, value in payload.items()]
    return " ".join(fields)


def write_report(path: Path, status: DroughtStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(status), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_PUBLICATIONS_URL)
    parser.add_argument("--input-json", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--now", help="ISO timestamp; defaults to current UTC time")
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--enforce-exit-code",
        action="store_true",
        help="Return 1 on drought; default is report-only for systemd timer hygiene.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        payload = fetch_publications(args.url) if args.input_json is None else load_payload(args.input_json)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"status=fail reason=fetch_or_parse_error error={type(exc).__name__}: {exc}")
        return 2
    now = parse_timestamp(args.now) if args.now else dt.datetime.now(dt.UTC)
    if now is None:
        print("status=fail reason=invalid_now")
        return 2
    status = evaluate_drought(
        publication_rows(payload),
        now=now,
        max_age_hours=args.max_age_hours,
        triage=build_triage(args.runs_root),
    )
    write_report(args.report_path, status)
    print(render_status(status, as_json=args.json))
    return 0 if status.passed or not args.enforce_exit_code else 1


if __name__ == "__main__":
    raise SystemExit(main())
