#!/usr/bin/env python3
"""PAT-only OSF V1 publisher foundation.

Dry-run and snapshot-only modes never require OSF_PAT and never touch
the network. Live mode reads OSF_PAT from env and fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from bundle_snapshot import build_snapshot, write_snapshot

DEFAULT_OSF_API = "https://api.osf.io/v2"
PLAN_NAME = "osf_publish_plan.json"
RESULT_NAME = "osf_publish_result.json"


def build_plan(
    run_dir: Path,
    snapshot: dict,
    *,
    base_url: str = DEFAULT_OSF_API,
) -> dict:
    """Build a local publish plan without credentials or mtimes."""
    return {
        "schema": "researka.osf_publish_plan.v1",
        "mode": "dry-run",
        "run_id": run_dir.resolve().name,
        "osf_api": base_url.rstrip("/"),
        "file_count": snapshot["file_count"],
        "total_size": snapshot["total_size"],
        "aggregate_sha256": snapshot["aggregate_sha256"],
        "actions": [
            {
                "action": "create_private_project",
                "title": f"Researka bundle: {run_dir.resolve().name}",
            },
            *[
                {
                    "action": "upload_file",
                    "path": item["path"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                }
                for item in snapshot["files"]
            ],
        ],
    }


def write_plan(run_dir: Path, plan: dict) -> Path:
    path = run_dir / PLAN_NAME
    path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
    }


def publish_live(
    run_dir: Path,
    snapshot: dict,
    *,
    token: str,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_OSF_API,
) -> dict[str, Any]:
    """Create a private OSF project for the bundle.

    File upload is represented in the deterministic plan; this V1 live
    foundation intentionally only creates the private project envelope.
    """
    owns_client = client is None
    http = client or httpx.Client(timeout=30.0)
    title = f"Researka bundle: {run_dir.resolve().name}"
    payload = {
        "data": {
            "type": "nodes",
            "attributes": {
                "title": title,
                "category": "project",
                "public": False,
                "description": (
                    "Researka bundle envelope. File manifest aggregate "
                    f"sha256={snapshot['aggregate_sha256']}."
                ),
            },
        },
    }
    try:
        response = http.post(
            f"{base_url.rstrip('/')}/nodes/",
            headers=_auth_headers(token),
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        return {
            "schema": "researka.osf_publish_result.v1",
            "run_id": run_dir.resolve().name,
            "osf_node_id": data.get("id"),
            "osf_url": data.get("links", {}).get("html"),
            "aggregate_sha256": snapshot["aggregate_sha256"],
            "uploaded_files": 0,
            "planned_files": snapshot["file_count"],
        }
    finally:
        if owns_client:
            http.close()


def run(
    run_dir: Path,
    *,
    dry_run: bool,
    snapshot_only: bool,
    client: httpx.Client | None = None,
) -> dict[str, Path | None]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise NotADirectoryError(run_dir)
    snapshot_path = write_snapshot(run_dir)
    snapshot = build_snapshot(run_dir)
    if snapshot_only:
        return {"snapshot": snapshot_path, "plan": None, "result": None}
    base_url = os.environ.get("OSF_API_BASE", DEFAULT_OSF_API)
    plan = build_plan(run_dir, snapshot, base_url=base_url)
    plan_path = write_plan(run_dir, plan)
    if dry_run:
        return {"snapshot": snapshot_path, "plan": plan_path, "result": None}
    token = os.environ.get("OSF_PAT")
    if not token:
        raise RuntimeError("OSF_PAT is required for live OSF publish")
    result = publish_live(
        run_dir,
        snapshot,
        token=token,
        client=client,
        base_url=base_url,
    )
    result_path = run_dir / RESULT_NAME
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"snapshot": snapshot_path, "plan": plan_path, "result": result_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run or bundle directory")
    parser.add_argument("--dry-run", action="store_true", help="Write local plan only")
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Write bundle_snapshot.json only",
    )
    args = parser.parse_args(argv)
    try:
        paths = run(
            Path(args.run_dir),
            dry_run=args.dry_run,
            snapshot_only=args.snapshot_only,
        )
    except (OSError, RuntimeError, httpx.HTTPError) as exc:
        print(f"osf publish failed: {exc}", file=sys.stderr)
        return 2
    for label, path in paths.items():
        if path is not None:
            print(f"{label}: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
