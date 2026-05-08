"""Read-only endgame basket audit over synthesis run directories."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from basket_failure_triage import triage_run_dir
from basket_stability_matrix import collect_rows

FIELDS = (
    "topic",
    "run_dir",
    "verdict",
    "maturity_level",
    "receipts",
    "tensions",
    "grok_flags",
    "strips",
    "journal_surface",
    "l6_candidate",
    "regression",
    "failure_class",
)

FAILURE_WEIGHT = {
    "js": 60,
    "grok": 50,
    "corpus-thin": 40,
    "backfill": 30,
    "verdict": 20,
    "pass": 0,
}


def audit(paths: list[Path], *, baseline_paths: list[Path] | None = None) -> dict[str, Any]:
    rows = collect_rows(paths, baseline_paths=baseline_paths, group_runs=True)
    triage = {item["run_dir"]: item for item in (triage_run_dir(p) for p in paths if p.is_dir())}
    runs = [_audit_row(row, triage.get(str(row["run_dir"]), {})) for row in rows]
    weakest = max(runs, key=_weakness_score) if runs else {}
    classifier = _classifier_signal(runs)
    return {
        "runs": runs,
        "weakest": weakest,
        "l5_not_l6": [row for row in runs if row["maturity_level"] >= 5 and not row["l6_candidate"]],
        "cert_regressed": [
            row for row in runs
            if row["regression"] and int(row["receipts"]) >= 10
        ],
        "thin_false_positive_suspects": [
            row for row in runs
            if row["failure_class"] == "corpus-thin" and int(row["receipts"]) >= 10
        ],
        "universal_classifier_fix_indicated": classifier["indicated"],
        "universal_classifier_fix_reason": classifier["reason"],
    }


def rows_to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def rows_to_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Endgame Basket Audit",
        "",
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    for row in data["runs"]:
        lines.append("| " + " | ".join(_md(row[field]) for field in FIELDS) + " |")
    weakest = data["weakest"]
    lines.extend([
        "",
        "## Weakest Remaining Run",
        "",
        _weakest_line(weakest),
        "",
        "## Readiness Flags",
        "",
        f"- L5 not L6: {len(data['l5_not_l6'])}",
        f"- corpus-rich cert regressions: {len(data['cert_regressed'])}",
        f"- thin-corpus false-positive suspects: {len(data['thin_false_positive_suspects'])}",
        "",
        "## Universal Classifier Signal",
        "",
        f"- indicated: `{str(data['universal_classifier_fix_indicated']).lower()}`",
        f"- reason: {data['universal_classifier_fix_reason']}",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--baseline", nargs="*", type=Path, default=[])
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    data = audit(args.runs, baseline_paths=args.baseline)
    json_text = rows_to_json(data)
    markdown_text = rows_to_markdown(data)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown_text, encoding="utf-8")
    print(json_text if args.format == "json" else markdown_text, end="")
    return 0


def _audit_row(row: dict[str, Any], triage: dict[str, str]) -> dict[str, Any]:
    return {
        "topic": row["topic"],
        "run_dir": row["run_dir"],
        "verdict": row["verdict"],
        "maturity_level": row["maturity_level"],
        "receipts": row["receipts"],
        "tensions": row["tensions"],
        "grok_flags": row["grok_flags"],
        "strips": row["strips"],
        "journal_surface": row["js_pass"],
        "l6_candidate": row["l6_candidate"],
        "baseline_run_dir": row["baseline_run_dir"],
        "receipt_delta": row["receipt_delta"],
        "tension_delta": row["tension_delta"],
        "maturity_delta": row["maturity_delta"],
        "regression": row["regression"],
        "failure_class": triage.get("failure_class", "unknown"),
        "failure_reason": triage.get("reason", "not triaged"),
    }


def _weakness_score(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        FAILURE_WEIGHT.get(str(row["failure_class"]), 10),
        5 - int(row["maturity_level"]),
        1 if row["journal_surface"] in {"false", "unknown"} else 0,
        int(row["grok_flags"]) + int(row["strips"]),
        max(0, 20 - int(row["receipts"])),
    )


def _classifier_signal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [
        str(row["failure_class"]) for row in rows
        if row["failure_class"] not in {"pass", "verdict", "unknown"}
    ]
    counts = Counter(failures)
    repeated = [name for name, count in counts.items() if count > 1]
    if repeated:
        name = max(repeated, key=lambda item: FAILURE_WEIGHT.get(item, 0))
        return {"indicated": True, "reason": f"repeated {name} failures across {counts[name]} runs"}
    if any(row["journal_surface"] == "false" for row in rows):
        return {"indicated": True, "reason": "journal surface failure present"}
    return {"indicated": False, "reason": "no repeated universal classifier failure signal"}


def _weakest_line(row: dict[str, Any]) -> str:
    if not row:
        return "- none"
    return (
        f"- `{row['topic']}` / `{row['run_dir']}`: {row['failure_class']} "
        f"({row['failure_reason']})"
    )


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
