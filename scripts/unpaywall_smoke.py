#!/usr/bin/env python3
"""Weekly smoke test for Unpaywall adapter.

Resolves 5 known OA DOIs. Records hit rate in a dated markdown report.
Exits non-zero if hit rate drops below 60% (Unpaywall outage or code regression).

Runs from .github/workflows/weekly-reports.yml. Does not require MIMO_API_KEY.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.sources.unpaywall import UnpaywallAdapter


# 5 DOIs guaranteed to be OA (PLOS, eLife, MDPI, BMC, Nature Sci Rep).
# Stable, well-indexed in Unpaywall. Change only if API breaks them.
_SMOKE_DOIS = [
    "10.1371/journal.pone.0170258",        # PLOS ONE
    "10.7554/elife.46314",                  # eLife
    "10.3390/ijms20174213",                 # MDPI IJMS
    "10.1186/s12874-018-0611-x",            # BMC Med Res Methodol
    "10.1038/s41598-017-08547-0",           # Nature Scientific Reports
]

_HIT_RATE_FLOOR = 0.60


def run_smoke(report_dir: Path) -> dict[str, Any]:
    """Resolve each DOI, record hit rate + details."""
    adapter = UnpaywallAdapter()
    results: list[dict[str, Any]] = []
    hits = 0

    for doi in _SMOKE_DOIS:
        try:
            resolution = adapter.resolve(doi)
        except Exception as exc:
            results.append({"doi": doi, "status": "error", "error": str(exc)})
            continue

        if resolution is None:
            results.append({"doi": doi, "status": "not_found"})
            continue

        if resolution.get("is_oa"):
            hits += 1
            results.append({
                "doi": doi,
                "status": "ok",
                "oa_url": resolution.get("oa_url", ""),
                "version": resolution.get("version", ""),
                "license": resolution.get("license", ""),
            })
        else:
            results.append({"doi": doi, "status": "closed"})

    hit_rate = hits / len(_SMOKE_DOIS)
    report = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(_SMOKE_DOIS),
        "hits": hits,
        "hit_rate": hit_rate,
        "floor": _HIT_RATE_FLOOR,
        "pass": hit_rate >= _HIT_RATE_FLOOR,
        "results": results,
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = report_dir / f"{stamp}-unpaywall.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    (report_dir / f"{stamp}-unpaywall.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Unpaywall Weekly Smoke \u2014 {report['date']}",
        "",
        f"- DOIs tested: {report['total']}",
        f"- OA hits: {report['hits']}",
        f"- Hit rate: {report['hit_rate']:.0%}",
        f"- Floor: {report['floor']:.0%}",
        f"- Status: {'PASS' if report['pass'] else 'FAIL'}",
        "",
        "## Per-DOI",
        "",
        "| DOI | Status | OA URL | Version |",
        "|---|---|---|---|",
    ]
    for r in report["results"]:
        url = r.get("oa_url") or "\u2014"
        ver = r.get("version") or "\u2014"
        lines.append(
            f"| `{r['doi']}` | {r['status']} | "
            f"{url[:60]} | {ver} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    report_dir = repo_root / "docs" / "weekly"
    report = run_smoke(report_dir)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Unpaywall smoke: {report['hits']}/{report['total']} = {report['hit_rate']:.0%}")
    print(f"Report: docs/weekly/{stamp}-unpaywall.md")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
