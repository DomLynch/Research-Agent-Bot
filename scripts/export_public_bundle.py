"""Researka Public Bundle exporter.

Copies the publishable artifacts from a synthesis run into one
self-contained directory suitable for OSF / Zenodo / GitHub Pages
upload. The bundle is the public-error-surface package: paper +
audit + cert + patch log + registry + manifest.

Output layout:

  bundles/<run-id>/
    paper.md                       — the manuscript
    audit.json + audit.md          — stage-1 audit
    consistency.json + .md         — stage-2 consistency audit
    final_verdict.json + .md       — unified pipeline verdict
    certification.json + .md       — Researka A2A-AAA cert
    patches.json                   — full Grok patch list (raw)
    patch_log.json                 — orchestrator decisions on each
    fix_log.json                   — deterministic auto-fix log
    citation_registry.json         — every citation with traceback
    manifest.json                  — run-level metadata
    no_regression_report.json + .md — diff vs prior baseline
    README.md                      — bundle entry point

No new science logic. Pure file copy + README composition.

Usage:
  python scripts/export_public_bundle.py <run-dir>
  python scripts/export_public_bundle.py <run-dir> --out bundles/custom
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE_ROOT = REPO / "bundles"

# Source filename → bundle filename
_FILE_MAP: dict[str, str] = {
    "full_paper.md": "paper.md",
    "full_paper.audit.json": "audit.json",
    "full_paper.audit.md": "audit.md",
    "full_paper.consistency.json": "consistency.json",
    "full_paper.consistency.md": "consistency.md",
    "full_paper.final_verdict.json": "final_verdict.json",
    "full_paper.final_verdict.md": "final_verdict.md",
    "full_paper.certification.json": "certification.json",
    "full_paper.certification.md": "certification.md",
    "full_paper.review_patches.json": "patches.json",
    "full_paper.review_patch_log.json": "patch_log.json",
    "full_paper.fixed_log.json": "fix_log.json",
    "citation_registry.json": "citation_registry.json",
    "manifest.json": "manifest.json",
    "no_regression_report.json": "no_regression_report.json",
    "no_regression_report.md": "no_regression_report.md",
    "run_mode_contract.json": "run_mode_contract.json",
}

# Files that, if missing, just get skipped (not an error).
_OPTIONAL = {
    "full_paper.certification.json",
    "full_paper.certification.md",
    "no_regression_report.json",
    "no_regression_report.md",
    "run_mode_contract.json",
}


def export_bundle(
    run_dir: Path, bundle_dir: Path,
) -> dict[str, list[str]]:
    """Copy artifacts from run_dir → bundle_dir. Returns
    {'copied': [...], 'skipped': [...], 'missing_required': [...]}."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "copied": [], "skipped": [], "missing_required": [],
    }
    for src_name, dst_name in _FILE_MAP.items():
        src = run_dir / src_name
        if not src.exists():
            if src_name in _OPTIONAL:
                result["skipped"].append(src_name)
            else:
                result["missing_required"].append(src_name)
            continue
        dst = bundle_dir / dst_name
        shutil.copy2(src, dst)
        result["copied"].append(f"{src_name} → {dst_name}")
    # Compose README from cert + manifest
    readme = _compose_readme(run_dir, bundle_dir)
    (bundle_dir / "README.md").write_text(readme)
    result["copied"].append("README.md (composed)")
    return result


def _compose_readme(run_dir: Path, bundle_dir: Path) -> str:
    """Write a top-level README.md that explains the bundle layout
    and links to the cert + verdict at a glance."""
    cert = _read_json_safe(bundle_dir / "certification.json")
    verdict = _read_json_safe(bundle_dir / "final_verdict.json")
    manifest = _read_json_safe(bundle_dir / "manifest.json")
    no_reg = _read_json_safe(bundle_dir / "no_regression_report.json")

    run_id = run_dir.name
    git_sha = (cert or {}).get("git_sha", "unknown")
    cert_status = (
        "Researka Certified A2A-AAA"
        if (cert or {}).get("aaa_certified")
        and (cert or {}).get("aaa_pass")
        else (
            (cert or {}).get("final_verdict", "Unknown")
        )
    )
    final_v = (verdict or {}).get("verdict", "Unknown")
    n_receipts = (manifest or {}).get("n_receipts", 0)
    n_claims = (manifest or {}).get(
        "n_high_confidence_claims_total", 0
    )
    n_tensions = (manifest or {}).get(
        "n_non_orthogonal_tensions", 0
    )
    no_reg_str = (
        "PASS" if (no_reg or {}).get("passes")
        else ("FAIL" if no_reg else "no baseline")
    )

    lines = [
        f"# Researka Public Bundle — {run_id}",
        "",
        f"**Status:** {cert_status}",
        f"**Final verdict:** {final_v}",
        f"**Bundled at:** "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"**Git SHA:** `{git_sha}`",
        "",
        "## What's in this bundle",
        "",
        "Every artifact the pipeline produced for this run, in a "
        "self-contained directory. No external dependencies; "
        "everything you need to audit the manuscript is here.",
        "",
        "## Layout",
        "",
        "| File | Purpose |",
        "|---|---|",
        "| `paper.md` | The manuscript |",
        "| `certification.md` | Researka A2A-AAA cert + dissent log |",
        "| `final_verdict.md` | Unified pipeline verdict |",
        "| `audit.md` | Stage-1 quantitative audit (Q1-Q13) |",
        "| `consistency.md` | Stage-2 consistency check (C01-C14) |",
        "| `no_regression_report.md` | Diff vs prior baseline |",
        "| `patches.json` | Full Grok review patch list (raw) |",
        "| `patch_log.json` | Orchestrator decisions per patch |",
        "| `fix_log.json` | Deterministic auto-fix interventions |",
        "| `citation_registry.json` | Every citation with traceback |",
        "| `manifest.json` | Run metadata (corpus, costs, etc.) |",
        "",
        "## Run-level summary",
        "",
        f"- Receipts: {n_receipts}",
        f"- High-confidence claims: {n_claims}",
        f"- Non-orthogonal tensions: {n_tensions}",
        f"- No-regression vs baseline: {no_reg_str}",
        "",
        "## How to verify",
        "",
        "1. Read `certification.md` for the A2A-AAA gate result.",
        "2. Read `audit.md` for Q1-Q13 quantitative checks "
        "(numeric traceability, citation coverage, depth floors, "
        "etc.).",
        "3. Read `consistency.md` for C01-C14 surface integrity "
        "checks (no duplicate sections, no internal labels, no "
        "change-value misreads, etc.).",
        "4. Read `patches.json` + `patch_log.json` for the full "
        "reviewer-intervention trail. Every change to the paper "
        "after initial render is logged.",
        "5. Cross-check `citation_registry.json` against the "
        "manuscript's `## References` block — every claim cites a "
        "registry entry; every entry resolves to a corpus paper.",
        "",
        "## Researka manifesto note",
        "",
        "This bundle is the **public error surface**: every "
        "intervention, every patch, every audit decision is here "
        "for inspection. If you find an error not surfaced by the "
        "audit/cert artifacts, that is a bug in the trust-spine "
        "and we want to know.",
        "",
        "Trust-spine principle: **LLM proposes, code disposes.** "
        "Every claim, citation, and numeric traces to source via "
        "deterministic registries; every reviewer suggestion is "
        "gate-checked before application.",
    ]
    return "\n".join(lines) + "\n"


def _read_json_safe(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a synthesis run as a public bundle",
    )
    parser.add_argument("run_dir", help="runs/<...> directory")
    parser.add_argument(
        "--out",
        help="Bundle directory (default: bundles/<run-id>/)",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"not found: {run_dir}", file=sys.stderr)
        return 2
    if not (run_dir / "full_paper.md").exists():
        print(
            f"not a synthesis run dir (no full_paper.md): {run_dir}",
            file=sys.stderr,
        )
        return 2
    bundle_dir = (
        Path(args.out).resolve() if args.out
        else DEFAULT_BUNDLE_ROOT / run_dir.name
    )
    result = export_bundle(run_dir, bundle_dir)
    print(
        f"Bundle written to: {bundle_dir}\n"
        f"  copied: {len(result['copied'])} file(s)\n"
        f"  skipped (optional): {len(result['skipped'])} file(s)\n"
        f"  missing required: {len(result['missing_required'])} "
        f"file(s)",
        file=sys.stderr,
    )
    if result["missing_required"]:
        for f in result["missing_required"]:
            print(f"  MISSING: {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
