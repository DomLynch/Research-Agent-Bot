"""Pure-JSON L6 reproducibility batch reporter."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


def build_batch_report(
    groups: Mapping[str, Sequence[Path]],
    *,
    contribution_summaries: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    contribution_summaries = contribution_summaries or {}
    topics = []
    for topic, run_dirs in sorted(groups.items()):
        rows = _rows_for_topic(topic, run_dirs)
        candidates = [r for r in rows if r["l6_candidate"]]
        latest_candidate = bool(rows and rows[-1]["l6_candidate"])
        topics.append(
            {
                "topic": topic,
                "n_runs": len(rows),
                "latest_consecutive_l5": rows[-1]["consecutive_l5"] if rows else 0,
                "l6_candidate": latest_candidate,
                "under_claimed_l6": latest_candidate
                and int(rows[-1]["maturity_level"]) < 6,
                "candidate_runs": candidates[-1]["streak_run_dirs"]
                if candidates
                else [],
                "research_contribution_summary": dict(
                    contribution_summaries.get(topic, {}),
                ),
                "runs": rows,
            }
        )
    return {
        "schema": "l6_batch_report.v1",
        "certification_mode": "pure_final_verdict_json",
        "topics": topics,
    }


def group_run_dirs(run_dirs: Sequence[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        topic = _topic_for_run(run_dir)
        groups.setdefault(topic, []).append(run_dir)
    return groups


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# L6 Batch Report",
        "",
        f"Certification mode: `{report.get('certification_mode', 'unknown')}`",
        "",
        "| Topic | Runs | Latest L5 streak | L6 candidate | Under-claimed L6 | Candidate runs |",
        "|---|---:|---:|---|---|---|",
    ]
    for topic in report.get("topics", []):
        candidates = ", ".join(topic.get("candidate_runs") or ())
        lines.append(
            f"| {topic['topic']} | {topic['n_runs']} | "
            f"{topic['latest_consecutive_l5']} | "
            f"{str(topic['l6_candidate']).lower()} | "
            f"{str(topic.get('under_claimed_l6', False)).lower()} | "
            f"{candidates} |"
        )
        if topic.get("research_contribution_summary"):
            summary = ", ".join(
                f"{k}={v}"
                for k, v in sorted(
                    topic["research_contribution_summary"].items(),
                )
            )
            lines.append(f"<!-- research_contribution: {topic['topic']}: {summary} -->")
    lines += ["", "## Run Rows", ""]
    for topic in report.get("topics", []):
        lines += [
            f"### {topic['topic']}",
            "",
            "| Run | Verdict | Maturity | L5 | Streak | L6 candidate |",
            "|---|---|---:|---|---:|---|",
        ]
        for row in topic.get("runs", []):
            lines.append(
                f"| {row['run_dir']} | {row['verdict']} | "
                f"{row['maturity_level']} | {str(row['is_l5']).lower()} | "
                f"{row['consecutive_l5']} | {str(row['l6_candidate']).lower()} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args(argv)
    report = build_batch_report(group_run_dirs(args.run_dirs))
    json_text = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    md_text = render_markdown(report)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.md_out:
        args.md_out.write_text(md_text, encoding="utf-8")
    print(json_text if args.format == "json" else md_text, end="")
    return 0


def _rows_for_topic(topic: str, run_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    streak = 0
    streak_runs: list[str] = []
    rows = []
    for run_dir in sorted(run_dirs, key=_run_sort_key):
        final = _read_json(run_dir / "full_paper.final_verdict.json")
        maturity = _maturity_level(final)
        is_l5 = maturity >= 5
        if is_l5:
            streak += 1
            streak_runs.append(run_dir.name)
        else:
            streak = 0
            streak_runs = []
        rows.append(
            {
                "topic": topic,
                "run_dir": run_dir.name,
                "generated_at": _generated_at(run_dir),
                "verdict": str(
                    final.get("verdict") or final.get("final_verdict") or "unknown"
                ),
                "maturity_level": maturity,
                "journal_surface_pass": bool(final.get("journal_surface_pass", False)),
                "is_l5": is_l5,
                "consecutive_l5": streak,
                "l6_candidate": streak >= 2,
                "streak_run_dirs": tuple(streak_runs[-2:]) if streak >= 2 else (),
            }
        )
    return rows


def _topic_for_run(run_dir: Path) -> str:
    for name in ("manifest.json", "full_paper.final_verdict.json"):
        data = _read_json(run_dir / name)
        if data.get("topic"):
            return str(data["topic"])
    match = re.match(r"(?:synthesis-)?([A-Za-z0-9_]+)", run_dir.name)
    return match.group(1) if match else run_dir.name


def _generated_at(run_dir: Path) -> str:
    manifest = _read_json(run_dir / "manifest.json")
    final = _read_json(run_dir / "full_paper.final_verdict.json")
    return str(
        manifest.get("generated_at")
        or manifest.get("finished_at")
        or final.get("generated_at")
        or run_dir.name
    )


def _maturity_level(final: Mapping[str, Any]) -> int:
    value = final.get("maturity_level", final.get("level", 0))
    return int(value) if isinstance(value, int | float) else 0


def _run_sort_key(run_dir: Path) -> tuple[str, str]:
    return (_generated_at(run_dir), run_dir.name)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = ["build_batch_report", "group_run_dirs", "main", "render_markdown"]


if __name__ == "__main__":
    raise SystemExit(main())
