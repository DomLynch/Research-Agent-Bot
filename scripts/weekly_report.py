#!/usr/bin/env python3
"""Weekly report: aggregate run logs from runs/ directory."""

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNS_DIR = Path("runs")


def _load_runs(runs_dir: Path, days: int = 7) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min(days, 36500))
    runs = []
    for p in sorted(runs_dir.glob("*.json")):
        if ".raw." in p.name or not p.suffix == ".json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        started = data.get("started_at")
        if not started:
            continue
        ts = _parse_ts(started)
        if ts is None or ts < cutoff:
            continue
        runs.append(data)
    return runs


def _parse_ts(s: str) -> datetime | None:
    """Parse ISO-ish timestamps (with Z or +00:00)."""
    try:
        s = s.replace("Z", "+00:00").replace("+00:00", "+00:00")
        if "+00:00" not in s:
            s += "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _report(runs: list[dict]) -> str:
    total = len(runs)
    if total == 0:
        return "No runs in the last 7 days."

    errors = [r for r in runs if r.get("error")]
    submissions = [r for r in runs if r.get("submission_id")]
    gate_blocked = [r for r in runs if r.get("submission", {}).get("gate_blocked")]
    duplicates = [r for r in runs if r.get("submission", {}).get("duplicate")]
    sub_errors = [r for r in runs if r.get("submission_error")]
    costs = [r.get("estimated_cost_usd", 0.0) for r in runs]
    topics = Counter(r.get("topic", "?") for r in runs)
    domains = Counter(r.get("domain_slug", "?") for r in runs)
    evidence_counts = [r.get("evidence_selected", 0) for r in runs]

    reached_researka = len(submissions) + len(duplicates)

    lines = [
        f"# Weekly Report ({total} runs in last 7 days)",
        "",
        f"- Errors (draft): {len(errors)}/{total}",
        f"- Submissions posted: {len(submissions)}/{total}",
        f"- Duplicates skipped: {len(duplicates)}/{total}",
        f"- Quality-gate blocked: {len(gate_blocked)}/{total}",
        f"- Submission errors: {len(sub_errors)}/{total}",
        f"- Submission success rate: {len(submissions) / reached_researka * 100:.0f}% ({len(submissions)}/{reached_researka} intended)"
        if reached_researka
        else "- Submission success rate: N/A (no submissions intended)",
        f"- Avg cost/run: ${sum(costs) / total:.4f}",
        f"- Total cost: ${sum(costs):.4f}",
        f"- Avg evidence selected: {sum(evidence_counts) / total:.1f}",
        "",
    ]

    lines.append("## Top Topics")
    for topic, count in topics.most_common(5):
        lines.append(f"  {topic}: {count}")

    lines.extend(["", "## Top Domains"])
    for domain, count in domains.most_common(5):
        lines.append(f"  {domain}: {count}")

    if errors:
        lines.extend(["", "## Draft Errors"])
        for r in errors[:10]:
            topic = r.get("topic", "?")
            err = r.get("error", "?")
            lines.append(f"  - [{topic}] {err}")

    if gate_blocked:
        lines.extend(["", "## Quality-Gate Blocks"])
        for r in gate_blocked[:10]:
            topic = r.get("topic", "?")
            reason = r.get("submission", {}).get("reason", "?")
            lines.append(f"  - [{topic}] {reason}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    runs_dir = RUNS_DIR
    days = 7
    if argv:
        if "--days" in argv:
            idx = argv.index("--days")
            days = int(argv[idx + 1])
        if "--runs-dir" in argv:
            idx = argv.index("--runs-dir")
            runs_dir = Path(argv[idx + 1])

    runs = _load_runs(runs_dir, days)
    print(_report(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
