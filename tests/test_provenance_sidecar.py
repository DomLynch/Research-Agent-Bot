"""Tests for the tamper-evident provenance sidecar (agent/provenance_sidecar.py)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent.provenance_sidecar import (
    SCHEMA_VERSION,
    build_provenance,
    sha256_file,
    verify_provenance_sidecar,
    write_provenance_sidecar,
)

_REVIEWERS = ["google/gemma-4-31b-it", "openrouter/grok-4.3"]


def _artifact(tmp_path: Path, body: str = "full paper body\n") -> Path:
    p = tmp_path / "full_paper.md"
    p.write_text(body, encoding="utf-8")
    return p


def _build(art: Path, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return build_provenance(
        run_id="run-001", artifact_path=art, author_model="minimax/m2.5-pro",
        reviewer_models=_REVIEWERS, verdict="L5_SUBMISSION_READY",
        generated_at="2026-06-14T12:00:00Z", extra=extra,
    )


def _write(tmp_path: Path, art: Path) -> Path:
    return write_provenance_sidecar(
        tmp_path, run_id="run-001", artifact_path=art,
        author_model="minimax/m2.5-pro", reviewer_models=_REVIEWERS,
        verdict="L5_SUBMISSION_READY", generated_at="2026-06-14T12:00:00Z",
    )


def test_build_records_core_fields_and_real_hash(tmp_path: Path) -> None:
    art = _artifact(tmp_path)
    rec = _build(art)
    assert rec["schema_version"] == SCHEMA_VERSION
    assert rec["artifact"] == "full_paper.md"
    assert rec["sha256"] == sha256_file(art)
    assert rec["author_model"] == "minimax/m2.5-pro"
    assert rec["reviewer_models"] == _REVIEWERS
    assert rec["verdict"] == "L5_SUBMISSION_READY"


def test_extra_cannot_clobber_core_fields(tmp_path: Path) -> None:
    art = _artifact(tmp_path)
    rec = _build(art, extra={"verdict": "FORGED", "note": "ok"})
    assert rec["verdict"] == "L5_SUBMISSION_READY"  # core wins
    assert rec["note"] == "ok"  # genuinely-new extra kept


def test_write_then_verify_roundtrip(tmp_path: Path) -> None:
    art = _artifact(tmp_path)
    path = _write(tmp_path, art)
    assert path.name == "provenance.json"
    assert json.loads(path.read_text())["run_id"] == "run-001"
    assert verify_provenance_sidecar(tmp_path) is True


def test_verify_detects_tampered_artifact(tmp_path: Path) -> None:
    art = _artifact(tmp_path)
    _write(tmp_path, art)
    art.write_text("body has been edited after grading\n", encoding="utf-8")
    assert verify_provenance_sidecar(tmp_path) is False


def test_verify_false_when_artifact_or_sidecar_missing(tmp_path: Path) -> None:
    assert verify_provenance_sidecar(tmp_path) is False  # no sidecar at all
    art = _artifact(tmp_path)
    _write(tmp_path, art)
    art.unlink()
    assert verify_provenance_sidecar(tmp_path) is False  # artifact gone
