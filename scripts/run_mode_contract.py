"""Run-mode contract and deterministic public Methods renderer.

The LLM never writes Methods. The orchestrator freezes what actually
ran in RunModeContract; this module renders only from that contract and
blocks legacy pipeline boilerplate from public manuscript prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.template_language import mask_fenced_markdown


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

    # Empty defaults are fail-closed: callers must freeze positive evidence.
    deterministic_stages: tuple[str, ...] = ()
    source_inventory: tuple[tuple[str, str], ...] = ()
    # Public protocol statements are part of the frozen run contract;
    # render_methods must not invent process claims outside this tuple.
    methods_protocol: tuple[str, ...] = ()


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
    if any(not item.strip() for item in c.methods_protocol):
        errors.append("methods_protocol must contain only non-empty statements")
    valid_statuses = {"enabled", "succeeded", "failed"}
    if any(
        not name.strip() or status not in valid_statuses
        for name, status in c.source_inventory
    ):
        errors.append(
            "source_inventory entries require a name and an "
            "enabled/succeeded/failed status"
        )
    return errors


def render_methods(c: RunModeContract) -> str:
    """Deterministic Methods section. Pure function over the contract;
    output is bounded so it cannot contain blocked phrases."""
    topic_label = c.topic.replace("_", " ").replace("-", " ").strip()
    parts = [
        "## Methods",
        (
            f"The frozen run contract records {c.n_papers_in_corpus} "
            f"source papers on {topic_label} and "
            f"{c.n_high_confidence_claims_used_by_writer} source-bound "
            "observations supplied to the manuscript writer."
        ),
    ]
    if c.source_inventory:
        succeeded = sum(
            status == "succeeded" for _, status in c.source_inventory
        )
        failed = sum(status == "failed" for _, status in c.source_inventory)
        pending = sum(status == "enabled" for _, status in c.source_inventory)
        parts.append(
            "### Information sources\n\n"
            f"The frozen inventory records {len(c.source_inventory)} enabled "
            f"sources: {succeeded} succeeded, {failed} failed, and {pending} "
            "enabled without a recorded outcome."
        )
    parts.extend(c.methods_protocol)
    return "\n\n".join(parts) + "\n"


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
    safe = mask_fenced_markdown(paper_md)
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
