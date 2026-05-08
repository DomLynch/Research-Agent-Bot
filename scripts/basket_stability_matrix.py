"""Read-only basket stability matrix over synthesis run directories."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

FIELDS = (
    "topic", "generated_at", "run_dir", "verdict", "maturity_level",
    "is_l5", "consecutive_l5", "l6_candidate", "receipts", "tensions",
    "grok_flags", "strips", "js_pass", "quarantine_counts",
    "baseline_run_dir", "receipt_delta", "tension_delta", "maturity_delta",
    "regression",
)


def collect_rows(
    paths: list[Path],
    *,
    baseline_paths: list[Path] | None = None,
    group_runs: bool = False,
) -> list[dict[str, Any]]:
    rows = [row_from_run_dir(p) for p in paths if p.is_dir()]
    rows = sorted(rows, key=_sort_key)
    if baseline_paths:
        rows = with_baseline_comparison(rows, [row_from_run_dir(p) for p in baseline_paths])
    if group_runs:
        rows = with_group_stability(rows)
    return rows


def row_from_run_dir(run_dir: Path) -> dict[str, Any]:
    manifest = _read_json(run_dir / "manifest.json")
    final = _read_json(run_dir / "full_paper.final_verdict.json")
    audit = _read_json(run_dir / "full_paper.audit.json")
    consistency = _read_json(run_dir / "full_paper.consistency.json")
    patch_log = _read_json(run_dir / "full_paper.review_patch_log.json")
    source = manifest or _read_json(run_dir / "multi_receipt_manifest.json")
    maturity = _maturity(final, source, audit)
    return {
        "topic": _topic(source, run_dir),
        "generated_at": source.get("generated_at") or source.get("finished_at") or "",
        "run_dir": run_dir.name,
        "verdict": _verdict(final, source, audit),
        "maturity_level": maturity,
        "is_l5": maturity >= 5,
        "consecutive_l5": 0,
        "l6_candidate": False,
        "receipts": _int(source.get("n_receipts", source.get("n_clusters", 0))),
        "tensions": _int(source.get("n_non_orthogonal_tensions", _tension_count(run_dir))),
        "grok_flags": _int(final.get("grok_unresolved_p1", patch_log.get("n_flagged", 0))),
        "strips": _int(final.get("auto_stripped_count", patch_log.get("n_auto_stripped", 0))),
        "js_pass": _js_pass(final, audit, consistency),
        "quarantine_counts": _quarantine_count(source, audit),
        "baseline_run_dir": "",
        "receipt_delta": "",
        "tension_delta": "",
        "maturity_delta": "",
        "regression": False,
    }


def with_group_stability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    streaks: dict[str, int] = {}
    out = []
    for row in sorted(rows, key=_sort_key):
        topic = str(row["topic"])
        streaks[topic] = streaks.get(topic, 0) + 1 if row["is_l5"] else 0
        row = {**row, "consecutive_l5": streaks[topic]}
        row["l6_candidate"] = row["consecutive_l5"] >= 2
        out.append(row)
    return out


def with_baseline_comparison(
    rows: list[dict[str, Any]], baselines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_topic = {str(row["topic"]): row for row in sorted(baselines, key=_sort_key)}
    out = []
    for row in rows:
        base = by_topic.get(str(row["topic"]))
        if not base:
            out.append(row)
            continue
        receipt_delta = int(row["receipts"]) - int(base["receipts"])
        tension_delta = int(row["tensions"]) - int(base["tensions"])
        maturity_delta = int(row["maturity_level"]) - int(base["maturity_level"])
        out.append({
            **row,
            "baseline_run_dir": base["run_dir"],
            "receipt_delta": receipt_delta,
            "tension_delta": tension_delta,
            "maturity_delta": maturity_delta,
            "regression": maturity_delta < 0 or receipt_delta < 0,
        })
    return out


def rows_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--baseline", nargs="*", type=Path, default=[])
    parser.add_argument("--group-runs", action="store_true")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    args = parser.parse_args(argv)
    rows = collect_rows(
        args.runs,
        baseline_paths=args.baseline,
        group_runs=args.group_runs,
    )
    json_text = rows_to_json(rows)
    csv_text = rows_to_csv(rows)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.csv_out:
        args.csv_out.write_text(csv_text, encoding="utf-8")
    print(json_text if args.format == "json" else csv_text, end="")
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row["topic"]), str(row["generated_at"]), str(row["run_dir"]))


def _topic(source: dict[str, Any], run_dir: Path) -> str:
    if source.get("topic"):
        return str(source["topic"])
    match = re.match(r"(?:synthesis-)?([A-Za-z0-9_]+)", run_dir.name)
    return match.group(1) if match else run_dir.name


def _maturity(final: dict[str, Any], source: dict[str, Any], audit: dict[str, Any]) -> int:
    for data in (final, source, audit):
        for key in ("maturity_level", "level"):
            if isinstance(data.get(key), int | float):
                return int(data[key])
    if str(final.get("verdict", "")).upper() == "AAA":
        return 5
    score = audit.get("score_out_of_10")
    if audit.get("p1_pass") is True and isinstance(score, int | float) and score >= 8.5:
        return 4
    return 0


def _verdict(final: dict[str, Any], source: dict[str, Any], audit: dict[str, Any]) -> str:
    for data in (final, source):
        for key in ("verdict", "final_verdict"):
            if data.get(key):
                return str(data[key])
    if audit:
        return "pass" if audit.get("p1_pass") is True else "fail"
    return "unknown"


def _tension_count(run_dir: Path) -> int:
    data = _read_json(run_dir / "tension_matrix.json")
    for key in ("n_non_orthogonal_tensions", "n_tensions"):
        if isinstance(data.get(key), int):
            return int(data[key])
    for key in ("tensions", "pairs"):
        if isinstance(data.get(key), list):
            return len(data[key])
    return 0


def _js_pass(final: dict[str, Any], audit: dict[str, Any], consistency: dict[str, Any]) -> str:
    for data in (final, consistency):
        if isinstance(data.get("js_pass"), bool):
            return str(data["js_pass"]).lower()
        if isinstance(data.get("journal_surface_pass"), bool):
            return str(data["journal_surface_pass"]).lower()
    for check in audit.get("checks", []):
        text = f"{check.get('name', '')} {check.get('detail', '')}".lower()
        if "js" in text or "javascript" in text:
            return str(check.get("passed") is True).lower()
    return "unknown"


def _quarantine_count(source: dict[str, Any], audit: dict[str, Any]) -> int:
    rejected = source.get("rejected_evidence")
    if isinstance(rejected, list):
        return len(rejected)
    for check in audit.get("checks", []):
        text = str(check.get("detail", ""))
        match = re.search(r"(\d+)\s+rejected receipts?", text)
        if match:
            return int(match.group(1))
    return 0


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


if __name__ == "__main__":
    raise SystemExit(main())
