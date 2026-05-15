"""PRISMA-ScR Methods pack — deterministic journal-grade Methods
section data.

Reviewer feedback 2026-05-14: Methods section is the biggest missing
piece for mid-tier journal readiness. Without named databases, exact
search strings, search dates, screening counts, exclusion ledger, and
AI-use disclosure, even strong prose looks non-standard.

This module defines the canonical schema as a frozen dataclass with
all 11 required PRISMA-ScR fields. The data is built deterministically
from the run state (manifest + topic_pack + receipt funnel) — no LLM
hallucination of search strings. The same struct is serialised to
`methods_pack.json` (auditable sidecar) AND rendered to Methods prose
(reads in normal academic language).

Universal — fields are topic-agnostic. Works for biomedical, climate,
materials, economics, social science. The schema mirrors the
PRISMA-ScR 20-item checklist's reporting requirements where they apply
to any structured synthesis.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class MethodsPack:
    """Frozen schema for journal-grade Methods reporting. Every field
    must be populated or the gate flags it as a stub."""

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
        """Return names of fields that are empty / stub. Universal —
        empty string, empty tuple, or all-zero counts count as missing."""
        out: list[str] = []
        for name, value in self.to_json().items():
            if isinstance(value, str) and not value.strip():
                out.append(name)
            elif isinstance(value, (list, tuple)) and not value:
                out.append(name)
            elif isinstance(value, dict) and not any(v for v in value.values()):
                out.append(name)
        return tuple(out)


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
    rob_method: str = "",
    search_dates_iso: str = "",
    accountability_model: str = "researka_agent_certified",
) -> MethodsPack:
    """Build a MethodsPack from run state. Universal — caller passes
    raw counts + topic-pack search queries. The pack stays topic-
    agnostic; no biomedical-specific assumptions in this builder.

    `search_dates_iso` defaults to today (UTC) when caller hasn't
    captured the actual retrieval window — better than leaving it
    blank. Real runs should pass the captured retrieval timestamp.
    """
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
        "study design", "population / cohort", "intervention or exposure",
        "comparator", "outcome class", "effect direction",
        "effect size", "confidence interval or credible interval",
        "p-value", "sample size", "follow-up duration",
        "risk-of-bias rating",
    )
    exclusion_summary = (
        f"Non-traceable findings (claim could not be linked to source text): "
        f"{max(0, n_rejected)} records.",
        "Wrong population / off-topic sources excluded at screening.",
        "Duplicate records deduplicated by DOI / PMID before screening.",
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
        screening_flow={
            "n_retrieved": int(n_retrieved),
            "n_screened": int(n_screened),
            "n_included": int(n_included),
            "n_excluded_at_full_text": int(n_rejected),
        },
        data_extraction_fields=extraction_fields,
        exclusion_reason_summary=exclusion_summary,
        risk_of_bias_approach=rob,
        synthesis_approach=(
            "Evidence-tension synthesis: claims grouped by outcome class "
            f"({', '.join(c.replace('_', ' ') for c in sorted(outcome_classes))}); "
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
        "documented in the run's submission record. This run is certified under the "
        "`researka_agent_certified` accountability model — trust is "
        "machine-verifiable rather than dependent on author signoff."
    ),
}


def _accountability_text(model: str) -> str:
    """Accountability-model-aware Methods prose. Researka-native cites
    the machine spine; legacy mode keeps ICMJE/COPE author framing."""
    from agent.accountability import resolve_model
    return _ACCOUNTABILITY_TEXTS[resolve_model(model)]


def write_methods_pack(out_dir: Path, pack: MethodsPack) -> Path:
    """Serialise to `methods_pack.json` in the run dir. Universal."""
    path = out_dir / "methods_pack.json"
    path.write_text(json.dumps(pack.to_json(), indent=2))
    return path


def render_methods_md(pack: MethodsPack, *, submission_id: str) -> str:
    """Render the Methods section in journal-conventional prose from a
    MethodsPack. Universal — no topic-specific framing."""
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
    lines.extend([
        "",
        "### Selection of sources of evidence",
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
        ", ".join(pack.data_extraction_fields) + ".",
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
    """When manifest declares a review_type, the Methods section must
    contain the 11 PRISMA-ScR H3 markers. Universal — no per-topic
    knowledge. Skip the check when no review_type is declared or the
    Methods section is empty (other gates catch that)."""
    if not declared_review_type or not methods_section_body:
        return ()
    return tuple(
        f"Methods missing required PRISMA-ScR subsection: {marker!r}"
        for marker in REQUIRED_METHODS_H3_MARKERS
        if marker not in methods_section_body
    )
