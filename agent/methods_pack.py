from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from agent.outcome_class_remap import unique_outcome_displays
from agent.selection_flow import receipt_admission_rows


@dataclass(frozen=True, slots=True)
class MethodsPack:
    review_type: str
    databases_searched: tuple[str, ...]
    search_strings: tuple[str, ...]
    search_dates: str
    eligibility_criteria: tuple[str, ...]
    screening_flow: dict[str, int]
    data_extraction_fields: tuple[str, ...]
    exclusion_reason_summary: tuple[str, ...]
    risk_of_bias_approach: str
    synthesis_approach: str
    ai_use_disclosure: str
    human_accountability: str
    source_inventory: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["screening_flow"] = dict(self.screening_flow)
        return d

    def required_fields_missing(self) -> tuple[str, ...]:
        def missing(value: Any) -> bool:
            return (
                (isinstance(value, str) and not value.strip())
                or (isinstance(value, (list, tuple)) and not value)
                or (isinstance(value, dict) and not any(value.values()))
            )
        return tuple(name for name, value in self.to_json().items() if missing(value))


def build_methods_pack(
    *,
    review_type: str,
    topic: str,
    corpus_search_queries: Sequence[str],
    n_retrieved: int,
    n_screened: int,
    n_included: int,
    n_rejected: int,
    outcome_classes: Sequence[str],
    source_inventory: Sequence[tuple[str, str]] = (),
    receipt_funnel: Any | None = None,
    rob_method: str = "",
    search_dates_iso: str = "",
    accountability_model: str = "researka_agent_certified",
) -> MethodsPack:
    frozen_sources = tuple(source_inventory)
    if any(
        not name.strip() or status not in {"enabled", "succeeded", "failed"}
        for name, status in frozen_sources
    ):
        raise ValueError(
            "source_inventory requires named enabled/succeeded/failed entries"
        )
    # Universal default eligibility — explicit; caller may override
    # by passing a richer pack via override fields in a later slice.
    eligibility = (
        f"Sources whose primary content addresses {topic.replace('_', ' ')}.",
        "Sources with extractable quantitative or qualitative findings.",
        "Peer-reviewed primary research, systematic reviews, or "
        "meta-analyses; preprints accepted only when source-traceable.",
        "Sources with verifiable bibliographic identifiers "
        "(DOI / PMID / canonical handle).",
    )
    extraction_fields = (
        "study design", "population / cohort", "intervention or exposure", "comparator",
        "outcome class", "effect direction", "effect size",
        "confidence interval or credible interval", "p-value", "sample size",
        "follow-up duration", "risk-of-bias rating",
    )
    # Count-backed exclusion summary: state an exclusion reason ONLY when a
    # real count backs it, so the "Exclusion reasons" list can never
    # contradict a "0 excluded" screening flow (reviewer-flagged). When no
    # instrumented gate recorded exclusions, say so plainly instead of
    # listing phantom reasons. Universal — no per-topic logic.
    n_screening_excluded = max(
        0, int(n_retrieved) - int(n_included) - max(0, int(n_rejected))
    )
    exclusion_lines: list[str] = []
    if int(n_rejected) > 0:
        exclusion_lines.append(
            "Non-traceable findings (claim could not be linked to source "
            f"text): {int(n_rejected)} records."
        )
    if n_screening_excluded > 0:
        exclusion_lines.append(
            "Off-topic or ineligible-population sources removed during "
            f"title/abstract screening: {n_screening_excluded} records."
        )
    if not exclusion_lines:
        exclusion_lines.append(
            "No additional records were excluded after final receipt admission; "
            "upstream non-admission buckets are reported separately in the "
            "receipt funnel and are not post-admission exclusions."
        )
    exclusion_summary = tuple(exclusion_lines)
    screening_flow = {
        "n_retrieved": int(n_retrieved),
        "n_screened": int(n_screened),
        "n_included": int(n_included),
        "n_excluded_at_full_text": int(n_rejected),
    }
    if isinstance(receipt_funnel, dict):
        counts = receipt_funnel.get("counts") or {}
        for key in (
            "receipt_candidate_union", "classified_receipt_candidates",
            "candidate_no_claims", "candidate_none_only",
            "candidate_partial_and_none_only", "candidate_partial_only",
            "original_strict_high_confidence_receipts",
        ):
            screening_flow[key] = int(counts.get(key) or receipt_funnel.get(key) or 0)
        screening_flow["admitted_receipts"] = int(
            counts.get("admitted_receipts") or counts.get("accepted_high_confidence") or 0
        )
    rob = rob_method or (
        "Risk-of-bias framework assignment follows study design "
        "(RoB-2 for RCTs, ROBINS-I for non-randomised studies, AMSTAR-2 "
        "for systematic reviews / meta-analyses). Public appraisal claims "
        "are limited to populated `risk_of_bias.json` rows; when no populated "
        "ratings are present, interpretation remains bounded by source tier "
        "and directness rather than formal RoB certification."
    )
    return MethodsPack(
        review_type=review_type,
        databases_searched=tuple(
            name for name, status in frozen_sources
            if status == "succeeded"
        ),
        search_strings=tuple(corpus_search_queries),
        search_dates=search_dates_iso,
        eligibility_criteria=eligibility,
        screening_flow=screening_flow,
        data_extraction_fields=extraction_fields,
        exclusion_reason_summary=exclusion_summary,
        risk_of_bias_approach=rob,
        synthesis_approach=(
            "Evidence-tension synthesis: claims grouped by outcome class "
            f"({', '.join(unique_outcome_displays(sorted(outcome_classes), lower=True))}); "
            "within-class agreement, disagreement, and directness gaps "
            "surfaced explicitly. Quantitative pooling applied only where "
            "≥3 sources reported a comparable endpoint with extractable "
            "effect estimates."
        ),
        ai_use_disclosure=(
            "Manuscript drafting used large language models under a "
            "deterministic audit-trail protocol. Claim and citation "
            "trace artifacts are recorded in the supplementary "
            "`manifest.json`; source-provider outcomes are limited to "
            "the frozen inventory reported above."
        ),
        human_accountability=_accountability_text(accountability_model),
        source_inventory=frozen_sources,
    )


_ACCOUNTABILITY_TEXTS: dict[str, str] = {
    "legacy_journal_submission": (
        "The author named in `human_signoff.json` accepts responsibility "
        "for the included evidence, the synthesis conclusions, and the "
        "manuscript text. AI assistance does not transfer authorship or "
        "accountability."
    ),
    "researka_agent_certified": (
        "Accountability is established through reproducible artifacts: a "
        "deterministic protocol (`methods_pack.json`), a complete claim "
        "and citation registry, source-bound numeric trace, deterministic "
        "gates (`full_paper.journal_surface.json`, `pre_submit_gate.json`, "
        "`artifact_consistency.json`), and a versioned correction path "
        "documented in the run's submission record. Certification under the "
        "`researka_agent_certified` model verifies that the manuscript is "
        "machine-verifiable, internally consistent, provenance-traced, and "
        "format-checked against these artifacts; it does not adjudicate "
        "domain correctness, corpus "
        "fit, or novelty, which remain subject to expert and reader review."
    ),
}


def _accountability_text(model: str) -> str:
    from agent.accountability import resolve_model
    return _ACCOUNTABILITY_TEXTS[resolve_model(model)]


def write_methods_pack(out_dir: Path, pack: MethodsPack) -> Path:
    path = out_dir / "methods_pack.json"
    path.write_text(json.dumps(pack.to_json(), indent=2))
    return path


def render_methods_md(pack: MethodsPack, *, submission_id: str) -> str:
    from agent.manuscript_prisma import source_inventory_summary
    from agent.review_type import display_label
    inventory = pack.source_inventory
    source_disclosure = (
        "The frozen retrieval record reports "
        f"{source_inventory_summary(inventory)}. Named sources: "
        + "; ".join(f"{name} ({status})" for name, status in inventory)
        + "."
        if inventory else
        "No database inventory was frozen; no database coverage or "
        "execution claim is made."
    )
    date_disclosure = (
        f" Retrieval record date: {pack.search_dates}."
        if pack.search_dates else
        " No retrieval date was frozen."
    )
    lines: list[str] = [
        "## Methods",
        "",
        "### Review type and protocol",
        f"This manuscript is reported as a {display_label(pack.review_type)}. "
        "This methods pack freezes the run-reported selection counts, "
        "extraction fields, and synthesis settings used for manuscript "
        "rendering. The full audit trail is in the "
        f"supplementary `methods_pack.json` and the timestamped "
        f"submission directory `{submission_id}`.",
        "",
        "### Information sources",
        source_disclosure + date_disclosure,
        "",
        "### Search strategy",
        (
            "The following query strings are recorded in the frozen "
            "retrieval record:"
            if pack.search_strings else
            "No query strings were frozen; no query-execution claim is made."
        ),
        "",
    ]
    lines.extend(f"- `{q}`" for q in pack.search_strings[:10])
    if len(pack.search_strings) > 10:
        lines.append(
            f"- (... {len(pack.search_strings) - 10} additional queries; "
            "see `methods_pack.json` for the full list)",
        )
    lines.extend([
        "",
        "### Eligibility criteria",
    ])
    lines.extend(f"- {c}" for c in pack.eligibility_criteria)
    sf = pack.screening_flow
    admission_rows = receipt_admission_rows(sf)
    union = sf.get("receipt_candidate_union")
    classified = sf.get("classified_receipt_candidates")
    admitted = sf.get("admitted_receipts", sf.get("n_included", 0))
    lines.extend([
        "",
        "### Selection of sources of evidence",
    ])
    if admission_rows and union:
        lines.append(
            "The synthesis did not begin from an unfiltered database export. "
            "It began from a pre-curated receipt-candidate set generated by "
            f"the retrieval and claim-binding pipeline. Of {union} records "
            f"in the receipt-candidate union, {classified or 0} were classified "
            f"as receipt candidates and {admitted} were admitted as traceable "
            "synthesis receipts. Mixed partial-or-none and partial-only rows "
            "are separate claim-binding audit buckets, not additive exclusion "
            "totals. No additional records were excluded after final receipt "
            "admission."
        )
        lines += ["", "### Receipt admission funnel", "", "| Admission bucket | n |", "|---|---:|"]
        lines += [f"| {label} | {value} |" for label, value in admission_rows]
        lines += ["", "### Exclusion reasons"]
    else:
        lines.extend([
            f"Of {sf.get('n_retrieved', 0)} records retrieved, "
            f"{sf.get('n_screened', 0)} were screened against the "
            f"eligibility criteria, {sf.get('n_included', 0)} were included "
            f"in the synthesis, and "
            f"{sf.get('n_excluded_at_full_text', 0)} were excluded at full-"
            "text review. Reasons for exclusion are summarised below.",
            "",
            "### Exclusion reasons",
        ])
    lines.extend(f"- {r}" for r in pack.exclusion_reason_summary)
    lines.extend([
        "",
        "### Data items",
        "The following fields were extracted from each included source: " +
        ", ".join(pack.data_extraction_fields) + ". Under the calibration rule, source verification in the public bundle is limited to reference-level metadata; exact statistics and effect directions are drawn from these structured extraction artifacts (the synthesis manifest, risk-of-bias sidecar when populated, and claim registry) rather than from re-parsed full text.",  # noqa: E501
        "",
        "### Directness coding criteria",
        "A source was coded as direct only when it tested the topic itself "
        "against a clinically proximate outcome in the relevant population. "
        "Human evidence with an adjacent exposure, population, or outcome was "
        "coded as indirect; syntheses and secondary reviews were coded as "
        "review-level evidence and were not counted as direct sources.",
        "",
        "### Risk-of-bias appraisal",
        pack.risk_of_bias_approach,
        "",
        "### Synthesis approach",
        pack.synthesis_approach,
        "",
        "### AI-use disclosure",
        pack.ai_use_disclosure,
        "",
        "### Accountability",
        pack.human_accountability,
        "",
    ])
    return "\n".join(lines) + "\n"


# Required H3 markers in the rendered Methods section. The gate
# checks for presence — missing any one indicates a stub Methods.
REQUIRED_METHODS_H3_MARKERS: tuple[str, ...] = (
    "### Review type and protocol",
    "### Information sources",
    "### Search strategy",
    "### Eligibility criteria",
    "### Selection of sources of evidence",
    "### Exclusion reasons",
    "### Data items",
    "### Risk-of-bias appraisal",
    "### Synthesis approach",
    "### AI-use disclosure",
    "### Accountability",
)


def methods_pack_completeness_issue_messages(
    methods_section_body: str, declared_review_type: str | None,
) -> tuple[str, ...]:
    if not declared_review_type or not methods_section_body:
        return ()
    return tuple(
        f"Methods missing required PRISMA-ScR subsection: {marker!r}"
        for marker in REQUIRED_METHODS_H3_MARKERS
        if marker not in methods_section_body
    )
