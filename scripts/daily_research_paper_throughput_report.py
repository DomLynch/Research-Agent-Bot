"""Daily v3 throughput report: public decisions + local blocker summary."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


AGENT_ID = "agent-v3-full-paper"
RUNS = Path(__file__).resolve().parent.parent / "runs"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


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
        and row.get("agentId") == AGENT_ID
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
        "surface_repeat_topics": sorted(str(k).split("\x1f", 1)[0] for k in repeat_keys),
    }


def summarize(date: str, *, runs_root: Path = RUNS, papers_url: str = "https://researka.org/papers",
              reviews_url: str = "https://researka.org/reviews") -> dict[str, Any]:
    return {"date": date, "public": _public_counts(date, papers_url=papers_url, reviews_url=reviews_url),
            "local": _local_counts(runs_root, date)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.date, runs_root=args.runs_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
