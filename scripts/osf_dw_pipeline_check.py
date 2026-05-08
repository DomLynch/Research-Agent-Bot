#!/usr/bin/env python3
"""Dry-run OSF -> reader -> DW verifier.

Builds and validates local payload shapes only. It never reads OSF_PAT,
DW_API_TOKEN, or performs network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import osf_publish
import researka_reader_manifest as reader

GENERATED_NAMES = {
    "bundle_snapshot.json",
    "osf_publish_plan.json",
    "osf_publish_result.json",
    "researka_reader_manifest.json",
}
SECRET_MARKERS = ("OSF_PAT", "DW_API_TOKEN", "Bearer ")


def build_check(
    run_dir: Path,
    *,
    public_url: str,
    osf_node_id: str | None = None,
    osf_url: str | None = None,
    osf_doi: str | None = None,
) -> dict[str, Any]:
    root = run_dir.resolve()
    snapshot = osf_publish.build_publish_snapshot(root)
    plan = osf_publish.build_plan(root, snapshot)
    repeat_plan = osf_publish.build_plan(root, snapshot)
    osf = {"node_id": osf_node_id, "url": osf_url, "doi": osf_doi}
    manifest = reader.build_reader_manifest(root, public_url=public_url, osf=osf)
    repeat_manifest = reader.build_reader_manifest(root, public_url=public_url, osf=osf)
    payload = reader.build_dw_register_payload(
        manifest,
        public_url=public_url,
        osf=osf,
    )
    repeat_payload = reader.build_dw_register_payload(
        repeat_manifest,
        public_url=public_url,
        osf=osf,
    )
    errors = _validate(plan, manifest, payload)
    stability = {
        "osf_idempotency_key": plan.get("idempotency_key")
        == repeat_plan.get("idempotency_key"),
        "dw_idempotency_key": payload.get("idempotency_key")
        == repeat_payload.get("idempotency_key"),
    }
    if not all(stability.values()):
        errors.append("idempotency keys unstable")
    reader_paths = [item["path"] for item in manifest.get("files", [])]
    return {
        "schema": "researka.osf_dw_pipeline_check.v1",
        "run_id": root.name,
        "ok": not errors,
        "errors": errors,
        "dry_run_only": True,
        "live_mode": "not supported by verifier",
        "upstream_live_gate": {
            "cli_flag": "--live",
            "env_var": getattr(osf_publish, "LIVE_ENV", "OSF_PUBLISH_LIVE"),
        },
        "idempotency_stable": stability,
        "secret_scan": {
            "passed": not contains_secret_marker(json.dumps(plan) + json.dumps(payload)),
            "markers": list(SECRET_MARKERS),
        },
        "osf_plan": {
            "schema": plan.get("schema"),
            "idempotency_key": plan.get("idempotency_key"),
            "file_count": plan.get("file_count"),
            "planned_paths": [item["path"] for item in plan.get("planned_files", [])],
        },
        "reader_manifest": {
            "schema": manifest.get("schema"),
            "public_url": manifest.get("public_url"),
            "file_count": manifest.get("file_count"),
            "paths": reader_paths,
        },
        "dw_payload": {
            "schema": payload.get("schema"),
            "idempotency_key": payload.get("idempotency_key"),
            "public_url": payload.get("public_url"),
            "osf": payload.get("osf"),
        },
    }


def _validate(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not plan.get("idempotency_key"):
        errors.append("osf plan missing idempotency_key")
    if not payload.get("idempotency_key"):
        errors.append("dw payload missing idempotency_key")
    planned = [str(item.get("path", "")) for item in plan.get("planned_files", [])]
    generated = sorted({Path(path).name for path in planned} & GENERATED_NAMES)
    if generated:
        errors.append(f"generated artifacts planned for upload: {generated}")
    if not manifest.get("public_url") or not payload.get("public_url"):
        errors.append("public_url missing")
    manifest_paths = [
        str(item.get("path", "")) for item in manifest.get("files", [])
    ]
    manifest_generated = sorted(
        {Path(path).name for path in manifest_paths} & GENERATED_NAMES
    )
    if manifest_generated:
        errors.append(f"generated artifacts in reader manifest: {manifest_generated}")
    osf = payload.get("osf")
    if not isinstance(osf, dict) or set(osf) != {"node_id", "url", "doi"}:
        errors.append("dw payload missing osf slots")
    return errors


def contains_secret_marker(text: str) -> bool:
    return any(marker in text for marker in SECRET_MARKERS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--osf-node-id")
    parser.add_argument("--osf-url")
    parser.add_argument("--osf-doi")
    args = parser.parse_args(argv)
    try:
        result = build_check(
            Path(args.run_dir),
            public_url=args.public_url,
            osf_node_id=args.osf_node_id,
            osf_url=args.osf_url,
            osf_doi=args.osf_doi,
        )
    except OSError as exc:
        print(f"osf/dw pipeline check failed: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
