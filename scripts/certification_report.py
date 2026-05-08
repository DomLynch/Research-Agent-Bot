"""Researka Certified A2A-AAA — certification report generator.

Reads a synthesis run directory and emits two artifacts:

  full_paper.certification.json — machine-readable cert record
  full_paper.certification.md   — human-readable cert page

Plus enforces the A2A-AAA gate (return non-zero exit when criteria
fail). Minimal criteria for v1:

  1. Final verdict = AAA
  2. Q2 numeric traceability = 100%
  3. Stage-2 P1 = 0 AND P2 = 0
  4. Zero unresolved Grok P1 (post-repair-loop)
  5. No-regression gate PASS vs current baseline
  6. Old-defect scan clean (0.13 m/s misuse, walk-speed parenthetical
     pattern, paper-ID leakage)

Stronger criteria (≥2 consecutive AAA runs) are checked by
`certify_consecutive(...)` which takes multiple run dirs.

Public-error-surface fields (per Researka manifesto):

  - applied_patches            count of Grok patches that were applied
  - repaired_patches           count rerouted via repair loop
  - auto_stripped_patches      count nuked by smart-gate fallback
  - rejected_patches           count blocked by smart-gate
  - flagged_patches            count requiring manual review
  - known_limitations          editorialised in cert.md
  - dissent_log                full patch trail in cert.json

Trust-spine identity fields:

  - run_id                     run directory basename
  - git_sha                    HEAD SHA at cert time
  - model_stack                writer/reviewer/judge model identities
  - timestamp_iso              cert time in UTC ISO

Usage:
  python scripts/certification_report.py runs/<run-dir>/full_paper.md
  python scripts/certification_report.py --consecutive run1 run2 [...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.topic_maturity import format_maturity_label

REPO = Path(__file__).resolve().parent.parent
CERTIFICATION_GATE_VERSION = "l6-reproducibility-v1"

# Old-defect scan patterns: known reviewer-detected misreads from
# prior runs that must NOT recur.
_OLD_DEFECT_PATTERNS = [
    # Fix #54 cohort: 0.13 m/s walk-speed parenthetical near
    # threshold-comparison phrasing.
    {
        "id": "walk_speed_parenthetical_threshold",
        "description": (
            "0.13 m/s rendered as walk speed value compared to "
            "0.8 m/s threshold (Fix #54)"
        ),
        "regex": (
            r"this\s+walk\s+speed\s+value\s+is\s+below\s+the\s+0\.8"
        ),
    },
    # Fix #46 cohort: 0.13 m/s rendered as absolute speed below
    # threshold (single-sentence).
    {
        "id": "walk_speed_value_of_0_13",
        "description": (
            "0.13 m/s rendered as absolute speed below the 0.8 m/s "
            "frailty threshold (Fix #37)"
        ),
        "regex": (
            r"value\s+of\s+0\.13\s+m/s.*below\s+the\s+0\.8"
        ),
    },
    # Internal pipeline language leakage.
    {
        "id": "internal_run_tag_in_prose",
        "description": (
            "Internal run tag ('synthesis-metformin-v06-...') leaked "
            "into rendered prose body (should be in supplement only)"
        ),
        # Matches both raw 'Submission:' and markdown-bolded
        # '**Submission:**' headers above a backticked run tag.
        "regex": r"Submission:\*?\*?\s*`?synthesis-",
    },
]


@dataclass(frozen=True, slots=True)
class CertificationVerdict:
    """A single-run cert verdict. Promoted to ResearkaCertifiedAAA
    only when *every* criterion is True AND a second consecutive
    AAA run is paired."""
    run_id: str
    git_sha: str
    timestamp_iso: str
    final_verdict: str  # AAA / Trust-Spine Pass / etc.
    aaa_pass: bool
    q2_traceability_pct: float  # 0-100
    q2_full: bool
    stage1_pass_rate: str  # "13/13"
    stage2_p1: int
    stage2_p2: int
    stage2_clean: bool
    grok_unresolved_p1: int
    grok_clean: bool
    no_regression_pass: bool
    old_defect_scan_clean: bool
    old_defect_hits: list[dict[str, str]] = field(default_factory=list)
    applied_patches: int = 0
    repaired_patches: int = 0
    auto_stripped_patches: int = 0
    rejected_patches: int = 0
    flagged_patches: int = 0
    word_count: int = 0
    cost_usd: float = 0.0
    model_stack: dict[str, str] = field(default_factory=dict)
    topic: str | None = None
    journal_surface_pass: bool = True
    certification_gate_version: str = CERTIFICATION_GATE_VERSION

    @property
    def aaa_certified(self) -> bool:
        """All single-run criteria pass — but not yet "consecutive."""
        return (
            self.aaa_pass
            and self.q2_full
            and self.stage2_clean
            and self.grok_clean
            and self.no_regression_pass
            and self.old_defect_scan_clean
        )

    @property
    def l5_certified(self) -> bool:
        """Single-run Journal-Ready cert: AAA plus no strip/flag scars."""
        return (
            self.aaa_certified
            and self.auto_stripped_patches == 0
            and self.flagged_patches == 0
        )

    @property
    def l6_eligible(self) -> bool:
        """Topic-level L6 candidate: clean L5 plus journal surface pass."""
        return self.l5_certified and self.journal_surface_pass


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _git_head_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, text=True, timeout=5,
        ).strip()
        return out
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def _scan_old_defects(paper_md: str) -> list[dict[str, str]]:
    """Return list of {id, description, sample} for each defect
    pattern that matches the paper. Empty list = clean."""
    import re as _re
    hits: list[dict[str, str]] = []
    for pattern in _OLD_DEFECT_PATTERNS:
        m = _re.search(pattern["regex"], paper_md, _re.IGNORECASE)
        if m:
            sample = paper_md[
                max(0, m.start() - 30):min(len(paper_md), m.end() + 80)
            ].replace("\n", " ").strip()
            hits.append({
                "id": pattern["id"],
                "description": pattern["description"],
                "sample": sample[:200],
            })
    return hits


def _parse_q2_pct(audit_json: dict) -> tuple[float, bool]:
    """Pull numeric traceability % from audit checks. Returns
    (percentage, is_100_percent)."""
    for check in audit_json.get("checks", []):
        if check.get("name") != "Q2_numeric_integrity":
            continue
        detail = check.get("detail", "")
        # detail format: "38/38 numerics trace to corpus (100%); ..."
        import re as _re
        m = _re.search(r"\((\d+)%\)", detail)
        if m:
            pct = float(m.group(1))
            return pct, pct >= 100.0
    return 0.0, False


def _count_patches(patch_log_json: dict) -> dict[str, int]:
    """Count patches by status. Reads from
    full_paper.review_patch_log.json (orchestrator writes summary
    counts as n_applied / n_rejected / n_flagged / n_auto_stripped).
    'repaired' is counted by scanning per-patch decision strings for
    'applied_via_repair'."""
    counts = {
        "applied": 0,
        "repaired": 0,
        "auto_stripped": 0,
        "rejected": 0,
        "flagged": 0,
    }
    if not patch_log_json:
        return counts
    counts["applied"] = int(patch_log_json.get("n_applied", 0))
    counts["rejected"] = int(patch_log_json.get("n_rejected", 0))
    counts["flagged"] = int(patch_log_json.get("n_flagged", 0))
    counts["auto_stripped"] = int(
        patch_log_json.get("n_auto_stripped", 0)
    )
    # Repaired patches are a sub-count of applied — scan decisions
    for p in patch_log_json.get("patches", []):
        decision = (p.get("decision") or "").lower()
        if "repair" in decision:
            counts["repaired"] += 1
    return counts


def certify_run(paper_md_path: Path) -> CertificationVerdict:
    """Build a CertificationVerdict for a single synthesis run.
    Reads the run's audit, consistency, verdict, manifest, and patch
    artifacts. No LLM calls."""
    paper_md = paper_md_path.read_text()
    run_dir = paper_md_path.parent
    audit = _read_json(paper_md_path.with_suffix(".audit.json")) or {}
    verdict_doc = _read_json(
        paper_md_path.with_suffix(".final_verdict.json")
    ) or {}
    consistency = _read_json(
        paper_md_path.with_suffix(".consistency.json")
    ) or []
    if not isinstance(consistency, list):
        consistency = consistency.get("issues", []) if isinstance(
            consistency, dict
        ) else []
    # Patch summary is in review_patch_log.json (orchestrator-
    # written summary), not review_patches.json (raw Grok output).
    patch_log = _read_json(
        paper_md_path.with_suffix(".review_patch_log.json")
    ) or {}
    manifest = _read_json(run_dir / "manifest.json") or {}
    no_reg_report = _read_json(
        run_dir / "no_regression_report.json"
    ) or {}

    # Pull verdict signals
    final_verdict = verdict_doc.get("verdict", "Unknown")
    aaa_pass = final_verdict == "AAA"
    stage1_pass_rate = verdict_doc.get(
        "stage1_pass_rate", "?/?",
    )
    stage2_p1 = int(verdict_doc.get("stage2_p1", 0))
    stage2_p2 = int(verdict_doc.get("stage2_p2", 0))
    grok_unresolved = int(
        verdict_doc.get("grok_unresolved_p1", 0)
    )
    # No-regression report uses 'passes' (boolean) not 'verdict'.
    # Edge: a fresh run before a baseline exists registers no file.
    if not no_reg_report:
        no_regression_pass = True
    else:
        no_regression_pass = bool(no_reg_report.get("passes", False))

    q2_pct, q2_full = _parse_q2_pct(audit)
    p_counts = _count_patches(patch_log)
    defect_hits = _scan_old_defects(paper_md)

    # Cost: orchestrator writes total_cost_usd to manifest (writer
    # only); patch_log adds cost_usd (Grok review). Sum both.
    writer_cost = float(manifest.get("total_cost_usd", 0.0))
    patches_raw = _read_json(
        paper_md_path.with_suffix(".review_patches.json")
    ) or {}
    review_cost = float(patches_raw.get("cost_usd", 0.0))
    cost_usd = writer_cost + review_cost
    word_count = int(manifest.get("total_words", 0)) or len(
        paper_md.split()
    )

    # Model stack: read from run_metadata if present, else default
    model_stack = manifest.get("model_stack", {})
    if not model_stack:
        model_stack = {
            "writer": "MiMo-VL-7B-RL-2508",
            "reviewer": "Grok-4.3-Reasoning",
            "extractor": "MiMo-VL-7B-RL-2508",
        }
    topic = manifest.get("topic") or verdict_doc.get("topic")
    gate_version = (
        verdict_doc.get("certification_gate_version")
        or manifest.get("certification_gate_version")
        or CERTIFICATION_GATE_VERSION
    )

    return CertificationVerdict(
        run_id=run_dir.name,
        git_sha=_git_head_sha(),
        timestamp_iso=datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        final_verdict=final_verdict,
        aaa_pass=aaa_pass,
        q2_traceability_pct=q2_pct,
        q2_full=q2_full,
        stage1_pass_rate=stage1_pass_rate,
        stage2_p1=stage2_p1,
        stage2_p2=stage2_p2,
        stage2_clean=(stage2_p1 == 0 and stage2_p2 == 0),
        grok_unresolved_p1=grok_unresolved,
        grok_clean=(grok_unresolved == 0),
        no_regression_pass=no_regression_pass,
        old_defect_scan_clean=(len(defect_hits) == 0),
        old_defect_hits=defect_hits,
        applied_patches=p_counts["applied"],
        repaired_patches=p_counts["repaired"],
        auto_stripped_patches=p_counts["auto_stripped"],
        rejected_patches=p_counts["rejected"],
        flagged_patches=p_counts["flagged"],
        word_count=word_count,
        cost_usd=cost_usd,
        model_stack=model_stack,
        topic=str(topic) if topic else None,
        journal_surface_pass=bool(
            verdict_doc.get(
                "journal_surface_pass",
                verdict_doc.get("journal_ready", True),
            )
        ),
        certification_gate_version=str(gate_version),
    )


def certify_consecutive(
    paper_md_paths: list[Path],
) -> dict[str, Any]:
    """Topic-level L6 gate over the latest chronological adjacent pair."""
    per_run = [certify_run(p) for p in paper_md_paths]
    blockers = _l6_blockers(per_run)
    if len(per_run) < 2:
        return _consecutive_result(per_run, None, blockers)
    sorted_runs = sorted(
        zip(paper_md_paths, per_run), key=lambda x: _run_sort_key(x[0])
    )
    selected = [r for _, r in sorted_runs[-2:]]
    blockers.extend(_pair_blockers(selected))
    return _consecutive_result(per_run, selected, blockers)


def _consecutive_result(
    per_run: list[CertificationVerdict],
    selected_pair: list[CertificationVerdict] | None,
    blockers: list[str],
) -> dict[str, Any]:
    pair = selected_pair or []
    structural_blocked = any(
        b.startswith(("need >=2", "mixed topics", "mixed certification"))
        for b in blockers
    )
    all_pass = (
        bool(pair) and not structural_blocked
        and all(r.aaa_certified for r in pair)
    )
    l6_ready = bool(pair) and not blockers and all(r.l6_eligible for r in pair)
    maturity_level = 6 if l6_ready else 5 if all_pass else 0
    failures = [
        {"run_id": r.run_id, "reason": _failure_reasons(r)}
        for r in pair if not r.aaa_certified
    ]
    gate_version = _common_gate_version(pair or per_run)
    return {
        "certified": all_pass,
        "n_runs": len(per_run),
        "reason": blockers[0] if blockers else "",
        "n_aaa_certified": sum(r.aaa_certified for r in per_run),
        "n_l5_certified": sum(r.l5_certified for r in per_run),
        "all_aaa_consecutive": all_pass,
        "l6_reproducibly_journal_ready": l6_ready,
        "selected_pair": [r.run_id for r in pair],
        "l6_blockers": blockers,
        "certification_gate_version": gate_version,
        "maturity_level": maturity_level,
        "maturity_label": format_maturity_label(maturity_level),
        "git_sha": _git_head_sha(),
        "timestamp_iso": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "failures": failures,
        "runs": [asdict(r) for r in per_run],
    }


def _l6_blockers(runs: list[CertificationVerdict]) -> list[str]:
    blockers: list[str] = []
    if len(runs) < 2:
        blockers.append(f"need >=2 runs; only {len(runs)} provided")
        return blockers
    topics = {r.topic for r in runs if r.topic}
    if len(topics) > 1:
        blockers.append("mixed topics: " + ", ".join(sorted(topics)))
    gate_versions = {r.certification_gate_version for r in runs}
    if len(gate_versions) > 1:
        blockers.append(
            "mixed certification gates: "
            + ", ".join(sorted(gate_versions))
        )
    return blockers


def _pair_blockers(pair: list[CertificationVerdict]) -> list[str]:
    blockers: list[str] = []
    for r in pair:
        prefix = f"{r.run_id}: "
        if not r.aaa_certified:
            blockers.append(prefix + "; ".join(_failure_reasons(r)))
        if r.grok_unresolved_p1:
            blockers.append(prefix + "unresolved Grok P1")
        if r.auto_stripped_patches:
            blockers.append(prefix + "auto-stripped patches")
        if not r.journal_surface_pass:
            blockers.append(prefix + "journal surface failed")
    return blockers


def _common_gate_version(runs: list[CertificationVerdict]) -> str:
    versions = {r.certification_gate_version for r in runs}
    if len(versions) == 1:
        return next(iter(versions))
    return CERTIFICATION_GATE_VERSION


def _run_sort_key(path: Path) -> str:
    run_dir = path.parent
    for candidate in (run_dir / "manifest.json", path.with_suffix(
        ".final_verdict.json"
    )):
        doc = _read_json(candidate) or {}
        for key in ("generated_at", "timestamp_iso", "timestamp"):
            if doc.get(key):
                return str(doc[key])
    import re as _re
    match = _re.search(
        r"20\d\d-\d\d-\d\dT\d\d[-:]\d\d[-:]\d\dZ?", run_dir.name
    )
    if match:
        return match.group(0).replace("-", ":", 2)
    return run_dir.name


def _failure_reasons(v: CertificationVerdict) -> list[str]:
    reasons: list[str] = []
    if not v.aaa_pass:
        reasons.append(
            f"final_verdict={v.final_verdict!r} (need AAA)"
        )
    if not v.q2_full:
        reasons.append(
            f"Q2_traceability={v.q2_traceability_pct}% (need 100%)"
        )
    if not v.stage2_clean:
        reasons.append(
            f"stage2 P1={v.stage2_p1} P2={v.stage2_p2} (need 0/0)"
        )
    if not v.grok_clean:
        reasons.append(
            f"grok_unresolved_p1={v.grok_unresolved_p1} (need 0)"
        )
    if not v.no_regression_pass:
        reasons.append("no_regression_gate failed")
    if not v.old_defect_scan_clean:
        reasons.append(
            f"old_defect_scan: {len(v.old_defect_hits)} hit(s) — "
            + ", ".join(h["id"] for h in v.old_defect_hits)
        )
    return reasons


def write_certification(
    paper_md_path: Path, verdict: CertificationVerdict,
) -> tuple[Path, Path]:
    """Write the JSON + MD cert artifacts next to the paper.
    Returns (json_path, md_path)."""
    json_path = paper_md_path.with_suffix(".certification.json")
    md_path = paper_md_path.with_suffix(".certification.md")
    json_path.write_text(json.dumps(asdict(verdict), indent=2))
    md_path.write_text(_format_certification_md(verdict))
    return json_path, md_path


def _format_certification_md(v: CertificationVerdict) -> str:
    """Human-readable cert page (Markdown). Includes the 'public
    error surface' (patch trail) per Researka manifesto."""
    badge = (
        "Researka Certified A2A-AAA (single-run pending consecutive)"
        if v.aaa_certified else
        "NOT CERTIFIED — see failure reasons below"
    )
    lines = [
        f"# {badge}",
        "",
        f"**Run ID:** `{v.run_id}`",
        f"**Git SHA:** `{v.git_sha}`",
        f"**Certified at:** {v.timestamp_iso}",
        f"**Final verdict:** {v.final_verdict}",
        "",
        "## Trust-Spine Criteria",
        "",
        f"- AAA verdict: {'✅' if v.aaa_pass else '❌'}",
        f"- Q2 numeric traceability: {v.q2_traceability_pct}% "
        f"({'✅' if v.q2_full else '❌'})",
        f"- Stage-1 audit: {v.stage1_pass_rate}",
        f"- Stage-2 consistency: P1={v.stage2_p1} P2={v.stage2_p2} "
        f"({'✅' if v.stage2_clean else '❌'})",
        f"- Grok unresolved P1: {v.grok_unresolved_p1} "
        f"({'✅' if v.grok_clean else '❌'})",
        f"- No-regression gate: "
        f"{'PASS ✅' if v.no_regression_pass else 'FAIL ❌'}",
        f"- Old-defect scan: "
        f"{'CLEAN ✅' if v.old_defect_scan_clean else 'HITS ❌'}",
    ]
    if v.old_defect_hits:
        lines.append("")
        lines.append("### Old-defect scan hits")
        for h in v.old_defect_hits:
            lines.append(f"- **{h['id']}**: {h['description']}")
            lines.append(f"  - sample: `{h['sample']}`")

    if not v.aaa_certified:
        lines.append("")
        lines.append("## Failure Reasons")
        for r in _failure_reasons(v):
            lines.append(f"- {r}")

    lines += [
        "",
        "## Public Error Surface (Patch Trail)",
        "",
        f"- Patches applied: {v.applied_patches}",
        f"- Patches repaired (via repair loop): {v.repaired_patches}",
        f"- Patches auto-stripped (smart-gate fallback): "
        f"{v.auto_stripped_patches}",
        f"- Patches rejected: {v.rejected_patches}",
        f"- Patches flagged for manual review: {v.flagged_patches}",
        "",
        "Every reviewer intervention is logged. Inspect "
        "`full_paper.review_patches.json` for the full trail.",
        "",
        "## Run Metadata",
        "",
        f"- Word count: {v.word_count}",
        f"- Cost (USD): ${v.cost_usd:.4f}",
        "",
        "### Model Stack",
        "",
    ]
    for role, model in sorted(v.model_stack.items()):
        lines.append(f"- {role}: `{model}`")

    lines += [
        "",
        "## What This Certification Means",
        "",
        "This is a single-run cert. The full Researka A2A-AAA seal "
        "requires ≥2 consecutive AAA runs (run "
        "`scripts/certification_report.py --consecutive run1 run2`). "
        "The trust-spine architecture (LLM proposes, code disposes) "
        "ensures that every claim, citation, and numeric in this "
        "paper traces to the source corpus AND survives an "
        "adversarial review pass with logged interventions.",
        "",
        "## What This Certification Does NOT Mean",
        "",
        "- This is NOT a peer-reviewed publication.",
        "- This is NOT a definitive review of the topic.",
        "- This IS a demonstration that an autonomous agent-to-"
        "agent pipeline can produce a traceable, reviewer-"
        "constrained synthesis whose error surface is publicly "
        "inspectable.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Researka Certified A2A-AAA — cert generator",
    )
    parser.add_argument(
        "paper_md", nargs="?",
        help="full_paper.md path (single-run cert mode)",
    )
    parser.add_argument(
        "--consecutive", nargs="+",
        help="≥2 paper_md paths for the consecutive-AAA gate",
    )
    args = parser.parse_args(argv)

    if args.consecutive:
        paths = [Path(p).resolve() for p in args.consecutive]
        for p in paths:
            if not p.exists():
                print(f"not found: {p}", file=sys.stderr)
                return 2
        result = certify_consecutive(paths)
        print(json.dumps(result, indent=2))
        return 0 if result["certified"] else 1

    if not args.paper_md:
        parser.error("either paper_md or --consecutive required")
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    verdict = certify_run(paper_path)
    json_path, md_path = write_certification(paper_path, verdict)
    print(
        f"Certification written:\n  {json_path}\n  {md_path}",
        file=sys.stderr,
    )
    if verdict.aaa_certified:
        print(
            "✅ Researka Certified A2A-AAA (single-run; pending "
            "consecutive)",
            file=sys.stderr,
        )
        return 0
    print(
        "❌ NOT certified — see cert.md for failure reasons",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
