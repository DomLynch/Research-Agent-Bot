#!/usr/bin/env python3
"""Deep read-only release watchdog from captured status artifacts."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_LARGE_BYTES = 5_000_000
ACCEPTABLE_HTTP = {"200", "404", "503"}
SKIP_SCAN_PARTS = {".git", ".venv", "__pycache__", "quality-reference"}
SECRET_PATTERNS = {
    "osf_pat_assignment": re.compile(r"OSF_PAT\s*=\s*[A-Za-z0-9_-]{20,}"),
    "bare_80char_mixed_token": re.compile(r"\b(?=[A-Za-z0-9]{80,}\b)(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9]+\b"),
    "private_key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
}
OSF_PLACEMENT_PATTERNS = {
    "osf_pat": re.compile(r"\bOSF_PAT\b"),
    "osf_api": re.compile(r"api\.osf\.io|files\.osf\.io"),
    "osf_live_gate": re.compile(r"\bOSF_PUBLISHER_LIVE\b"),
}
OSF_ALLOWED_PREFIXES = (
    "docs/",
    "reports/",
    "tests/",
    "scripts/osf_live_readiness.py",
    "scripts/release_watchdog",
    "scripts/arbitration",
    "scripts/bundle_snapshot.py",
    "scripts/dw_register_public_bundle.py",
    "scripts/export_public_bundle.py",
    "scripts/researka_reader_manifest.py",
)


def read_text(path: Path | None) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path and path.exists() else ""


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


def classify_lane(path: str) -> str:
    if path.startswith("reports/release_watchdog_deep/") or path in {
        "docs/release_watchdog_v2.md",
        "scripts/release_watchdog_deep.py",
        "tests/test_release_watchdog_deep.py",
    }:
        return "release_watchdog_deep"
    if path.startswith(("reports/release_watchdog/", "docs/release_watchdog_v1.md", "scripts/release_watchdog_report.py")):
        return "release_watchdog"
    if "reader" in path:
        return "reader"
    if "journal_surface" in path:
        return "journal_surface"
    if "basket" in path:
        return "basket"
    if "osf" in path:
        return "osf"
    if "l6_campaign" in path:
        return "l6"
    return "other"


def parse_status(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("## "):
            continue
        code = line[:2]
        path = line[3:].strip()
        rows.append(
            {
                "code": code.strip() or "?",
                "path": path,
                "staged": code[0] not in {" ", "?"},
                "untracked": code == "??",
                "lane": classify_lane(path),
            }
        )
    return rows


def path_size(repo: Path, rel: str) -> int:
    path = repo / rel
    return path.stat().st_size if path.is_file() else 0


def large_file_warnings(repo: Path, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    warnings = []
    for row in rows:
        size = path_size(repo, row["path"])
        if size > limit:
            warnings.append({"path": row["path"], "bytes": size, "lane": row["lane"]})
    return warnings


def lane_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    lanes = sorted({row["lane"] for row in rows})
    return {lane: sum(1 for row in rows if row["lane"] == lane) for lane in lanes}


def secret_hits_in_text(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def should_scan(path: Path) -> bool:
    return path.is_file() and not any(part in SKIP_SCAN_PARTS for part in path.parts)


def scan_secrets(repo: Path, roots: list[str]) -> list[dict[str, str]]:
    hits = []
    for root in roots:
        base = repo / root
        paths = [base] if base.is_file() else list(base.rglob("*")) if base.exists() else []
        for path in paths:
            if not should_scan(path):
                continue
            patterns = secret_hits_in_text(read_text(path))
            if patterns:
                hits.append({"path": str(path.relative_to(repo)), "patterns": ",".join(patterns)})
    return hits


def scan_osf_placement(
    repo: Path, roots: tuple[str, ...] = ("agent", "scripts")
) -> list[dict[str, str]]:
    warnings = []
    for root in roots:
        base = repo / root
        paths = [base] if base.is_file() else list(base.rglob("*")) if base.exists() else []
        for path in paths:
            if not should_scan(path):
                continue
            rel = str(path.relative_to(repo))
            if rel.startswith(OSF_ALLOWED_PREFIXES):
                continue
            names = [
                name
                for name, pattern in OSF_PLACEMENT_PATTERNS.items()
                if pattern.search(read_text(path))
            ]
            if names:
                warnings.append({"path": rel, "patterns": ",".join(names)})
    return warnings


def sha_summary(sha_text: str, tri_sync: dict[str, Any]) -> dict[str, Any]:
    kv = parse_kv(sha_text)
    local_full = kv.get("local_full")
    origin_full = kv.get("origin_full")
    local_short = (tri_sync.get("local") or {}).get("head")
    vps = [item for item in tri_sync.get("vps", []) if isinstance(item, dict)]
    return {
        "local_full": local_full,
        "origin_full": origin_full,
        "full_match": bool(local_full and origin_full and local_full == origin_full),
        "display_short": local_short,
        "vps_match": all(
            bool(local_full and item.get("head") and local_full.startswith(str(item["head"])))
            for item in vps
        ),
        "note": "tri-sync uses short display SHA; full SHA is used for local/origin confidence.",
    }


def vps_warnings(tri_sync: dict[str, Any]) -> list[str]:
    warnings = []
    for item in tri_sync.get("vps", []):
        if not isinstance(item, dict):
            continue
        label = item.get("path", "vps")
        if item.get("error"):
            warnings.append(f"{label}: {item['error']}")
        if item.get("dirty_count") not in (0, None):
            warnings.append(f"{label}: dirty_count={item.get('dirty_count')}")
        if item.get("service") not in (None, "active"):
            warnings.append(f"{label}: service={item.get('service')}")
        if item.get("http") not in ACCEPTABLE_HTTP:
            warnings.append(f"{label}: http={item.get('http')}")
    return warnings


def build_report(
    *,
    repo: Path,
    status_text: str,
    sha_text: str,
    tri_sync: dict[str, Any],
    secret_roots: list[str],
    large_limit: int = DEFAULT_LARGE_BYTES,
) -> dict[str, Any]:
    rows = parse_status(status_text)
    shas = sha_summary(sha_text, tri_sync)
    large = large_file_warnings(repo, rows, large_limit)
    secrets = scan_secrets(repo, secret_roots)
    osf_placement = scan_osf_placement(repo)
    vps = vps_warnings(tri_sync)
    blockers = []
    if rows:
        blockers.append(f"{len(rows)} dirty path(s)")
    if not shas["full_match"]:
        blockers.append("local/origin full SHA mismatch")
    if not shas["vps_match"]:
        blockers.append("VPS short SHA does not match local full SHA prefix")
    if vps:
        blockers.append("VPS warning(s)")
    if secrets:
        blockers.append("secret scan hit(s)")
    if large:
        blockers.append("large staged/untracked file warning(s)")
    if osf_placement:
        blockers.append("OSF code placement warning(s)")
    return {
        "verdict": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "dirty_count": len(rows),
        "staged_count": sum(1 for row in rows if row["staged"]),
        "untracked_count": sum(1 for row in rows if row["untracked"]),
        "lane_counts": lane_counts(rows),
        "large_files": large,
        "secret_hits": secrets,
        "osf_placement_warnings": osf_placement,
        "sha": shas,
        "vps_warnings": vps,
        "endpoint_semantics": "503 is acceptable for the paused dashboard stub.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release Watchdog Deep Report",
        "",
        f"**Verdict:** {report['verdict']}",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in (report["blockers"] or ["none"])],
        "",
        "## Dirty State",
        "",
        f"- Dirty paths: `{report['dirty_count']}`",
        f"- Staged paths: `{report['staged_count']}`",
        f"- Untracked paths: `{report['untracked_count']}`",
        f"- Lane counts: `{json.dumps(report['lane_counts'], sort_keys=True)}`",
        "",
        "## Integrity",
        "",
        f"- Full SHA match: `{report['sha']['full_match']}`",
        f"- VPS SHA prefix match: `{report['sha']['vps_match']}`",
        f"- Secret hits: `{len(report['secret_hits'])}`",
        f"- Large file warnings: `{len(report['large_files'])}`",
        f"- OSF placement warnings: `{len(report['osf_placement_warnings'])}`",
        "",
        "## Recovery Commands",
        "",
        "- Dirty state: `git status --short --untracked-files=all`",
        "- Full SHA: `git rev-parse HEAD && git rev-parse origin/main`",
        "- VPS read-only: `python scripts/tri_sync_status.py --repo . --vps-host root@49.12.7.18 --ssh-key ~/.ssh/binance_futures_tool --json`",
        "- Final tests: `python -m pytest`",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--sha", type=Path, required=True)
    parser.add_argument("--tri-sync-json", type=Path, required=True)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--large-limit", type=int, default=DEFAULT_LARGE_BYTES)
    parser.add_argument("--secret-root", action="append", default=["docs", "scripts", "tests", "reports"])
    args = parser.parse_args(argv)
    report = build_report(
        repo=args.repo.resolve(),
        status_text=read_text(args.status),
        sha_text=read_text(args.sha),
        tri_sync=read_json(args.tri_sync_json),
        secret_roots=args.secret_root,
        large_limit=args.large_limit,
    )
    if args.out_json:
        args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.write_text(render_markdown(report), encoding="utf-8")
    if not args.out_json and not args.out_md:
        print(render_markdown(report), end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
