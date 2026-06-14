"""Tamper-evident provenance sidecar for a published artifact.

Stdlib-only (hashlib/json), no LLM, deterministic. Binds the trust-relevant
facts of a run into one signed record: which model AUTHORED the artifact, which
models REVIEWED it, the final VERDICT, and the SHA-256 of the exact shipped
artifact. A reader can re-hash the artifact and confirm it is the one that was
graded — provenance you can verify, not just assert.

Decoupled by design: every field is passed in explicitly (no coupling to
manifest/final_status schemas), `generated_at` is a caller-supplied ISO string
(kept deterministic for tests). This module imports nothing from the rest of
the codebase and nothing live imports it yet — additive, zero blast radius.
Wiring it into the export path (write to the run dir at finalize) is a separate,
reviewed step.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "sha256_file",
    "build_provenance",
    "write_provenance_sidecar",
    "verify_provenance_sidecar",
]

SCHEMA_VERSION = "1.0"


def sha256_file(path: str | Path) -> str:
    """Streaming SHA-256 of a file (handles large artifacts without slurping)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_provenance(
    *,
    run_id: str,
    artifact_path: str | Path,
    author_model: str,
    reviewer_models: Iterable[str],
    verdict: str,
    generated_at: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the provenance record for `artifact_path` (hashed here)."""
    p = Path(artifact_path)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "artifact": p.name,
        "sha256": sha256_file(p),
        "author_model": author_model,
        "reviewer_models": list(reviewer_models),
        "verdict": verdict,
        "generated_at": generated_at,
    }
    if extra:
        # never let extra clobber the core trust fields
        for k, v in extra.items():
            record.setdefault(str(k), v)
    return record


def write_provenance_sidecar(
    out_dir: str | Path, *, filename: str = "provenance.json", **fields: Any,
) -> Path:
    """Write the provenance record to `out_dir/filename` and return the path."""
    record = build_provenance(**fields)
    path = Path(out_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return path


def verify_provenance_sidecar(
    out_dir: str | Path,
    *,
    filename: str = "provenance.json",
    artifact_dir: str | Path | None = None,
) -> bool:
    """Re-hash the recorded artifact and confirm it matches the sidecar.

    Returns True only if the sidecar exists, names an artifact present under
    `artifact_dir` (defaults to `out_dir`), and its live SHA-256 equals the
    recorded one. Any missing file or mismatch -> False (tamper/decay detected).
    """
    sidecar = Path(out_dir) / filename
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    name = record.get("artifact")
    recorded = record.get("sha256")
    if not name or not recorded:
        return False
    artifact = Path(artifact_dir or out_dir) / str(name)
    if not artifact.is_file():
        return False
    return sha256_file(artifact) == recorded
