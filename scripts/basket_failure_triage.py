"""Classify the weakest visible failure for synthesis run directories."""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any

from basket_stability_matrix import row_from_run_dir

FIELDS = ("run_dir", "topic", "failure_class", "reason")


def triage_run_dir(run_dir: Path) -> dict[str, str]:
    row = row_from_run_dir(run_dir)
    final = _read_json(run_dir / "full_paper.final_verdict.json")
    audit = _read_json(run_dir / "full_paper.audit.json")
    manifest = _read_json(run_dir / "manifest.json")
    reason = "no blocking failure detected"
    klass = "pass"
    if str(row["js_pass"]) == "false":
        klass, reason = "js", "javascript/consistency check failed"
    elif int(row["grok_flags"]) > 0:
        klass, reason = "grok", f"{row['grok_flags']} unresolved Grok flag(s)"
    elif _is_corpus_thin(final, manifest, row):
        klass, reason = "corpus-thin", "corpus gaps or thin receipt/tension surface"
    elif int(row["strips"]) > 0:
        klass, reason = "backfill", f"{row['strips']} automatic strip/backfill event(s)"
    elif str(row["verdict"]).upper() not in {"AAA", "PASS", "TRUST-SPINE PASS"}:
        klass, reason = "verdict", str(final.get("reason") or row["verdict"])
    elif audit.get("p1_pass") is False:
        klass, reason = "verdict", "audit p1 failed"
    return {
        "run_dir": run_dir.name,
        "topic": str(row["topic"]),
        "failure_class": klass,
        "reason": reason,
    }


def collect_triage(paths: list[Path]) -> list[dict[str, str]]:
    return [triage_run_dir(p) for p in paths if p.is_dir()]


def rows_to_json(rows: list[dict[str, str]]) -> str:
    return json.dumps(rows, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def rows_to_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    args = parser.parse_args(argv)
    rows = collect_triage(args.runs)
    json_text = rows_to_json(rows)
    csv_text = rows_to_csv(rows)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.csv_out:
        args.csv_out.write_text(csv_text, encoding="utf-8")
    print(json_text if args.format == "json" else csv_text, end="")
    return 0


def _is_corpus_thin(
    final: dict[str, Any], manifest: dict[str, Any], row: dict[str, Any],
) -> bool:
    gaps = final.get("corpus_gaps")
    if isinstance(gaps, list) and gaps:
        return True
    return int(row["receipts"]) < 10 or int(manifest.get("n_high_confidence_claims_total", 0)) < 20


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
