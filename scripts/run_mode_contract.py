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
    output is bounded so it cannot contain blocked phrases.

    Output structure: short narrative naming what ran + an ordered
    list of pipeline stages + a CONDITIONAL "did NOT run" disclosure
    block (only emitted when at least one stage did NOT run)."""
    stages_md = "\n".join(
        f"{i}. {stage}." for i, stage in enumerate(c.deterministic_stages, 1)
    )

    not_run_lines: list[str] = []
    if not c.spar_adjudication_ran:
        not_run_lines.append(
            "- SPAR (multi-judge panel adjudication) did NOT run on this corpus."
        )
    if not c.multi_receipt_clusters_ran:
        not_run_lines.append(
            "- Multi-receipt cluster aggregation did NOT run."
        )
    if not c.llm_fact_extraction_ran:
        not_run_lines.append(
            "- LLM fact extraction (extraction-time fact proposing) did NOT "
            "run; claims came from deterministic regex extraction over per-"
            "paper source documents."
        )
    if not c.rejected_evidence_quarantine_ran:
        not_run_lines.append(
            "- Rejected-evidence quarantine did NOT run (no SPAR rejections "
            "to quarantine)."
        )

    # Conditionally include the disclosure section ONLY when there's
    # something to disclose. A future run with all flags True will
    # silently omit the section instead of leaving a header dangling.
    not_run_section = ""
    if not_run_lines:
        not_run_section = (
            "### What did NOT run\n\n"
            "Explicit-absence audit-trail block — earlier drafts inherited "
            "Methods boilerplate describing pipeline stages that were not "
            "actually executed.\n\n"
            + "\n".join(not_run_lines)
            + "\n\n"
        )

    return (
        f"## Methods\n\n"
        f"This synthesis was produced by the **{c.run_mode}** pipeline "
        f"on the *{c.topic}* corpus (submission `{c.submission_id}`). "
        f"All claims trace to one of {c.n_papers_in_corpus} curated source "
        f"papers and {c.n_high_confidence_claims_used_by_writer} "
        f"high-confidence bound claims used by the writer. Citations, "
        f"evidence tiers, numeric claims, and thesis selection are constrained "
        f"by the run registry and audit record.\n\n"
        f"### LLM roles\n\n"
        f"- **Writer:** `{c.writer_model}` produces section prose given "
        f"the deterministic receipts + thesis as structured input.\n"
        f"- **In-writing reviewer:** `{c.in_writing_judge_model}` judges "
        f"each section against the receipt set; failed sections trigger "
        f"a writer revision pass.\n"
        f"- **Final-layer reviewer:** `{c.final_layer_reviewer_model}` "
        f"performs a final adversarial pass over the assembled paper "
        f"(fallback `{c.final_layer_fallback_model}` if the primary is "
        f"unreachable). Patches are auto-applied subject to a single-"
        f"occurrence mechanical safety gate.\n\n"
        f"### Pipeline stages (deterministic, in order)\n\n"
        f"{stages_md}\n\n"
        f"{not_run_section}"
        f"### Claim source\n\n"
        f"`{c.claim_source}` — the canonical ground truth for every "
        f"sentence in this paper.\n"
    )


def validate_rendered(methods_md: str) -> list[str]:
    """Return SORTED list of blocked phrases found in the rendered
    Methods. Empty list = clean. Case-insensitive substring match.

    Excludes the `### What did NOT run` disclosure block from the
    haystack — that block is BY DESIGN explicit-named ('Multi-receipt
    cluster aggregation did NOT run' must mention 'multi-receipt
    cluster'). Validation only runs against assertion prose."""
    # Strip the disclosure section if present.
    haystack_md = re.sub(
        r"^### What did NOT run\b.*?(?=^### |\Z)",
        "",
        methods_md,
        flags=re.MULTILINE | re.DOTALL,
    )
    haystack = haystack_md.lower()
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
