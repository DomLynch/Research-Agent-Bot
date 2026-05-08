#!/usr/bin/env python3
"""Offline final checkpoint report from tri-sync JSON and test output snippets."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def parse_test_summary(text: str) -> dict[str, Any]:
    lowered = text.lower()
    numbers = {
        name: sum(int(n) for n in re.findall(rf"(\d+)\s+{name}\b", lowered))
        for name in ("passed", "failed", "skipped")
    }
    error_count = sum(int(n) for n in re.findall(r"(\d+)\s+errors?\b", lowered))
    ruff_clean = "all checks passed" in lowered
    ok = numbers["failed"] == 0 and error_count == 0 and (ruff_clean or numbers["passed"] > 0)
    return {
        "ok": ok,
        "ruff_clean": ruff_clean,
        "passed": numbers["passed"],
        "failed": numbers["failed"],
        "errors": error_count,
        "skipped": numbers["skipped"],
    }


def dirty_category(count: Any) -> str:
    count = as_int(count)
    if count is None:
        return "unknown"
    if count == 0:
        return "clean"
    if count <= 5:
        return "light_dirty"
    return "dirty"


def github_state(local: dict[str, Any]) -> str:
    ahead = as_int(local.get("ahead"))
    behind = as_int(local.get("behind"))
    if ahead is not None and behind is not None:
        if ahead and behind:
            return "diverged"
        if ahead:
            return "ahead"
        if behind:
            return "behind"
        if local.get("head") and local.get("origin_main") and local["head"] != local["origin_main"]:
            return "sha_mismatch"
        return "synced"
    state = local.get("state")
    if state in {"ahead", "behind", "diverged", "synced", "sha_mismatch"}:
        return str(state)
    if local.get("head") and local.get("origin_main") and local["head"] != local["origin_main"]:
        return "sha_mismatch"
    return "unknown"


def classify_vps(vps: dict[str, Any], expected_head: str | None) -> str:
    if vps.get("error"):
        return "unreachable"
    if dirty_category(vps.get("dirty_count")) not in {"clean", "unknown"}:
        return "dirty"
    if expected_head and vps.get("head") and vps["head"] != expected_head:
        return "sha_mismatch"
    if vps.get("service") not in (None, "active"):
        return "service_not_active"
    if vps.get("http") not in (None, "200", "404", "503"):
        return "http_unexpected"
    return "synced"


def build_report(status: dict[str, Any], test_text: str = "") -> dict[str, Any]:
    local = status.get("local", {})
    tests = parse_test_summary(test_text)
    github = github_state(local)
    expected_head = local.get("head") or local.get("origin_main")
    vps = [
        {**item, "state": classify_vps(item, expected_head)}
        for item in status.get("vps", [])
        if isinstance(item, dict)
    ]
    local_clean = dirty_category(local.get("dirty_count")) == "clean"
    vps_clean = all(item["state"] == "synced" for item in vps)
    ready = local_clean and github == "synced" and vps_clean and (not test_text or tests["ok"])
    return {
        "ready": ready,
        "local": {**local, "dirty_category": dirty_category(local.get("dirty_count"))},
        "github_state": github,
        "vps": vps,
        "tests": tests,
    }


def render_markdown(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["ready"] else "BLOCKED"
    local = report["local"]
    lines = [
        "# Final Checkpoint Report",
        "",
        f"**Verdict:** {verdict}",
        "",
        "## Sync",
        "",
        "| Surface | State | Detail |",
        "|---|---|---|",
        (
            f"| Local | {local.get('dirty_category')} | "
            f"HEAD `{local.get('head')}`, dirty `{local.get('dirty_count')}` |"
        ),
        (
            f"| GitHub | {report.get('github_state')} | "
            f"origin/main `{local.get('origin_main')}`, ahead/behind "
            f"`{local.get('ahead')}/{local.get('behind')}` |"
        ),
    ]
    for item in report["vps"]:
        lines.append(
            f"| VPS {item.get('path')} | {item.get('state')} | "
            f"HEAD `{item.get('head')}`, dirty `{item.get('dirty_count')}`, "
            f"service `{item.get('service')}`, http `{item.get('http')}` |"
        )
    tests = report["tests"]
    lines.extend(
        [
            "",
            "## Tests",
            "",
            (
                f"- ok: `{tests['ok']}`; ruff_clean: `{tests['ruff_clean']}`; "
                f"passed: `{tests['passed']}`; failed: `{tests['failed']}`; "
                f"errors: `{tests['errors']}`; skipped: `{tests['skipped']}`"
            ),
            "",
            "## No-Dirt Checklist",
            "",
            f"- Local clean: `{local.get('dirty_category') == 'clean'}`",
            f"- GitHub synced: `{report.get('github_state') == 'synced'}`",
            f"- VPS synced: `{all(item.get('state') == 'synced' for item in report['vps'])}`",
            f"- Tests clean: `{tests['ok']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tri-sync-json", type=Path)
    parser.add_argument("--test-output", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = read_json(args.tri_sync_json)
    test_text = args.test_output.read_text(encoding="utf-8") if args.test_output else ""
    report = build_report(status, test_text)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json else render_markdown(report)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
