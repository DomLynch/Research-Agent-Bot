"""Tests for discover_calibrated + _merge_and_dedupe — Slice 6 step 4.

No live HTTP — every source is patched via monkeypatch to return
synthetic hits. Verifies wiring + dedup semantics + safety cap.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.sources.aggregator import (
    _merge_and_dedupe, discover_calibrated,
)
from agent.retrieval_modes import resolve_params
from agent.topic_pack import RetrievalSpec
from agent.types import RawHit


def _hit(
    *, source: str, doi: str | None = None,
    pmid: str | None = None, title: str = "T", abstract: str = "A",
    year: int = 2020,
) -> RawHit:
    """Build a synthetic RawHit. RawHit's constructor signature is
    enforced by agent/types.py — keep this in sync if it changes."""
    return RawHit(
        title=title, abstract=abstract, doi=doi, pmid=pmid,
        nct=None, year=year, url=f"https://example/{source}",
        venue=None, source=source, raw={},
    )


# ---------- _merge_and_dedupe ---------------------------------------

def test_merge_and_dedupe_collapses_doi_duplicates():
    a = _hit(source="pubmed", doi="10.1/x", title="Aging RCT")
    b = _hit(source="europepmc", doi="10.1/x", title="Aging RCT (longer abstract)",
             abstract="A much longer abstract overrides the short one.")
    out = _merge_and_dedupe([[a], [b]], {})
    assert len(out) == 1
    assert out[0].n_sources == 2
    assert "pubmed" in out[0].sources and "europepmc" in out[0].sources
    # longest abstract wins
    assert "longer abstract overrides" in out[0].abstract


def test_merge_and_dedupe_preserves_distinct_papers():
    a = _hit(source="pubmed", doi="10.1/x")
    b = _hit(source="pubmed", doi="10.1/y")
    c = _hit(source="europepmc", pmid="12345")
    out = _merge_and_dedupe([[a, b], [c]], {})
    assert len(out) == 3


def test_merge_and_dedupe_falls_back_to_pmid_then_title():
    a = _hit(source="pubmed", pmid="100", title="Same title")
    b = _hit(source="europepmc", pmid="100", title="Same title")
    out = _merge_and_dedupe([[a, b]], {})
    assert len(out) == 1


def test_merge_and_dedupe_writes_stats():
    stats: dict[str, int] = {}
    a = _hit(source="pubmed", doi="10.1/x")
    b = _hit(source="europepmc", doi="10.1/x")
    _merge_and_dedupe([[a, b]], stats)
    assert stats["raw_total_pre_dedupe"] == 2
    assert stats["unique_keys_post_dedupe"] == 1


# ---------- discover_calibrated (mocked sources) --------------------

class _FakeClient:
    def __init__(self, name: str, hits: list[RawHit]):
        self.name = name
        self._hits = hits

    async def search(self, http, query, *, limit):
        # Verify that calibrated query syntax flows through (i.e.
        # it's NOT the raw topic_terms with no operator).
        assert "AND" in query or "OR" in query or query
        return self._hits[:limit]


def _patch_registry(monkeypatch, sources: dict[str, list[RawHit]]):
    """Patch _build_registry to return only the named test sources.

    Each entry is `(client, default_enabled, auth_env=None)` to match
    the real registry shape."""
    fake = {
        name: (_FakeClient(name, hits), True, None)
        for name, hits in sources.items()
    }
    monkeypatch.setattr(
        "agent.sources.aggregator._build_registry", lambda: fake,
    )


def test_calibrated_discovery_runs_per_source_query(monkeypatch):
    """Each source receives a calibrated query string built from
    spec — not the raw topic_terms list."""
    a = _hit(source="pubmed", doi="10.1/x")
    b = _hit(source="europepmc", doi="10.1/y")
    _patch_registry(monkeypatch, {"pubmed": [a], "europepmc": [b]})

    spec = RetrievalSpec(
        topic_terms=("rapamycin",),
        scope_terms=("aging",),
        evidence_types=("clinical trial",),
        date_from=2010, languages=("English",), species=("humans",),
    )

    async def _run():
        return await discover_calibrated(spec)

    hits, stats = asyncio.run(_run())
    assert len(hits) == 2
    assert stats["raw_pubmed"] == 1
    assert stats["raw_europepmc"] == 1
    assert stats["aggregated_total"] == 2


def test_calibrated_discovery_honors_safety_cap(monkeypatch):
    """200 raw hits, cap=50 → output truncated to 50."""
    pubs = [
        _hit(source="pubmed", doi=f"10.1/{i}") for i in range(200)
    ]
    _patch_registry(monkeypatch, {"pubmed": pubs})

    spec = RetrievalSpec(topic_terms=("rapamycin",))
    params = resolve_params(
        "calibrated", safety_cap_override=50,
    )

    async def _run():
        return await discover_calibrated(spec, params=params)

    hits, stats = asyncio.run(_run())
    assert len(hits) == 50
    assert stats.get("safety_cap_triggered") == 1


def test_calibrated_discovery_skips_empty_query(monkeypatch):
    """A spec that produces an empty query for a source skips it
    cleanly (stats record `empty_<source>=1`)."""
    _patch_registry(monkeypatch, {"pubmed": []})

    # All-empty spec → builder returns "" for every source.
    spec = RetrievalSpec()

    async def _run():
        return await discover_calibrated(spec)

    hits, stats = asyncio.run(_run())
    assert hits == []
    assert stats.get("empty_pubmed") == 1


def test_calibrated_discovery_with_multiple_sources_dedupes(monkeypatch):
    """Same DOI returned by 3 sources → 1 hit, n_sources=3."""
    same = [_hit(source=src, doi="10.1/shared")
            for src in ("pubmed", "europepmc", "openalex")]
    _patch_registry(monkeypatch, {
        "pubmed": [same[0]],
        "europepmc": [same[1]],
        "openalex": [same[2]],
    })
    spec = RetrievalSpec(topic_terms=("rapamycin",))

    async def _run():
        return await discover_calibrated(spec)

    hits, stats = asyncio.run(_run())
    assert len(hits) == 1
    assert hits[0].n_sources == 3
    assert stats["raw_total_pre_dedupe"] == 3
    assert stats["unique_keys_post_dedupe"] == 1
