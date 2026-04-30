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
a single load-bearing principle: **LLM proposes, code disposes**.
Topic of synthesis: *{topic}*. Every claim that appears in this paper
is either anchored to a specific source-paper receipt by deterministic
trace verification, or is explicitly marked as scoped framing prose
that cannot make novel quantitative assertions. The architecture is
designed so that hallucinated numerics, fabricated trial identifiers,
and over-claimed clinical effects are caught before they reach the
reader. Where the pipeline is uncertain or where a canonical paper
fails internal review, the artifact records that fact transparently
rather than silently filtering it.

### Corpus

The input corpus is a predeclared canonical set of {n_total} candidate
research papers ({n_accepted} accepted by SPAR adjudication and
integrated as evidence; {n_rejected} rejected and quarantined under
"Rejected / Contested Evidence" in the brief). Corpus declaration is
locked before any run via `tests/fixtures/<topic>_canonical/` so
papers cannot be silently added or removed after the fact. This
predeclared-benchmark discipline is the AAA-grade anti-cherry-picking
guarantee: the audit trail records exactly which papers were
evaluated, which passed SPAR, which failed and why. The corpus was
selected from the topic's published high-quality reference set
(canonical RCTs and major review/meta-analysis articles); papers were
not added in response to favorable findings nor removed in response
to unfavorable ones.

### Per-paper claim receipts

Each paper enters a single-source claim-receipt pipeline:

1. **Fact extraction** — an LLM proposes verbatim source-quote facts
   from the abstract; the proposed quote must appear character-for-
   character in the source (whitespace and Unicode normalization
   tolerated, semantic edits rejected). Structured fields
   (`outcome`, `estimate`, `p_value`, `ci`) are kept only when they
   are clean substrings of the verified source quote, otherwise
   nulled. Two extractor-side filters protect against the most
   common mis-extraction failure modes: an OBJECTIVE-AS-CLAIM filter
   rejects spans like "To determine whether..." that describe study
   purposes rather than findings, and a MECHANISM-INFLATION filter
   rejects clinical-effect verbs ("protective effect on cognition",
   "demonstrates efficacy") when the cited source is mechanistic,
   preclinical, or a tier-B/C review.
2. **Compile** — accepted facts become typed claims with deterministic
   role/directness/tier classifications derived from the source
   metadata; the claim graph is bundled and a thesis is chosen by a
   deterministic 6-dimension scoring tournament (canonical-trial
   priority, directness, tier, recency, confidence, claim id).
3. **Citation tracing** — every claim's NCT IDs, ISRCTN IDs, alias
   names, p-values, percentages, and bibliographic identifiers are
   traced against ClinicalTrials.gov v2, the ISRCTN registry,
   ChEMBL, and the abstract text itself. Failed traces propagate
   to SPAR as evidence-integrity signals. The trace clients
   distinguish "registry has the trial but no posted results" (a
   normal data-lag condition for journal-published RCTs whose
   results live in the paper, not the registry) from "registry has
   no record of this trial" (a fabrication signal).
4. **SPAR adjudication** — three role-bound LLM judges adjudicate
   the claim graph plus citation traces plus source abstracts in
   parallel: Evidence Auditor (verifies claim ↔ source
   correspondence), Domain Skeptic (looks for over-claiming, missing
   caveats, mechanism inflation, off-topic drift), Final Judge
   (votes independently after reading the prior two). The panel
   verdict is computed deterministically: 3-0 accept → accept_clean,
   2-1 accept → accept_caveated, 1-2 reject → reject_majority,
   0-3 reject → reject_critical. Dissent in any 2-1 split is
   always published verbatim in the receipt.
5. **Receipt emission** — accepted claim receipts (verdict starts
   with `accept`) contribute to the synthesis layer; rejected
   receipts are quarantined for transparency and surfaced in the
   "Rejected / Contested Evidence" section of the brief and in the
   relevant outcome subsection of this paper's Results.

### Cross-source synthesis

The accepted receipts feed a synthesis layer that:

1. Builds a **tension matrix** — every pair of receipts is
   classified as orthogonal (cover different outcome classes),
   agreement (same outcome, same direction), disagreement (same
   outcome, opposing direction), indirectness_gap (one direct, one
   mechanistic on the same outcome), or null_vs_positive (one null
   result, one signed effect, same outcome). The classification is
   purely deterministic per pair; no LLM is involved at this stage.
2. Runs a **thesis tournament** — an LLM proposes K=3 candidate
   integrating theses; a deterministic validator enforces ≥3
   distinct receipts referenced, ≥1 non-orthogonal tension addressed
   verbatim (when the matrix has any), no novel numerics absent
   from receipts, and ≤30-word length. The picker selects the
   highest-ranked valid candidate by descending receipt-coverage
   then descending tension-coverage then ascending word-count then
   alphabetical text. When no candidate validates, the thesis falls
   back to a deterministic stub and the picker rationale records
   "all candidates rejected" so the audit trail is unambiguous.
3. Renders a **structured evidence brief** (`paper_synthesis.md`) —
   bullet-anchored summary where every sentence cites at least one
   receipt. The brief is the auditable evidence layer; readers who
   need to verify a specific claim can trace it directly to a
   receipt without reading the full paper.
4. Renders this **full paper** (`full_paper.md`) — multi-section
   prose with tiered validation. ANCHORED sections (Abstract,
   Results, Cross-Domain Synthesis, Limitations) require every
   paragraph to cite ≥1 accepted receipt and reject paragraphs that
   introduce numerics absent from the corpus. SCOPED sections
   (Introduction, Background, Discussion, Conclusion) are framing
   prose; they may cite receipts but are not required to, must
   mention the topic alias ≥2 times per paragraph, must contain
   at least one hedge phrase per paragraph, and must not introduce
   novel numerics. DETERMINISTIC sections (Methods, References)
   render from pipeline constants and receipt metadata with no LLM
   call. This tiered design preserves the trust-spine guarantees of
   the brief while permitting the prose density expected of a
   publishable artifact.
5. Runs a **Q1-Q7 quality audit** — deterministic checks against
   the rendered paper covering: borderline-p hedging discipline
   (Q1), null-result acknowledgment (Q2), mixed-directness
   transitions (Q3, load-bearing), single-trial replication-gap
   surfacing (Q4), healthspan-claim discipline (Q5, load-bearing),
   adverse-event surfacing (Q6), and numeric fidelity (Q7). Q1, Q3,
   and Q5 are designated load-bearing — failure on any one of them
   blocks ship regardless of overall score. The audit notes the
   load-bearing-failure list explicitly and reports score as a
   percentage of applicable checks (N/A checks are not counted as
   passes — load-bearing N/A blocks ship just as load-bearing
   failure does).

### Outcome class distribution (accepted slice)

{outcome_lines}

### Reproducibility

All artifacts produced by a single run are written to disk under a
timestamped per-submission directory: the {n_total} cluster receipts
(8 JSON files each, plus a `claim_receipt.md` per cluster), the
multi-receipt manifest, the brief (`paper_synthesis.md`), this full
paper (`full_paper.md`), the synthesis quality audit
(`synthesis_quality_audit.json`), the receipt summaries
(`receipt_summaries.json`), the tension matrix
(`tension_matrix.json`), and the synthesis metadata including the
LLM cost ledger and the rejected thesis candidates. The corpus
fixture is committed to the repository alongside the run artifacts
so any reviewer with the source tree can re-run the pipeline and
verify byte-identical outputs (modulo provider-side LLM stochasticity
when no seed is supplied).
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
