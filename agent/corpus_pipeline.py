"""Classify-before-extract corpus pipeline — Slice 6 step 4c
(Wave 7 cont., 2026-05-05).

The load-bearing optimization. Naïve flow:
  retrieve 5K papers → extract quant_claims on every paper → classify

The deterministic quant_claim_extract step takes ~1-2s per paper,
so 5K papers = 1-3 CPU hours. Most of that is wasted because 60%
of the papers will land in reject / off_thesis and never enter
synthesis.

Calibrated flow (this module):
  retrieve (waves) → CLASSIFY on metadata → drop reject / off_thesis
                  → extract quant_claims ONLY on kept pool

Drops 50-70% of the extraction work without losing any synthesis
inputs. The 5-class classifier already runs on title + abstract
metadata only (no full-text needed), so this gate is essentially
free.

Universal across topics + domains. Pure-Python orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.corpus_classifier import (
    CorpusClassification, classify_paper,
)
from agent.retrieval_modes import RetrievalParams, resolve_params
from agent.sources.aggregator import AggregatedHit
from agent.topic_pack import TopicPack
from agent.wave_retrieval import WaveReport, run_waves

# Classes that survive the gate (extracted; enter synthesis).
_KEEP_CLASSES: frozenset[str] = frozenset((
    "core_on_thesis", "background_mechanism", "adjacent_clinical",
))
# Classes that are dropped (no extraction).
_DROP_CLASSES: frozenset[str] = frozenset(("off_thesis", "reject"))


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """One paper after classification — ready (or not) for extraction."""
    hit: AggregatedHit
    classification: CorpusClassification
    pool: str   # "core" or "background"
    keep_for_extraction: bool


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    """Output of the classify-before-extract pipeline. The funnel
    dashboard reads `funnel` for the retrieve→classify→extract→...
    breakdown per topic."""
    topic: str
    entries: tuple[CorpusEntry, ...]
    funnel: dict[str, int]
    per_wave_stats: tuple[dict[str, Any], ...] = field(
        default_factory=tuple,
    )

    def kept(self) -> tuple[CorpusEntry, ...]:
        return tuple(e for e in self.entries if e.keep_for_extraction)

    def dropped(self) -> tuple[CorpusEntry, ...]:
        return tuple(
            e for e in self.entries if not e.keep_for_extraction
        )

    def by_class(self, cls: str) -> tuple[CorpusEntry, ...]:
        return tuple(
            e for e in self.entries if e.classification.classification == cls
        )


def _hit_to_paper_dict(
    hit: AggregatedHit, *, fallback_id: str,
) -> dict[str, Any]:
    """Adapt AggregatedHit → corpus_classifier paper dict."""
    paper_id = (
        hit.doi or hit.pmid or hit.nct
        or fallback_id
    )
    return {
        "paper_id": paper_id, "title": hit.title,
        "sections": {"abstract": hit.abstract},
    }


def classify_and_filter(
    report: WaveReport, *, topic: str,
    topic_aliases: tuple[str, ...],
    expected_slots: tuple[str, ...] = (),
) -> CorpusManifest:
    """Classify every hit from a WaveReport on title + abstract.
    Drop reject + off_thesis from the extraction pool. Returns a
    CorpusManifest ready to feed the extraction stage."""
    entries: list[CorpusEntry] = []
    n_kept = 0
    n_dropped = 0
    class_counts: dict[str, int] = {}
    for i, hit in enumerate(report.all_hits):
        paper_dict = _hit_to_paper_dict(hit, fallback_id=f"hit_{i}")
        cls = classify_paper(
            paper_dict,
            topic_aliases=topic_aliases,
            expected_slots=expected_slots,
        )
        keep = cls.classification in _KEEP_CLASSES
        # Pool from the wave report (core / background) — only
        # applies to kept entries; dropped entries don't get a pool.
        pool = report.pool_by_key.get(
            _key_from_aggregated(hit), "core",
        )
        if cls.classification == "background_mechanism":
            pool = "background"
        entries.append(CorpusEntry(
            hit=hit, classification=cls,
            pool=pool if keep else "_dropped",
            keep_for_extraction=keep,
        ))
        if keep:
            n_kept += 1
        else:
            n_dropped += 1
        class_counts[cls.classification] = class_counts.get(
            cls.classification, 0,
        ) + 1
    funnel = {
        "retrieved": len(report.all_hits),
        "classified_keep": n_kept,
        "classified_drop": n_dropped,
        "extractable_core": sum(
            1 for e in entries
            if e.keep_for_extraction and e.pool == "core"
        ),
        "extractable_background": sum(
            1 for e in entries
            if e.keep_for_extraction and e.pool == "background"
        ),
        **{f"class_{k}": v for k, v in class_counts.items()},
        "cap_triggered": int(report.cap_triggered),
    }
    return CorpusManifest(
        topic=topic,
        entries=tuple(entries),
        funnel=funnel,
        per_wave_stats=report.per_wave_stats,
    )


def _key_from_aggregated(hit: AggregatedHit) -> str:
    if hit.doi:
        return f"doi:{hit.doi}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    if hit.nct:
        return f"nct:{hit.nct}"
    return f"title:{hit.title.lower()[:80]}"


def format_funnel_md(manifest: CorpusManifest) -> str:
    """Render the funnel breakdown as markdown for the dashboard.

    Slice 4d: surface every step of the corpus pipeline so an
    operator can see where papers were dropped.
    """
    f = manifest.funnel
    lines = [
        f"### Corpus funnel — {manifest.topic}",
        "",
        "| Stage | Count |",
        "|---|---|",
        f"| Retrieved (post-dedupe) | {f.get('retrieved', 0)} |",
        f"| Classified — keep | {f.get('classified_keep', 0)} |",
        f"| Classified — drop | {f.get('classified_drop', 0)} |",
        f"| Extractable — core pool | "
        f"{f.get('extractable_core', 0)} |",
        f"| Extractable — background pool | "
        f"{f.get('extractable_background', 0)} |",
        "",
        "**Class distribution:**",
        "",
    ]
    for cls in (
        "core_on_thesis", "background_mechanism",
        "adjacent_clinical", "off_thesis", "reject",
    ):
        n = f.get(f"class_{cls}", 0)
        if n:
            lines.append(f"- `{cls}`: {n}")
    if f.get("cap_triggered"):
        lines.append(
            "\n_Note: GLOBAL_SAFETY_CAP fired; retrieval was "
            "truncated. Tighten the calibrated query._",
        )
    return "\n".join(lines) + "\n"


async def build_corpus_manifest(
    pack: TopicPack, *,
    params: RetrievalParams | None = None,
) -> CorpusManifest:
    """End-to-end: pack → waves → classify → manifest. Async because
    discover_calibrated is async (HTTP-bound)."""
    if pack.retrieval is None:
        raise ValueError(
            f"Topic pack '{pack.topic}' lacks a [retrieval] block; "
            f"cannot run calibrated pipeline."
        )
    p = params or resolve_params("calibrated")
    report = await run_waves(pack.retrieval, params=p)
    aliases = tuple(pack.aliases_display)
    return classify_and_filter(
        report, topic=pack.topic, topic_aliases=aliases,
        expected_slots=pack.expected_evidence_slots,
    )


__all__ = [
    "CorpusEntry", "CorpusManifest",
    "classify_and_filter", "build_corpus_manifest",
    "format_funnel_md",
]
