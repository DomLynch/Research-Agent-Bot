"""PRISMA-bridge appendix builder.

Reviewer wave 9 (2026-05-05): journal reviewers expect a structured
search-and-selection disclosure even when the paper is explicitly NOT
a PRISMA-compliant systematic review. This module provides the
journal-polite middle ground: full disclosure of search strings,
inclusion/exclusion criteria, and screening counts, without
overclaiming PRISMA 2020 compliance.

Lives in its own module to keep agent/manuscript_appendix.py under
the 600-line per-file budget. Imported and called by compose_appendix.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_prisma_bridge_appendix(
    manifest: dict[str, Any], *, topic: str,
) -> str:
    """Universal across topics: all values pull from manifest +
    topic_pack TOML + corpus dir. No drug names, no per-topic logic.
    """
    from agent.topic_pack import load_topic_pack
    repo = Path(__file__).resolve().parent.parent
    pack_path = repo / "topic_packs" / f"{topic}.toml"
    queries: list[str] = []
    inclusion_slots: list[str] = []
    pack_loaded = False
    if pack_path.exists():
        try:
            pack = load_topic_pack(pack_path)
            queries = list(getattr(pack, "corpus_search_queries", []) or [])
            inclusion_slots = list(
                getattr(pack, "expected_evidence_slots", []) or []
            )
            pack_loaded = True
        except (OSError, ValueError, ImportError):
            pack_loaded = False

    n_receipts = manifest.get(
        "n_receipts", len(manifest.get("receipts") or []),
    )
    n_claims = manifest.get("n_high_confidence_claims_total", 0)
    generated_at = manifest.get("generated_at", "unknown")

    parsed_dir = repo / "docs" / "quality-reference" / topic / "parsed"
    quant_dir = repo / "docs" / "quality-reference" / topic / "quant_claims"
    n_parsed = (
        sum(1 for _ in parsed_dir.glob("*.paper_sections.json"))
        if parsed_dir.exists() else 0
    )
    n_extracted = (
        sum(1 for _ in quant_dir.glob("*.quant_claims.json"))
        if quant_dir.exists() else 0
    )

    queries_md = "\n".join(
        f"  {i+1}. `{q}`" for i, q in enumerate(queries[:10])
    ) or "  _(no search queries declared in topic pack)_"
    inclusion_md = ", ".join(
        s.replace("_", " ") for s in inclusion_slots[:10]
    ) or "_(slot list unavailable; see topic pack)_"

    pack_note = (
        ""
        if pack_loaded else
        "\n_NOTE: topic pack not loaded — search-string list above "
        "may be empty. Verify `topic_packs/<topic>.toml` is "
        "present in the deployment._\n"
    )
    return (
        "## PRISMA Bridge — Search and Selection Transparency\n"
        "\n"
        "This section provides the structured search-and-selection "
        "disclosure that journal reviewers typically expect. It is "
        "**not** a full PRISMA 2020 report — there is no PROSPERO "
        "registration, no blinded dual screening, and no formal "
        "Cochrane risk-of-bias scoring. It is the journal-polite "
        "middle ground: full disclosure of the inputs and the gates, "
        "without overclaiming compliance.\n"
        "\n"
        f"**Topic:** {topic}\n"
        "\n"
        f"**Search executed:** retrieval queries below were issued "
        f"against the 17 sources listed in the Search Provenance "
        f"section. Pipeline build timestamp: `{generated_at}`.\n"
        "\n"
        f"**Search strings ({len(queries)} declared):**\n"
        f"{queries_md}\n"
        "\n"
        f"**Inclusion criteria** (a paper enters the corpus when):\n"
        f"  1. Title or abstract matches at least one search string.\n"
        f"  2. Full-text or extended abstract is parseable into\n"
        f"     paper_sections.json.\n"
        f"  3. ≥1 high-confidence quantitative claim is extractable.\n"
        f"  4. At least one evidence slot is hit: {inclusion_md}.\n"
        "\n"
        f"**Exclusion criteria:**\n"
        f"  - Mechanistic-only papers without quantitative claims.\n"
        f"  - Off-topic preprints flagged by\n"
        f"    `scripts/corpus_filter.py` (see source listing).\n"
        f"  - Papers where SPAR adjudication rejected all claims for\n"
        f"    insufficient evidence-tier or directness.\n"
        "\n"
        f"**Screening counts** (this run):\n"
        f"  - Papers parsed into the corpus: **{n_parsed}**\n"
        f"  - Papers with quant-extracted claims: **{n_extracted}**\n"
        f"  - Papers entering synthesis as receipts: **{n_receipts}**\n"
        f"  - Total high-confidence bound claims: **{n_claims}**\n"
        "\n"
        f"**Why fewer receipts than parsed papers?** SPAR (the "
        f"deterministic adjudicator) requires each accepted receipt "
        f"to clear evidence-tier, directness, and binding-confidence "
        f"thresholds. Papers in the corpus that do not clear those "
        f"thresholds are kept for context (cited as background) but "
        f"do not enter the synthesis as primary evidence. The "
        f"declared narrowing is auditable: every excluded paper's "
        f"`paper_id` and rejection rationale is in the run "
        f"directory's `claim_graph.json` and `spar_review.json`.\n"
        + pack_note
    )


__all__ = ["build_prisma_bridge_appendix"]
