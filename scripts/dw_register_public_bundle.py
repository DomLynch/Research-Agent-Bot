#!/usr/bin/env python3
"""Build or POST a Derivation Web public-bundle registration payload.

Default is dry-run: print the payload shape only. Live mode is opt-in
and requires DW_API_URL + DW_API_TOKEN. Tokens are never stored or
printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

import researka_reader_manifest as reader


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed or missing JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON must be an object: {path}")
    return data


def _manifest_path(path: Path) -> Path:
    return path / reader.MANIFEST_NAME if path.is_dir() else path


def build_payload(
    manifest_or_dir: Path,
    *,
    public_url: str | None = None,
    osf_result: Path | None = None,
) -> dict[str, Any]:
    manifest = _read_json(_manifest_path(manifest_or_dir))
    osf = _read_json(osf_result) if osf_result else None
    return reader.build_dw_register_payload(
        manifest,
        public_url=public_url,
        osf=osf,
    )


def post_payload(
    payload: dict[str, Any],
    *,
    api_url: str,
    token: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        response = http.post(
            api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": str(payload["idempotency_key"]),
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return {
            "registered": True,
            "status_code": response.status_code,
            "idempotency_key": payload["idempotency_key"],
            "response_id": data.get("id") if isinstance(data, dict) else None,
        }
    finally:
        if owns_client:
            http.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_or_dir", help="reader manifest path or bundle dir")
    parser.add_argument("--public-url")
    parser.add_argument("--osf-result", help="Optional osf_publish_result.json path")
    parser.add_argument("--live", action="store_true", help="POST to DW_API_URL")
    args = parser.parse_args(argv)
    try:
        payload = build_payload(
            Path(args.manifest_or_dir),
            public_url=args.public_url,
            osf_result=Path(args.osf_result) if args.osf_result else None,
        )
        if not args.live:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        api_url = os.environ.get("DW_API_URL")
        token = os.environ.get("DW_API_TOKEN")
        if not api_url or not token:
            raise RuntimeError("DW_API_URL and DW_API_TOKEN are required for --live")
        result = post_payload(payload, api_url=api_url, token=token)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        print(f"dw register failed: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
