"""Wave-based retrieval orchestration — Slice 6 step 4b
(Wave 7 cont., 2026-05-05).

Calibrated retrieval doesn't run a single query — it runs three
WAVES against the same calibrated spec, each targeting a different
citation pool. This solves the "Harrison/Lamming/Mannick canon
papers get rejected as off-thesis" problem because the Background
wave deliberately retrieves them into the background pool.

Waves implemented in this MVP:

  Precision   topic_terms + scope_terms + evidence_types + exclude
              → core_on_thesis pool (strict on-topic clinical evidence)
  Recall      topic_terms + scope_terms (drops evidence_types)
              → core_on_thesis pool (broader recall on the same topic)
  Background  topic_terms + background_allow (drops evidence_types,
              swaps scope_terms for the [retrieval.background] allow
              list) → background_literature pool

Future waves (deferred to follow-up): Snowball (refs + cited-by from
accepted core papers) and Gap-fill (targeted missing-outcome queries
informed by funnel dashboard).

Universal across topics + domains. Pure-Python orchestrator; the
actual retrieval calls discover_calibrated() per wave.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from agent.retrieval_modes import (
    RetrievalParams, resolve_params,
)
from agent.sources.aggregator import (
    AggregatedHit, discover_calibrated,
)
from agent.topic_pack import RetrievalSpec


@dataclass(frozen=True, slots=True)
class Wave:
    """One retrieval wave: label, spec to use, target pool name."""
    label: str
    spec: RetrievalSpec
    target_pool: str  # "core" or "background"


@dataclass(frozen=True, slots=True)
class WaveReport:
    """Output of run_waves: deduped hits + pool assignment + stats."""
    all_hits: tuple[AggregatedHit, ...]
    pool_by_key: dict[str, str]               # dedup_key → "core"/"background"
    per_wave_stats: tuple[dict[str, Any], ...]
    cap_triggered: bool = False


def compose_waves(base: RetrievalSpec) -> list[Wave]:
    """Derive Precision / Recall / Background waves from a single
    base RetrievalSpec.

    Waves whose source slice is empty (e.g. no background_allow
    set) are skipped — every emitted wave has at least one
    discriminating field set.
    """
    waves: list[Wave] = []

    # Wave A — Precision: full strict spec.
    if base.topic_terms or base.scope_terms:
        waves.append(Wave("precision", base, "core"))

    # Wave B — Recall: drop evidence_types so we don't filter out
    # papers whose pub-type field doesn't match our enum (e.g. a
    # cohort study filed as "research article"). Same scope_terms
    # so we stay on-thesis.
    if base.evidence_types:
        recall_spec = replace(base, evidence_types=())
        waves.append(Wave("recall", recall_spec, "core"))

    # Wave C — Background canon: swap scope_terms for the
    # [retrieval.background].allow list so we deliberately retrieve
    # mechanism / preclinical landmark / dose rationale / field
    # history papers into the background pool. They'd be rejected by
    # the strict on-thesis filter — that's the whole reason this
    # wave exists.
    if base.background_allow:
        bg_spec = replace(
            base,
            scope_terms=base.background_allow,
            evidence_types=(),  # background isn't filtered by pub-type
        )
        waves.append(Wave("background", bg_spec, "background"))

    return waves


async def run_waves(
    base: RetrievalSpec, *,
    params: RetrievalParams | None = None,
    enabled_sources: Iterable[str] | None = None,
    timeout: float | None = None,
) -> WaveReport:
    """Run all waves derived from base spec, accumulate deduped
    hits across waves, assign each unique paper to its first-touched
    target pool. Honors params.safety_cap as a global ceiling
    (across all waves combined)."""
    p = params or resolve_params("calibrated")
    waves = compose_waves(base)
    accumulated: dict[str, AggregatedHit] = {}
    pool_by_key: dict[str, str] = {}
    per_wave_stats: list[dict[str, Any]] = []
    cap_triggered = False

    for wave in waves:
        if cap_triggered:
            per_wave_stats.append({
                "wave": wave.label, "skipped": "cap_triggered",
            })
            continue
        hits, stats = await discover_calibrated(
            wave.spec,
            params=p,
            enabled_sources=enabled_sources,
            timeout=timeout or 120.0,
        )
        new_keys = 0
        for hit in hits:
            key = _key_from_aggregated(hit)
            if key not in accumulated:
                accumulated[key] = hit
                pool_by_key[key] = wave.target_pool
                new_keys += 1
            if len(accumulated) >= p.safety_cap:
                cap_triggered = True
                break
        per_wave_stats.append({
            "wave": wave.label,
            "target_pool": wave.target_pool,
            "raw_total": stats.get("raw_total_pre_dedupe", 0),
            "wave_unique": stats.get("unique_keys_post_dedupe", 0),
            "new_to_corpus": new_keys,
            "cumulative": len(accumulated),
            "stats": stats,
        })
    return WaveReport(
        all_hits=tuple(accumulated.values()),
        pool_by_key=pool_by_key,
        per_wave_stats=tuple(per_wave_stats),
        cap_triggered=cap_triggered,
    )


def _key_from_aggregated(hit: AggregatedHit) -> str:
    """Mirror _dedupe_key from aggregator, but operate on
    AggregatedHit. Same DOI > PMID > NCT > title-prefix priority."""
    if hit.doi:
        return f"doi:{hit.doi}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    if hit.nct:
        return f"nct:{hit.nct}"
    return f"title:{hit.title.lower()[:80]}"


__all__ = [
    "Wave", "WaveReport", "compose_waves", "run_waves",
]
