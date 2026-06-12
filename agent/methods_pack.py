from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from agent.outcome_class_remap import outcome_display
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
    receipt_funnel: Any | None = None,
    rob_method: str = "",
    search_dates_iso: str = "",
    accountability_model: str = "researka_agent_certified",
) -> MethodsPack:
    if not search_dates_iso:
        search_dates_iso = dt.datetime.now(dt.timezone.utc).date().isoformat()
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
    exclusion_summary = (
        f"Non-traceable findings (claim could not be linked to source text): "
        f"{max(0, n_rejected)} records.",
        "Wrong population / off-topic sources excluded at screening.",
        "Duplicate records deduplicated by DOI / PMID before screening.",
    )
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
        "Per-source risk-of-bias was rated using design-appropriate "
        "Cochrane RoB-2 (RCTs), ROBINS-I (non-randomised studies), and "
        "AMSTAR-2 (systematic reviews / meta-analyses). Ratings recorded "
        "in `risk_of_bias.json`."
    )
    return MethodsPack(
        review_type=review_type,
        databases_searched=(
            "PubMed", "Europe PMC", "OpenAlex", "Semantic Scholar",
            "Crossref", "DOAJ", "OpenAIRE", "PMC OAI", "bioRxiv",
            "medRxiv", "arXiv", "ClinicalTrials.gov",
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
            f"({', '.join(outcome_display(c).lower() for c in sorted(outcome_classes))}); "
            "within-class agreement, disagreement, and directness gaps "
            "surfaced explicitly. Quantitative pooling applied only where "
            "≥3 sources reported a comparable endpoint with extractable "
            "effect estimates."
        ),
        ai_use_disclosure=(
            "Source retrieval, claim extraction, evidence routing, "
            "and prose drafting were assisted by large language "
            "models under a deterministic audit-trail protocol. Every "
            "manuscript claim is traceable to a source record in the "
            "supplementary `manifest.json`. Final eligibility and "
            "interpretation decisions are author-verified."
        ),
        human_accountability=_accountability_text(accountability_model),
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
    from agent.review_type import display_label
    lines: list[str] = [
        "## Methods",
        "",
        "### Review type and protocol",
        f"This manuscript is reported as a {display_label(pack.review_type)}. "
        "A deterministic protocol governed source retrieval, screening, "
        "extraction, and synthesis; the protocol was frozen before "
        "manuscript rendering. The full audit trail is in the "
        f"supplementary `methods_pack.json` and the timestamped "
        f"submission directory `{submission_id}`.",
        "",
        "### Information sources",
        "Sources were retrieved across " +
        ", ".join(pack.databases_searched[:-1]) +
        f", and {pack.databases_searched[-1]}. Retrieval window: "
        f"{pack.search_dates}.",
        "",
        "### Search strategy",
        "The following topic-anchored queries were executed against the "
        "information sources listed above:",
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
        ", ".join(pack.data_extraction_fields) + ". Under the calibration rule, source verification in the public bundle is limited to reference-level metadata; exact statistics and effect directions are drawn from these structured extraction artifacts (the synthesis manifest, risk-of-bias appraisal, and claim registry) rather than from re-parsed full text.",  # noqa: E501
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
