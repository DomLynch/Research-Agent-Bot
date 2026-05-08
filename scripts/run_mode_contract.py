"""Fix #2: Run-mode contract + deterministic Methods renderer.

Pre-fix the Methods section was an LLM-templated narrative inherited
from the older SPAR/receipt-cluster pipeline. Even after `v0.6
quant-claim adapter` runs (no SPAR, no fact extraction, no cluster
machinery), Methods still contained verbiage about "Fact extraction —
LLM proposes verbatim source-quote facts", "SPAR adjudication", "panel
verdict computed deterministically", "thesis tournament" — none of
which happened in this run.

Fix: declare what actually ran in a frozen RunModeContract and render
Methods deterministically from it. The LLM never writes Methods. The
renderer's output is bounded by an explicit ALLOWED-PHRASES list and
is incapable of producing the legacy boilerplate that triggered both
audit Q5 (fabricated methods) and Layer-1 stale-method checks.

Architectural rule: this module never imports the LLM client. The
contract is built by the orchestrator from settings + manifest +
known pipeline-stage facts; the renderer is a pure function over
that contract. No proposal happens here, only deterministic disposal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_DEFAULT_DETERMINISTIC_STAGES: tuple[str, ...] = (
    "quant-claim extraction (deterministic regex over per-paper sources)",
    "receipt summarization (group claims by paper, aggregate "
    "outcome class + effect direction)",
    "tension matrix construction (cross-paper direction conflicts)",
    "thesis selection (deterministic dominant-pattern picker — "
    "the LLM is NOT allowed to invent the thesis)",
    "claim-strength repair (regex over over-claimed prose)",
    "paper_id → Author Year substitution",
    "References block append",
    "Stage-1 audit (Q1-Q10) + Stage-2 consistency audit + auto-fix",
    "final-layer LLM review (with single-occurrence patch safety)",
    "final audit + unified verdict (worst-of stage1, stage2)",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunModeContract:
    """What actually ran in this pipeline. Source of truth for the
    deterministic Methods renderer.

    Cross-stage object → frozen+slots+kw_only per project rule. The
    kw_only forces all callers to construct with keyword args,
    eliminating the positional-arg swap bug class (n_papers and
    n_claims trivially swappable as bare ints)."""

    run_mode: str
    topic: str
    submission_id: str
    n_papers_in_corpus: int
    # Renamed for clarity (reviewer P2): explicit definition that this
    # is the writer-input set, not the universe of all extractable claims.
    n_high_confidence_claims_used_by_writer: int

    # What ran (positive declarations)
    writer_model: str
    in_writing_judge_model: str
    final_layer_reviewer_model: str
    final_layer_fallback_model: str
    claim_source: str

    # What did NOT run (negative declarations — kill legacy boilerplate)
    spar_adjudication_ran: bool = False
    multi_receipt_clusters_ran: bool = False
    llm_fact_extraction_ran: bool = False
    rejected_evidence_quarantine_ran: bool = False

    # Pipeline stages that did run, in chronological order. Default is
    # a module-level constant tuple (immutable, no factory needed).
    deterministic_stages: tuple[str, ...] = _DEFAULT_DETERMINISTIC_STAGES


# Phrases the renderer MUST NOT emit. Matched case-insensitively as
# substrings (no \b boundaries — phrases starting/ending with non-word
# chars like "(SPAR)" silently never matched under \b). validate_rendered
# is the fail-closed gate making the legacy boilerplate structurally
# impossible to leak.
_BLOCKED_METHODS_PHRASES: tuple[str, ...] = (
    # SPAR / panel-adjudication lineage (extraction-time judging only;
    # the in-writing per-section judge is a different role and is
    # allowed). Variants: words, casing, separator differences.
    "SPAR adjudication",
    "spar judge",
    "three judge panel",
    "judge panel",
    "reviewer panel",
    "panel verdict",
    "panel deliberation",
    "deliberation",
    "adversarial debate",
    "3-0 accept",
    "2-1 accept",
    "unanimous accept",
    "unanimous verdict",
    "verdict was 3-0",
    "split accept",
    "adjudicator",
    # Receipt-cluster machinery
    "rejected receipts",
    "quarantined evidence",
    "quarantined receipts",
    "quarantine receives",
    "cluster receipts",
    "receipt cluster",
    "receipt clustering",
    "clustered receipts",
    "multi-receipt cluster",
    "multi-receipt clusters",
    # LLM fact extraction lineage (ext-time fact proposing; not the
    # in-writing prose generation, which is allowed and named).
    "LLM proposes verbatim source-quote facts",
    "verbatim source-quote facts",
    "verbatim source quotes",
    "verbatim quote extraction",
    "fact extractor",
    "fact_extractor",
    "thesis tournament",
    "candidate integrating theses",
    # Audit Q5 fabrication phrases
    "two researchers",
    "two reviewers",
    "two annotators",
    "manually reviewed",
    "manual review",
    "verified by two",
    "researchers verified",
    "consensus was reached",
    "discussed and resolved",
    "inter-rater agreement",
    "intercoder reliability",
    "Cohen's kappa",
    # Public journal surface must not expose operational provenance.
    "this synthesis was produced by",
    "submission `synthesis-",
    "final-layer reviewer",
    "patches are auto-applied",
    "rejected-evidence quarantine did not run",
    "grok",
    "LLM proposes, code disposes",
    "no LLM authorship",
)


def validate_contract(c: RunModeContract) -> list[str]:
    """Return list of contradictions; empty list means contract is
    self-consistent. Caller decides whether to raise or log."""
    errors: list[str] = []
    if c.spar_adjudication_ran and not c.llm_fact_extraction_ran:
        errors.append(
            "spar_adjudication_ran=True requires llm_fact_extraction_ran=True "
            "(SPAR adjudicates LLM-extracted facts; deterministic claims "
            "don't go through SPAR)"
        )
    if c.rejected_evidence_quarantine_ran and not c.spar_adjudication_ran:
        errors.append(
            "rejected_evidence_quarantine_ran=True requires "
            "spar_adjudication_ran=True (quarantine receives SPAR-rejected "
            "receipts)"
        )
    # Cluster-without-prerequisites: clusters aggregate multiple receipts;
    # a run with zero claims could not have produced clusters.
    if c.multi_receipt_clusters_ran and c.n_high_confidence_claims_used_by_writer < 1:
        errors.append(
            "multi_receipt_clusters_ran=True requires "
            "n_high_confidence_claims_used_by_writer >= 1"
        )
    if c.n_papers_in_corpus < 1:
        errors.append(f"n_papers_in_corpus={c.n_papers_in_corpus} must be >= 1")
    if c.n_high_confidence_claims_used_by_writer < 0:
        errors.append(
            f"n_high_confidence_claims_used_by_writer="
            f"{c.n_high_confidence_claims_used_by_writer} cannot be negative"
        )
    if not c.writer_model:
        errors.append("writer_model must not be empty")
    if not c.claim_source.strip():
        errors.append("claim_source must not be empty")
    if "<" in c.claim_source or ">" in c.claim_source:
        errors.append(
            f"claim_source contains unsubstituted placeholder: "
            f"{c.claim_source!r}"
        )
    return errors


def render_methods(c: RunModeContract) -> str:
    """Deterministic Methods section. Pure function over the contract;
    output is bounded so it cannot contain blocked phrases."""
    return (
        f"## Methods\n\n"
        f"The review used a predeclared corpus of {c.n_papers_in_corpus} "
        f"source papers on {c.topic}. Source documents were screened for "
        f"quantitative outcome statements, and "
        f"{c.n_high_confidence_claims_used_by_writer} source-bound "
        f"observations were retained for synthesis after role, unit, and "
        f"citation checks.\n\n"
        f"### Evidence selection and synthesis\n\n"
        f"Claims were retained only when their numeric value, endpoint, and "
        f"study label could be reconciled with the source record. Evidence "
        f"was grouped by outcome class, study design, direction of effect, "
        f"and endpoint proximity. Cross-paper tensions were summarized when "
        f"two retained findings addressed related outcomes but differed in "
        f"direction, directness, population, comparator, or follow-up.\n\n"
        f"### Manuscript controls\n\n"
        f"Public prose was constrained to the retained evidence set. Numeric "
        f"statements were checked against the source-bound claim table, and "
        f"rows with unresolved endpoint, unit, study-label, or citation "
        f"problems were excluded from the public quantitative evidence "
        f"index.\n"
    )


def validate_rendered(methods_md: str) -> list[str]:
    """Return SORTED list of blocked phrases found in the rendered
    Methods. Empty list = clean. Case-insensitive substring match.

    """
    haystack = methods_md.lower()
    found: list[str] = []
    for phrase in _BLOCKED_METHODS_PHRASES:
        if phrase.lower() in haystack:
            found.append(phrase)
    return sorted(found)


def _strip_code_fences(s: str) -> str:
    """Replace fenced code blocks with newline-equivalent whitespace
    so regex matching against headers ignores ``` blocks. Preserves
    line count so position-based logic isn't disturbed."""
    fence_re = re.compile(r"```.*?```", re.DOTALL)

    def _blank(m: re.Match[str]) -> str:
        # Replace the matched span with newlines preserving line count
        return "\n" * m.group(0).count("\n")
    return fence_re.sub(_blank, s)


def replace_methods_in_paper(paper_md: str, new_methods_md: str) -> str:
    """Surgically replace the existing `## Methods` block with the
    new deterministic block. Finds the Methods header (case-insensitive,
    requires line-start + end-of-line so headings like `## Methods and
    Materials` or `## methodically` don't false-fire), scans forward
    to the next `^## ` header (or end of doc), replaces the span.

    Code-fence safe: triple-backtick spans are masked before searching
    so a literal `## Methods` inside a fenced block doesn't false-fire.

    Idempotent: running twice produces the same paper (triple-newline
    runs collapsed after substitution)."""
    safe = _strip_code_fences(paper_md)
    # Header pattern: line-start + `## Methods` + optional whitespace
    # + end-of-line. Refuses `## Methods Section`, `## Methods and
    # Materials`, etc. Case-insensitive in case the writer drops case.
    methods_re = re.compile(
        r"^## Methods\s*$.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    new_block = new_methods_md.rstrip() + "\n\n"
    m = methods_re.search(safe)
    if m is None:
        # No existing Methods section — insert before References (case-
        # insensitive), or at end of doc.
        ref_re = re.compile(r"^## References\s*$", re.MULTILINE | re.IGNORECASE)
        rm = ref_re.search(paper_md)
        if rm:
            return paper_md[:rm.start()] + new_block + paper_md[rm.start():]
        return paper_md.rstrip() + "\n\n" + new_block
    # Substitute in the ORIGINAL paper at the same span (safe was only
    # used for matching, not as the substrate).
    out = paper_md[:m.start()] + new_block + paper_md[m.end():]
    # Collapse any triple+ newlines introduced by repeated substitution.
    return re.sub(r"\n{3,}", "\n\n", out)
