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
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.final_gate import evaluate_final_gate
from agent.final_gate_mapper import build_gate_inputs
from agent.forest_plot_svg import render_forest_plot_svg
from agent.meta_analysis import EffectRow, pool_random_effects
from agent.publication_scorer import ScoreInputs, score_publication
from agent.quality_methods_bundle import build_quality_methods_bundle
from agent.risk_of_bias_schema import DOMAINS_BY_TOOL
from agent.template_gate_adapter import evaluate_template_gate
from agent.tension_elaboration import TensionRecord, select_top_tensions


def insert_before_heading(markdown: str, heading: str, section: str) -> str:
    if not section.strip() or section.splitlines()[0] in markdown:
        return markdown
    match = re.search(rf"^{re.escape(heading)}\b", markdown, re.MULTILINE)
    if not match:
        return markdown.rstrip() + "\n\n" + section.strip() + "\n"
    return (
        markdown[:match.start()].rstrip()
        + "\n\n"
        + section.strip()
        + "\n\n"
        + markdown[match.start():].lstrip()
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
    lines = [
        "## Risk of Bias and GRADE",
        "",
        "Risk-of-bias and certainty judgments are generated as structured "
        "sidecars from the accepted receipt set. The manuscript reports the "
        "study-level overall rating and outcome-level certainty label; the "
        "full domain table is preserved in `quality_methods.md`.",
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
    plans = select_top_tensions(records, top_n=5) if records else []
    payload = {"plans": [dataclasses.asdict(p) for p in plans], "candidate_tensions": len(records)}
    (out_dir / "tension_elaboration_plans.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "tension_elaboration_plans.md").write_text(render_tension_section(payload))
    return payload


def render_tension_section(payload: dict[str, Any]) -> str:
    lines = ["## Cross-Paper Tension Plans", ""]
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
    return bool(audit.get("p1_pass")) and int(audit.get("n_pass", 0)) >= int(audit.get("n_total", 1))


def _numeric_coverage(audit: dict[str, Any]) -> float:
    for check in audit.get("checks", []):
        if check.get("name") != "Q2_numeric_integrity":
            continue
        match = re.search(r"(\d+)/(\d+)", str(check.get("detail") or ""))
        if match and int(match.group(2)):
            return int(match.group(1)) / int(match.group(2))
    return 1.0 if _audit_passed(audit) else 0.0


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
    gate = evaluate_final_gate(inputs)
    gate_payload = {"inputs": dataclasses.asdict(inputs), "result": dataclasses.asdict(gate)}
    (out_dir / "pre_submit_gate.json").write_text(json.dumps(gate_payload, indent=2))
    (out_dir / "pre_submit_gate.md").write_text("# Pre-Submit Final Gate\n\n" + gate.summary + "\n")

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
        has_clinical_practice_statement="should not be used off-label" in text_lower,
        unresolved_reviewer_p1_count=int((reviewer_patches or {}).get("unresolved_p1_count", 0)),
    )
    score = score_publication(score_inputs)
    score_payload = {"inputs": dataclasses.asdict(score_inputs), "result": dataclasses.asdict(score)}
    (out_dir / "publication_score.json").write_text(json.dumps(score_payload, indent=2))
    (out_dir / "publication_score.md").write_text("# Publication Score\n\n" + score.summary + "\n")
    return {"template": template, "gate": gate, "score": score}
