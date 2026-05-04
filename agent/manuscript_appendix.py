"""Researka manuscript appendix composer (Phase A polish).

Adds the four publication-ready sections that journals expect from
AI-generated research synthesis:

  1. Search Provenance     — honest reconstruction of what databases
                             were queried, what filters applied, what
                             scoring decided which papers reached
                             synthesis. Acknowledges this is NOT a
                             PRISMA-compliant systematic review; it's
                             an auditable agent-to-agent synthesis
                             with the equivalent transparency layer.
  2. AI-Use Disclosure     — ICMJE-compliant statement. Names every
                             model used, what role it played, what
                             gates constrained it. Modeled on Nature/
                             BMJ/ICMJE 2024 guidance.
  3. Human Accountability  — template for the human submitter to
                             fill in their name, affiliation, and
                             accountability statement (per ICMJE,
                             AI cannot be an author).
  4. Data & Code Availability — links to the public bundle, run ID,
                             git SHA at certification, and
                             reproduction recipe.

Pure-Python composer. No LLM calls. Reads from the run manifest,
audit, and model-stack metadata.

Usage from orchestrator (Stage 5 post-audit):
    from agent.manuscript_appendix import compose_appendix
    appendix_md = compose_appendix(manifest, audit, model_stack,
                                   run_id=..., git_sha=...)
    paper_md = paper_md.replace(
        "## References", appendix_md + "\\n\\n## References", 1,
    )
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


__all__ = [
    "build_search_provenance_appendix",
    "build_ai_use_disclosure",
    "build_human_accountability_template",
    "build_data_code_availability",
    "compose_appendix",
]


# Databases the retrieval layer can query. Source of truth:
# agent/sources/*.py (clinicaltrials, europepmc, openalex, pubmed).
# bioRxiv + ChEMBL are MCP-available but not yet wired into the
# default retrieval; documented honestly here.
_DATABASES_QUERIED = [
    {
        "name": "PubMed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
        "client": "agent.sources.pubmed.PubMedClient",
        "purpose": "biomedical literature, indexed",
    },
    {
        "name": "Europe PMC",
        "url": "https://europepmc.org/",
        "client": "agent.sources.europepmc.EuropePMCClient",
        "purpose": "biomedical literature + preprints + full-text",
    },
    {
        "name": "OpenAlex",
        "url": "https://openalex.org/",
        "client": "agent.sources.openalex.OpenAlexClient",
        "purpose": "open scholarly graph (250M+ works)",
    },
    {
        "name": "ClinicalTrials.gov",
        "url": "https://clinicaltrials.gov/",
        "client": "agent.sources.clinicaltrials.ClinicalTrialsClient",
        "purpose": "registered clinical trials (NCT IDs)",
    },
]

_DATABASES_NOT_QUERIED = [
    "bioRxiv / medRxiv (preprints — MCP-available, not in default "
    "retrieval pipeline)",
    "Web of Science (subscription, not used)",
    "Scopus (subscription, not used)",
    "Google Scholar (no stable API; not used)",
    "Cochrane Library (not yet integrated)",
]


def build_search_provenance_appendix(
    manifest: dict[str, Any], topic: str = "metformin",
) -> str:
    """Compose the Search Provenance section.

    Reads from the manifest to report receipts, claims, tensions,
    tier/directness distribution. Names every database queried.
    Acknowledges what was NOT queried. Honest framing as 'auditable
    agent-to-agent synthesis' NOT 'PRISMA systematic review'."""
    receipts = manifest.get("receipts", [])
    # Prefer explicit n_receipts field; fall back to list length.
    # The orchestrator writes both, but a synthetic test fixture
    # may only set the field.
    n_receipts = manifest.get("n_receipts", len(receipts))
    n_claims = manifest.get("n_high_confidence_claims_total", 0)
    n_tensions = manifest.get("n_non_orthogonal_tensions", 0)

    tier_counts = Counter(
        r.get("evidence_tier", "?") for r in receipts
    )
    direct_counts = Counter(
        r.get("directness", "?") for r in receipts
    )
    outcome_counts = Counter(
        r.get("outcome_class", "?") for r in receipts
    )

    lines = [
        "## Search Provenance and Selection",
        "",
        f"This synthesis on **{topic}** is an **auditable "
        f"agent-to-agent (A2A) evidence synthesis**, not a PRISMA-"
        f"compliant systematic review. We do not claim formal "
        f"compliance with the PRISMA 2020 reporting checklist or "
        f"prospective registration in PROSPERO. Instead, this "
        f"section reports the equivalent transparency layer the "
        f"Researka pipeline produces automatically.",
        "",
        "### Databases queried",
        "",
        "| Database | Purpose | Client |",
        "|---|---|---|",
    ]
    for db in _DATABASES_QUERIED:
        lines.append(
            f"| [{db['name']}]({db['url']}) | {db['purpose']} | "
            f"`{db['client']}` |"
        )
    lines += [
        "",
        "### Databases NOT queried (transparency)",
        "",
    ]
    for db in _DATABASES_NOT_QUERIED:
        lines.append(f"- {db}")
    lines += [
        "",
        "### Selection logic",
        "",
        "Papers were retrieved per topic via the deterministic "
        f"`agent/sources/` clients above. The retrieval pool was "
        f"filtered to a corpus of high-confidence quant-extractable "
        f"papers (full corpus: see "
        f"`docs/quality-reference/{topic}/quant_claims/`). Of these, "
        f"**{n_receipts} contributing papers** had sufficient claim "
        f"density to enter the synthesis as evidence receipts. "
        f"Selection was deterministic — the LLM proposed; "
        f"the receipt builder disposed via the receipt-summary "
        f"density gate.",
        "",
        "### Per-receipt summary",
        "",
        f"- Total receipts contributing to synthesis: **{n_receipts}**",
        f"- Total high-confidence quantitative claims: **{n_claims}**",
        f"- Non-orthogonal tensions identified: **{n_tensions}**",
        "",
        "**Evidence tier distribution:**",
        "",
        "| Tier | Description | Count |",
        "|---|---|---|",
    ]
    tier_descriptions = {
        "A1": "RCT or registered trial (highest)",
        "A2": "Human mechanistic / observational with adequate n",
        "B1": "Review or meta-analysis",
        "B2": "Observational, indirect",
        "C1": "Preclinical",
        "C2": "In vitro",
    }
    for tier in sorted(tier_counts):
        desc = tier_descriptions.get(tier, "?")
        lines.append(f"| {tier} | {desc} | {tier_counts[tier]} |")

    lines += [
        "",
        "**Directness distribution:**",
        "",
        "| Directness | Count |",
        "|---|---|",
    ]
    for d in sorted(direct_counts):
        lines.append(f"| {d} | {direct_counts[d]} |")

    lines += [
        "",
        "**Outcome-class coverage:**",
        "",
        "| Outcome class | Receipts |",
        "|---|---|",
    ]
    for o in sorted(outcome_counts):
        lines.append(f"| {o} | {outcome_counts[o]} |")

    lines += [
        "",
        "### What this enables a reader to verify",
        "",
        "1. Reproduce the database queries via the source clients.",
        "2. Recompute the receipt-density filter on the corpus.",
        "3. Trace every numeric claim in the synthesis to its "
        "source receipt + corpus quant-claim file.",
        "4. Audit the tier/directness assignment per receipt "
        "against the topic pack rules.",
        "",
        "Reproduction recipe: see **Data and Code Availability** "
        "below.",
        "",
        "### Limitations of this selection approach (vs PRISMA)",
        "",
        "- No prospective protocol registration (cf. PROSPERO).",
        "- No blinded dual-screener pass.",
        "- No formal risk-of-bias scoring per Cochrane RoB tools.",
        "- Database coverage is narrower than a full systematic "
        "review (4 databases vs typical 6-10).",
        "- The synthesis is automated and reproducible, but "
        "automation does not substitute for domain-expert framing "
        "of the question or interpretation of clinical implications.",
        "",
        "Future versions of the Researka pipeline will add bioRxiv, "
        "Cochrane, and dual-screener support to close the gap "
        "toward formal systematic-review compliance.",
    ]
    return "\n".join(lines) + "\n"


def build_ai_use_disclosure(
    manifest: dict[str, Any],
    audit: dict[str, Any] | None = None,
    model_stack: dict[str, str] | None = None,
) -> str:
    """ICMJE-compliant AI-use disclosure statement.

    Per ICMJE 2024 / Nature 2024 / BMJ 2024 guidance: AI cannot be
    listed as author; humans remain accountable; AI use must be
    disclosed at submission with what role each model played."""
    model_stack = model_stack or {}
    n_llm_calls = manifest.get("n_llm_calls", 0)
    cost_usd = float(manifest.get("total_cost_usd", 0.0))
    extractor_version = manifest.get("extractor_version", "v0.6.x")
    repairs = manifest.get("claim_strength_repairs", 0)

    lines = [
        "## AI-Use Disclosure (ICMJE-Compliant)",
        "",
        "Per **ICMJE Recommendations on AI-Use by Authors** "
        "(2024), **Nature Editorial Policies on AI** (2024), and "
        "**BMJ AI-use Policy** (2024), the following discloses "
        "the role of AI in producing this manuscript.",
        "",
        "### Models used and their roles",
        "",
        "| Role | Model | Constraint Layer |",
        "|---|---|---|",
    ]
    role_constraints = {
        "writer": (
            "Output gated by section-word floors, citation "
            "registry, and Stage-1 audit (Q1-Q13)"
        ),
        "extractor": (
            "Output schema-validated; binding_confidence='high' "
            "filter applied"
        ),
        "reviewer": (
            "Patches gated by smart-gate (no new numerics/citations); "
            "repair-loop fallback; auto-strip safety net"
        ),
        "thesis": (
            "Output deterministically selected by 6-dim tournament "
            "scoring"
        ),
        "judge": (
            "Tie-break only when bound thesis tournament is degenerate"
        ),
    }
    for role in sorted(model_stack):
        model = model_stack[role]
        constraint = role_constraints.get(
            role, "schema-validated output"
        )
        lines.append(f"| {role} | `{model}` | {constraint} |")

    lines += [
        "",
        "### What AI did NOT do",
        "",
        "- AI did not select the research question or topic scope.",
        "- AI did not interpret clinical implications without "
        "deterministic-rule constraint.",
        "- AI did not write or edit prose without claim-registry "
        "and citation-registry validation.",
        "- AI did not adjudicate evidence tier or directness — "
        "those are set by the receipt-builder per topic-pack rules.",
        "- AI did not produce or modify the deterministic Methods "
        "section (built from manifest by `build_methods_section`).",
        "- AI did not produce or modify References (built "
        "deterministically from receipts by "
        "`build_references_full_section`).",
        "",
        "### Trust-spine architecture (what gates AI output)",
        "",
        "Every LLM-produced sentence in this manuscript survived "
        "the following deterministic gates:",
        "",
        "1. **Citation registry** — every citation must resolve to "
        "a registered receipt or background-literature entry.",
        "2. **Numeric registry** — every numeric must trace to a "
        "corpus quant-claim or background-literature entry.",
        "3. **Stage-1 audit (Q1-Q13)** — quantitative checks: "
        "numeric integrity, citation coverage, polarity, depth "
        "floors, hedge density, analytical ratio.",
        "4. **Stage-2 consistency audit (C01-C14)** — surface "
        "checks: no duplicate sections, no internal labels, no "
        "change-value misreads, no anaphoric misreads (Fix #54), "
        "no internal-pipeline metadata leaks (Fix #56).",
        "5. **Smart-gate review (Grok)** — adversarial reviewer "
        "patches must pass safety simplification rules (no new "
        "numerics, no new citations, no new identifiers, AFTER "
        "words ⊆ BEFORE words).",
        "6. **No-regression gate** — run cannot worsen any of: "
        "P1 count, numeric traceability, consistency-issue count, "
        "citation leakage, word count, orphan-citation blocks vs "
        "the prior baseline.",
        "7. **Researka A2A-AAA cert** — all of the above must be "
        "clean for ≥2 consecutive runs (see "
        "`full_paper.certification.md`).",
        "",
        "### Run-level disclosure",
        "",
        f"- Total LLM calls: **{n_llm_calls}**",
        f"- Total LLM cost: **${cost_usd:.4f} USD**",
        f"- Extractor pipeline version: **{extractor_version}**",
        f"- Claim-strength repair passes: **{repairs}**",
        "",
        "### Adverse-effect disclosure",
        "",
        "Known limitations of this AI-generated synthesis:",
        "",
        "- LLM hallucination can produce plausible-but-untraceable "
        "claims; the trust-spine gates above catch these but "
        "absence of evidence is not evidence of absence.",
        "- The corpus is bounded by what the retrieval clients "
        "could fetch on the cutoff date (see manifest "
        "`generated_at`).",
        "- The interpretation may reflect biases in the underlying "
        "model training data; the deterministic registries reduce "
        "but do not eliminate this.",
        "- The reviewer model (Grok) and writer model differ to "
        "reduce same-family blind spots, but adversarial review "
        "is not infallible.",
    ]
    return "\n".join(lines) + "\n"


def build_human_accountability_template() -> str:
    """Per ICMJE: AI cannot be listed as an author. A named human
    must accept accountability for the final manuscript. This is a
    template for the human submitter to fill in."""
    return (
        "## Human Accountability Statement\n"
        "\n"
        "Per ICMJE 2024 guidance, AI tools cannot be listed as "
        "authors and human accountability is required for the "
        "final manuscript. The following human(s) accept "
        "accountability for the content of this manuscript:\n"
        "\n"
        "**Submitter:** _[Human submitter to fill in: name, "
        "affiliation, ORCID, contact]_\n"
        "\n"
        "**Statement of accountability:**\n"
        "\n"
        "> The submitter has reviewed the AI-generated manuscript "
        "in full, including the certification artifact, audit "
        "report, consistency report, patch trail, and citation "
        "registry. The submitter accepts accountability for the "
        "accuracy and originality of the content, the integrity "
        "of the citations, the appropriateness of the AI-use "
        "disclosure, and the absence of plagiarism. Errors found "
        "post-publication will be corrected via standard erratum/"
        "correction procedures.\n"
        "\n"
        "**Conflict of interest:** _[Submitter to declare "
        "conflicts.]_\n"
        "\n"
        "**Funding:** _[Submitter to declare funding sources.]_\n"
        "\n"
        "**Ethics approval:** Not applicable — this is a "
        "secondary literature synthesis with no primary human or "
        "animal data collection.\n"
    )


def build_data_code_availability(
    run_id: str,
    git_sha: str,
    bundle_path: str | None = None,
    repo_url: str = "https://github.com/DomLynch/Research-Agent-Bot",
) -> str:
    """Data and Code Availability — links to the public bundle so
    a reviewer can reproduce the synthesis end-to-end."""
    bundle_str = (
        f"`{bundle_path}`" if bundle_path
        else "see `bundles/<run_id>/` in the source repository"
    )
    return (
        "## Data and Code Availability\n"
        "\n"
        "This manuscript is reproducible end-to-end. All artifacts "
        "are public.\n"
        "\n"
        "### Public bundle\n"
        "\n"
        f"**Run ID:** `{run_id}`\n"
        f"**Git SHA at certification:** `{git_sha}`\n"
        f"**Bundle path:** {bundle_str}\n"
        "\n"
        "The bundle contains: the manuscript itself, the Stage-1 "
        "audit (Q1-Q13), the Stage-2 consistency audit (C01-C14), "
        "the unified verdict, the Researka A2A-AAA certification, "
        "the full Grok review-patch list (raw), the orchestrator's "
        "decision per patch, the deterministic auto-fix log, the "
        "citation registry with traceback to corpus, the run "
        "manifest, and the no-regression report vs the prior "
        "baseline. README.md in the bundle root explains the "
        "layout and verification recipe.\n"
        "\n"
        "### Reproduce the synthesis\n"
        "\n"
        "```bash\n"
        f"git clone {repo_url}\n"
        f"cd Research-Agent-Bot && git checkout {git_sha}\n"
        "python scripts/run_v06_synthesis.py --topic metformin\n"
        "```\n"
        "\n"
        "The pipeline is deterministic given the corpus + topic "
        "pack + LLM seed. Re-running on the same corpus produces "
        "the same receipts, the same tensions, and the same "
        "audit verdict; the writer's prose varies stochastically "
        "but the trust-spine gates ensure the verdict converges.\n"
        "\n"
        "### Inspect the trust spine\n"
        "\n"
        "- Audit code: `scripts/audit_v06_paper.py` + "
        "`scripts/final_consistency_audit.py`\n"
        "- Cert code: `scripts/certification_report.py`\n"
        "- Patch-gate code: `scripts/apply_patches.py`\n"
        "- Repair-loop code: `scripts/run_v06_synthesis.py` "
        "(`_agent_repair_loop`)\n"
        "- Pipeline orchestrator: `scripts/run_v06_synthesis.py` "
        "(`_run`)\n"
        "\n"
        "### Found an error?\n"
        "\n"
        "If you find an unsupported claim, numeric misread, "
        "citation mismatch, or contradiction not surfaced by the "
        "audit/cert artifacts, please open an issue at "
        f"{repo_url}/issues. Errors found in the trust-spine itself "
        "(false negatives in the audit) are higher-priority than "
        "errors in the synthesis prose; both are welcome.\n"
    )


def compose_appendix(
    manifest: dict[str, Any],
    audit: dict[str, Any] | None = None,
    model_stack: dict[str, str] | None = None,
    *,
    topic: str = "metformin",
    run_id: str = "unknown-run",
    git_sha: str = "unknown",
    bundle_path: str | None = None,
) -> str:
    """Top-level composer. Returns the full appendix block, ready
    to splice into the paper before the References section.

    Order matters — Search Provenance comes first because it sets
    the methodological frame; AI-Use is the longest and most
    journal-required; Accountability and Data/Code are short
    closers."""
    blocks = [
        build_search_provenance_appendix(manifest, topic=topic),
        build_ai_use_disclosure(manifest, audit, model_stack),
        build_human_accountability_template(),
        build_data_code_availability(
            run_id, git_sha, bundle_path=bundle_path,
        ),
    ]
    return "\n\n".join(b.rstrip() for b in blocks) + "\n"


# Convenience: detect the splice point in an existing paper
_REFERENCES_SPLICE_RE = re.compile(
    r"(\n)(##\s+References\b)", re.MULTILINE,
)


def splice_appendix_before_references(
    paper_md: str, appendix_md: str,
) -> str:
    """Splice the appendix into the paper just before '## References'.

    Idempotent — if the appendix's lead heading already exists in
    the paper, returns the paper unchanged. Otherwise inserts the
    appendix block immediately before the first '## References'
    occurrence; if no References section exists, appends to end."""
    # Idempotency: don't double-insert
    if "## Search Provenance and Selection" in paper_md:
        return paper_md
    m = _REFERENCES_SPLICE_RE.search(paper_md)
    if m:
        insert_pos = m.start() + 1  # after the leading newline
        return (
            paper_md[:insert_pos]
            + appendix_md.rstrip()
            + "\n\n"
            + paper_md[insert_pos:]
        )
    # No References section — append to end
    return paper_md.rstrip() + "\n\n" + appendix_md
