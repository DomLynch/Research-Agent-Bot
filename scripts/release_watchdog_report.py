#!/usr/bin/env python3
"""Offline release watchdog report from captured checkpoint artifacts."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def read_text(path: Path | None) -> str:
    return path.read_text(encoding="utf-8") if path and path.exists() else ""


def read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def parse_dirty(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        status, path = line[:2].strip() or "?", line[3:].strip()
        rows.append({"status": status, "path": path, "lane": classify_lane(path)})
    return rows


def classify_lane(path: str) -> str:
    if path.startswith(
        (
            "reports/release_watchdog/",
            "docs/release_watchdog_v1.md",
            "scripts/release_watchdog_",
            "tests/test_release_watchdog_",
        )
    ):
        return "release_watchdog"
    if path.startswith("reports/journal_surface_root_cause/"):
        return "journal_surface"
    if path.startswith("reports/reader_publication/"):
        return "reader"
    if path.startswith(("reports/l6_campaign/", "reports/osf_provenance_drill/")):
        return "other"
    if path.startswith(("scripts/tri_sync_status.py", "tests/test_tri_sync_status.py")):
        return "tri_sync_status"
    if "reader" in path:
        return "reader"
    if "basket" in path:
        return "basket"
    if "journal_surface" in path:
        return "journal_surface"
    return "other"


def parse_test_summary(text: str) -> dict[str, Any]:
    lower = text.lower()
    failed = sum(int(n) for n in re.findall(r"(\d+)\s+failed\b", lower))
    errors = sum(int(n) for n in re.findall(r"(\d+)\s+errors?\b", lower))
    passed = sum(int(n) for n in re.findall(r"(\d+)\s+passed\b", lower))
    ruff = "all checks passed" in lower
    return {"ok": failed == 0 and errors == 0 and (passed > 0 or ruff), "passed": passed, "failed": failed, "errors": errors, "ruff_clean": ruff}


def sha_report(tri_sync: dict[str, Any], sha_text: str) -> dict[str, Any]:
    kv = parse_kv(sha_text)
    local_full = kv.get("local_full")
    origin_full = kv.get("origin_full")
    local_short = (tri_sync.get("local") or {}).get("head")
    origin_short = (tri_sync.get("local") or {}).get("origin_main")
    vps = tri_sync.get("vps", [])
    return {
        "local_full": local_full,
        "origin_full": origin_full,
        "local_short": local_short,
        "origin_short": origin_short,
        "full_match": bool(local_full and origin_full and local_full == origin_full),
        "short_match": bool(local_short and origin_short and local_short == origin_short),
        "short_sha_note": "8-char tri-sync SHA is display-only; full SHA controls release confidence.",
        "vps_short_match": all(item.get("head") == local_short for item in vps if isinstance(item, dict)),
    }


def build_report(
    *,
    tri_sync: dict[str, Any],
    sha_text: str,
    dirty_text: str,
    test_text: str,
) -> dict[str, Any]:
    local = tri_sync.get("local") or {}
    vps = [item for item in tri_sync.get("vps", []) if isinstance(item, dict)]
    dirty = parse_dirty(dirty_text)
    tests = parse_test_summary(test_text)
    shas = sha_report(tri_sync, sha_text)
    vps_ok = all(
        item.get("dirty_count") == 0
        and item.get("service") == "active"
        and item.get("http") == "200"
        and not item.get("error")
        for item in vps
    )
    blockers = []
    if dirty:
        blockers.append(f"{len(dirty)} uncommitted path(s)")
    if not shas["full_match"]:
        blockers.append("local/origin full SHA mismatch or missing full SHA data")
    if local.get("ahead") or local.get("behind"):
        blockers.append(f"local ahead/behind is {local.get('ahead')}/{local.get('behind')}")
    if not vps_ok:
        blockers.append("VPS status mismatch")
    if not tests["ok"]:
        blockers.append("tests not clean")
    return {
        "verdict": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "dirty": dirty,
        "dirty_by_lane": {lane: sum(1 for row in dirty if row["lane"] == lane) for lane in sorted({row["lane"] for row in dirty})},
        "sha": shas,
        "local": local,
        "vps": vps,
        "tests": tests,
        "endpoint_semantics": "200 required: deployed service must present live status.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release Watchdog Report",
        "",
        f"**Verdict:** {report['verdict']}",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in (report["blockers"] or ["none"])],
        "",
        "## SHA",
        "",
        f"- Local full: `{report['sha'].get('local_full')}`",
        f"- Origin full: `{report['sha'].get('origin_full')}`",
        f"- Full SHA match: `{report['sha'].get('full_match')}`",
        f"- Short SHA note: {report['sha'].get('short_sha_note')}",
        "",
        "## Dirty Files",
        "",
        *[f"- `{row['path']}` ({row['status']}, {row['lane']})" for row in report["dirty"]],
        "",
        "## VPS",
        "",
        *[
            f"- `{item.get('path')}` head `{item.get('head')}`, dirty `{item.get('dirty_count')}`, service `{item.get('service')}`, http `{item.get('http')}`"
            for item in report["vps"]
        ],
        "",
        "## Tests",
        "",
        f"- ok `{report['tests']['ok']}`, ruff `{report['tests']['ruff_clean']}`, passed `{report['tests']['passed']}`, failed `{report['tests']['failed']}`, errors `{report['tests']['errors']}`",
        "",
        "## Recovery Commands",
        "",
        "- Dirty local: review `git status --short`, commit intended files, leave unrelated work alone.",
        "- Origin mismatch: push the intended commit after tests pass.",
        "- VPS mismatch: deploy the intended commit to `/opt` and `/root`, then rerun tri-sync.",
        "- Service mismatch: inspect `systemctl status research-agent-bot.service` before restart.",
        "",
        "## Final No-Dirt Checklist",
        "",
        f"- Local clean: `{not report['dirty']}`",
        f"- Local/origin full SHA match: `{report['sha'].get('full_match')}`",
        f"- VPS status acceptable: `{all(item.get('dirty_count') == 0 and item.get('service') == 'active' for item in report['vps'])}`",
        f"- Tests clean: `{report['tests']['ok']}`",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tri-sync-json", type=Path)
    parser.add_argument("--sha", type=Path)
    parser.add_argument("--dirty", type=Path)
    parser.add_argument("--tests", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(
        tri_sync=read_json(args.tri_sync_json),
        sha_text=read_text(args.sha),
        dirty_text=read_text(args.dirty),
        test_text=read_text(args.tests),
    )
    output = json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(report)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
