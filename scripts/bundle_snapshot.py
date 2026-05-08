#!/usr/bin/env python3
"""Deterministic sha256/size manifest for a run or public bundle dir."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SNAPSHOT_NAME = "bundle_snapshot.json"

_GENERATED_NAMES = {
    SNAPSHOT_NAME,
    "osf_publish_plan.json",
    "osf_publish_result.json",
}
_SECRET_MARKERS = (
    ".env",
    "apikey",
    "api_key",
    "credential",
    "credentials",
    "passwd",
    "password",
    "secret",
    "token",
)
_SECRET_SUFFIXES = (".pem", ".p12", ".pfx", ".key")


def is_secret_path(path: Path) -> bool:
    """Return True for filenames likely to contain credentials."""
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    return (
        any(marker in part for part in parts for marker in _SECRET_MARKERS)
        or name.endswith(_SECRET_SUFFIXES)
    )


def iter_snapshot_files(root: Path) -> list[Path]:
    """Return deterministic, non-secret regular files under root."""
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.name in _GENERATED_NAMES or is_secret_path(rel):
            continue
        files.append(rel)
    return sorted(files, key=lambda p: p.as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(root: Path) -> dict:
    """Build a deterministic manifest with no mtimes or absolute paths."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    entries = []
    for rel in iter_snapshot_files(root):
        path = root / rel
        entries.append({
            "path": rel.as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    aggregate = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "researka.bundle_snapshot.v1",
        "file_count": len(entries),
        "total_size": sum(e["size"] for e in entries),
        "aggregate_sha256": aggregate,
        "files": entries,
    }


def write_snapshot(root: Path, out: Path | None = None) -> Path:
    snapshot = build_snapshot(root)
    out_path = out or root / SNAPSHOT_NAME
    out_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Run or bundle directory")
    parser.add_argument("--out", help=f"Output path (default: <run-dir>/{SNAPSHOT_NAME})")
    args = parser.parse_args(argv)
    try:
        out = write_snapshot(
            Path(args.run_dir),
            Path(args.out).resolve() if args.out else None,
        )
    except OSError as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    print(f"snapshot written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
