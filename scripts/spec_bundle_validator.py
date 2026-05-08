from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_BUNDLE_FILES = (
    "README.md",
    "bundle_manifest.json",
    "full_paper.md",
    "full_paper.audit.json",
    "full_paper.audit.md",
    "full_paper.final_verdict.md",
    "full_paper.review_summary.md",
    "full_paper.review_patches.json",
    "full_paper.review_patch_log.json",
    "full_paper.consistency.md",
    "manifest.json",
    "provenance.json",
    "citation.bib",
    "citation.csl.json",
    "paper.schema.jsonld",
    "trust_panel.json",
    "checksums.sha256",
    "versions.html",
    "index.html",
)

MANIFEST_FIELDS = (
    "schema_version",
    "run_id",
    "topic",
    "generated_at",
    "source_run_dir",
    "canonical_url",
    "files",
    "provenance",
)

JSONLD_FIELDS = (
    "@context",
    "@type",
    "name",
    "description",
    "dateCreated",
    "publisher",
    "identifier",
    "url",
    "isBasedOn",
)


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError as exc:
        return None, f"invalid_json:{exc.msg}"


def _safe_relative(value: str) -> bool:
    path = Path(value)
    return value and not path.is_absolute() and ".." not in path.parts


def validate_jsonld(path: Path) -> dict[str, Any]:
    data, error = _load_json(path)
    issues: list[str] = []
    if error:
        return {"path": str(path), "passed": False, "issues": [error]}
    if not isinstance(data, dict):
        issues.append("not_object")
        data = {}
    for field in JSONLD_FIELDS:
        if field not in data:
            issues.append(f"missing:{field}")
    if data.get("@context") != "https://schema.org":
        issues.append("bad_context")
    if data.get("@type") not in {"ScholarlyArticle", "CreativeWork"}:
        issues.append("bad_type")
    return {"path": str(path), "passed": not issues, "issues": issues}


def validate_bundle_dir(path: Path) -> dict[str, Any]:
    issues: list[str] = []
    missing = [name for name in REQUIRED_BUNDLE_FILES if not (path / name).exists()]
    issues.extend(f"missing:{name}" for name in missing)

    manifest, error = _load_json(path / "bundle_manifest.json")
    if error:
        issues.append(f"bundle_manifest:{error}")
        manifest = {}
    if not isinstance(manifest, dict):
        issues.append("bundle_manifest:not_object")
        manifest = {}

    if manifest:
        for field in MANIFEST_FIELDS:
            if field not in manifest:
                issues.append(f"bundle_manifest:missing:{field}")
        if manifest.get("schema_version") != "bundle_schema.v1":
            issues.append("bundle_manifest:bad_schema_version")
        files = manifest.get("files")
        if not isinstance(files, list):
            issues.append("bundle_manifest:files_not_list")
        else:
            for entry in files:
                _validate_file_entry(path, entry, issues)

    return {
        "path": str(path),
        "passed": not issues,
        "missing_required_files": missing,
        "issues": issues,
    }


def _validate_file_entry(root: Path, entry: Any, issues: list[str]) -> None:
    if not isinstance(entry, dict):
        issues.append("bundle_manifest:file_entry_not_object")
        return
    rel = entry.get("path")
    if not isinstance(rel, str) or not _safe_relative(rel):
        issues.append("bundle_manifest:unsafe_path")
        return
    target = root / rel
    if not target.exists():
        issues.append(f"bundle_manifest:file_missing:{rel}")
        return
    if "bytes" in entry and entry["bytes"] != target.stat().st_size:
        issues.append(f"bundle_manifest:bad_bytes:{rel}")
    if "sha256" in entry:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if entry["sha256"] != digest:
            issues.append(f"bundle_manifest:bad_sha256:{rel}")


def build_report(bundle_dirs: list[Path], jsonld_files: list[Path]) -> dict[str, Any]:
    bundles = [validate_bundle_dir(path) for path in bundle_dirs]
    jsonld = [validate_jsonld(path) for path in jsonld_files]
    return {
        "schema": "spec_validation.v1",
        "bundles": bundles,
        "jsonld": jsonld,
        "passed": all(row["passed"] for row in bundles + jsonld),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = ["# Spec Validation 2026-05-08", ""]
    lines += ["## Bundle Checks", ""]
    lines += ["| Path | Passed | Missing required files |", "|---|---:|---|"]
    for row in report["bundles"]:
        missing = ", ".join(row["missing_required_files"]) or "none"
        lines.append(f"| `{row['path']}` | {row['passed']} | {missing} |")
    lines += ["", "## JSON-LD Checks", ""]
    lines += ["| Path | Passed | Issues |", "|---|---:|---|"]
    for row in report["jsonld"]:
        issues = ", ".join(row["issues"]) or "none"
        lines.append(f"| `{row['path']}` | {row['passed']} | {issues} |")
    lines += [
        "",
        "## Open Blockers",
        "",
        "- Existing synthesis run directories are not yet full Bundle Schema 1.0 public bundles.",
        "- `bundle_manifest.json`, `provenance.json`, citation exports, trust panel, checksums, and reader files must be generated before public publication.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", action="append", default=[])
    parser.add_argument("--jsonld", action="append", default=[])
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    args = parser.parse_args()

    report = build_report(
        [Path(value) for value in args.bundle],
        [Path(value) for value in args.jsonld],
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.md_out:
        write_markdown(report, Path(args.md_out))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
