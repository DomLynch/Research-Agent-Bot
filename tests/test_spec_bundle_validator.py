from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from spec_bundle_validator import (  # noqa: E402
    REQUIRED_BUNDLE_FILES,
    build_report,
    validate_bundle_dir,
    validate_jsonld,
)


def _jsonld(path: Path, **overrides: object) -> Path:
    data = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "name": "Example paper",
        "description": "Fixture",
        "dateCreated": "2026-05-08",
        "publisher": "Researka",
        "identifier": "run-1",
        "url": "https://provenance.researka.org/papers/run-1/",
        "isBasedOn": "https://provenance.researka.org/provenance/run-1",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_jsonld_fixture_shape_passes(tmp_path: Path) -> None:
    row = validate_jsonld(_jsonld(tmp_path / "paper.schema.jsonld"))

    assert row["passed"] is True
    assert row["issues"] == []


def test_jsonld_missing_required_field_fails_closed(tmp_path: Path) -> None:
    path = _jsonld(tmp_path / "paper.schema.jsonld")
    data = json.loads(path.read_text())
    del data["isBasedOn"]
    path.write_text(json.dumps(data), encoding="utf-8")

    row = validate_jsonld(path)

    assert row["passed"] is False
    assert "missing:isBasedOn" in row["issues"]


def test_bundle_manifest_shape_and_hashes_pass(tmp_path: Path) -> None:
    for name in REQUIRED_BUNDLE_FILES:
        (tmp_path / name).write_text(name, encoding="utf-8")
    digest = hashlib.sha256((tmp_path / "full_paper.md").read_bytes()).hexdigest()
    (tmp_path / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "bundle_schema.v1",
                "run_id": "run-1",
                "topic": "alpha",
                "generated_at": "2026-05-08T00:00:00Z",
                "source_run_dir": "runs/run-1",
                "canonical_url": "https://provenance.researka.org/papers/run-1/",
                "files": [
                    {
                        "path": "full_paper.md",
                        "bytes": (tmp_path / "full_paper.md").stat().st_size,
                        "sha256": digest,
                        "media_type": "text/markdown",
                        "required": True,
                    }
                ],
                "provenance": {"repo_commit": "abc123"},
            }
        ),
        encoding="utf-8",
    )

    row = validate_bundle_dir(tmp_path)

    assert row["passed"] is True


def test_bundle_manifest_blocks_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "bundle_schema.v1",
                "run_id": "run-1",
                "topic": "alpha",
                "generated_at": "2026-05-08T00:00:00Z",
                "source_run_dir": "runs/run-1",
                "canonical_url": "https://provenance.researka.org/papers/run-1/",
                "files": [{"path": "../secret", "required": True}],
                "provenance": {},
            }
        ),
        encoding="utf-8",
    )

    row = validate_bundle_dir(tmp_path)

    assert row["passed"] is False
    assert "bundle_manifest:unsafe_path" in row["issues"]


def test_build_report_combines_bundle_and_jsonld_results(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    jsonld = _jsonld(tmp_path / "paper.schema.jsonld")

    report = build_report([bundle], [jsonld])

    assert report["schema"] == "spec_validation.v1"
    assert report["bundles"][0]["passed"] is False
    assert report["jsonld"][0]["passed"] is True
    assert report["passed"] is False
