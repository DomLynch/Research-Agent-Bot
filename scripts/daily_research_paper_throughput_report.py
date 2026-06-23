"""Daily v3 throughput report: public decisions + local blocker summary."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, TextIO

from publishing_capacity_plan import live_plan


AGENT_ID = "agent-v3-full-paper"
AGENT_IDS = frozenset((AGENT_ID, f"{AGENT_ID}-live"))
RUNS = Path(__file__).resolve().parent.parent / "runs"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _rows_from_next_html(html: str) -> list[dict[str, Any]]:
    match = NEXT_RE.search(html)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("createdAt") and (value.get("title") or value.get("decision")):
                rows.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return rows


def _fetch_rows(url: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return _rows_from_next_html(response.read().decode("utf-8", errors="replace"))


def _public_counts(date: str, *, papers_url: str, reviews_url: str) -> dict[str, Any]:
    rows = [
        row for row in _fetch_rows(papers_url) + _fetch_rows(reviews_url)
        if str(row.get("createdAt") or "").startswith(date)
        and row.get("agentId") in AGENT_IDS
        and row.get("artifactType") == "research_paper"
    ]
    decisions: dict[str, int] = {}
    examples: list[dict[str, str]] = []
    for row in rows:
        decision = str(row.get("decision") or "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
        examples.append({
            "time": str(row.get("createdAt") or ""),
            "decision": decision,
            "title": str(row.get("title") or ""),
            "reason": str(row.get("reviewSummary") or "")[:240],
        })
    return {"decisions": decisions, "examples": examples[:12]}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cycle_view(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data.get(k) for k in ("started_at", "mode", "status", "submitted", "published", "attempted_topic")}


def _local_counts(runs_root: Path, date: str) -> dict[str, Any]:
    ledger_dir = runs_root / "_daily_research_paper_cycle_ledger"
    cycles = {
        mode: _read_json(ledger_dir / f"{date}{suffix}.json")
        for mode, suffix in (("mixed", ""), ("fresh", "-fresh"), ("revise", "-revise"))
    }
    cycle = max(
        (row for row in cycles.values() if row),
        key=lambda row: str(row.get("started_at") or ""),
        default={},
    )
    submit = _read_json(runs_root / "_daily_research_paper_ledger" / f"{date}.json")
    hist = _read_json(ledger_dir / "_blocker_histogram.json")
    throughput = _read_json(ledger_dir / "_daily_throughput_summary.json").get("days", {}).get(date, {})
    decisions = _read_json(ledger_dir / "_decisions_by_day.json").get("days", {}).get(date, {})
    raw_blockers = hist.get("blockers")
    blockers = raw_blockers if isinstance(raw_blockers, dict) else {}
    top = sorted(
        (
            {"code": code, "count": int(row.get("count") or 0), "class": str(row.get("class") or "")}
            for code, row in blockers.items() if isinstance(row, dict)
        ),
        key=lambda row: (-row["count"], row["code"]),
    )
    repeats = hist.get("repeats")
    repeat_keys = repeats if isinstance(repeats, dict) else {}
    return {
        "cycle": _cycle_view(cycle),
        "cycle_modes": {mode: _cycle_view(data) for mode, data in cycles.items() if data},
        "throughput": throughput if isinstance(throughput, dict) else {},
        "decisions": decisions if isinstance(decisions, dict) else {},
        "submit": {k: submit.get(k) for k in ("status", "submitted", "published", "topic", "run")},
        "top_blockers": top[:8],
        "surface_repeat_topics": sorted({str(k).split("\x1f", 1)[0] for k in repeat_keys}),
    }


def _capacity_snapshot() -> dict[str, Any]:
    try:
        return {
            "one_year": live_plan(target=5000, years=1.0, interval_minutes=120),
            "two_year": live_plan(target=5000, years=2.0, interval_minutes=120),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _required_daily(plan: dict[str, Any]) -> float:
    target = _int_value(plan.get("target"))
    days = _int_value(plan.get("days"))
    return round(target / days, 2) if days else 0.0


def _rolling_pace_snapshot(runs_root: Path, capacity: dict[str, Any], *, window_days: int = 7) -> dict[str, Any]:
    ledger_dir = runs_root / "_daily_research_paper_cycle_ledger"
    days = _read_json(ledger_dir / "_daily_throughput_summary.json").get("days")
    if not isinstance(days, dict) or not days:
        return {
            "window_days": window_days,
            "observed_days": 0,
            "source": "_daily_throughput_summary.json",
            "status": "missing_throughput_summary",
        }
    selected_dates = sorted(str(date) for date in days if DAY_KEY_RE.fullmatch(str(date)))[-window_days:]
    if not selected_dates:
        return {
            "window_days": window_days,
            "observed_days": 0,
            "source": "_daily_throughput_summary.json",
            "status": "missing_throughput_summary",
        }
    selected = [days[date] for date in selected_dates if isinstance(days.get(date), dict)]
    submitted = sum(_int_value(day.get("submitted")) for day in selected)
    published = sum(_int_value(day.get("published")) for day in selected)
    cycles = sum(_int_value(day.get("cycles")) for day in selected)
    one_year = capacity.get("one_year")
    two_year = capacity.get("two_year")
    one_year_daily = _required_daily(one_year if isinstance(one_year, dict) else {})
    two_year_daily = _required_daily(two_year if isinstance(two_year, dict) else {})
    observed_days = len(selected)
    two_year_required = round(two_year_daily * observed_days, 2)
    one_year_required = round(one_year_daily * observed_days, 2)
    return {
        "window_days": window_days,
        "observed_days": observed_days,
        "dates": selected_dates,
        "local_submitted": submitted,
        "local_published": published,
        "cycles": cycles,
        "required_for_observed_window": {
            "one_year": one_year_required,
            "two_year": two_year_required,
        },
        "gap_to_required_for_observed_window": {
            "one_year_by_local_submissions": max(0.0, round(one_year_required - submitted, 2)),
            "two_year_by_local_submissions": max(0.0, round(two_year_required - submitted, 2)),
            "one_year_by_local_published": max(0.0, round(one_year_required - published, 2)),
            "two_year_by_local_published": max(0.0, round(two_year_required - published, 2)),
        },
    }


def _pace_snapshot(local: dict[str, Any], public: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
    throughput = local.get("throughput")
    throughput = throughput if isinstance(throughput, dict) else {}
    decisions = public.get("decisions")
    decisions = decisions if isinstance(decisions, dict) else {}
    two_year = capacity.get("two_year")
    two_year = two_year if isinstance(two_year, dict) else {}
    one_year = capacity.get("one_year")
    one_year = one_year if isinstance(one_year, dict) else {}
    two_year_daily = _required_daily(two_year)
    submitted = _int_value(throughput.get("submitted"))
    local_published = _int_value(throughput.get("published"))
    public_accepts = _int_value(decisions.get("accept"))
    return {
        "required_daily_average": {
            "one_year": _required_daily(one_year),
            "two_year": two_year_daily,
        },
        "today_observed": {
            "local_submitted": submitted,
            "local_published": local_published,
            "public_accepts": public_accepts,
        },
        "today_gap_to_two_year_daily_average": {
            "by_local_submissions": max(0.0, round(two_year_daily - submitted, 2)),
            "by_local_published": max(0.0, round(two_year_daily - local_published, 2)),
            "by_public_accepts": max(0.0, round(two_year_daily - public_accepts, 2)),
        },
    }


def summarize(date: str, *, runs_root: Path = RUNS, papers_url: str = "https://researka.org/papers",
              reviews_url: str = "https://researka.org/reviews") -> dict[str, Any]:
    capacity = _capacity_snapshot()
    public = _public_counts(date, papers_url=papers_url, reviews_url=reviews_url)
    local = _local_counts(runs_root, date)
    return {
        "date": date,
        "capacity": capacity,
        "pace": {
            **_pace_snapshot(local, public, capacity),
            "rolling": _rolling_pace_snapshot(runs_root, capacity),
        },
        "public": public,
        "local": local,
    }


def _emit_json(payload: dict[str, Any], *, stream: TextIO | None = None) -> int:
    out = stream or sys.stdout
    try:
        out.write(json.dumps(payload, indent=2, sort_keys=True))
        out.write("\n")
        out.flush()
    except BrokenPipeError:
        if stream is None:
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except OSError:
                pass
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    args = parser.parse_args(argv)
    return _emit_json(summarize(args.date, runs_root=args.runs_root))


if __name__ == "__main__":
    raise SystemExit(main())
