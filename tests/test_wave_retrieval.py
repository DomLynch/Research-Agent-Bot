"""Tests for agent/wave_retrieval.py — Slice 6 step 4b.

Covers compose_waves derivation logic + run_waves orchestration
with mocked discover_calibrated. Universal across topics — uses
synthetic RetrievalSpecs.
"""
from __future__ import annotations

import asyncio

from agent.sources.aggregator import AggregatedHit
from agent.topic_pack import RetrievalSpec
from agent.wave_retrieval import (
    compose_waves, run_waves,
)


def _spec(**kw) -> RetrievalSpec:
    base = dict(
        topic_terms=("alpha",),
        scope_terms=("aging",),
        evidence_types=("clinical trial",),
        exclude_terms=(),
        date_from=2010, languages=("English",), species=("humans",),
    )
    base.update(kw)
    return RetrievalSpec(**base)


def _hit(*, doi: str, source: str = "pubmed") -> AggregatedHit:
    return AggregatedHit(
        title="T", abstract="A", doi=doi, pmid=None, nct=None,
        year=2024, url=f"https://example/{doi}", venue=None,
        sources=(source,), n_sources=1,
    )


# ---------- compose_waves -------------------------------------------

def test_precision_wave_uses_full_spec():
    spec = _spec()
    waves = compose_waves(spec)
    precision = next(w for w in waves if w.label == "precision")
    assert precision.target_pool == "core"
    assert precision.spec.evidence_types == ("clinical trial",)
    assert precision.spec.scope_terms == ("aging",)


def test_recall_wave_drops_evidence_types():
    """Recall keeps topic + scope, drops evidence_types so the
    pub-type filter doesn't squeeze out cohorts filed as 'article'."""
    spec = _spec()
    waves = compose_waves(spec)
    recall = next(w for w in waves if w.label == "recall")
    assert recall.target_pool == "core"
    assert recall.spec.evidence_types == ()
    assert recall.spec.scope_terms == ("aging",)


def test_background_wave_uses_background_allow_as_scope():
    """Background canon wave swaps scope_terms for background_allow
    + drops evidence_types so mechanism/dose-rationale papers get
    pulled into the background pool instead of being rejected as
    off-thesis."""
    spec = _spec(background_allow=("mTOR mechanism", "dose rationale"))
    waves = compose_waves(spec)
    bg = next(w for w in waves if w.label == "background")
    assert bg.target_pool == "background"
    assert bg.spec.scope_terms == ("mTOR mechanism", "dose rationale")
    assert bg.spec.evidence_types == ()


def test_background_wave_skipped_when_no_allow_list():
    """A pack without [retrieval.background].allow → no background
    wave (skipped, not zero-input)."""
    spec = _spec(background_allow=())
    waves = compose_waves(spec)
    labels = [w.label for w in waves]
    assert "background" not in labels


def test_recall_wave_skipped_when_no_evidence_types():
    """If evidence_types is already empty, recall == precision —
    skip the duplicate to avoid wasted retrieval."""
    spec = _spec(evidence_types=())
    waves = compose_waves(spec)
    labels = [w.label for w in waves]
    assert "recall" not in labels


def test_compose_waves_skips_when_spec_is_empty():
    """A bare spec with nothing useful set → no waves (caller
    responsible for handling)."""
    spec = RetrievalSpec()
    assert compose_waves(spec) == []


# ---------- run_waves (mocked) --------------------------------------

def _patch_discover(monkeypatch, hits_per_wave: list[list[AggregatedHit]]):
    """Patch discover_calibrated to return successive hit lists,
    one per wave call."""
    state = {"calls": 0}

    async def fake_discover(spec, *, params=None,
                            enabled_sources=None, timeout=None):
        i = state["calls"]
        state["calls"] += 1
        if i < len(hits_per_wave):
            return hits_per_wave[i], {
                "raw_total_pre_dedupe": len(hits_per_wave[i]),
                "unique_keys_post_dedupe": len(hits_per_wave[i]),
            }
        return [], {"raw_total_pre_dedupe": 0,
                    "unique_keys_post_dedupe": 0}

    monkeypatch.setattr(
        "agent.wave_retrieval.discover_calibrated", fake_discover,
    )


def test_run_waves_accumulates_dedup_across_waves(monkeypatch):
    """Same DOI returned by precision + recall → only counted once
    in WaveReport.all_hits, but recorded as 'new_to_corpus' only on
    the wave that first saw it."""
    a = _hit(doi="10.1/A")
    b = _hit(doi="10.1/B")
    c = _hit(doi="10.1/A")  # dup of A
    _patch_discover(monkeypatch, [[a, b], [c]])
    report = asyncio.run(run_waves(_spec()))
    assert len({h.doi for h in report.all_hits}) == 2
    # Precision: 2 new. Recall: 0 new (dup).
    by_label = {s["wave"]: s for s in report.per_wave_stats}
    assert by_label["precision"]["new_to_corpus"] == 2
    assert by_label["recall"]["new_to_corpus"] == 0


def test_run_waves_assigns_first_touched_pool(monkeypatch):
    """A paper retrieved by both precision (core) and background
    (background) gets the FIRST-touched pool — precision wins.
    This prevents background wave from downgrading a strict-on-thesis
    paper into the background pool."""
    a = _hit(doi="10.1/x")
    b = _hit(doi="10.1/y")
    c = _hit(doi="10.1/x")  # same as a, retrieved by background wave
    _patch_discover(monkeypatch, [[a], [], [c, b]])
    report = asyncio.run(run_waves(_spec(
        background_allow=("mechanism",),
    )))
    assert report.pool_by_key["doi:10.1/x"] == "core"
    assert report.pool_by_key["doi:10.1/y"] == "background"


def test_run_waves_honors_safety_cap(monkeypatch):
    """Safety cap of 1 → only one paper accumulated even though
    discover_calibrated returns 5 in the first wave."""
    hits = [_hit(doi=f"10.1/{i}") for i in range(5)]
    _patch_discover(monkeypatch, [hits, [], []])
    from agent.retrieval_modes import resolve_params
    params = resolve_params("calibrated", safety_cap_override=1)
    report = asyncio.run(run_waves(
        _spec(background_allow=("m",)),
        params=params,
    ))
    assert len(report.all_hits) == 1
    assert report.cap_triggered is True


def test_run_waves_returns_per_wave_stats(monkeypatch):
    """Per-wave stats expose the funnel breakdown (raw / wave_unique
    / new_to_corpus / cumulative). Slice 4d dashboard reads these."""
    a = _hit(doi="10.1/A")
    _patch_discover(monkeypatch, [[a], [], []])
    report = asyncio.run(run_waves(_spec(
        background_allow=("m",),
    )))
    stats = report.per_wave_stats
    assert len(stats) == 3  # precision + recall + background
    assert stats[0]["wave"] == "precision"
    assert stats[0]["new_to_corpus"] == 1
    assert stats[0]["cumulative"] == 1
