"""Runtime wiring for the paper-quality phases.

This module turns the tested Phase 4-8 primitives into production artifacts:
RoB/GRADE tables, valid meta-analysis pools, tension paragraph plans,
template-language repair/gate reports, final gate, and publication score.

It is deliberately orchestration-only. It does not create new scientific
claims; it renders and gates structured signals already present in receipts,
quant_claims, the citation registry, and audit artifacts.
"""
from __future__ import annotations

import dataclasses
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agent.final_gate import (
    DEFAULT_THRESHOLDS,
    GateResult,
    RECOMMENDED_SOURCE_CITATIONS,
    evaluate_final_gate,
    landscape_thresholds,
)
from agent.final_gate_mapper import build_gate_inputs
from agent.forest_plot_svg import render_forest_plot_svg
from agent.meta_analysis import EffectRow, pool_random_effects
from agent.publication_scorer import ScoreInputs, score_publication
from agent.quality_methods_bundle import build_quality_methods_bundle
from agent.risk_of_bias_schema import DOMAINS_BY_TOOL
from agent.template_gate_adapter import evaluate_template_gate
from agent.tension_elaboration import TensionRecord, select_top_tensions


def _has_clinical_practice_boundary(text: str) -> bool:
    """Recognize an explicit boundary on clinical use without requiring one phrase."""
    practice = r"(?:clinical (?:practice|recommendation)|treatment guideline|off-label)"
    boundary = r"(?:cannot|does not|do not|should not|insufficient to|unsupported for)"
    lower = text.lower()
    return bool(
        re.search(rf"\b{boundary}\b[^.\n]{{0,180}}\b{practice}\b", lower)
        or re.search(
            r"\bnot (?:(?:intended )?(?:for use )?as )?(?:a )?"
            r"(?:clinical recommendation|treatment guideline)\b",
            lower,
        )
    )


def _parsed_text(parsed_dir: Path, paper_id: str) -> str:
    matches = list(parsed_dir.glob(f"{paper_id}.paper_sections.json"))
    if not matches:
        matches = list(parsed_dir.glob(f"{paper_id}*.paper_sections.json"))
    if not matches:
        return ""
    try:
        data = json.loads(matches[0].read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    sections = data.get("sections") if isinstance(data, dict) else None
    if isinstance(sections, dict):
        return "\n".join(str(v) for v in sections.values()).lower()
    return json.dumps(data).lower()


def _design_for_receipt(receipt: dict[str, Any], source_text: str) -> str:
    tier = str(receipt.get("evidence_tier") or "").upper()
    directness = str(receipt.get("directness") or "").lower()
    identity = " ".join(str(receipt.get(k) or "") for k in ("paper_id", "receipt_id")).lower()
    if directness == "mechanistic" or tier.startswith("C") or any(
        token in source_text + " " + identity
        for token in (" mice ", " mouse ", " murine ", " rat ", " drosophila ", " c. elegans ")
    ):
        return "animal"
    if directness == "direct" and tier.startswith("A"):
        return "rct"
    return "observational"


def _rating_for_domain(design: str, domain: str, source_text: str) -> str:
    if design == "rct":
        if domain == "randomization":
            return "low" if "random" in source_text else "some_concerns"
        if domain == "deviations":
            return "low" if "double-blind" in source_text or "placebo" in source_text else "some_concerns"
        if domain in {"missing_data", "selective_reporting"}:
            return "some_concerns"
        return "low" if "blinded" in source_text else "some_concerns"
    if design == "observational":
        if domain == "confounding":
            return "some_concerns"
        if domain == "selection":
            return "some_concerns"
        return "low" if domain in {"intervention_classification", "selective_reporting"} else "some_concerns"
    if domain in {"sequence_generation", "random_housing", "blinding"}:
        return "unclear"
    return "some_concerns"


def _overall(ratings: list[str]) -> str:
    if "high" in ratings:
        return "high"
    if "some_concerns" in ratings or "unclear" in ratings:
        return "some_concerns"
    return "low"


def build_quality_method_payloads(
    receipts: list[dict[str, Any]], parsed_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rob_payload: list[dict[str, Any]] = []
    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        paper_id = str(receipt.get("paper_id") or receipt.get("receipt_id") or "")
        source_text = _parsed_text(parsed_dir, paper_id)
        design = _design_for_receipt(receipt, source_text)
        tool = {"rct": "rob2", "observational": "robins_i", "animal": "syrcle"}[design]
        domains = []
        ratings = []
        for domain in DOMAINS_BY_TOOL[tool]:
            rating = _rating_for_domain(design, domain, source_text)
            ratings.append(rating)
            domains.append({
                "domain": domain,
                "rating": rating,
                "rationale": (
                    f"Automated preliminary rating from accepted receipt metadata "
                    f"(design={design}, tier={receipt.get('evidence_tier')}, "
                    f"directness={receipt.get('directness')})."
                ),
            })
        rob_payload.append({
            "study_id": str(receipt.get("citation_token") or paper_id),
            "design": design,
            "tool": tool,
            "overall_rating": _overall(ratings),
            "domains": domains,
            "notes": "Preliminary automated assessment; source-linked receipt remains the trace unit.",
        })
        by_outcome[str(receipt.get("outcome_class") or "other")].append({
            **receipt, "design": design, "overall_rating": _overall(ratings),
        })

    grade_payload: list[dict[str, Any]] = []
    for outcome, rows in sorted(by_outcome.items()):
        designs = {r["design"] for r in rows}
        directions = {str(r.get("effect_direction") or "unclear").lower() for r in rows}
        directness = {str(r.get("directness") or "").lower() for r in rows}
        start = "high" if "rct" in designs else "low"
        downgrades: list[dict[str, Any]] = []
        if any(r.get("overall_rating") != "low" for r in rows):
            downgrades.append({"reason": "rob", "levels": 1, "rationale": "At least one contributing receipt has non-low automated RoB."})
        if len(directions - {"unclear"}) > 1:
            downgrades.append({"reason": "inconsistency", "levels": 1, "rationale": "Contributing receipts do not share a single effect direction."})
        if directness - {"direct"}:
            downgrades.append({"reason": "indirectness", "levels": 1, "rationale": "Outcome includes indirect or mechanistic receipts."})
        if len(rows) < 3:
            downgrades.append({"reason": "imprecision", "levels": 1, "rationale": "Fewer than three accepted receipts in this outcome class."})
        grade_payload.append({
            "outcome": outcome,
            "starting_certainty": start,
            "downgrades": downgrades,
            "upgrades": [],
            "notes": f"Generated from {len(rows)} accepted receipt(s).",
        })
    return rob_payload, grade_payload


def _write_rob_consistency_sidecar(out_dir: Path, rob_payload: list[dict[str, Any]]) -> None:
    """Advisory: flag any study whose stated overall_rating understates its
    worst domain (RoB worst-domain rule), via the rubric tree. Writes
    rob_consistency.json. Fail-open — never breaks finalize. Currently expected
    to report 0 inconsistent because `_overall` already derives worst-domain;
    it is a forward guard for when independent per-domain ratings feed in."""
    try:
        from agent.risk_of_bias_schema import DomainAssessment, StudyAssessment
        from agent.rob_consistency import inconsistent_studies
        studies = [
            StudyAssessment(
                study_id=s["study_id"], design=s["design"], tool=s["tool"],
                domains=tuple(
                    DomainAssessment(
                        domain=d["domain"], rating=d["rating"],
                        rationale=d.get("rationale", ""),
                    )
                    for d in s["domains"]
                ),
                overall_rating=s["overall_rating"], notes=s.get("notes", ""),
            )
            for s in rob_payload
        ]
        bad = inconsistent_studies(studies)
        payload = {
            "n_studies": len(studies),
            "n_inconsistent": len(bad),
            "inconsistent": [
                {
                    "study_id": r.study_id,
                    "stated_overall": r.stated_rating,
                    "worst_domain": r.worst_domain,
                    "worst_domain_rating": r.worst_domain_rating,
                    "message": r.message,
                }
                for r in bad
            ],
        }
        (out_dir / "rob_consistency.json").write_text(json.dumps(payload, indent=2))
    except Exception:
        # advisory sidecar only — must never block finalize
        pass


def _write_provenance_sidecar(
    out_dir: Path, manifest: dict[str, Any], gate_result: dict[str, Any],
) -> None:
    """Tamper-evident provenance receipt for the shipped paper: binds the
    author/reviewer model families + verdict + SHA-256 of full_paper.md, so a
    reader can re-hash and confirm the artifact is the one that was graded.
    Fail-open; writes provenance.json to the RUN DIR (not the submitted
    bundle, to avoid Researka payload-validation risk)."""
    try:
        from agent.provenance_sidecar import write_provenance_sidecar
        artifact = out_dir / "full_paper.md"
        if not artifact.is_file():
            return
        author_model = "unknown"
        reviewer_models = ["unknown"]
        try:
            from agent.settings import load_settings
            s = load_settings()
            author_model = getattr(s, "minimax_model", "") or "unknown"
            reviewer_models = [
                m for m in (
                    getattr(s, "judge_model", ""),
                    getattr(s, "final_layer_reviewer_model", ""),
                ) if m
            ] or ["unknown"]
        except Exception:
            pass  # model names are best-effort; SHA + verdict still bind
        # Verdict prefers the authoritative Researka readiness field.
        # which is written/reconciled AFTER finalize — so a paper promoted by the
        # post-finalize reconcile is reported correctly. Falls back to the
        # finalize-time gate's `passed` (GateResult has no status/level field)
        # when final_status.json isn't on disk yet; default "blocked" on missing.
        verdict = "ready" if gate_result.get("passed") else "blocked"
        fs_path = out_dir / "final_status.json"
        if fs_path.is_file():
            try:
                fs = json.loads(fs_path.read_text(encoding="utf-8"))
                readiness = (
                    fs.get("researka_publish_ready")
                    if "researka_publish_ready" in fs
                    else fs.get("submission_ready")
                )
                if readiness is not None:
                    verdict = "ready" if readiness else "blocked"
            except (OSError, ValueError):
                pass
        write_provenance_sidecar(
            out_dir,
            run_id=out_dir.name,
            artifact_path=artifact,
            author_model=author_model,
            reviewer_models=reviewer_models,
            verdict=verdict,
            generated_at=str(manifest.get("generated_at") or ""),
        )
    except Exception:
        pass


def write_quality_methods(out_dir: Path, receipts: list[dict[str, Any]], parsed_dir: Path) -> dict[str, Any]:
    rob_payload, grade_payload = build_quality_method_payloads(receipts, parsed_dir)
    outcomes = {str(r.get("outcome_class") or "other") for r in receipts}
    bundle = build_quality_methods_bundle(
        rob_payload=rob_payload,
        grade_payload=grade_payload,
        receipt_count=len(receipts),
        outcome_count=len(outcomes),
    )
    (out_dir / "risk_of_bias.json").write_text(json.dumps(rob_payload, indent=2))
    _write_rob_consistency_sidecar(out_dir, rob_payload)
    (out_dir / "grade_assessment.json").write_text(json.dumps(grade_payload, indent=2))
    (out_dir / "quality_methods.md").write_text(bundle.markdown)
    summary = {
        "rob_coverage": bundle.rob_coverage,
        "grade_coverage": bundle.grade_coverage,
        "receipt_count": bundle.receipt_count,
        "outcome_count": bundle.outcome_count,
        "risk_of_bias_path": "risk_of_bias.json",
        "grade_path": "grade_assessment.json",
        "markdown_path": "quality_methods.md",
    }
    (out_dir / "quality_methods.json").write_text(json.dumps(summary, indent=2))
    return {"bundle": bundle, "summary": summary}


def render_quality_section_for_paper(bundle: Any) -> str:
    has_rob = bool(getattr(bundle, "rob_assessments", ()))
    has_grade = bool(getattr(bundle, "grade_assessments", ()))
    intro = (
        "Risk-of-bias and certainty judgments are generated as structured "
        "sidecars from the accepted receipt set. The manuscript reports the "
        "study-level overall rating and outcome-level certainty label; the "
        "full domain table is preserved in `quality_methods.md`."
        if has_rob or has_grade
        else "No populated public risk-of-bias or GRADE rows were available "
        "for this run. Interpretation therefore remains bounded by source "
        "tier, directness, and receipt traceability rather than formal "
        "RoB/GRADE appraisal."
    )
    lines = [
        "## Risk of Bias and GRADE",
        "",
        intro,
        "",
        "### Risk-of-Bias Summary",
        "",
        "| Study | Tool | Overall rating |",
        "| --- | --- | --- |",
    ]
    for study in bundle.rob_assessments:
        lines.append(f"| {study.study_id} | {study.tool} | {study.overall_rating} |")
    lines.extend([
        "",
        "### GRADE Certainty Summary",
        "",
        "| Outcome | Final certainty | Main downgrade reasons |",
        "| --- | --- | --- |",
    ])
    for grade in bundle.grade_assessments:
        reasons = ", ".join(grade.downgrade_reasons) or "none"
        lines.append(f"| {grade.outcome} | {grade.final_certainty} | {reasons} |")
    return "\n".join(lines).rstrip()


_NUM = r"([-+]?[0-9]+(?:\.[0-9]+)?)"
_CI = r"95%\s*(?:confidence interval|ci)\s*[=:]?\s*[\[\(]?\s*"
_MD_RE = re.compile(
    r"(?:md|mean difference|adjusted mean difference)\s*[=:]\s*"
    + _NUM + r".{0,80}?" + _CI + _NUM + r"\s*(?:to|-|–|—)\s*" + _NUM,
    re.IGNORECASE,
)
_OR_RE = re.compile(
    r"(?:OR|odds ratio)\s*[=:]\s*" + _NUM + r".{0,80}?"
    + _CI + _NUM + r"\s*(?:to|-|–|—)\s*" + _NUM,
    re.IGNORECASE,
)


def _effect_rows_from_claims(receipts: list[dict[str, Any]], quant_dir: Path) -> dict[str, list[EffectRow]]:
    groups: dict[str, dict[str, EffectRow]] = defaultdict(dict)
    z = 1.959963984540054
    for receipt in receipts:
        paper_id = str(receipt.get("paper_id") or "")
        path = quant_dir / f"{paper_id}.quant_claims.json"
        if not path.exists():
            continue
        try:
            claims = json.loads(path.read_text()).get("claims", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        outcome = str(receipt.get("outcome_class") or "other")
        study = str(receipt.get("citation_token") or paper_id)
        for claim in claims:
            text = " ".join(str(claim.get(k) or "") for k in ("raw_text", "sentence"))
            matches = (("MD", _MD_RE.search(text)), ("log_OR", _OR_RE.search(text)))
            for metric, match in matches:
                if not match or study in groups[f"{outcome}:{metric}"]:
                    continue
                effect, lo, hi = (float(v) for v in match.groups())
                if metric == "log_OR":
                    if min(effect, lo, hi) <= 0:
                        continue
                    effect, lo, hi = math.log(effect), math.log(lo), math.log(hi)
                if hi < lo:
                    lo, hi = hi, lo
                se = (hi - lo) / (2 * z)
                if se > 0 and math.isfinite(se):
                    groups[f"{outcome}:{metric}"][study] = EffectRow(study, effect, se, 1, metric)
    return {key: list(value.values()) for key, value in groups.items()}


def write_meta_analysis(out_dir: Path, receipts: list[dict[str, Any]], quant_dir: Path) -> dict[str, Any]:
    rows_by_group = _effect_rows_from_claims(receipts, quant_dir)
    plot_dir = out_dir / "forest_plots"
    plot_dir.mkdir(exist_ok=True)
    pools: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for group, rows in sorted(rows_by_group.items()):
        if len(rows) < 3:
            skipped.append({"group": group, "reason": "fewer_than_three_compatible_studies", "k": len(rows)})
            continue
        pool = pool_random_effects(rows)
        svg = render_forest_plot_svg(rows, pool, title=group)
        plot_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", group).strip("_") + ".svg"
        (plot_dir / plot_name).write_text(svg)
        pools.append({
            "group": group,
            "plot": f"forest_plots/{plot_name}",
            "rows": [dataclasses.asdict(r) for r in rows],
            "pool": dataclasses.asdict(pool),
        })
    result = {"pools": pools, "skipped": skipped, "candidate_groups": len(rows_by_group)}
    (out_dir / "meta_analysis_results.json").write_text(json.dumps(result, indent=2))
    (out_dir / "meta_analysis_results.md").write_text(render_meta_analysis_section(result))
    return result


def render_meta_analysis_section(result: dict[str, Any]) -> str:
    lines = ["## Meta-Analysis Results", ""]
    pools = result.get("pools") or []
    if not pools:
        lines.append(
            "No quantitative pool was run because no outcome class met the "
            "pre-specified requirement for three or more accepted studies with "
            "the same effect metric and confidence-interval shape."
        )
        return "\n".join(lines)
    for pool in pools:
        p = pool["pool"]
        lines.append(f"### {pool['group']}")
        lines.append(
            f"Random-effects pooled effect {p['pooled_effect']:.3f} "
            f"({p['ci_lower']:.3f} to {p['ci_upper']:.3f}); "
            f"I2={p['i_squared']:.1f}%, tau2={p['tau_squared']:.4f}."
        )
        lines.append(f"![Forest plot]({pool['plot']})")
        lines.append("")
    return "\n".join(lines).rstrip()


def _weight(receipt: Any) -> float:
    tier = str(getattr(receipt, "evidence_tier", "")).upper()
    direct = str(getattr(receipt, "directness", "")).lower()
    tier_weight = 3.0 if tier.startswith("A") else 2.0 if tier.startswith("B") else 1.0
    return tier_weight + {"direct": 2.0, "indirect": 1.0, "mechanistic": 0.5}.get(direct, 0.0)


def _tension_directness(value: str) -> str:
    value = value.lower()
    if value in {"direct", "indirect", "mechanistic"}:
        return value
    return "indirect"


def write_tension_plans(out_dir: Path, matrix: Any) -> dict[str, Any]:
    by_id = {r.receipt_id: r for r in matrix.receipts}
    records = []
    outcome_pairs: Counter[str] = Counter()
    for idx, tension in enumerate(matrix.non_orthogonal(), start=1):
        a = by_id.get(tension.receipt_a_id)
        b = by_id.get(tension.receipt_b_id)
        if not a or not b:
            continue
        records.append(TensionRecord(
            tension_id=f"T{idx:03d}",
            paper_a=tension.receipt_a_id,
            paper_b=tension.receipt_b_id,
            conflict_type=tension.kind,
            outcome_class=tension.outcome_class,
            severity=max(1, min(5, int(tension.severity))),
            weight_a=_weight(a),
            weight_b=_weight(b),
            directness_a=_tension_directness(str(a.directness)),
            directness_b=_tension_directness(str(b.directness)),
            numeric_anchors_a=tuple(getattr(a, "p_values", ()) or ()),
            numeric_anchors_b=tuple(getattr(b, "p_values", ()) or ()),
        ))
        outcome_pairs[
            str(a.outcome_class)
            if a.outcome_class == b.outcome_class
            else " <-> ".join(sorted((str(a.outcome_class), str(b.outcome_class))))
        ] += 1
    plans = select_top_tensions(records, top_n=5) if records else []
    n_receipts = len(by_id)
    payload = {
        "plans": [dataclasses.asdict(p) for p in plans],
        "candidate_tensions": len(records),
        "calculation": {
            "unit": "unordered receipt dyad",
            "rule": (
                "Each unordered receipt pair is counted once. A dyad is "
                "non-orthogonal only when the deterministic classifier finds "
                "a directness gap, a mechanism-clinical boundary, or differing "
                "directions on a shared endpoint."
            ),
            "all_dyads": n_receipts * (n_receipts - 1) // 2,
            "non_orthogonal_dyads": len(records),
            "by_outcome": dict(sorted(outcome_pairs.items())),
            "by_conflict_type": dict(sorted(Counter(r.conflict_type for r in records).items())),
        },
    }
    (out_dir / "tension_elaboration_plans.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "tension_elaboration_plans.md").write_text(render_tension_section(payload))
    return payload


def render_tension_section(payload: dict[str, Any]) -> str:
    lines = ["## Cross-Paper Tension Plans", ""]
    calculation = payload.get("calculation") or {}
    if calculation:
        outcomes = ", ".join(
            f"{outcome}={count}"
            for outcome, count in (calculation.get("by_outcome") or {}).items()
        ) or "none"
        lines.extend([
            "### Pairwise Audit",
            str(calculation.get("rule") or ""),
            (
                f"Audited dyads: {calculation.get('all_dyads', 0)} total; "
                f"{calculation.get('non_orthogonal_dyads', 0)} non-orthogonal. "
                f"Per-outcome tally: {outcomes}."
            ),
            "",
        ])
    plans = payload.get("plans") or []
    if not plans:
        lines.append("No non-orthogonal cross-paper tension met the planning threshold.")
        return "\n".join(lines)
    for plan in plans:
        anchors = ", ".join(plan.get("numeric_anchors") or ()) or "no numeric anchor exposed"
        hypotheses = plan.get("hypotheses") or []
        lines.append(f"### {plan['tension_id']}: {plan['outcome_class']}")
        lines.append(f"- Papers: {plan['paper_a']} versus {plan['paper_b']}")
        lines.append(f"- Conflict type: {plan['conflict_type']}; severity {plan['severity']}")
        lines.append(f"- Numeric anchors: {anchors}")
        lines.append(f"- Hypotheses: {'; '.join(hypotheses)}")
        lines.append(f"- Corpus-weight winner: {plan['corpus_weight_winner']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def apply_template_repairs(markdown: str) -> tuple[str, list[dict[str, str]]]:
    replacements = {
        "In conclusion,": "The evidence profile indicates that",
        "In summary,": "The evidence profile indicates that",
        "Further research is needed": "The next decisive test is",
        "This synthesis suggests": "The accepted evidence base supports",
    }
    out = markdown
    log: list[dict[str, str]] = []
    for before, after in replacements.items():
        if before in out:
            out = out.replace(before, after)
            log.append({"before": before, "after": after})
    out, n_ordinal = re.subn(
        r"\bA (?:second|third|fourth|fifth|sixth|seventh|eighth) "
        r"(?=(?:major |critical |cross-domain )?tension)",
        "Another ",
        out,
        flags=re.IGNORECASE,
    )
    if n_ordinal:
        log.append({"before": "ordinal tension opener", "after": "Another"})
    return out, log


def _audit_passed(audit: dict[str, Any]) -> bool:
    return bool(audit.get("p1_pass"))


def _numeric_coverage(audit: dict[str, Any]) -> float:
    for check in audit.get("checks", []):
        if check.get("name") != "Q2_numeric_integrity":
            continue
        match = re.search(r"(\d+)/(\d+)", str(check.get("detail") or ""))
        if match and int(match.group(2)):
            return int(match.group(1)) / int(match.group(2))
    return 1.0 if _audit_passed(audit) else 0.0


def _section_word_count(markdown: str, heading: str) -> int:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\b.*?\n(.*?)(?=^##\s+|\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    return len(re.findall(r"\b\w+\b", match.group(1))) if match else 0


def _readiness_item(
    item_id: int,
    name: str,
    status: str,
    evidence: str,
    next_action: str,
    *,
    advisory: bool = False,
) -> dict[str, Any]:
    from agent.final_status import ADVISORY_READINESS_ITEM_IDS
    advisory = advisory or item_id in ADVISORY_READINESS_ITEM_IDS
    return {
        "id": item_id,
        "name": name,
        "status": status,
        "audit": evidence,
        "advisory": advisory,
        "blocks_submission": status != "pass" and not advisory,
        "next_action": next_action,
    }


def _runtime_integrity_issue(out_dir: Path) -> dict[str, Any] | None:
    path = out_dir / "benchmark_runtime.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "failure_stage": "benchmark_runtime",
            "failure_type": "unreadable_runtime_sidecar",
            "detail": f"benchmark_runtime_unreadable={exc.__class__.__name__}",
            "recoverable": True,
            "artifact_validity": "partial",
            "blocks_submission": True,
        }
    if not payload.get("fresh_run"):
        return None
    if payload.get("timed_out"):
        return {
            "failure_stage": "fresh_run",
            "failure_type": "timeout",
            "detail": "benchmark_runtime_timed_out",
            "recoverable": True,
            "artifact_validity": "partial",
            "blocks_submission": True,
        }
    return_code = payload.get("return_code")
    if return_code != 0:
        return {
            "failure_stage": "fresh_run",
            "failure_type": "nonzero_return_code",
            "detail": f"benchmark_runtime_return_code={return_code}",
            "recoverable": True,
            "artifact_validity": "partial",
            "blocks_submission": True,
        }
    return None


def _gate_with_runtime_integrity(gate: GateResult, runtime_failure: str | None) -> GateResult:
    if not runtime_failure:
        return gate
    failures = gate.failures + (runtime_failure,)
    return GateResult(
        passed=False,
        failures=failures,
        warnings=gate.warnings,
        summary=f"FAIL — {len(failures)} blocker(s): " + "; ".join(failures),
    )


def _accountability_readiness_row(
    accountability_model: str,
    accountability_pass: bool,
    accountability_detail: str,
) -> tuple[int, str, str, str, str]:
    """Item 13 of the readiness contract: accountability-model-aware.

    Universal — researka_agent_certified mode trusts the machine-artifact
    spine (artifact_consistency + citation_registry); legacy mode keeps
    the named-author signoff requirement. Avoids hardcoding human signoff
    as a universal gate when the run is certified agent-native."""
    from agent.accountability import resolve_model
    model = resolve_model(accountability_model)
    if model == "legacy_journal_submission":
        return (
            13, "human_signoff",
            "pass" if accountability_pass else "not_ready",
            accountability_detail
            or "submission requires author/domain-expert approval outside the bot",
            "Collect named author/domain-expert signoff before submission.",
        )
    return (
        13, "accountability",
        "pass" if accountability_pass else "not_ready",
        accountability_detail
        or "researka_agent_certified mode; verify artifact-consistency spine",
        "Restore artifact-consistency spine or citation registry.",
    )


def build_journal_readiness_contract(
    *,
    paper_text: str,
    manifest: dict[str, Any],
    gate: Any,
    score: Any,
    journal_surface: dict[str, Any],
    reviewer_patches: dict[str, Any] | None,
    citation_registry_complete: bool,
    template_language_blocking: bool,
    accountability_model: str = "researka_agent_certified",
    accountability_pass: bool = False,
    accountability_detail: str = "",
) -> list[dict[str, Any]]:
    """Map the 15-step journal-compiler roadmap to explicit run status.

    This is deliberately an audit contract, not new orchestration. It prevents
    roadmap items from being silently treated as complete.
    """
    receipts = int(manifest.get("n_receipts") or 0)
    claims = int(
        manifest.get("n_high_confidence_claims_total")
        or sum(int(r.get("n_claims") or 0) for r in manifest.get("receipts", []))
    )
    tensions = int(manifest.get("n_non_orthogonal_tensions") or 0)
    outcomes = {
        str(r.get("outcome_class") or "").strip()
        for r in manifest.get("receipts", [])
        if str(r.get("outcome_class") or "").strip()
    }
    abstract_words = _section_word_count(paper_text, "Abstract")
    conclusion_words = _section_word_count(paper_text, "Conclusion")
    submission_ready = bool(
        getattr(gate, "passed", False)
        and getattr(score, "verdict", "") == "accept"
    )
    return [
        _readiness_item(1, "product_tiers", (
            "pass" if getattr(gate, "passed", False) and bool(journal_surface.get("passed")) else "not_ready"
        ), (
            f"pre_submit_gate={getattr(gate, 'passed', False)}; "
            f"journal_surface={bool(journal_surface.get('passed'))}; "
            f"submission_ready={submission_ready}"
        ), "Resolve non-pass readiness items before submission."),
        _readiness_item(2, "feasibility_preflight", (
            "pass" if receipts >= DEFAULT_THRESHOLDS.min_receipts else "not_ready"
        ), (
            f"receipts={receipts}; recommended>={RECOMMENDED_SOURCE_CITATIONS}; "
            f"minimum>={DEFAULT_THRESHOLDS.min_receipts}"
        ),
            "Expand corpus toward 30 receipts or document thin-corpus scope."),
        _readiness_item(3, "domain_pack", "partial", (
            "domain profiles exist; run uses current topic pack metadata"
        ), "Declare the domain profile and evidence hierarchy in the topic pack."),
        _readiness_item(4, "journal_grade_retrieval", "partial", (
            "corpus and citations are traced; exhaustive PRISMA search is not asserted"
        ), "Add saved search strings/exclusions before systematic-review claims."),
        _readiness_item(5, "claim_atoms", (
            "pass" if claims > 0 and citation_registry_complete else "not_ready"
        ), f"claims={claims}; citation_registry_complete={citation_registry_complete}",
            "Repair claim extraction or citation registry before manuscript use."),
        _readiness_item(6, "evidence_graph", (
            # The outcome graph is "built" once there is >=1 outcome class.
            # Zero non-orthogonal tensions is a valid finding for a
            # landscape / agreement corpus (the evidence-map path exists for
            # exactly these null-dominant briefs), so it must not block a paper
            # that otherwise carries a full outcome graph. Universal — no topic
            # knowledge; tensions stay reported as a richness signal.
            "pass" if outcomes else "not_ready"
        ), f"outcome_classes={len(outcomes)}; tensions={tensions}",
            "Build the outcome graph (>=1 outcome class) before rendering prose."),
        _readiness_item(7, "deterministic_manuscript_compiler", (
            "pass" if bool(journal_surface.get("passed")) else "not_ready"
        ), f"journal_surface_passed={bool(journal_surface.get('passed'))}",
            "Fix compiler-owned section/table/reference contracts."),
        _readiness_item(8, "deterministic_abstract_conclusion", (
            "pass" if 150 <= abstract_words <= 300 and 200 <= conclusion_words <= 320 else "partial"
        ), f"abstract_words={abstract_words}; conclusion_words={conclusion_words}",
            "Regenerate bounded abstract/conclusion slots from registry counts."),
        _readiness_item(9, "journal_surface_gate", (
            "pass" if bool(journal_surface.get("passed")) else "not_ready"
        ), f"issues={len(journal_surface.get('issues') or [])}",
            "Repair all journal-surface defects and rerun gate."),
        _readiness_item(10, "section_repair_loop", "partial", (
            "bounded final polish ran; no full multi-loop repair engine asserted"
        ), "Add bounded section-level retries only if recurring failures persist."),
        _readiness_item(11, "adversarial_reviewer_roles", (
            "pass" if int((reviewer_patches or {}).get("unresolved_p1_count", 0)) == 0 else "not_ready"
        ), f"unresolved_p1={int((reviewer_patches or {}).get('unresolved_p1_count', 0))}",
            "Resolve reviewer P1s or mark as human-blocking."),
        _readiness_item(12, "target_journal_finalizer", "not_ready", (
            "no target-journal style pack selected for this run"
        ), "Select target journal and generate style/checklist package.",
            advisory=True),
        _readiness_item(*_accountability_readiness_row(
            accountability_model, accountability_pass, accountability_detail,
        )),
        _readiness_item(14, "universal_benchmark_target", "not_ready", (
            "single-run artifact; 20-topic benchmark threshold not evaluated here"
        ), "Run the frozen benchmark and attach aggregate metrics.",
            advisory=True),
        _readiness_item(15, "end_state_architecture", (
            "partial" if not template_language_blocking else "not_ready"
        ), "core synthesis/gates exist; target finalizer and human signoff remain explicit gaps",
            "Keep closing partial/not-ready items without adding new layers.",
            advisory=True),
    ]


def _format_readiness_contract(contract: list[dict[str, Any]]) -> str:
    rows = [
        "| # | Item | Status | Audit | Next action |",
        "|---:|---|---|---|---|",
    ]
    for item in contract:
        rows.append(
            f"| {item['id']} | {item['name']} | {item['status']} | "
            f"{item['audit']} | {item['next_action']} |"
        )
    return "\n".join(rows)


def write_final_quality_gates(
    *,
    out_dir: Path,
    paper_text: str,
    manifest: dict[str, Any],
    audit: dict[str, Any],
    journal_surface: dict[str, Any],
    reviewer_patches: dict[str, Any] | None,
    quality_bundle: Any,
    citation_registry_complete: bool,
) -> dict[str, Any]:
    template = evaluate_template_gate(paper_text, source=str(out_dir / "full_paper.md"))
    (out_dir / "template_language_gate.json").write_text(template.json_report)
    (out_dir / "template_language_gate.md").write_text(template.markdown_report)
    inputs = build_gate_inputs(
        numeric_coverage=_numeric_coverage(audit),
        citation_registry_complete=citation_registry_complete,
        audit_gates_passed=_audit_passed(audit),
        journal_surface_passed=bool(journal_surface.get("passed") or journal_surface.get("pass")),
        unresolved_reviewer_p1_count=int((reviewer_patches or {}).get("unresolved_p1_count", 0)),
        rob_coverage=quality_bundle.rob_coverage,
        grade_coverage=quality_bundle.grade_coverage,
        n_tensions=int(manifest.get("n_non_orthogonal_tensions", 0)),
        n_receipts=int(manifest.get("n_receipts", 0)),
        template_language_blocking=template.template_language_blocking,
    )
    runtime_issue = _runtime_integrity_issue(out_dir)
    runtime_failure = str(runtime_issue["detail"]) if runtime_issue else None
    gate = _gate_with_runtime_integrity(
        evaluate_final_gate(
            inputs,
            thresholds=landscape_thresholds(inputs.n_receipts, inputs.n_tensions),
        ),
        runtime_failure,
    )

    field = json.loads((out_dir / "field_engagement.json").read_text()) if (out_dir / "field_engagement.json").exists() else []
    supported = sum(1 for item in field if item.get("status") in {"support", "extends"})
    text_lower = paper_text.lower()
    score_inputs = ScoreInputs(
        n_receipts=int(manifest.get("n_receipts", 0)),
        n_outcome_classes=len({r.get("outcome_class") for r in manifest.get("receipts", [])}),
        n_tensions=int(manifest.get("n_non_orthogonal_tensions", 0)),
        rob_coverage=quality_bundle.rob_coverage,
        grade_coverage=quality_bundle.grade_coverage,
        numeric_coverage=_numeric_coverage(audit),
        citation_registry_complete=citation_registry_complete,
        audit_gates_passed=_audit_passed(audit),
        template_language_blocking=template.template_language_blocking,
        field_engagements_supported=supported,
        field_engagements_total=len(field),
        has_explicit_thesis=bool(str(manifest.get("thesis") or "").strip()),
        has_limitations_section="## limitations" in text_lower,
        has_clinical_practice_statement=_has_clinical_practice_boundary(paper_text),
        unresolved_reviewer_p1_count=int((reviewer_patches or {}).get("unresolved_p1_count", 0)),
    )
    score = score_publication(score_inputs)
    # Resolve accountability model + pass state from the run state so
    # item 13 of the readiness contract reflects the ladder this run
    # was certified under (researka_agent_certified vs legacy).
    from agent.accountability import accountability_pass as _acc_pass
    _acc_model = str(
        manifest.get("accountability_model") or "researka_agent_certified"
    )
    _acc_ok, _acc_detail = _acc_pass(out_dir, _acc_model)
    readiness_contract = build_journal_readiness_contract(
        paper_text=paper_text,
        manifest=manifest,
        gate=gate,
        score=score,
        journal_surface=journal_surface,
        reviewer_patches=reviewer_patches,
        citation_registry_complete=citation_registry_complete,
        template_language_blocking=template.template_language_blocking,
        accountability_model=_acc_model,
        accountability_pass=_acc_ok,
        accountability_detail=_acc_detail,
    )
    gate_payload = {
        "inputs": dataclasses.asdict(inputs),
        "result": dataclasses.asdict(gate),
        "runtime_integrity_failure": runtime_failure,
        "runtime_integrity": runtime_issue or {"blocks_submission": False},
        "journal_readiness_contract": readiness_contract,
    }
    (out_dir / "pre_submit_gate.json").write_text(json.dumps(gate_payload, indent=2))
    (out_dir / "pre_submit_gate.md").write_text(
        "# Pre-Submit Final Gate\n\n"
        + gate.summary
        + "\n\n## Journal Readiness Contract\n\n"
        + _format_readiness_contract(readiness_contract)
        + "\n"
    )
    score_payload = {"inputs": dataclasses.asdict(score_inputs), "result": dataclasses.asdict(score)}
    (out_dir / "publication_score.json").write_text(json.dumps(score_payload, indent=2))
    (out_dir / "publication_score.md").write_text("# Publication Score\n\n" + score.summary + "\n")
    _write_provenance_sidecar(out_dir, manifest, dataclasses.asdict(gate))
    return {"template": template, "gate": gate, "score": score}
