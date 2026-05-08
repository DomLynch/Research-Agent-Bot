#!/usr/bin/env python3
"""Read-only line excerpt helper for journal surface root-cause reports."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def excerpt_report(audit_json: Path) -> dict:
    data = json.loads(audit_json.read_text(encoding="utf-8"))
    rows = []
    for run in data["runs"]:
        manuscript = run.get("manuscript")
        if not manuscript:
            continue
        lines = Path(manuscript).read_text(encoding="utf-8").splitlines()
        paragraphs = _paragraphs(lines)
        for issue in run["issues"]:
            rows.append({
                "run_dir": run["run_dir"],
                "issue_type": issue["issue_type"],
                "detail": issue["detail"],
                "hits": _hits(lines, paragraphs, issue),
            })
    return {"source": str(audit_json), "rows": rows}


def _hits(lines: list[str], paragraphs: list[dict], issue: dict) -> list[dict]:
    if issue["issue_type"] == "duplicate_paragraph":
        nums = [int(n) for n in re.findall(r"\d+", issue["location"])]
        return [
            {
                "line": paragraphs[n - 1]["line"],
                "text": paragraphs[n - 1]["text"][:240],
            }
            for n in nums
            if 0 < n <= len(paragraphs)
        ]
    needle = issue["detail"].lower()
    if not needle:
        return []
    return [
        {"line": idx, "text": line.strip()[:240]}
        for idx, line in enumerate(lines, 1)
        if needle in line.lower()
    ][:8]


def _paragraphs(lines: list[str]) -> list[dict]:
    out = []
    start = 0
    buf: list[str] = []
    for idx, line in enumerate([*lines, ""], 1):
        if line.strip():
            if not buf:
                start = idx
            buf.append(line.strip())
        elif buf:
            text = " ".join(buf)
            if len(re.findall(r"[a-z0-9]+", text.lower())) >= 30:
                out.append({"line": start, "text": text})
            buf = []
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    report = excerpt_report(args.audit_json)
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(data, encoding="utf-8")
    else:
        print(data, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
