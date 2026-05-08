#!/usr/bin/env python3
"""PAT-only OSF V1 publisher foundation.

Dry-run and snapshot-only modes never require OSF_PAT and never touch
the network. Live mode reads OSF_PAT from env and fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from bundle_snapshot import SNAPSHOT_NAME, build_snapshot

DEFAULT_OSF_API = "https://api.osf.io/v2"
PLAN_NAME = "osf_publish_plan.json"
RESULT_NAME = "osf_publish_result.json"
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
LIVE_ENV = "OSF_PUBLISH_LIVE"
PUBLISH_GENERATED_NAMES = {
    SNAPSHOT_NAME,
    PLAN_NAME,
    RESULT_NAME,
    "researka_reader_manifest.json",
}


def _idempotency_key(run_dir: Path, aggregate_sha256: str) -> str:
    material = f"{run_dir.resolve().name}:{aggregate_sha256}"
    return hashlib.sha256(material.encode()).hexdigest()


def build_publish_snapshot(run_dir: Path) -> dict:
    """Build the upload snapshot, excluding generated publisher artifacts."""
    snapshot = build_snapshot(run_dir)
    files = [
        item
        for item in snapshot["files"]
        if Path(item["path"]).name not in PUBLISH_GENERATED_NAMES
    ]
    aggregate = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **snapshot,
        "file_count": len(files),
        "total_size": sum(item["size"] for item in files),
        "aggregate_sha256": aggregate,
        "files": files,
    }


def write_publish_snapshot(run_dir: Path) -> Path:
    path = run_dir / SNAPSHOT_NAME
    path.write_text(
        json.dumps(build_publish_snapshot(run_dir), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def build_plan(
    run_dir: Path,
    snapshot: dict,
    *,
    base_url: str = DEFAULT_OSF_API,
) -> dict:
    """Build a local publish plan without credentials or mtimes."""
    planned_files = [
        {
            "path": item["path"],
            "size": item["size"],
            "sha256": item["sha256"],
            "file_url": None,
        }
        for item in snapshot["files"]
    ]
    return {
        "schema": "researka.osf_publish_plan.v1",
        "mode": "dry-run",
        "run_id": run_dir.resolve().name,
        "idempotency_key": _idempotency_key(run_dir, snapshot["aggregate_sha256"]),
        "osf_api": base_url.rstrip("/"),
        "file_count": snapshot["file_count"],
        "total_size": snapshot["total_size"],
        "aggregate_sha": snapshot["aggregate_sha256"],
        "aggregate_sha256": snapshot["aggregate_sha256"],
        "planned_files": planned_files,
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
                    "file_url": None,
                }
                for item in planned_files
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


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return exc.__class__.__name__
    return exc.__class__.__name__


def _live_enabled() -> bool:
    return os.environ.get(LIVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _request_with_retry(
    http: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    retry_delay: float = 0.0,
    **kwargs: Any,
) -> httpx.Response:
    last_exc: httpx.HTTPError | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = http.request(method, url, **kwargs)
            if response.status_code in TRANSIENT_STATUSES and attempt < attempts:
                if retry_delay:
                    time.sleep(retry_delay)
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in TRANSIENT_STATUSES or attempt == attempts:
                raise
            last_exc = exc
        except httpx.TransportError as exc:
            if attempt == attempts:
                raise
            last_exc = exc
        if retry_delay:
            time.sleep(retry_delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable retry state")


def _file_url(data: dict[str, Any]) -> str | None:
    links = data.get("links", {})
    if isinstance(links, dict):
        html = links.get("html")
        if isinstance(html, str):
            return html
    inner = data.get("data", {})
    if isinstance(inner, dict):
        return _file_url(inner)
    return None


def upload_file(
    http: httpx.Client,
    *,
    node_id: str,
    run_dir: Path,
    rel_path: str,
    token: str,
    files_url: str = "https://files.osf.io/v1",
    attempts: int = 3,
) -> dict[str, str | None]:
    """Upload one snapshot file to OSF Storage via WaterButler."""
    path = run_dir / rel_path
    quoted_name = quote(rel_path, safe="/")
    url = (
        f"{files_url.rstrip('/')}/resources/{node_id}/providers/osfstorage/"
        f"?kind=file&name={quoted_name}"
    )
    response = _request_with_retry(
        http,
        "PUT",
        url,
        attempts=attempts,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        },
        content=path.read_bytes(),
    )
    data = response.json() if response.content else {}
    return {"path": rel_path, "file_url": _file_url(data)}


def publish_live(
    run_dir: Path,
    snapshot: dict,
    *,
    token: str,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_OSF_API,
    files_url: str = "https://files.osf.io/v1",
) -> dict[str, Any]:
    """Create a private OSF project and upload snapshot files."""
    owns_client = client is None
    http = client or httpx.Client(timeout=30.0)
    title = f"Researka bundle: {run_dir.resolve().name}"
    idempotency_key = _idempotency_key(run_dir, snapshot["aggregate_sha256"])
    payload = {
        "data": {
            "type": "nodes",
            "attributes": {
                "title": title,
                "category": "project",
                "public": False,
                "description": (
                    "Researka bundle envelope. File manifest aggregate "
                    f"sha256={snapshot['aggregate_sha256']}. "
                    f"idempotency_key={idempotency_key}."
                ),
            },
        },
    }
    errors: list[str] = []
    uploaded_files: list[dict[str, str | None]] = []
    node_id = None
    url = None
    try:
        response = _request_with_retry(
            http,
            "POST",
            f"{base_url.rstrip('/')}/nodes/",
            headers={**_auth_headers(token), "Idempotency-Key": idempotency_key},
            json=payload,
        )
        data = response.json().get("data", {})
        node_id = data.get("id")
        url = data.get("links", {}).get("html")
        if node_id:
            for item in snapshot["files"]:
                try:
                    uploaded_files.append(
                        upload_file(
                            http,
                            node_id=node_id,
                            run_dir=run_dir,
                            rel_path=item["path"],
                            token=token,
                            files_url=files_url,
                        )
                    )
                except httpx.HTTPError as exc:
                    errors.append(f"{item['path']}: {_safe_error(exc)}")
        else:
            errors.append("node: missing id")
        return {
            "schema": "researka.osf_publish_result.v1",
            "run_id": run_dir.resolve().name,
            "idempotency_key": idempotency_key,
            "node_id": node_id,
            "osf_node_id": node_id,
            "url": url,
            "osf_url": url,
            "aggregate_sha": snapshot["aggregate_sha256"],
            "aggregate_sha256": snapshot["aggregate_sha256"],
            "planned_files": [
                {
                    "path": item["path"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                }
                for item in snapshot["files"]
            ],
            "uploaded_files": uploaded_files,
            "errors": errors,
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
    force: bool = False,
) -> dict[str, Path | None]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise NotADirectoryError(run_dir)
    result_path = run_dir / RESULT_NAME
    if result_path.exists() and not force and not snapshot_only:
        return {"snapshot": None, "plan": None, "result": result_path}
    snapshot_path = write_publish_snapshot(run_dir)
    snapshot = build_publish_snapshot(run_dir)
    if snapshot_only:
        return {"snapshot": snapshot_path, "plan": None, "result": None}
    base_url = os.environ.get("OSF_API_BASE", DEFAULT_OSF_API)
    plan = build_plan(run_dir, snapshot, base_url=base_url)
    plan_path = write_plan(run_dir, plan)
    if dry_run:
        return {"snapshot": snapshot_path, "plan": plan_path, "result": None}
    if not _live_enabled():
        raise RuntimeError(f"{LIVE_ENV}=1 is required for live OSF publish")
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
        "--live",
        action="store_true",
        help=f"Publish live; also requires {LIVE_ENV}=1 and OSF_PAT.",
    )
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Write bundle_snapshot.json only",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing result")
    args = parser.parse_args(argv)
    try:
        paths = run(
            Path(args.run_dir),
            dry_run=not args.live or args.dry_run,
            snapshot_only=args.snapshot_only,
            force=args.force,
        )
    except httpx.HTTPError as exc:
        print(f"osf publish failed: {_safe_error(exc)}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:
        print(f"osf publish failed: {exc}", file=sys.stderr)
        return 2
    for label, path in paths.items():
        if path is not None:
            print(f"{label}: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
