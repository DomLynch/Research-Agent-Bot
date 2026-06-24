"""Deterministic sections of the full paper (Methods + References +
What-This-Adds).

These sections render from pipeline constants + receipt metadata
without any LLM call. Extracted from paper_writer.py to keep both
modules under the 600-cloc per-file cap.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agent.synthesis_schemas import (
    ReceiptSummary, SynthesisSection, SynthesisThesis, TensionMatrix,
)
from agent.synthesis_writer import filter_accepted
from agent.outcome_class_remap import outcome_display

__all__ = [
    "build_methods_section",
    "build_references_full_section",
    "build_what_this_adds_section",
]

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s;,)]+", re.IGNORECASE)


def _first_clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = _DOI_RE.search(str(value))
    if not match:
        return None
    return match.group(0).rstrip(".,")


def build_methods_section(
    receipts: Sequence[ReceiptSummary],
    *,
    topic: str,
    submission_id: str,
) -> SynthesisSection:
    """Render concise deterministic Methods prose from final state."""
    n_accepted = len(filter_accepted(receipts))
    n_total = len(receipts)
    n_rejected = n_total - n_accepted
    by_outcome: dict[str, int] = {}
    for r in filter_accepted(receipts):
        by_outcome[r.outcome_class] = by_outcome.get(r.outcome_class, 0) + 1
    outcome_lines = "\n".join(
        f"- **{oc}**: {n} included source{'s' if n != 1 else ''}"
        for oc, n in sorted(by_outcome.items())
    ) or "- (no included sources)"
    topic_label = topic.replace("_", " ")
    body = f"""## Methods

We conducted a structured evidence synthesis on {topic_label}. The
source set was frozen before manuscript rendering: {n_total} candidate
papers were screened, {n_accepted} sources entered the public synthesis,
and {n_rejected} were kept out of main-body inference because they failed
eligibility, traceability, or evidence-role checks. Excluded sources and
dense audit artifacts are retained in the supplement rather than used to
support public claims.

Each included source was converted into a source-bound evidence record.
Candidate findings were retained only when the quoted source text could be
traced directly to the paper and when numeric fields, study identifiers,
and bibliographic identifiers matched the underlying record. Deterministic
classifiers then assigned evidence tier, directness, outcome class, and
effect direction. These fields, not the prose writer, determine which
sources can enter each Results subsection.

Cross-source interpretation used the frozen evidence records to identify
agreement, disagreement, null-positive contrasts, and directness gaps within
the same outcome class. The manuscript writer received only section-specific
evidence packets and could compress, frame, and interpret those packets, but
could not add new studies, new numbers, or move evidence between outcome
sections. Tables, full extraction rows, rejected sources, audit trails, and
pipeline diagnostics are reported in supplementary files.

Accepted evidence was distributed across outcome classes as follows:

{outcome_lines}

All manuscript, supplement, citation registry, audit, and verdict files for
this run were written to a timestamped submission directory
(`{submission_id}`), allowing the public article to be checked against the
same frozen evidence state.
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
    if doi := _first_clean_doi(r.source_doi):
        parts.append(f"doi:{doi}.")
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


def _public_disagreement_clause(n_pairs: int, n_sources: int) -> str:
    if n_pairs <= 0:
        return "with no cross-study disagreements surfaced"
    if n_sources >= 25 and n_pairs >= n_sources * 4:
        return "and a high-density pairwise disagreement map"
    return (
        f"and {n_pairs} cross-study disagreement"
        + ("" if n_pairs == 1 else "s")
    )


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
        "null_vs_negative": "null vs negative",
        "p_value": "p-value",
        "sample_size": "sample size",
        "unit_value": "unit value",
    }
    s = (value or "").strip()
    return labels.get(s, outcome_display(s).lower())


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
        "| Outcome class | Direct sources | Indirect / mechanism sources | Direction profile | Interpretation boundary |",
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
        n_sources = direct + indirect
        rationale = (
            f"{direct} direct and {indirect} indirect "
            f"{'source' if n_sources == 1 else 'sources'}; "
            f"direction profile: {directions or 'unclear'}"
        )
        lines.append(f"| P{i} | {_public_label(oc)}: {gap} | {rationale} |")
    _, target_oc, direct, indirect, _, gap = top[0]
    target = _public_label(target_oc)
    population = (
        "adults or older adults with baseline risk in the target outcome domain"
        if direct == 0 else
        "the same population type as the strongest direct receipt cluster"
    )
    duration = "at least 12 months" if gap == "direct clinical gap" else "at least 24 weeks"
    sample_size = "at least 200 participants per arm" if direct == 0 else "at least 100 participants per arm"
    lines += [
        "",
        "### Next-Study Design Recommendation",
        "",
        f"The next high-yield study for {topic} should target the "
        f"**{target}** evidence gap, pre-register the primary endpoint, "
        "separate clinical from mechanistic endpoints, preserve safety "
        "and adherence capture, and include an analysis plan that can "
        "falsify the current boundary-condition claim rather than only "
        f"confirming a favorable direction. Minimum useful design: {sample_size}, "
        f"a priority population of {population}, and follow-up lasting {duration}; "
        "shorter or smaller studies should be treated as hypothesis-generating.",
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
      - the picked thesis sentence (verbatim — already trust-spine
        validated by the thesis tournament)
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
        f"{n_acc} included source" if n_acc == 1
        else f"{n_acc} included sources"
    )

    lines: list[str] = ["## What This Synthesis Adds", ""]

    pair_clause = _public_disagreement_clause(n_pairs, n_acc)
    lines.append(
        f"This synthesis maps {n_acc_s} on {cap} across "
        f"{n_outcomes} outcome class"
        + ("" if n_outcomes == 1 else "es")
        + f" {pair_clause}. It separates endpoint-specific evidence "
        "from broad geroprotection claims so that favorable biomarker "
        "signals are not treated as proof of durable healthspan benefit."
    )
    lines.append("")

    if thesis and getattr(thesis, "text", "").strip():
        lines.append(thesis.text.strip())
        lines.append("")

    if load_bearing is not None:
        a = getattr(load_bearing, "receipt_a_id", "?") or "?"
        b = getattr(load_bearing, "receipt_b_id", "?") or "?"
        kind = (getattr(load_bearing, "kind", "") or "tension").replace(
            "_", " ",
        )
        oc = getattr(load_bearing, "outcome_class", "") or "an outcome"
        sev = getattr(load_bearing, "severity", 0) or 0
        lines.append(
            f"The strongest unresolved contrast is the {kind} between "
            f"{a} and {b} on {_public_label(oc)} (severity {sev}/5), "
            "which defines the boundary condition future studies must "
            "test rather than smooth over."
        )
        lines.append("")

    if review_cites:
        cites_str = ", ".join(review_cites[:5])
        lines.append(
            f"Prior reviews in the corpus ({cites_str}) emphasize "
            f"convergent signals on {cap}. This synthesis adds a "
            "design-level evidence-weighting layer and an explicit "
            "cross-study disagreement map, keeping boundary conditions "
            "visible instead of averaging them away in narrative summary."
        )
    else:
        lines.append(
            "This synthesis adds a design-level evidence-weighting "
            "layer and an explicit cross-study disagreement map, "
            "keeping boundary conditions visible instead of averaging "
            "them away in narrative summary."
        )
    lines.append("")
    _append_research_contribution_layer(lines, accepted, matrix, cap)

    return "\n".join(lines).rstrip() + "\n"
