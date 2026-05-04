"""Synthesis-layer schemas — Day 10 end-game.

The Day 9 pipeline produces atomic CLAIM RECEIPTS, one per source-paper
cluster. The Day 10 synthesis layer takes N receipts from the same
retrieval and produces a `paper_synthesis.md` — the actual research
paper that integrates findings across sources, surfaces tensions, and
hedges contested evidence honestly.

This module defines the structured types that flow between the new
synthesis stages. Stdlib only, frozen dataclasses, slots=True — same
discipline as agent/schemas.py for the receipt layer.

Hard rule (LLM PROPOSES. CODE DISPOSES.) extends to synthesis:
  - Tension detection: deterministic features (outcome_class, tier,
    directness, effect_sign). LLM never decides what's a tension.
  - Synthesis thesis: LLM proposes K candidates → code disposes by
    contract (must reference ≥3 receipts, must address ≥1 tension,
    no new numerics).
  - Synthesis prose: LLM-generated section text validated per
    sentence — every claim must map to a SynthesisClaimAnchor; no
    sentence may introduce numerics absent from any receipt.

Eight new structured types. Each documents the gate in its docstring.

Pipeline diagram:
  [N claim receipts]
    → ReceiptSummary (one-per-receipt structured summary, deterministic)
    → TensionMatrix (per-pair tensions, deterministic)
    → SynthesisThesisCandidate (K LLM proposals, validated)
    → SynthesisThesis (the picked candidate, code-disposed)
    → SynthesisSection (one per paper section, prose + claim anchors)
    → SynthesisPaper (the assembled artifact)
    → SynthesisQualityAudit (scores against 7-paper rubric)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "OutcomeClass",
    "EffectDirection",
    "TensionKind",
    "ReceiptSummary",
    "Tension",
    "TensionMatrix",
    "SynthesisClaimAnchor",
    "SynthesisThesisCandidate",
    "SynthesisThesis",
    "SynthesisSection",
    "SynthesisPaper",
    "QualityCheckResult",
    "SynthesisQualityAudit",
    "SynthesisInvariantError",
    "assert_synthesis_invariants",
]

# --- Enums ----------------------------------------------------------------

OutcomeClass = Literal[
    # Coarse outcome classification used for tension-pair compatibility.
    # Not the topic_pack's expected_evidence_slots (which is finer-grained
    # and pack-specific) — these are cross-topic categories that let the
    # tension matrix work on any drug pack without per-pack rules.
    "muscle_function",      # MASTERS-style hypertrophy / strength outcomes
    "cardiometabolic",      # CV mortality, glycemic control, lipids
    "cognitive",            # MMSE, dementia incidence, cognitive decline
    "frailty",              # walk speed, grip strength, frailty index
    "longevity",            # all-cause mortality, exceptional longevity
    "immune",               # vaccine response, RTI incidence, T-cell function
    "ophthalmologic",       # AMD, diabetic retinopathy
    "oncology",             # cancer incidence / mortality (often indirect)
    "mechanism",            # in vitro / animal pathway findings
    "safety",               # adverse events, tolerability, GI side effects
    "other",                # default — caller didn't classify
]

EffectDirection = Literal[
    "positive",   # treatment improves outcome (e.g. HR < 1 for mortality)
    "negative",   # treatment worsens outcome (e.g. HR > 1)
    "null",       # no statistically significant difference (p>=0.05 + effect~0)
    "mixed",      # significant findings in BOTH directions across endpoints
    "unclear",    # signs ambiguous, only-mechanistic, or inconclusive
]

TensionKind = Literal[
    "agreement",       # both receipts point same direction on same outcome class
    "disagreement",    # receipts point opposite directions on same outcome class
    "indirectness_gap",  # one direct trial finding + one mechanistic claim about
                       # the same outcome class — synthesis must keep them separate
    "null_vs_positive",  # one receipt is null, another is positive — partial conflict
    # Day 10.17 Phase 2 — cross-domain tension. Different outcome
    # classes BUT one receipt is direct/clinical and the other is
    # mechanistic/preclinical. This is where the metformin paper's
    # central tension lives ("clinical muscle suppression observed
    # in c01" vs "preclinical longevity promise from c04") and the
    # old classifier wrongly buried it as "orthogonal" because the
    # outcome classes were different.
    "mechanism_vs_clinical",
    "orthogonal",      # receipts cover different outcome classes; no logical conflict
]


# --- ReceiptSummary -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReceiptSummary:
    """Compact structured view of one claim receipt.

    Built deterministically from the 8 receipt JSON files (claim_graph,
    spar_review, evidence_cards). The synthesis layer operates on these
    summaries, not the raw receipt dirs — keeps the multi-receipt
    surface small and predictable.

    `outcome_class` and `effect_direction` are the load-bearing fields
    for tension detection. They're derived from claim text + supporting
    evidence_cards, not LLM-inferred.
    """

    receipt_id: str                # output_dir leaf (e.g. metformin-001-...-abcd)
    receipt_path: str              # filesystem path to the receipt dir
    topic: str
    thesis_text: str
    spar_verdict: str              # accept_clean / accept_caveated / reject_*
    n_claims: int
    n_failed_traces: int
    canonical_trial_id: str | None  # NCT / ISRCTN if anchored on a canonical trial
    evidence_tier: str             # A1 / A2 / B / C / mixed
    directness: str                # direct / indirect / mechanistic
    outcome_class: OutcomeClass
    effect_direction: EffectDirection
    p_values: tuple[str, ...]      # canonical-form p-values mentioned in the thesis
    population_summary: str        # e.g. "older adults, age 65+" (extracted from abstract)
    # Day 10.17 Phase 3 — bibliographic fields surfaced from
    # evidence_cards.json so the rendered References section can show
    # publication-grade citations (Title, Year, Venue, DOI, PMID)
    # instead of internal cfab-c01 receipt IDs. All optional with
    # default None so existing test fixtures and old run dirs that
    # predate Phase 3 still construct cleanly.
    source_title: str | None = None
    source_year: int | None = None
    source_doi: str | None = None
    source_pmid: str | None = None
    source_venue: str | None = None


# --- TensionMatrix --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tension:
    """One pairwise tension between two receipts.

    The (receipt_a_id, receipt_b_id) pair is canonicalized so the
    comparison `< b` always holds — the matrix doesn't double-count.
    """

    receipt_a_id: str
    receipt_b_id: str
    kind: TensionKind
    outcome_class: OutcomeClass
    summary: str                   # one-line deterministic description
    severity: int                  # 0 (orthogonal) → 5 (direct disagreement on same outcome)


@dataclass(frozen=True, slots=True)
class TensionMatrix:
    """The full pairwise tension structure across N receipts.

    `pairs` is canonical (sorted by receipt_a_id, receipt_b_id). The
    synthesis writer reads this to render the Tensions section and to
    drive thesis-candidate validation (a synthesis thesis MUST address
    ≥1 tension when the matrix has any non-orthogonal entry).
    """

    receipts: tuple[ReceiptSummary, ...]
    pairs: tuple[Tension, ...]

    def non_orthogonal(self) -> tuple[Tension, ...]:
        """Tensions that actually constrain the thesis (kind != orthogonal)."""
        return tuple(p for p in self.pairs if p.kind != "orthogonal")


# --- SynthesisClaimAnchor -------------------------------------------------


@dataclass(frozen=True, slots=True)
class SynthesisClaimAnchor:
    """A single sentence in the synthesis paper, with its receipt anchors.

    Trust contract for synthesis prose: every sentence written by the
    LLM must produce one of these. `receipt_ids` lists the receipt_id(s)
    the sentence is grounded in. The synthesis writer's validator
    rejects any sentence with no anchor or with anchors that reference
    unknown receipts.

    `numerics` is the set of numeric tokens (p-values, percentages,
    HR/OR/RR values) the sentence cites. Code disposes by checking each
    numeric appears in at least one anchored receipt's claim_graph or
    citation_traces — no new numerics may enter the synthesis layer.
    """

    sentence: str
    receipt_ids: tuple[str, ...]
    numerics: tuple[str, ...]


# --- SynthesisThesisCandidate / SynthesisThesis ---------------------------


@dataclass(frozen=True, slots=True)
class SynthesisThesisCandidate:
    """One LLM-proposed candidate for the synthesis thesis.

    Day 10.3 thesis tournament: the LLM proposes K candidates (default 3),
    each is validated by code (referenced receipts exist, tensions
    addressed, no new numerics), the picker selects by deterministic
    score (receipts_referenced > tensions_addressed > brevity).
    """

    text: str
    receipt_ids_referenced: tuple[str, ...]
    tensions_addressed: tuple[str, ...]   # tension summaries the thesis names
    word_count: int


@dataclass(frozen=True, slots=True)
class SynthesisThesis:
    """The picked candidate. Embedded in `SynthesisPaper.thesis`."""

    text: str
    receipt_ids_referenced: tuple[str, ...]
    tensions_addressed: tuple[str, ...]
    rejected_candidates: tuple[SynthesisThesisCandidate, ...]  # for audit
    picker_rationale: str           # one-line deterministic explanation


# --- SynthesisPaper -------------------------------------------------------


SectionName = Literal[
    # --- Brief (~870-word) layer (Day 10.x) — the structured evidence
    # summary, retained verbatim per Day 10.16 reviewer guidance: brief
    # is the auditable evidence layer, paper is the publishable artifact.
    "title",
    "thesis",
    "evidence_summary",     # deterministic table of receipts
    "direct_evidence",      # deterministic — accepted direct receipts
    "indirect_evidence",    # deterministic — accepted mechanistic / review receipts
    "rejected_evidence",    # Day 10.10 — quarantine: SPAR-rejected receipts listed
                            # for transparency but NOT cited as evidence in synthesis
    "tensions",             # mixed — LLM enumerates tensions from matrix
    "synthesis",            # LLM — paragraphs anchored to ACCEPTED receipts only
    "limitations",          # LLM with template scaffold per evidence tier mix
    "spar_adjudication",    # deterministic from receipt-level + synthesis-level SPAR
    "references",           # deterministic — every receipt's source papers
    # --- Full-paper layer (Day 10.16) — multi-section publishable
    # artifact. Each section has a designated validation tier
    # (anchored / scoped / deterministic) — see paper_writer.py.
    "abstract",             # ~300 words; ANCHORED — every claim cites receipt
    "introduction",         # ~1500-2500; SCOPED — topic-relevant + hedged
    "background",           # ~1000-2000; SCOPED — broader field synthesis
    "quantitative_results_table",  # DETERMINISTIC — per-study n / effect / CI / p
                            # markdown table built from corpus quant_claims;
                            # universal Q9 numeric-density structural fix.
                            # See agent/results_table.py.
    "methods",              # ~1000-1500; DETERMINISTIC — describes SPAR pipeline
    "results",              # ~3000-5000; ANCHORED — multi-paragraph by outcome class
    "cross_domain_synthesis",  # ~800-1500; ANCHORED — integrates outcomes with
                            # cross-outcome tensions
    "discussion",           # ~2000-3000; SCOPED — evidence-says vs interpretation
    "limitations_full",     # ~500-1000; ANCHORED — includes quarantine rationale
    "conclusion",           # ~300-500; SCOPED — hedged summary
    "references_full",      # DETERMINISTIC — formatted citations from receipt metadata
]


@dataclass(frozen=True, slots=True)
class SynthesisSection:
    """One section of the synthesis paper.

    `body_md` is the rendered markdown for the section. `anchors` lists
    the per-sentence claim anchors for the LLM-generated sections (empty
    tuple for deterministic sections — `evidence_summary`,
    `direct_evidence`, etc.).
    """

    name: SectionName
    body_md: str
    anchors: tuple[SynthesisClaimAnchor, ...]


@dataclass(frozen=True, slots=True)
class SynthesisPaper:
    """The assembled synthesis artifact.

    `body_md` is the full paper as markdown — what gets written to
    `paper_synthesis.md`. `sections` carries the structured pieces so
    audit code can inspect them individually.
    """

    submission_id: str
    topic: str
    thesis: SynthesisThesis
    matrix: TensionMatrix
    sections: tuple[SynthesisSection, ...]
    body_md: str
    render_version: str             # e.g. "synthesis-writer/2026-04-29"


# --- SynthesisQualityAudit ------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityCheckResult:
    """One quality-checklist question evaluated against the synthesis paper.

    The 7 questions live in `agent/prompts/judge_quality_checklist.md`,
    each keyed to a paper from the 7-paper Quality Reference Corpus.

    Day 10.7 (reviewer P2): `applicable=False` means the corpus lacks
    the evidence type this check evaluates (e.g. no null receipts to
    test Q2, no safety receipts to test Q6). Vacuous passes (corpus
    has nothing to check) MUST NOT inflate the audit score — the
    aggregate is `passed_applicable / total_applicable * 10`, with a
    minimum-applicable floor before the score is meaningful.
    """

    question_id: str                # e.g. "Q1-konopka-p008-hedging"
    question: str
    passed: bool
    detail: str
    excerpt: str | None = None      # passage from synthesis paper, if relevant
    applicable: bool = True          # False means "corpus lacks this evidence type"


@dataclass(frozen=True, slots=True)
class SynthesisQualityAudit:
    """The full audit of the synthesis paper against the rubric.

    `score` is the count of passed checks divided by total, scaled to
    /10. Day 10 ship criterion: ≥8.5/10. Below that, the synthesis is
    not publishable.
    """

    submission_id: str
    checks: tuple[QualityCheckResult, ...]
    score: float                    # 0.0 → 10.0
    notes: str


# --- Invariants -----------------------------------------------------------


class SynthesisInvariantError(AssertionError):
    """Raised when synthesis structure violates contract."""


def assert_synthesis_invariants(paper: SynthesisPaper) -> None:
    """Verify the synthesis paper is structurally well-formed.

    - thesis must reference ≥1 receipt
    - tensions matrix must be canonical (sorted pairs)
    - every LLM-generated section's anchors must reference real receipts
    - sections list must include thesis + evidence_summary + references at minimum
    """
    if not paper.thesis.receipt_ids_referenced:
        raise SynthesisInvariantError(
            "synthesis thesis must reference at least one receipt"
        )

    receipt_ids = {r.receipt_id for r in paper.matrix.receipts}
    for sect in paper.sections:
        for anchor in sect.anchors:
            for rid in anchor.receipt_ids:
                if rid not in receipt_ids:
                    raise SynthesisInvariantError(
                        f"section {sect.name!r} anchor references unknown "
                        f"receipt_id {rid!r}; matrix has {sorted(receipt_ids)}"
                    )

    # Canonical pair ordering
    for pair in paper.matrix.pairs:
        if pair.receipt_a_id >= pair.receipt_b_id:
            raise SynthesisInvariantError(
                f"tension pair not canonically ordered: "
                f"({pair.receipt_a_id!r}, {pair.receipt_b_id!r}) — "
                f"a < b required"
            )

    required_sections = {"title", "thesis", "evidence_summary", "references"}
    section_names = {s.name for s in paper.sections}
    missing = required_sections - section_names
    if missing:
        raise SynthesisInvariantError(
            f"synthesis paper missing required sections: {sorted(missing)}"
        )
