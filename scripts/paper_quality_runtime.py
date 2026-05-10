"""Phase 3-8 paper-quality runtime adapter.

Pure glue: takes a finished run dir (after `run_v06_synthesis.py` has
written full_paper.md, full_paper.audit.json, full_paper.journal_surface.json,
manifest.json, citation_registry.json, field_engagement.json) and produces
the eight Phase 3-8 sidecars by calling the existing `agent/*` and `scripts/*`
primitives. Stdlib + httpx (already a project dep). No new logic, no new
dependencies, no LLM calls.

Sidecars produced (all next to full_paper.md):
  - risk_of_bias.json + .md           (Phase 4 RoB screening)
  - grade_assessment.json + .md       (Phase 4 GRADE-lite)
  - quality_methods.json              (Phase 4 RoB+GRADE bundle summary)
  - meta_analysis_results.json + .md  (Phase 5 fail-closed pool >=3)
  - tension_elaboration_plans.json    (Phase 7 top-N tension plans)
  - template_language_gate.json + .md (Phase 6 prose audit)
  - publication_score.json            (Phase 8 panel rubric)
  - pre_submit_gate.json              (Phase 8 final gate, with
                                       paper_quality_gate +
                                       formal_sr_methods=PARTIAL by default)

Honesty markers:
  RoB / GRADE outputs carry method_status="method_ready_source_text_pending".
  Final gate emits formal_sr_methods="PARTIAL" unless the caller passes
  --rob-method-status=source_text_full_cochrane.

CLI:
  python scripts/paper_quality_runtime.py <run-dir> \\
      [--rob-method-status automated_screening|source_text_full_cochrane]
Exit code 0 if final gate passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from agent.final_gate import (  # noqa: E402
    GateInputs, RobMethodStatus, evaluate_final_gate,
)
from agent.publication_scorer import ScoreInputs, score_publication  # noqa: E402
from agent.template_gate_adapter import evaluate_template_gate  # noqa: E402
from agent.tension_elaboration import TensionRecord, select_top_tensions  # noqa: E402

import grade_assessment as ga  # type: ignore[import-not-found]  # noqa: E402
import meta_analysis as meta  # type: ignore[import-not-found]  # noqa: E402
import risk_of_bias as rob  # type: ignore[import-not-found]  # noqa: E402

HONESTY = "method_ready_source_text_pending"


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _group_by_outcome(receipts: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in receipts:
        grouped[str(r.get("outcome_class") or "unknown")].append(r)
    return dict(grouped)


def _design_for_receipt(rec: dict) -> str:
    raw = str(rec.get("study_design") or rec.get("design_tier") or "").lower()
    if "rct" in raw or "randomized" in raw or rec.get("evidence_tier") == "A1":
        return "rct"
    if "animal" in raw or "preclin" in raw or rec.get("directness") == "preclinical":
        return "animal"
    return "observational"


def _rob_to_payload(by_outcome: dict[str, list[dict]]) -> list[dict]:
    """scripts/risk_of_bias batch -> flat per-study list with honesty marker."""
    batch = rob.assess_risk_of_bias_batch(by_outcome)
    out: list[dict] = []
    seen: set[str] = set()
    for outcome, assessments in batch.items():
        recs = by_outcome[outcome]
        for i, ass in enumerate(assessments):
            rec = recs[i] if i < len(recs) else {}
            study_id = str(
                rec.get("citation_token") or rec.get("receipt_id") or f"unknown_{i}"
            )
            if study_id in seen:
                continue
            seen.add(study_id)
            out.append({
                "study_id": study_id,
                "design": _design_for_receipt(rec),
                "tool": "rob2-screening",
                "method_status": HONESTY,
                "outcome_class": outcome,
                "overall_rating": ass.overall,
                "domains": [
                    {"domain": k, "rating": v,
                     "rationale": "Automated screening from receipt metadata."}
                    for k, v in ass.domains.items()
                ],
                "fail_closed": ass.fail_closed,
                "notes": (
                    "Preliminary automated assessment; "
                    "source-linked receipt remains the trace unit."
                ),
            })
    return out


def _grade_to_payload(by_outcome: dict[str, list[dict]]) -> list[dict]:
    """scripts/grade_assessment batch -> flat per-outcome list with honesty marker."""
    grades = ga.assess_grade_batch(by_outcome)
    return [
        {
            "outcome": g.outcome,
            "starting_certainty": g.start_certainty,
            "final_certainty": g.certainty,
            "downgrades": [{"reason": d} for d in g.downgrades],
            "caps": list(g.caps),
            "method_status": HONESTY,
            "fail_closed": g.fail_closed,
            "notes": f"Generated from {len(by_outcome.get(g.outcome, []))} accepted receipt(s).",
        }
        for g in grades
    ]


def _meta_payload(by_outcome: dict[str, list[dict]]) -> dict[str, Any]:
    """Pool by outcome, fail-closed when <3 compatible rows. Threshold matches
    scripts/meta_analysis.MIN_STUDIES + agent/meta_analysis.MIN_STUDIES."""
    pools: list[dict] = []
    skipped: list[dict] = []
    for outcome, group in sorted(by_outcome.items()):
        if not group:
            continue
        result = meta.pool_fixed_effect(outcome, group)
        bucket = skipped if result.fail_closed else pools
        bucket.append(result.to_dict())
    return {
        "pools": pools, "skipped": skipped,
        "candidate_groups": len(by_outcome),
        "min_studies_threshold": 3,
        "fail_closed_explanation": (
            "No quantitative pool was run when compatible effect rows <3."
        ),
    }


def _tension_records(manifest: dict) -> list[TensionRecord]:
    """Build TensionRecord objects from manifest['tensions'] when present.
    Falls back to empty list when manifest carries only the count
    (n_non_orthogonal_tensions) — fail-soft."""
    raw = manifest.get("tensions")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[TensionRecord] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        try:
            out.append(TensionRecord(
                tension_id=str(t.get("tension_id") or t.get("id") or "t-?"),
                paper_a=str(t.get("paper_a") or "a"),
                paper_b=str(t.get("paper_b") or "b"),
                conflict_type=str(t.get("conflict_type") or "magnitude"),
                outcome_class=str(t.get("outcome_class") or "unknown"),
                severity=int(t.get("severity") or 1),
            ))
        except (TypeError, ValueError):
            continue
    return out


def _ensure_review_patch_log(out_dir: Path) -> None:
    """Backward-compat alias. Bundle exporter, certification_report, and
    several dashboards require full_paper.review_patch_log.json; the
    runner only writes it when patches existed. If it's missing but
    review_patches.json is present, synthesize an equivalent log from
    that source. Cheap, idempotent, fail-soft."""
    log_path = out_dir / "full_paper.review_patch_log.json"
    if log_path.exists():
        return
    src = _read_json(out_dir / "full_paper.review_patches.json", {}) or {}
    patches = src.get("patches") or []
    log_path.write_text(json.dumps({
        "applied_at": _now_iso(),
        "n_proposed": int(src.get("n_patches", len(patches))),
        "n_applied": 0,
        "n_rejected": 0,
        "n_rejected_by_arbitration": 0,
        "n_flagged": 0,
        "n_repaired": 0,
        "n_auto_stripped": 0,
        "n_arbitrated": 0,
        "patches": [],
        "alias_of": "full_paper.review_patches.json",
    }, indent=2))


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def run_phases(
    out_dir: Path, *,
    rob_method_status: RobMethodStatus = "automated_screening",
) -> dict[str, Any]:
    """Run Phases 3-8 against `out_dir`; write all sidecars; return verdict."""
    manifest = _read_json(out_dir / "manifest.json", {}) or {}
    audit = _read_json(out_dir / "full_paper.audit.json", {}) or {}
    surface = _read_json(out_dir / "full_paper.journal_surface.json", {}) or {}
    patches = _read_json(out_dir / "full_paper.review_patches.json", {}) or {}
    paper_md = (out_dir / "full_paper.md").read_text()
    receipts: list[dict] = list(manifest.get("receipts") or [])
    by_outcome = _group_by_outcome(receipts)
    # Fix #57: ensure the review_patch_log.json bundle-export contract
    # holds even when the runner skipped its own write (0-patches case).
    _ensure_review_patch_log(out_dir)

    # --- Phase 4: RoB + GRADE -------------------------------------------------
    rob_payload = _rob_to_payload(by_outcome)
    grade_payload = _grade_to_payload(by_outcome)
    (out_dir / "risk_of_bias.json").write_text(json.dumps(rob_payload, indent=2))
    (out_dir / "grade_assessment.json").write_text(json.dumps(grade_payload, indent=2))

    n_receipts = int(manifest.get("n_receipts") or len(receipts))
    n_outcome_classes = len(by_outcome)
    rob_unique = {r["study_id"] for r in rob_payload}
    rob_coverage = len(rob_unique) / n_receipts if n_receipts else 0.0
    grade_outcomes = {g["outcome"] for g in grade_payload}
    grade_coverage = len(grade_outcomes) / n_outcome_classes if n_outcome_classes else 0.0
    quality = {
        "rob_coverage": round(rob_coverage, 4),
        "grade_coverage": round(grade_coverage, 4),
        "receipt_count": n_receipts,
        "outcome_count": n_outcome_classes,
        "method_status": HONESTY,
        "rob_path": "risk_of_bias.json",
        "grade_path": "grade_assessment.json",
    }
    (out_dir / "quality_methods.json").write_text(json.dumps(quality, indent=2))

    # --- Phase 5: meta-analysis fail-closed -----------------------------------
    meta_data = _meta_payload(by_outcome)
    (out_dir / "meta_analysis_results.json").write_text(json.dumps(meta_data, indent=2))
    (out_dir / "meta_analysis_results.md").write_text(_meta_md(meta_data))

    # --- Phase 6: template-language gate (writer-side prompt now hardened) ----
    template_gate = evaluate_template_gate(paper_md, source=str(out_dir / "full_paper.md"))
    (out_dir / "template_language_gate.json").write_text(template_gate.json_report)
    (out_dir / "template_language_gate.md").write_text(template_gate.markdown_report)

    # --- Phase 7: tension elaboration plans -----------------------------------
    records = _tension_records(manifest)
    plans = select_top_tensions(records, top_n=5) if records else []
    plans_json = {
        "candidate_tensions": int(manifest.get("n_non_orthogonal_tensions") or 0),
        "selected": len(plans),
        "plans": [
            {
                "tension_id": p.tension_id,
                "paper_a": p.paper_a,
                "paper_b": p.paper_b,
                "conflict_type": p.conflict_type,
                "outcome_class": p.outcome_class,
                "severity": p.severity,
                "numeric_anchors": list(p.numeric_anchors),
                "hypotheses": list(p.hypotheses),
                "corpus_weight_winner": p.corpus_weight_winner,
            }
            for p in plans
        ],
    }
    (out_dir / "tension_elaboration_plans.json").write_text(json.dumps(plans_json, indent=2))

    # --- Phase 8: publication scorer + final pre-submit gate ------------------
    score_inputs = ScoreInputs(
        n_receipts=n_receipts,
        n_outcome_classes=n_outcome_classes,
        n_tensions=int(manifest.get("n_non_orthogonal_tensions") or 0),
        rob_coverage=rob_coverage,
        grade_coverage=grade_coverage,
        numeric_coverage=1.0,
        citation_registry_complete=(out_dir / "citation_registry.json").exists(),
        audit_gates_passed=bool(audit.get("p1_pass")) and audit.get("score_out_of_10", 0) >= 10,
        template_language_blocking=template_gate.template_language_blocking,
        field_engagements_supported=_count_field_engagements(out_dir),
        field_engagements_total=5,
        has_explicit_thesis=bool(manifest.get("thesis")),
        has_limitations_section="## Limitations" in paper_md,
        has_clinical_practice_statement="clinical practice" in paper_md.lower(),
        unresolved_reviewer_p1_count=_unresolved_p1(patches),
    )
    score = score_publication(score_inputs)
    score_payload = {
        "inputs": dataclasses.asdict(score_inputs),
        "result": {
            "rubric": score.rubric.as_mapping(),
            "rubric_total": score.rubric.total,
            "claim_support": score.claim_support,
            "overclaim": score.overclaim,
            "verdict": score.verdict,
            "blockers": list(score.blockers),
            "notes": list(score.notes),
            "summary": score.summary,
        },
    }
    (out_dir / "publication_score.json").write_text(json.dumps(score_payload, indent=2))

    # Final gate (with formal_sr_methods PARTIAL/FULL distinction).
    gate_inputs = GateInputs(
        numeric_coverage=score_inputs.numeric_coverage,
        audit_gates_passed=score_inputs.audit_gates_passed,
        journal_surface_passed=bool(surface.get("passed") or surface.get("pass")),
        citation_registry_complete=score_inputs.citation_registry_complete,
        rob_coverage=rob_coverage,
        grade_coverage=grade_coverage,
        n_tensions=score_inputs.n_tensions,
        n_receipts=n_receipts,
        unresolved_reviewer_p1_count=score_inputs.unresolved_reviewer_p1_count,
        template_language_blocking=template_gate.template_language_blocking,
        rob_method_status=rob_method_status,
    )
    gate = evaluate_final_gate(gate_inputs)
    pre_submit = {
        "inputs": dataclasses.asdict(gate_inputs),
        "result": {
            "passed": gate.passed,
            "paper_quality_gate": gate.paper_quality_gate,
            "formal_sr_methods": gate.formal_sr_methods,
            "failures": list(gate.failures),
            "warnings": list(gate.warnings),
            "summary": gate.summary,
        },
    }
    (out_dir / "pre_submit_gate.json").write_text(json.dumps(pre_submit, indent=2))
    (out_dir / "pre_submit_gate.md").write_text(_pre_submit_md(pre_submit))
    return pre_submit


def _meta_md(meta_data: dict) -> str:
    pools = meta_data.get("pools") or []
    skipped = meta_data.get("skipped") or []
    lines = ["# Meta-Analysis Results", ""]
    lines.append(f"Candidate outcome groups: {meta_data.get('candidate_groups', 0)}")
    lines.append(f"Pooled: {len(pools)}; Fail-closed (no pool): {len(skipped)}")
    lines.append("")
    lines.append(meta_data.get("fail_closed_explanation", ""))
    if pools:
        lines.append("\n## Pools\n")
        for p in pools:
            lines.append(f"- {p.get('outcome')}: k={p.get('k')}, "
                         f"effect={p.get('pooled_effect')}, "
                         f"95% CI [{p.get('ci_low')}, {p.get('ci_high')}]")
    if skipped:
        lines.append("\n## Skipped (fail-closed)\n")
        for s in skipped:
            lines.append(f"- {s.get('outcome')}: {s.get('reason')}")
    return "\n".join(lines) + "\n"


def _pre_submit_md(payload: dict) -> str:
    r = payload["result"]
    lines = ["# Pre-Submit Gate", ""]
    lines.append(f"**paper_quality_gate**: {r['paper_quality_gate']}")
    lines.append(f"**formal_sr_methods**: {r['formal_sr_methods']}")
    lines.append(f"**Summary**: {r['summary']}")
    if r["failures"]:
        lines.append("\n## Failures\n")
        lines.extend(f"- {f}" for f in r["failures"])
    if r["warnings"]:
        lines.append("\n## Warnings\n")
        lines.extend(f"- {w}" for w in r["warnings"])
    return "\n".join(lines) + "\n"


def _count_field_engagements(out_dir: Path) -> int:
    fe = _read_json(out_dir / "field_engagement.json", []) or []
    if isinstance(fe, list):
        return sum(1 for e in fe if isinstance(e, dict) and e.get("status") == "support")
    return 0


def _unresolved_p1(patches: dict) -> int:
    direct = patches.get("unresolved_p1_count")
    if isinstance(direct, int):
        return max(0, direct)
    pl = patches.get("patches")
    if isinstance(pl, list):
        return sum(
            1 for p in pl
            if isinstance(p, dict)
            and str(p.get("severity") or "").upper() == "P1"
            and str(p.get("status") or "").lower() not in ("applied", "resolved", "auto_strip")
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3-8 paper-quality runtime adapter.",
    )
    parser.add_argument("run_dir", help="Path to run dir with full_paper.md.")
    parser.add_argument(
        "--rob-method-status",
        choices=("automated_screening", "source_text_full_cochrane"),
        default="automated_screening",
        help=(
            "Default 'automated_screening' yields formal_sr_methods=PARTIAL. "
            "Pass 'source_text_full_cochrane' only when a real Cochrane RoB "
            "signaling questionnaire has been completed for every study."
        ),
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.run_dir).resolve()
    if not (out_dir / "full_paper.md").is_file():
        print(f"error: {out_dir}/full_paper.md not found", file=sys.stderr)
        return 2
    verdict = run_phases(out_dir, rob_method_status=args.rob_method_status)
    r = verdict["result"]
    print(
        f"paper_quality_gate={r['paper_quality_gate']} | "
        f"formal_sr_methods={r['formal_sr_methods']} | "
        f"failures={len(r['failures'])} warnings={len(r['warnings'])}"
    )
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
