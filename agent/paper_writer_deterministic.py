"""Deterministic sections of the full paper (Methods + References +
What-This-Adds).

These sections render from pipeline constants + receipt metadata
without any LLM call. Extracted from paper_writer.py to keep both
modules under the 600-cloc per-file cap.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.synthesis_schemas import (
    ReceiptSummary, SynthesisSection, SynthesisThesis, TensionMatrix,
)
from agent.synthesis_writer import filter_accepted

__all__ = [
    "build_methods_section",
    "build_references_full_section",
    "build_what_this_adds_section",
]


def build_methods_section(
    receipts: Sequence[ReceiptSummary],
    *,
    topic: str,
    submission_id: str,
) -> SynthesisSection:
    """Deterministic Methods section. No LLM call."""
    n_accepted = len(filter_accepted(receipts))
    n_total = len(receipts)
    n_rejected = n_total - n_accepted
    topic_label = topic.replace("_", " ").replace("-", " ")
    body = f"""## Methods

This synthesis used a predeclared corpus of {n_total} source papers on
{topic_label}. After evidence adjudication, {n_accepted} receipt(s)
entered the synthesis and {n_rejected} were kept out of main-body
inference.

Source documents were screened for quantitative outcome statements.
Claims were retained only when the value, endpoint, study label, and
citation could be reconciled with the source record. Retained evidence
was grouped by outcome class, study design, direction of effect,
directness, and endpoint proximity.

The public manuscript uses the adjudicated receipt set as its inference
base. Quarantined receipts may remain visible in the supplement for
auditability, but they are not used to support the Results, Discussion,
or Conclusion. Dense extraction artifacts, including the full numeric
index and structured evidence tables, are routed to the supplement so
the main text can report only the evidence needed for interpretation.

Cross-paper tensions were summarized when retained findings addressed
related outcomes but differed in direction, population, comparator,
measurement method, or follow-up window. Direct human trials carried
the most weight for clinical endpoints; mechanistic, animal, cellular,
and review-level evidence was used to clarify plausibility and
boundary conditions rather than to establish clinical benefit.

All counts in the manuscript are derived from the same frozen receipt
state used to build the tables, references, and supplement. This keeps
screened, accepted, rejected, claim, and tension counts synchronized
across the public manuscript and the audit bundle.

The synthesis is descriptive and evidence-mapping rather than a
formal treatment recommendation. It does not pool heterogeneous
endpoints unless the effect scale, comparator, and follow-up window are
compatible. Where studies address related but non-identical endpoints,
the manuscript reports them as boundary conditions rather than forcing
them into a single average. This preserves the distinction between
mechanistic plausibility, biomarker movement, functional response, and
hard clinical inference. The same rule is applied across all topics.
"""
    return SynthesisSection(name="methods", body_md=body, anchors=())


def format_bibliographic_citation(r: ReceiptSummary) -> str:
    """Day 10.17 Phase 3: render publication-grade citation from the
    bibliographic fields populated in build_receipt_summary. Uses
    Title (Year). Venue. PMID/DOI format — not author-year, since
    evidence_cards source data does not include authors. Falls back
    to the receipt ID when no bibliographic data is available (older
    fixtures, malformed receipts)."""
    parts: list[str] = []
    if r.source_title:
        title = r.source_title.rstrip(".")
        parts.append(f"{title}.")
    if r.source_year:
        parts.append(f"({r.source_year}).")
    if r.source_venue:
        parts.append(f"{r.source_venue}.")
    if r.source_pmid:
        parts.append(f"PMID: {r.source_pmid}.")
    if r.source_doi:
        parts.append(f"doi:{r.source_doi}.")
    if r.canonical_trial_id:
        parts.append(f"Trial: {r.canonical_trial_id}.")
    if not parts:
        # No bibliographic data — fall back to internal id so the
        # reference still has SOMETHING the auditor can match.
        return f"`{r.receipt_id}`"
    return " ".join(parts)


def build_references_full_section(
    receipts: Sequence[ReceiptSummary],
) -> SynthesisSection:
    """References is DETERMINISTIC — formatted bibliographic citations
    from each receipt's metadata. No LLM call.

    Day 10.17 Phase 3: leads with publication-grade citation
    (Title / Year / Venue / PMID / DOI) and surfaces the internal
    receipt_id and SPAR verdict on a follow-up line for traceability."""
    lines = ["## References", ""]
    accepted = filter_accepted(receipts)
    accepted_ids = {r.receipt_id for r in accepted}
    rejected = [r for r in receipts if r.receipt_id not in accepted_ids]
    all_in_order = list(accepted) + list(rejected)
    for i, r in enumerate(all_in_order, start=1):
        citation = format_bibliographic_citation(r)
        verdict_tag = (
            f"[accepted: {r.spar_verdict}]"
            if r.spar_verdict.startswith("accept")
            else f"[QUARANTINED: {r.spar_verdict}]"
        )
        thesis_excerpt = r.thesis_text[:160].rstrip()
        lines.append(
            f"[{i}] {citation}\n"
            f"    Receipt: `{r.receipt_id}` {verdict_tag}\n"
            f"    {thesis_excerpt}\n"
        )
    return SynthesisSection(
        name="references_full",
        body_md="\n".join(lines).rstrip() + "\n",
        anchors=(),
    )


# --- Fix #25: What This Synthesis Adds (deterministic originality) -----


def _outcome_class_set(receipts: Sequence[ReceiptSummary]) -> set[str]:
    """Distinct non-empty outcome_class values across the corpus."""
    return {
        (r.outcome_class or "").strip() for r in receipts
        if (r.outcome_class or "").strip()
    }


def _named_review_citations(
    receipts: Sequence[ReceiptSummary],
) -> list[str]:
    """Extract systematic-review citations (B1 tier) for the
    'beyond prior reviews' framing. Returns body-citation strings
    (already transformed to Author-Year form by the orchestrator)."""
    out: list[str] = []
    for r in receipts:
        if (r.evidence_tier or "").upper() != "B1":
            continue
        rid = (r.receipt_id or "").strip()
        if rid:
            out.append(rid)
    return out


def _load_bearing_tension(matrix: TensionMatrix) -> Any | None:
    """Highest-severity Tension from the matrix (severity ≥ 4 if any).
    Falls back to highest available severity. None if matrix empty."""
    if matrix is None:
        return None
    pairs = list(getattr(matrix, "non_orthogonal", lambda: [])())
    if not pairs:
        return None
    return max(pairs, key=lambda t: getattr(t, "severity", 0) or 0)


_OUTCOME_IMPORTANCE = {
    "longevity": 5, "frailty": 4, "muscle_function": 4,
    "cardiometabolic": 4, "cognitive": 4, "safety": 4,
    "immune": 3, "oncology": 3, "ophthalmologic": 3,
    "mechanism": 2, "other": 1,
}


def _public_label(value: str) -> str:
    labels = {
        "cross_domain": "cross-domain",
        "mean_sd": "mean ± SD",
        "null_vs_positive": "null vs positive",
        "p_value": "p-value",
        "sample_size": "sample size",
        "unit_value": "unit value",
    }
    s = (value or "").strip()
    return labels.get(s, s.replace("_", " "))


def _outcome_rows(
    receipts: Sequence[ReceiptSummary], matrix: TensionMatrix | None,
) -> list[tuple[int, str, int, int, str, str]]:
    pairs = list(getattr(matrix, "non_orthogonal", lambda: [])()) if matrix else []
    rows: list[tuple[int, str, int, int, str, str]] = []
    for oc in sorted(_outcome_class_set(receipts)):
        rs = [r for r in receipts if r.outcome_class == oc]
        direct = sum(1 for r in rs if (r.directness or "").lower() == "direct")
        indirect = len(rs) - direct
        directions = ", ".join(sorted({
            (r.effect_direction or "unclear").replace("_", " ") for r in rs
        }))
        conflict = max(
            (getattr(t, "severity", 0) or 0 for t in pairs
             if getattr(t, "outcome_class", "") == oc),
            default=0,
        )
        gap = "direct clinical gap" if direct == 0 else "replication gap"
        if conflict >= 4:
            gap = "conflict-resolution gap"
        priority = (
            _OUTCOME_IMPORTANCE.get(oc, 1)
            * (3 if direct == 0 else 1)
            * (2 if conflict >= 3 else 1)
        )
        rows.append((priority, oc, direct, indirect, directions, gap))
    return sorted(rows, key=lambda row: (-row[0], row[1]))


def _append_research_contribution_layer(
    lines: list[str], receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix | None, topic: str,
) -> None:
    rows = _outcome_rows(receipts, matrix)
    if not rows:
        return
    lines += [
        "",
        "### Boundary-Condition Matrix",
        "",
        "| Outcome class | Direct receipts | Indirect / mechanism receipts | Direction profile | Interpretation boundary |",
        "|---|---:|---:|---|---|",
    ]
    for _, oc, direct, indirect, directions, gap in rows:
        lines.append(
            f"| {_public_label(oc)} | {direct} | {indirect} | "
            f"{directions or 'unclear'} | {gap} |"
        )
    top = rows[:5]
    lines += [
        "",
        "### Evidence-Gap Priority",
        "",
        "| Priority | Gap | Rationale |",
        "|---|---|---|",
    ]
    for i, (_, oc, direct, indirect, directions, gap) in enumerate(top, 1):
        rationale = (
            f"{direct} direct and {indirect} indirect receipt(s); "
            f"direction profile: {directions or 'unclear'}"
        )
        lines.append(f"| P{i} | {_public_label(oc)}: {gap} | {rationale} |")
    target = _public_label(top[0][1])
    lines += [
        "",
        "### Next-Study Design Recommendation",
        "",
        f"The next high-yield study for {topic} should target the "
        f"**{target}** evidence gap, pre-register the primary endpoint, "
        "separate clinical from mechanistic endpoints, preserve safety "
        "and adherence capture, and include an analysis plan that can "
        "falsify the current boundary-condition claim rather than only "
        "confirming a favorable direction.",
    ]


def build_what_this_adds_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix | None,
    thesis: SynthesisThesis,
    *,
    topic: str,
) -> str:
    """Fix #25 — DETERMINISTIC `## What This Synthesis Adds` section.

    Returns the section as a raw markdown string so the orchestrator
    can splice it into the paper at the right position (between
    Conclusion and References). Returning `str` instead of
    SynthesisSection avoids polluting the SectionName Literal — the
    section is structurally a 'what-this-adds' originality block, not
    one of the eight enumerated section types.

    Templated from receipts + matrix + thesis so the originality
    claim is grounded in pipeline data, not LLM rhetoric:

      - corpus characterisation (N receipts, N outcome classes,
        N non-orthogonal tensions)
      - the picked thesis sentence
      - the load-bearing cross-domain tension (highest severity)
      - explicit comparison vs the named B1 systematic reviews in
        the corpus (the 'beyond prior reviews' framing)
      - one-line statement of the boundary condition the synthesis
        adds beyond the prior reviews

    Position in the paper: between Conclusion and References."""
    accepted = list(filter_accepted(receipts))
    n_acc = len(accepted)
    outcome_classes = _outcome_class_set(accepted)
    n_outcomes = len(outcome_classes)
    n_pairs = 0
    if matrix is not None:
        n_pairs = len(list(getattr(matrix, "non_orthogonal", lambda: [])()))
    review_cites = _named_review_citations(accepted)
    load_bearing = _load_bearing_tension(matrix) if matrix else None
    cap = topic.strip() or "the topic"
    n_acc_s = (
        f"{n_acc} accepted receipt" if n_acc == 1
        else f"{n_acc} accepted receipts"
    )

    lines: list[str] = ["## What This Synthesis Adds", ""]

    # Sentence 1 — corpus + structure
    pair_clause = (
        f"and {n_pairs} non-orthogonal cross-domain tension"
        + ("" if n_pairs == 1 else "s")
    ) if n_pairs else "with no non-orthogonal tensions surfaced"
    lines.append(
        f"This synthesis adjudicates {n_acc_s} on {cap} across "
        f"{n_outcomes} outcome class"
        + ("" if n_outcomes == 1 else "es")
        + f" {pair_clause}, "
        "using a structured evidence-audit workflow with "
        "deterministic claim extraction, citation resolution, and "
        "design-level evidence weighting; see Methods and supplement."
    )
    lines.append("")

    # Sentence 2 — picked thesis. Plain-language label is universal
    # and reader-friendly across topics.
    if thesis and getattr(thesis, "text", "").strip():
        lines.append(
            f"**Central claim:** {thesis.text.strip()}"
        )
        lines.append("")

    # Sentence 3 — load-bearing tension highlight
    if load_bearing is not None:
        a = getattr(load_bearing, "receipt_a_id", "?") or "?"
        b = getattr(load_bearing, "receipt_b_id", "?") or "?"
        kind = (getattr(load_bearing, "kind", "") or "tension").replace(
            "_", " ",
        )
        oc = getattr(load_bearing, "outcome_class", "") or "an outcome"
        sev = getattr(load_bearing, "severity", 0) or 0
        lines.append(
            f"The load-bearing cross-domain tension this synthesis "
            f"surfaces is the {kind} between {a} and {b} on {oc} "
            f"(severity {sev}/5). Prior narrative reviews of {cap} "
            "have not adjudicated this pair head-to-head."
        )
        lines.append("")

    # Sentence 4 — comparison vs prior reviews. Keep this citation-free:
    # named review citations here are narrative context, not load-bearing
    # source-bound evidence, and the public consistency audit correctly
    # treats them as unsupported when they are used this way.
    if review_cites:
        lines.append(
            f"Prior reviews of {cap} usually emphasize convergent "
            "literature signals. This synthesis adds per-receipt "
            "evidence weighting, a source-bound numeric index, and an "
            "explicit tension matrix so the boundary conditions are "
            "visible rather than averaged away in narrative summary."
        )
    else:
        lines.append(
            "This synthesis adds per-receipt evidence weighting, a "
            "source-bound numeric index, and an explicit tension matrix "
            "so the boundary conditions are visible rather than averaged "
            "away in narrative summary."
        )
    lines.append("")
    _append_research_contribution_layer(lines, accepted, matrix, cap)

    return "\n".join(lines).rstrip() + "\n"
