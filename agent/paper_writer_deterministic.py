"""Deterministic sections of the full paper (Methods + References).

These sections render from pipeline constants + receipt metadata
without any LLM call. Extracted from paper_writer.py to keep both
modules under the 600-cloc per-file cap.
"""
from __future__ import annotations

from collections.abc import Sequence

from agent.synthesis_schemas import ReceiptSummary, SynthesisSection
from agent.synthesis_writer import filter_accepted

__all__ = [
    "build_methods_section",
    "build_references_full_section",
]


def build_methods_section(
    receipts: Sequence[ReceiptSummary],
    *,
    topic: str,
    submission_id: str,
) -> SynthesisSection:
    """Methods is DETERMINISTIC — describes the SPAR pipeline that
    produced the receipts, rendered from constants. No LLM call."""
    n_accepted = len(filter_accepted(receipts))
    n_total = len(receipts)
    n_rejected = n_total - n_accepted
    by_outcome: dict[str, int] = {}
    for r in filter_accepted(receipts):
        by_outcome[r.outcome_class] = by_outcome.get(r.outcome_class, 0) + 1
    outcome_lines = "\n".join(
        f"- **{oc}**: {n} receipt(s)"
        for oc, n in sorted(by_outcome.items())
    ) or "- (no accepted receipts)"
    body = f"""## Methods

This synthesis was produced by an automated multi-receipt research
pipeline (Researka v1, submission `{submission_id}`) that operates on
the principle: **LLM proposes, code disposes**. Topic of synthesis:
*{topic}*.

### Corpus

The input corpus is a predeclared canonical set of {n_total} candidate
research papers ({n_accepted} accepted by SPAR adjudication and
integrated as evidence; {n_rejected} rejected and quarantined under
"Rejected / Contested Evidence" in the brief). Corpus declaration is
locked before any run via `tests/fixtures/<topic>_canonical/` so
papers cannot be silently added or removed after the fact.

### Per-paper claim receipts

Each paper enters a single-source claim-receipt pipeline:

1. **Fact extraction** — an LLM proposes verbatim source-quote facts
   from the abstract; structurally-validated against the source text.
   Filters reject objective-as-claim spans (study purposes posing as
   findings) and mechanism-inflation extractions (clinical-effect
   verbs over preclinical/low-tier-review evidence).
2. **Compile** — facts → claims → claim graph; thesis chosen
   deterministically from a 6-dimension scoring tournament.
3. **Citation tracing** — every claim's NCT IDs, alias names,
   p-values, percentages, and bibliographic identifiers are traced
   against ClinicalTrials.gov / ISRCTN registries, ChEMBL, and the
   abstract text itself. Failed traces propagate to SPAR.
4. **SPAR adjudication** — three role-bound LLM judges (Evidence
   Auditor, Domain Skeptic, Final Judge) review the claim graph
   plus citation traces plus source abstracts. Verdict is computed
   deterministically (3-0 → accept_clean, 2-1 → accept_caveated,
   1-2 → reject_majority, 0-3 → reject_critical). Dissent is
   always published.
5. **Receipt emission** — accepted claim receipts contribute to
   the synthesis layer; rejected receipts are quarantined for
   transparency.

### Cross-source synthesis

The accepted receipts feed a synthesis layer that:

1. Builds a **tension matrix** — every pair of receipts is classified
   as orthogonal, agreement, disagreement, indirectness_gap, or
   null_vs_positive (deterministic per-pair classification).
2. Runs a **thesis tournament** — an LLM proposes K=3 candidate
   integrating theses; a deterministic validator enforces ≥3
   distinct receipts referenced, ≥1 non-orthogonal tension addressed
   (when the matrix has any), no novel numerics, and ≤30-word
   length. The picker selects the highest-ranked valid candidate.
3. Renders a **structured evidence brief** (`paper_synthesis.md`) —
   bullet-anchored summary, every sentence cited.
4. Renders this **full paper** (`full_paper.md`) — multi-section
   prose with tiered validation: ANCHORED sections (Abstract,
   Results, Cross-Domain Synthesis, Limitations) cite per sentence;
   SCOPED sections (Introduction, Background, Discussion,
   Conclusion) are unanchored framing with topic + hedge enforcement;
   DETERMINISTIC sections (Methods, References) render from
   pipeline constants.
5. Runs a **Q1-Q7 quality audit** — deterministic checks against
   the rendered paper covering hedging discipline, null-result
   acknowledgment, mixed-directness transitions, replication-gap
   surfacing, healthspan-claim discipline, adverse-event surfacing,
   and numeric fidelity. Load-bearing failures block ship.

### Outcome class distribution (accepted slice)

{outcome_lines}

### Reproducibility

All artifacts (the {n_total} cluster receipts, the brief, this paper,
the audit, the tension matrix, and the LLM cost ledger) are written
to disk per-submission and tracked alongside the source corpus so a
reviewer can reproduce or re-audit any result.
"""
    return SynthesisSection(name="methods", body_md=body, anchors=())


def build_references_full_section(
    receipts: Sequence[ReceiptSummary],
) -> SynthesisSection:
    """References is DETERMINISTIC — formatted bibliographic citations
    from each receipt's metadata. No LLM call."""
    lines = ["## References", ""]
    accepted = filter_accepted(receipts)
    accepted_ids = {r.receipt_id for r in accepted}
    rejected = [r for r in receipts if r.receipt_id not in accepted_ids]
    all_in_order = list(accepted) + list(rejected)
    for i, r in enumerate(all_in_order, start=1):
        trial = (
            f"({r.canonical_trial_id})"
            if r.canonical_trial_id else "(no trial registry id)"
        )
        venue_hint = (
            f" [accepted: {r.spar_verdict}]"
            if r.spar_verdict.startswith("accept")
            else f" [QUARANTINED: {r.spar_verdict}]"
        )
        thesis_excerpt = r.thesis_text[:160].rstrip()
        lines.append(
            f"[{i}] `{r.receipt_id}` {trial}{venue_hint}\n"
            f"    {thesis_excerpt}\n"
        )
    return SynthesisSection(
        name="references_full",
        body_md="\n".join(lines).rstrip() + "\n",
        anchors=(),
    )
