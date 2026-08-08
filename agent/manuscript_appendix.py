"""Compose journal appendices from frozen run evidence."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from agent.manuscript_prisma import (
    FrozenRetrievalRecord,
    frozen_retrieval_record,
    source_inventory_summary,
)
from agent.selection_flow import render_selection_flow_lines


__all__ = ["build_search_provenance_appendix", "build_ai_use_disclosure", "build_human_accountability_template", "build_data_code_availability", "compose_appendix"]


def build_search_provenance_appendix(
    manifest: dict[str, Any], topic: str,
    retrieval_record: FrozenRetrievalRecord | None = None,
) -> str:
    """Compose search provenance from the frozen manifest."""
    receipts = manifest.get("receipts", [])
    # Prefer explicit n_receipts field; fall back to list length.
    # The orchestrator writes both, but a synthetic test fixture
    # may only set the field.
    n_receipts = manifest.get("n_receipts", len(receipts))
    n_claims = manifest.get("n_high_confidence_claims_total", 0)
    n_tensions = manifest.get("n_non_orthogonal_tensions", 0)
    receipt_funnel = manifest.get("receipt_funnel") or {}
    retrieval = retrieval_record or frozen_retrieval_record(manifest)
    sources = retrieval.sources

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
        "### Retrieval sources recorded in the frozen manifest",
        "",
        "| Source | Enabled | Frozen outcome |",
        "|---|---|---|",
    ]
    lines.extend(f"| {name} | yes | {status} |" for name, status in sources)
    if not sources:
        lines.append(
            "| _(inventory unavailable)_ | - | No source-count claim is made. |",
        )
    lines += [
        "",
        "### Selection logic",
        "",
        "This synthesis consumed a corpus frozen before manuscript "
        "rendering. Of the corpus records, "
        f"**{n_receipts} contributing papers** had sufficient claim "
        f"density to enter the synthesis as evidence receipts. "
        f"Selection was deterministic — the LLM proposed; "
        f"the receipt builder disposed via the receipt-summary "
        f"density gate.",
        "",
    ]
    lines.extend(render_selection_flow_lines(receipt_funnel))
    source_limitation = (
        f"- Frozen source outcomes: {source_inventory_summary(sources)}; "
        "no unrecorded database coverage is claimed."
        if sources else
        "- The source inventory was not frozen in the run manifest; "
        "no source-count or database-coverage claim is made."
    )
    lines += [
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
        "1. Inspect the frozen query strings and source outcomes, when present.",
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
        source_limitation,
        "- The synthesis is automated and reproducible, but "
        "automation does not substitute for domain-expert framing "
        "of the question or interpretation of clinical implications.",
    ]
    return "\n".join(lines) + "\n"

def _verdict_phrase(verdict: str) -> str:
    """Return certification language that matches the verdict."""
    v = (verdict or "").strip()
    if v == "AAA":
        return "Researka-Certified A2A-AAA artifact"
    if v in ("Trust-Spine Pass",
             "Trust-Spine Pass — Agent Review Unresolved"):
        return "Researka Trust-Spine Pass audit artifact"
    if v == "SHIP-BLOCKED":
        return "Researka preliminary audit artifact"
    return "Researka audit-trail artifact"


def _submitter_attestation_text(verdict: str) -> str:
    v = (verdict or "").strip()
    phrase = _verdict_phrase(v)
    if v == "AAA":
        return (
            f"> I publicly release this {phrase} under the Researka "
            "Independent Standard. I have inspected the trust-spine "
            "bundle (paper + audit + consistency + patch trail + "
            "citation registry + certification record + manifest) and "
            "find no defects exceeding the certification tolerances. I "
            "invite any third party to re-run the pipeline and report "
            "errors via the public issue tracker. Errors found post-"
            "release will be corrected via versioned re-cert."
        )
    return (
        f"> I publicly release this {phrase} under the Researka "
        "Independent Standard. This bundle is not represented as an "
        "A2A-AAA certification. Its current verdict, limitations, "
        "unresolved review items, and corpus gaps are recorded in the "
        "audit trail for public inspection and re-run."
    )


def build_ai_use_disclosure(
    manifest: dict[str, Any],
    audit: dict[str, Any] | None = None,
    model_stack: dict[str, str] | None = None,
    *,
    verdict: str = "",
) -> str:
    """Render the AI-use disclosure from the frozen run record."""
    model_stack = model_stack or {}
    n_llm_calls = manifest.get("n_llm_calls", 0)
    cost_usd = float(manifest.get("total_cost_usd", 0.0))
    extractor_version = manifest.get("extractor_version", "v0.6.x")
    repairs = manifest.get("claim_strength_repairs", 0)

    lines = [
        "## AI-Use Disclosure",
        "",
        "This manuscript was produced under an AI-native audit "
        "protocol (the Researka A2A-AAA Protocol) designed to "
        "**complement, not replace,** conventional editorial peer "
        "review. The protocol provides a reproducible audit trail "
        "for every claim, citation, and numeric value in the "
        "manuscript; this is intended as an additional reproducibility "
        "and provenance layer that traditional human review may "
        "evaluate alongside its usual checks.",
        "",
        "**Scope and rationale.** A multi-thousand-word evidence "
        "synthesis containing dozens of numeric claims and citations "
        "across multiple outcome classes is difficult to verify "
        "exhaustively under standard editorial timeboxes. The audit "
        "trail described below makes every claim individually "
        "verifiable: the code that gates each claim is public, every "
        "automated revision is logged, and any reviewer or third "
        "party can re-run the pipeline against the public bundle and "
        "reproduce the verdict. This is offered as a tractable "
        "supplement to expert review, not as a substitute for it.",
        "",
        "### Models used and their roles",
        "",
        "| Role | Model | Constraint Layer |",
        "|---|---|---|",
    ]
    role_constraints = {
        "writer": (
            "Output gated by section-word floors, citation "
            "registry, and Stage-1 audit (Q1-Q14)"
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
        "LLM-produced text is evaluated by the following deterministic gates; "
        "the run sidecars record which checks passed:",
        "",
        "1. **Citation registry** — every citation must resolve to "
        "a registered receipt or background-literature entry.",
        "2. **Numeric registry** — every numeric must trace to a "
        "corpus quant-claim or background-literature entry.",
        "3. **Stage-1 audit (Q1-Q14)** — quantitative checks: "
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
        "7. **Unified verdict gate** — the run is labeled as AAA, "
        "Trust-Spine Pass, or SHIP-BLOCKED from the audit record; "
        "certification language is used only for artifacts that clear "
        "the certification gate.",
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


def build_human_accountability_template(*, verdict: str = "") -> str:
    """Render the human submitter accountability block."""
    attestation = _submitter_attestation_text(verdict)
    return (
        "## Researka Submitter Block\n"
        "\n"
        "Researka's accountability model differs from legacy peer-"
        "review venues. The audit trail IS the primary "
        "accountability mechanism — every claim is gate-checked, "
        "every patch is logged, and any third party can re-run "
        "the pipeline against the public bundle. The named human "
        "submitter releases the artifact and invites public error-"
        "reporting; they do not certify they personally re-read "
        "every word, because that's not what Researka treats as "
        "the trust signal.\n"
        "\n"
        "**Submitter:** _[Submitter: name, affiliation, ORCID, "
        "contact email — fill in before public release.]_\n"
        "\n"
        "**Submitter attestation:**\n"
        "\n"
        f"{attestation}\n"
        "\n"
        "**Conflict of interest:** _[Submitter to declare.]_\n"
        "\n"
        "**Funding:** _[Submitter to declare.]_\n"
        "\n"
        "**Ethics approval:** Not applicable — this is a "
        "secondary literature synthesis with no primary human or "
        "animal data collection.\n"
        "\n"
        "**Versioning:** This artifact carries a unique run ID "
        "+ git SHA. Re-running the pipeline at the same SHA on "
        "the same corpus reproduces the verdict; any divergence "
        "is itself a finding worth reporting.\n"
    )


def build_data_code_availability(
    run_id: str,
    git_sha: str,
    bundle_path: str | None = None,
    repo_url: str = "https://github.com/DomLynch/Research-Agent-Bot",
    topic: str = "the_topic",
    verdict: str = "",
) -> str:
    """Render reproducible data and code availability details."""
    verified_sha = git_sha if re.fullmatch(r"[0-9a-f]{7,40}", git_sha or "", re.I) else ""
    bundle_str = f"`{bundle_path}`" if bundle_path else "not verified as public"
    verdict_clean = (verdict or "").strip()
    if verdict_clean == "AAA":
        record_label = "the Researka A2A-AAA certification record"
        sha_label = "Git SHA at certification"
        code_label = "Cert/verdict code"
    else:
        record_label = "the unified verdict and audit record"
        sha_label = "Git SHA at run"
        code_label = "Verdict code"
    identity = (
        f"**{sha_label}:** `{verified_sha}`\n" if verified_sha
        else f"**{sha_label}:** not verified\n"
    )
    bundle_note = (
        "The run manifest declares this bundle path. Its contents and public "
        "availability must be checked independently.\n"
        if bundle_path else
        "No verified public reproducibility bundle is declared for this run.\n"
    )
    reproduce = (
        "### Reproduce the synthesis\n\n"
        "```bash\n"
        f"git clone {repo_url}\n"
        f"cd Research-Agent-Bot && git checkout {verified_sha}\n"
        f"python scripts/run_v06_synthesis.py --topic {topic}\n"
        "```\n\n"
        "This identifies the code revision; exact reproduction also requires "
        "the frozen corpus, topic pack, provider configuration, and seeds.\n\n"
        if verified_sha else
        "### Reproduce the synthesis\n\n"
        "No verified Git revision is available, so a runnable reproduction "
        "command is not asserted for this package.\n\n"
    )
    return (
        "## Data and Code Availability\n"
        "\n"
        "The available run artifacts and reproducibility identifiers are "
        "listed below; public availability is not asserted without a verified bundle.\n"
        "\n"
        "### Public bundle\n"
        "\n"
        f"**Run ID:** `{run_id}`\n"
        f"{identity}"
        f"**Bundle path:** {bundle_str}\n"
        f"**Expected verification record:** {record_label}\n"
        "\n"
        f"{bundle_note}"
        "\n"
        f"{reproduce}"
        "### Inspect the trust spine\n"
        "\n"
        "- Audit code: `scripts/audit_v06_paper.py` + "
        "`scripts/final_consistency_audit.py`\n"
        f"- {code_label}: `agent/final_status.py` + `agent/final_gate.py`\n"
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
    topic: str,
    run_id: str = "unknown-run",
    git_sha: str = "unknown",
    bundle_path: str | None = None,
    verdict: str = "",
) -> str:
    """Compose the verdict-aware publication appendix."""
    from agent.manuscript_prisma import build_prisma_bridge_appendix
    retrieval_record = frozen_retrieval_record(manifest)
    blocks = [
        build_search_provenance_appendix(
            manifest, topic=topic, retrieval_record=retrieval_record,
        ),
        build_prisma_bridge_appendix(
            manifest, topic=topic, retrieval_record=retrieval_record,
        ),
        build_ai_use_disclosure(
            manifest, audit, model_stack, verdict=verdict,
        ),
        build_human_accountability_template(verdict=verdict),
        build_data_code_availability(
            run_id, git_sha, bundle_path=bundle_path, topic=topic,
            verdict=verdict,
        ),
    ]
    return "## Publication Appendix\n\n" + "\n\n".join(b.rstrip() for b in blocks) + "\n"


# Convenience: detect the splice point in an existing paper
_REFERENCES_SPLICE_RE = re.compile(
    r"(\n)(##\s+References\b)", re.MULTILINE,
)


def splice_appendix_before_references(
    paper_md: str, appendix_md: str,
) -> str:
    """Splice the appendix before references, idempotently."""
    if "## Publication Appendix" not in appendix_md:
        appendix_md = "## Publication Appendix\n\n" + appendix_md.lstrip()
    # Idempotency: don't double-insert; wrap historical bare appendix.
    if "## Search Provenance and Selection" in paper_md:
        if "## Publication Appendix" in paper_md:
            return paper_md
        return paper_md.replace(
            "## Search Provenance and Selection",
            "## Publication Appendix\n\n## Search Provenance and Selection",
            1,
        )
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
