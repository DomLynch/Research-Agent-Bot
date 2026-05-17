#!/usr/bin/env python3
"""Build a public reader manifest for a run or exported bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from bundle_snapshot import is_secret_path, sha256_file

MANIFEST_NAME = "researka_reader_manifest.json"
SCHEMA = "researka.reader_manifest.v1"
DW_SCHEMA = "derivation_web.register_public_bundle.v1"
DW_ACTOR_ID = "researka:system:osf-publisher:v1"
_ORCID_RE = re.compile(r"^https://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

_EXCLUDED_NAMES = {
    MANIFEST_NAME,
    "bundle_snapshot.json",
    "osf_publish_plan.json",
    "osf_publish_result.json",
}
_ENTRYPOINT_CANDIDATES = {
    "paper": ("paper.md", "full_paper.md", "paper_synthesis.md"),
    "certification": ("certification.md", "full_paper.certification.md"),
    "audit": ("audit.md", "full_paper.audit.md"),
    "manifest": ("manifest.json", "multi_receipt_manifest.json"),
    "citations": ("citation_registry.json",),
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _topic(root: Path) -> str:
    manifest = _read_json(root / "manifest.json")
    topic = manifest.get("topic")
    if isinstance(topic, str) and topic:
        return topic
    name = root.name
    if name.startswith("synthesis-") and "-v" in name:
        return name.removeprefix("synthesis-").split("-v", 1)[0]
    return "unknown"


def _osf_value(osf: dict[str, Any] | None, *names: str) -> Any:
    data = osf or {}
    return next((data[name] for name in names if data.get(name)), None)


def _normalise_orcid(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", raw):
        raw = f"https://orcid.org/{raw}"
    if not _ORCID_RE.fullmatch(raw):
        raise ValueError("submitter ORCID must be https://orcid.org/0000-0000-0000-0000")
    return raw


def iter_public_files(root: Path) -> list[Path]:
    """Return deterministic, non-secret public files relative to root."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.name in _EXCLUDED_NAMES or is_secret_path(rel):
            continue
        files.append(rel)
    return sorted(files, key=lambda p: p.as_posix())


def build_reader_manifest(
    root: Path,
    *,
    public_url: str | None = None,
    osf: dict[str, Any] | None = None,
    submitter_orcid: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic public-reader manifest."""
    root = root.resolve()
    entries = [
        {
            "path": rel.as_posix(),
            "size": (root / rel).stat().st_size,
            "sha256": sha256_file(root / rel),
        }
        for rel in iter_public_files(root)
    ]
    paths = {entry["path"] for entry in entries}
    entrypoints = {
        key: next((name for name in names if name in paths), None)
        for key, names in _ENTRYPOINT_CANDIDATES.items()
    }
    topic = _topic(root)
    osf_url = _osf_value(osf, "url", "osf_url")
    doi = _osf_value(osf, "doi", "osf_doi")
    orcid = _normalise_orcid(submitter_orcid)
    json_ld = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "name": f"Researka synthesis: {topic}",
        "about": topic,
        "identifier": doi,
        "url": public_url,
        "isBasedOn": osf_url,
    }
    if orcid:
        json_ld["author"] = {"@type": "Person", "identifier": orcid, "sameAs": orcid}
    return {
        "schema": SCHEMA,
        "run_id": root.name,
        "topic": topic,
        "public_url": public_url,
        "submitter_orcid": orcid,
        "file_count": len(entries),
        "total_size": sum(entry["size"] for entry in entries),
        "entrypoints": entrypoints,
        "json_ld": json_ld,
        "files": entries,
    }


def aggregate_files_key(reader_manifest: dict[str, Any]) -> str:
    """Stable idempotency key from run_id + public file hashes."""
    if reader_manifest.get("schema") != SCHEMA:
        raise ValueError("reader manifest schema mismatch")
    files = reader_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("reader manifest has no files")
    aggregate = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("reader manifest file entry must be an object")
        try:
            aggregate.append({
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
                "size": int(item["size"]),
            })
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("reader manifest file entry is malformed") from exc
    body = {
        "run_id": reader_manifest.get("run_id"),
        "files": sorted(aggregate, key=lambda item: str(item["path"])),
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"dw-register:{digest}"


def write_reader_manifest(
    root: Path,
    out: Path | None = None,
    *,
    public_url: str | None = None,
    osf: dict[str, Any] | None = None,
    submitter_orcid: str | None = None,
) -> Path:
    manifest = build_reader_manifest(
        root,
        public_url=public_url,
        osf=osf,
        submitter_orcid=submitter_orcid,
    )
    out_path = out or root / MANIFEST_NAME
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def build_dw_register_payload(
    reader_manifest: dict[str, Any],
    *,
    public_url: str | None = None,
    osf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Derivation Web registration payload shape only."""
    key = aggregate_files_key(reader_manifest)
    public = public_url or reader_manifest.get("public_url")
    osf_block = {
        "node_id": _osf_value(osf, "node_id", "osf_node_id"),
        "url": _osf_value(osf, "url", "osf_url"),
        "doi": _osf_value(osf, "doi", "osf_doi"),
    }
    aggregate_files = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "size": item["size"],
        }
        for item in reader_manifest.get("files", [])
    ]
    return {
        "schema": DW_SCHEMA,
        "idempotency_key": key,
        "reader_manifest_schema": reader_manifest.get("schema"),
        "run_id": reader_manifest.get("run_id"),
        "topic": reader_manifest.get("topic"),
        "public_url": public,
        "osf": osf_block,
        "file_count": reader_manifest.get("file_count", 0),
        "aggregate_files": aggregate_files,
        "dw": {
            "append_only": True,
            "actor_id": DW_ACTOR_ID,
            "artifact": {
                "kind": "registry_record",
                "content_type": "application/json",
                "body_text": json.dumps(
                    {
                        "registry": "osf",
                        "run_id": reader_manifest.get("run_id"),
                        "topic": reader_manifest.get("topic"),
                        "public_url": public,
                        "submitter_orcid": reader_manifest.get("submitter_orcid"),
                        "osf": osf_block,
                        "idempotency_key": key,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "metadata": {
                    "registry": "osf",
                    "run_id": reader_manifest.get("run_id"),
                    "topic": reader_manifest.get("topic"),
                    "public_url": public,
                    "submitter_orcid": reader_manifest.get("submitter_orcid"),
                    "idempotency_key": key,
                },
                "actor_id": DW_ACTOR_ID,
            },
            "step": {
                "step_type": "register",
                "input_artifact_ids": [],
                "output_artifact_id": None,
                "target_artifact_id": reader_manifest.get("run_id"),
                "actor_id": DW_ACTOR_ID,
                "method": {
                    "registry": "osf",
                    "idempotency_key": key,
                    "file_count": reader_manifest.get("file_count", 0),
                },
                "created_at": None,
                "signature_b64": None,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Run or public bundle directory")
    parser.add_argument("--out", help=f"Output path; default <root>/{MANIFEST_NAME}")
    parser.add_argument("--public-url")
    parser.add_argument("--osf-result", help="Optional osf_publish_result.json path")
    parser.add_argument("--submitter-orcid", default=os.getenv("RESEARKA_SUBMITTER_ORCID"))
    args = parser.parse_args(argv)
    try:
        out = write_reader_manifest(
            Path(args.root),
            Path(args.out).resolve() if args.out else None,
            public_url=args.public_url,
            osf=_read_json(Path(args.osf_result)) if args.osf_result else None,
            submitter_orcid=args.submitter_orcid,
        )
    except (OSError, ValueError) as exc:
        print(f"reader manifest failed: {exc}", file=sys.stderr)
        return 2
    print(f"reader manifest written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
