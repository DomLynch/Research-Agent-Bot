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

from dataclasses import dataclass
from typing import Any


_SOURCE_STATUS_ALIASES = {
    "enabled": "enabled",
    "pending": "enabled",
    "not_attempted": "enabled",
    "ok": "succeeded",
    "success": "succeeded",
    "succeeded": "succeeded",
    "complete": "succeeded",
    "completed": "succeeded",
    "error": "failed",
    "failed": "failed",
    "rate_limited": "failed",
    "auth_failed": "failed",
    "http_error": "failed",
    "provider_error": "failed",
    "server_error": "failed",
    "transport_error": "failed",
    "timeout": "failed",
    "timed_out": "failed",
    "unavailable": "failed",
}
_SOURCE_STATUS_PRIORITY = {"enabled": 0, "failed": 1, "succeeded": 2}


@dataclass(frozen=True, slots=True)
class FrozenRetrievalRecord:
    """Run-frozen retrieval evidence shared by all public disclosures."""

    sources: tuple[tuple[str, str], ...] = ()
    queries: tuple[str, ...] = ()
    expected_evidence_slots: tuple[str, ...] = ()
    n_parsed: int = 0
    n_extracted: int = 0

    def to_manifest(self) -> dict[str, Any]:
        return {
            "sources": [
                {"name": name, "status": status}
                for name, status in self.sources
            ],
            "queries": list(self.queries),
            "expected_evidence_slots": list(self.expected_evidence_slots),
            "counts": {
                "parsed": self.n_parsed,
                "quant_extracted": self.n_extracted,
            },
        }


def _canonical_source_status(value: Any) -> str | None:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _SOURCE_STATUS_ALIASES.get(token)


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def frozen_retrieval_record(manifest: dict[str, Any]) -> FrozenRetrievalRecord:
    """Normalize only explicit retrieval evidence from one frozen manifest."""
    retrieval = manifest.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    raw_sources = (
        retrieval.get("sources")
        if "sources" in retrieval
        else manifest.get("retrieval_sources", ())
    )
    sources: dict[str, str] = {}

    def add_source(name_value: Any, status_value: Any) -> None:
        name = str(name_value or "").strip()
        status = _canonical_source_status(status_value)
        if not name or status is None:
            return
        previous = sources.get(name)
        rank = _SOURCE_STATUS_PRIORITY[status]
        previous_rank = (
            -1 if previous is None
            else _SOURCE_STATUS_PRIORITY[previous]
        )
        if rank > previous_rank:
            sources[name] = status

    if isinstance(raw_sources, dict):
        for name, status in raw_sources.items():
            add_source(name, status)
    elif isinstance(raw_sources, list | tuple):
        for row in raw_sources:
            if isinstance(row, str) and row.strip():
                add_source(row, "enabled")
            elif isinstance(row, dict):
                if row.get("enabled") is False:
                    continue
                status = row.get("status")
                if status is None:
                    status = "enabled" if row.get("enabled", True) else None
                add_source(row.get("name") or row.get("source"), status)
            elif isinstance(row, list | tuple) and len(row) == 2:
                add_source(row[0], row[1])

    if not sources:
        for wave in manifest.get("per_wave_stats") or ():
            stats = wave.get("stats") if isinstance(wave, dict) else None
            if not isinstance(stats, dict):
                continue
            for key, status in stats.items():
                if str(key).startswith("status_"):
                    add_source(str(key).removeprefix("status_").replace("_", " "), status)

    wave_queries: list[str] = []
    for wave in manifest.get("per_wave_stats") or ():
        stats = wave.get("stats") if isinstance(wave, dict) else None
        if not isinstance(stats, dict):
            continue
        wave_queries.extend(
            str(query).strip()
            for key, query in stats.items()
            if str(key).startswith("query_") and str(query).strip()
        )
    raw_queries = (
        retrieval.get("queries")
        or manifest.get("search_queries")
        or wave_queries
    )
    queries = (
        tuple(dict.fromkeys(
            str(query).strip() for query in raw_queries if str(query).strip()
        ))
        if isinstance(raw_queries, list | tuple) else ()
    )
    raw_slots = (
        retrieval.get("expected_evidence_slots")
        if "expected_evidence_slots" in retrieval
        else manifest.get("expected_evidence_slots", ())
    )
    slots = (
        tuple(str(slot).strip() for slot in raw_slots if str(slot).strip())
        if isinstance(raw_slots, list | tuple) else ()
    )
    counts = retrieval.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    funnel = manifest.get("receipt_funnel")
    funnel = funnel if isinstance(funnel, dict) else {}
    return FrozenRetrievalRecord(
        sources=tuple(sorted(sources.items())),
        queries=queries,
        expected_evidence_slots=slots,
        n_parsed=_nonnegative_int(
            counts.get("parsed") or funnel.get("active_paper_ids"),
        ),
        n_extracted=_nonnegative_int(
            counts.get("quant_extracted") or funnel.get("quant_claim_files"),
        ),
    )


def source_inventory_summary(sources: tuple[tuple[str, str], ...]) -> str:
    """Render the shared enabled/succeeded/failed disclosure counts."""
    succeeded = sum(status == "succeeded" for _, status in sources)
    failed = sum(status == "failed" for _, status in sources)
    pending = sum(status == "enabled" for _, status in sources)
    return (
        f"{len(sources)} enabled; {succeeded} succeeded; {failed} failed; "
        f"{pending} enabled without a recorded outcome"
    )


def build_prisma_bridge_appendix(
    manifest: dict[str, Any], *, topic: str,
    retrieval_record: FrozenRetrievalRecord | None = None,
) -> str:
    """Universal across topics; all run facts come from ``manifest``."""
    retrieval = retrieval_record or frozen_retrieval_record(manifest)
    queries = retrieval.queries
    inclusion_slots = retrieval.expected_evidence_slots
    sources = retrieval.sources

    n_receipts = manifest.get(
        "n_receipts", len(manifest.get("receipts") or []),
    )
    n_claims = manifest.get("n_high_confidence_claims_total", 0)
    generated_at = manifest.get("generated_at", "unknown")

    n_parsed = retrieval.n_parsed
    n_extracted = retrieval.n_extracted

    queries_md = "\n".join(
        f"  {i+1}. `{q}`" for i, q in enumerate(queries[:10])
    ) or "  _(no search queries frozen in the run manifest)_"
    inclusion_md = ", ".join(
        s.replace("_", " ") for s in inclusion_slots[:10]
    ) or "_(slot list unavailable in the frozen run manifest)_"

    source_statement = source_inventory_summary(sources) if sources else (
        "unavailable; no database coverage or execution claim is made"
    )
    outcomes_complete = sources and all(
        status != "enabled" for _, status in sources
    )
    query_statement = (
        f"The query strings below were run against the {len(sources)} source(s) "
        "recorded in the frozen run manifest."
        if queries and outcomes_complete else
        "The frozen run manifest does not evidence both query strings and "
        "complete source outcomes, so this section makes no query-execution claim."
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
        f"**Frozen source inventory:** {source_statement}. Pipeline build "
        f"timestamp: `{generated_at}`.\n"
        f"{query_statement}\n"
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
        f"    `agent/corpus_classifier.py` (see source listing).\n"
        f"  - Papers whose extracted claims failed receipt-level\n"
        f"    evidence-tier, directness, or binding-confidence checks.\n"
        "\n"
        f"**Screening counts** (this run):\n"
        f"  - Papers parsed into the corpus: **{n_parsed}**\n"
        f"  - Papers with quant-extracted claims: **{n_extracted}**\n"
        f"  - Papers entering synthesis as receipts: **{n_receipts}**\n"
        f"  - Total high-confidence bound claims: **{n_claims}**\n"
        "\n"
        f"**Why fewer receipts than parsed papers?** The deterministic "
        f"receipt qualifier requires each accepted receipt to clear "
        f"evidence-tier, directness, and binding-confidence "
        f"thresholds. Papers in the corpus that do not clear those "
        f"thresholds are kept for context (cited as background) but "
        f"do not enter the synthesis as primary evidence. The "
        f"declared narrowing is auditable: every excluded paper's "
        f"`paper_id` and rejection rationale is in the run "
        f"directory's `claim_graph.json` and `spar_review.json`.\n"
    )


__all__ = [
    "FrozenRetrievalRecord",
    "build_prisma_bridge_appendix",
    "frozen_retrieval_record",
    "source_inventory_summary",
]
