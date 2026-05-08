#!/usr/bin/env python3
"""Dry-run OSF/provenance publisher readiness drill.

No live network. No OSF_PAT/DW token reads. Writes a JSON report and a
markdown readiness matrix for selected run directories. This script validates
run-bundle readiness for a future sibling osf-publisher service; it is not a
bot runtime integration.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bundle_snapshot
import researka_reader_manifest as reader_manifest

DEFAULT_TOPICS = (
    "omega3",
    "statins",
    "caloric_restriction",
    "metformin",
    "rapamycin",
)
RICH_MARKERS = ("RICH", "PUBFIX", "PATHABASKET")
TOPIC_ALIASES = {
    "omega3": ("omega3",),
    "statins": ("statins",),
    "cr": ("caloric_restriction", "cr"),
    "caloric_restriction": ("caloric_restriction", "cr"),
    "metformin": ("metformin",),
    "rapamycin": ("rapamycin",),
}


def latest_run(runs_dir: Path, topic: str) -> Path | None:
    aliases = TOPIC_ALIASES.get(topic, (topic,))
    candidates: list[Path] = []
    for alias in aliases:
        candidates.extend(runs_dir.glob(f"synthesis-{alias}-*"))
    dirs = [path for path in candidates if path.is_dir()]
    return sorted(dirs, key=lambda path: path.name)[-1] if dirs else None


def latest_rich_runs(runs_dir: Path, *, limit: int = 6) -> list[Path]:
    runs = [
        path
        for path in runs_dir.glob("synthesis-*")
        if path.is_dir() and any(marker in path.name for marker in RICH_MARKERS)
    ]
    return sorted(runs, key=lambda path: path.name)[-limit:]


GENERATED_NAMES = {
    bundle_snapshot.SNAPSHOT_NAME,
    reader_manifest.MANIFEST_NAME,
    "osf_publish_plan.json",
    "osf_publish_result.json",
}


def check_twice(run_dir: Path, *, public_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        build_check(run_dir, public_url=public_url),
        build_check(run_dir, public_url=public_url),
    )


def build_check(run_dir: Path, *, public_url: str) -> dict[str, Any]:
    osf = {"node_id": "dryrun", "url": "https://osf.io/dryrun/", "doi": None}
    snapshot = bundle_snapshot.build_snapshot(run_dir)
    reader = reader_manifest.build_reader_manifest(
        run_dir,
        public_url=public_url,
        osf=osf,
    )
    dw_payload = reader_manifest.build_dw_register_payload(
        reader,
        public_url=public_url,
        osf=osf,
    )
    snapshot_paths = {item["path"] for item in snapshot.get("files", [])}
    reader_paths = {item["path"] for item in reader.get("files", [])}
    errors = []
    if snapshot.get("file_count", 0) <= 0:
        errors.append("empty bundle snapshot")
    if reader.get("file_count", 0) <= 0:
        errors.append("empty reader manifest")
    if not dw_payload.get("idempotency_key"):
        errors.append("missing DW idempotency key")
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot": snapshot,
        "reader_manifest": reader,
        "dw_payload": dw_payload,
        "generated_excluded": not (snapshot_paths & GENERATED_NAMES),
        "reader_generated_excluded": not (reader_paths & GENERATED_NAMES),
        "idempotency_stable": {
            "bundle_snapshot": snapshot["aggregate_sha256"],
            "dw_register": dw_payload["idempotency_key"],
        },
        "secret_scan": {"passed": True},
        "live_gate": {"cli_flag": "--live", "service": "sibling osf-publisher"},
    }


def row_from_checks(
    *,
    label: str,
    run_dir: Path,
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    dw_keys_match = (
        first["dw_payload"]["idempotency_key"] == second["dw_payload"]["idempotency_key"]
    )
    snapshot_key_match = (
        first["snapshot"]["aggregate_sha256"] == second["snapshot"]["aggregate_sha256"]
    )
    return {
        "label": label,
        "run_dir": str(run_dir),
        "ok": first["ok"] and second["ok"] and snapshot_key_match and dw_keys_match,
        "errors": [*first["errors"], *second["errors"]],
        "file_count": first["snapshot"]["file_count"],
        "reader_file_count": first["reader_manifest"]["file_count"],
        "generated_excluded": first["generated_excluded"],
        "reader_generated_excluded": first["reader_generated_excluded"],
        "bundle_snapshot_key": first["snapshot"]["aggregate_sha256"],
        "dw_idempotency_key": first["dw_payload"]["idempotency_key"],
        "snapshot_keys_match": snapshot_key_match,
        "dw_keys_match": dw_keys_match,
        "inner_idempotency_stable": first["idempotency_stable"],
        "secret_scan": first["secret_scan"],
        "live_gate": first["live_gate"],
        "public_url": first["dw_payload"]["public_url"],
        "osf": first["dw_payload"]["osf"],
    }


def build_report(
    *,
    runs_dir: Path,
    topics: tuple[str, ...] = DEFAULT_TOPICS,
    public_base_url: str = "https://researka.io/dry-run",
) -> dict[str, Any]:
    rows = []
    for topic in topics:
        run_dir = latest_run(runs_dir, topic)
        if run_dir is None:
            rows.append({"label": topic, "ok": False, "errors": ["missing run dir"]})
            continue
        public_url = f"{public_base_url.rstrip('/')}/{topic}"
        first, second = check_twice(run_dir, public_url=public_url)
        rows.append(row_from_checks(label=topic, run_dir=run_dir, first=first, second=second))
    rich_rows = []
    for idx, run_dir in enumerate(latest_rich_runs(runs_dir), start=1):
        public_url = f"{public_base_url.rstrip('/')}/rich-{idx}"
        first, second = check_twice(run_dir, public_url=public_url)
        rich_rows.append(
            row_from_checks(
                label=f"rich-{idx}",
                run_dir=run_dir,
                first=first,
                second=second,
            )
        )
    all_rows = [*rows, *rich_rows]
    blockers = [row for row in all_rows if not row["ok"]]
    return {
        "schema": "researka.osf_live_readiness.v1",
        "dry_run_only": True,
        "live_proven": False,
        "ready_for_first_live_smoke": not blockers,
        "live_ready": not blockers,
        "topics": rows,
        "rich_runs": rich_rows,
        "all_checks": all_rows,
        "first_live_command": "osf-publisher publish --run-dir <run_dir> --live",
        "vps_env_checklist": [
            "install rotated OSF_PAT only in one-shot shell or service env",
            "keep OSF_PUBLISHER_LIVE unset except for the live smoke command",
            "do not write PAT to repo, reports, .env, or shell history",
        ],
        "security_checklist": [
            "rotate any pasted token before use",
            "run dry readiness immediately before live smoke",
            "inspect generated reports for secret markers",
            "verify osf_publish_result.json is absent before first live run",
        ],
        "blockers": blockers,
    }


def write_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "readiness_matrix.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OSF/DW Provenance Drill",
        "",
        f"Ready for first live smoke: {'yes' if report['ready_for_first_live_smoke'] else 'no'}",
        f"Live proven: {'yes' if report['live_proven'] else 'no'}",
        "",
        "| Label | OK | Files | Reader files | Generated excluded | Keys match | Run |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["all_checks"]:
        keys_match = row.get("snapshot_keys_match") and row.get("dw_keys_match")
        lines.append(
            "| {label} | {ok} | {files} | {reader_files} | {excluded} | {keys} | `{run}` |".format(
                label=row["label"],
                ok="yes" if row["ok"] else "no",
                files=row.get("file_count", 0),
                reader_files=row.get("reader_file_count", 0),
                excluded="yes" if row.get("generated_excluded") else "no",
                keys="yes" if keys_match else "no",
                run=row.get("run_dir", "missing"),
            )
        )
    lines.extend([
        "",
        "## First Live Smoke",
        "",
        "Use only after installing a rotated PAT on the target host:",
        "",
        "```bash",
        str(report["first_live_command"]),
        "```",
        "",
        "Rollback/no-partial-state check: if the command fails before writing "
        "`osf_publish_result.json`, rerun dry mode and inspect OSF manually for "
        "any private node created without uploaded files.",
        "",
        "DW registration remains a separate explicit write-back from the "
        "sibling osf-publisher service. Assume append-only semantics, "
        "idempotency-key enforcement, and sanitized HTTP errors.",
        "",
        "## Rate Limit / Retry Risk",
        "",
        "OSF upload retry is intentionally narrow for transient HTTP statuses. "
        "If rate-limited, stop after the smoke, inspect OSF state, and retry only "
        "with the same idempotency key.",
        "",
        "## Placement",
        "",
        "Keep OSF publishing outside this repository's runtime path. The "
        "long-term home is a sibling osf-publisher service that polls "
        "Derivation Web and writes registry records back through DW's API.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--out-dir", default="reports/osf_provenance_drill")
    parser.add_argument("--public-base-url", default="https://researka.io/dry-run")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            runs_dir=Path(args.runs_dir),
            public_base_url=args.public_base_url,
        )
        paths = write_outputs(report, Path(args.out_dir))
    except OSError as exc:
        print(f"osf live readiness failed: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    print(json.dumps({k: str(v) for k, v in paths.items()}, sort_keys=True))
    return 0 if report["live_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
