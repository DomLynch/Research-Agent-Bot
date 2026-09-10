"""Disclose recorded search, selection and extraction stages without claiming PRISMA compliance."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


_SOURCE_STATUS_ALIASES = {
    **dict.fromkeys(("enabled", "pending", "not_attempted"), "enabled"),
    **dict.fromkeys(("ok", "success", "succeeded", "complete", "completed"), "succeeded"),
    **dict.fromkeys(("error", "failed", "rate_limited", "auth_failed", "http_error", "provider_error",
                     "server_error", "transport_error", "timeout", "timed_out", "unavailable"), "failed"),
}
_SOURCE_STATUS_PRIORITY = {"enabled": 0, "failed": 1, "succeeded": 2}


@dataclass(frozen=True, slots=True)
class FrozenRetrievalRecord:
    """Run-frozen retrieval evidence shared by all public disclosures."""

    sources: tuple[tuple[str, str], ...] = ()
    queries: tuple[str, ...] = ()
    retrieved_at: str = ""
    expected_evidence_slots: tuple[str, ...] = ()
    n_parsed: int = 0
    n_extracted: int = 0
    audit: dict[str, Any] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "sources": [
                {"name": name, "status": status}
                for name, status in self.sources
            ],
            "queries": list(self.queries),
            "retrieved_at": self.retrieved_at,
            "expected_evidence_slots": list(self.expected_evidence_slots),
            "counts": {
                "parsed": self.n_parsed,
                "quant_extracted": self.n_extracted,
            },
            **({"audit": self.audit} if self.audit else {}),
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
        retrieved_at=str(retrieval.get("retrieved_at") or manifest.get("retrieved_at") or "").strip(),
        expected_evidence_slots=slots,
        n_parsed=_nonnegative_int(
            counts.get("parsed") or funnel.get("active_paper_ids"),
        ),
        n_extracted=_nonnegative_int(
            counts.get("quant_extracted") or funnel.get("quant_claim_files"),
        ),
        audit=_retrieval_audit(manifest, retrieval),
    )


def _retrieval_audit(manifest: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
    if isinstance(retrieval.get("audit"), dict):
        return retrieval["audit"]
    if not manifest.get("per_wave_stats"):
        return {}
    return {
        "waves": manifest["per_wave_stats"],
        "selection_counts": manifest.get("funnel", {}),
        "exclusion_reasons": dict(Counter(str(row.get("reason") or "Reason not recorded")
            for row in manifest.get("entries", []) if row.get("keep_for_extraction") is False)),
    }


def render_retrieval_audit(audit: dict[str, Any]) -> str:
    """Keep recorded search waves distinct from extraction and receipt admission."""
    if not audit:
        return ""
    lines = ["### Recorded retrieval and selection stages", "",
        "Counts below describe separate recorded stages. Provider yields can overlap; "
        "a failed provider can return partial results. These are not full-text exclusion counts.", "",
        "| Search wave | Raw records | Unique within wave | Added to corpus | Cumulative corpus |",
        "|---|---:|---:|---:|---:|"]
    def cell(value: Any) -> str:
        return str(value).replace("|", "/").replace("\n", " ").replace("_", " ")
    for wave in audit.get("waves", []):
        lines.append("| " + " | ".join(cell(wave.get(key, "Not recorded")) for key in
            ("wave", "raw_total", "wave_unique", "new_to_corpus", "cumulative")) + " |")
    lines += ["", "| Search wave | Provider | Returned records | Recorded status |", "|---|---|---:|---|"]
    for wave in audit.get("waves", []):
        stats = wave.get("stats", {})
        for key, status in stats.items():
            if key.startswith("status_"):
                provider = key.removeprefix("status_")
                lines.append(f"| {cell(wave.get('wave', 'Not recorded'))} | {cell(provider)} | "
                             f"{cell(stats.get('raw_' + provider, 'Not recorded'))} | {cell(status)} |")
    for key, title in (("selection_counts", "Metadata selection counts"),
                       ("extraction_counts", "Extraction report counts"), ("exclusion_reasons", "Metadata exclusion reasons")):
        if rows := audit.get(key):
            lines += ["", f"#### {title}", "", "| Recorded stage or reason | Count |", "|---|---:|"]
            lines += [f"| {cell(label)} | {cell(value)} |" for label, value in rows.items()]
    lines += ["", "Metadata selection used automated title/abstract classification with source-level reasons. "
        "No blinded dual human screening or human full-text eligibility adjudication is evidenced by these records. "
        "Extraction failures and abstract fallbacks are not automatically study exclusions; "
        "the retained source set is established separately by receipt admission.", ""]
    return "\n".join(lines)


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
    sources = retrieval.sources
    n_receipts = manifest.get("n_receipts", len(manifest.get("receipts") or []))
    queries_md = "\n".join(f"  {i + 1}. `{query}`" for i, query in enumerate(retrieval.queries))
    queries_md = queries_md or "  _(no search queries frozen in the run manifest)_"
    source_statement = source_inventory_summary(sources) if sources else (
        "unavailable; no database coverage or execution claim is made"
    )
    return (
        "## PRISMA Bridge — Search and Selection Transparency\n\n"
        "This disclosure reports recorded retrieval and source-admission stages. "
        "It does not establish PRISMA 2020 compliance, registration, dual human "
        "screening or formal risk-of-bias appraisal. See Methods for the review protocol "
        "and populated appraisal records.\n\n"
        f"**Topic:** {topic}\n\n"
        f"**Frozen source inventory:** {source_statement}. "
        f"Retrieval record date: {retrieval.retrieved_at or 'not recorded'}.\n"
        "Queries are reproduced as recorded; provider outcomes and partial failures "
        "are reported separately. An enabled source alone makes no query-execution claim.\n\n"
        f"**Search strings ({len(retrieval.queries)} declared):**\n{queries_md}\n\n"
        "**Selection scope:** Source eligibility and admission follow the recorded "
        "review protocol. Search returns, metadata selection, parsed sources and "
        "admitted receipts are distinct stages. Diagnostic binding buckets may overlap "
        "and do not establish full-text exclusion counts or reasons.\n\n"
        f"**Screening counts** (this run):\n"
        f"  - Papers parsed into the corpus: **{retrieval.n_parsed}**\n"
        f"  - Papers with quant-extracted claims: **{retrieval.n_extracted}**\n"
        f"  - Papers entering synthesis as receipts: **{n_receipts}**\n"
        f"  - Total high-confidence bound claims: **{manifest.get('n_high_confidence_claims_total', 0)}**\n\n"
        + render_retrieval_audit(retrieval.audit)
    )


__all__ = [
    "FrozenRetrievalRecord",
    "build_prisma_bridge_appendix",
    "frozen_retrieval_record",
    "source_inventory_summary",
]
