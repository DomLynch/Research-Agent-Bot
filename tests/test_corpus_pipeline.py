"""Tests for agent/corpus_pipeline.py — Slice 6 step 4c.

Verifies the classify-before-extract gate: classify every retrieved
hit on metadata, drop reject + off_thesis from the extraction pool,
emit a corpus manifest with funnel breakdown.
"""
from __future__ import annotations

from agent.corpus_pipeline import (
    CorpusManifest, classify_and_filter,
)
from agent.sources.aggregator import AggregatedHit
from agent.wave_retrieval import WaveReport


def _hit(*, doi: str, title: str = "", abstract: str = "",
        n_sources: int = 1) -> AggregatedHit:
    return AggregatedHit(
        title=title, abstract=abstract, doi=doi, pmid=None, nct=None,
        year=2024, url=f"https://example/{doi}", venue=None,
        sources=("pubmed",), n_sources=n_sources,
    )


def _wave_report(hits: list[AggregatedHit],
                 pool_by_key: dict[str, str] | None = None,
                 ) -> WaveReport:
    return WaveReport(
        all_hits=tuple(hits),
        pool_by_key=pool_by_key or {},
        per_wave_stats=(),
    )


# ---------- classify_and_filter -------------------------------------

def test_drops_reject_and_off_thesis_from_extraction_pool():
    """reject + off_thesis NEVER enter extraction. core +
    background_mechanism + adjacent_clinical → keep."""
    hits = [
        # core_on_thesis: alias hit + RCT signal
        _hit(doi="10.1/A", title="Statin RCT all-cause mortality",
             abstract="A randomized controlled trial of statin "
                      "therapy showed lower all-cause mortality."),
        # background_mechanism: in-vitro signal
        _hit(doi="10.1/B", title="Statin signaling pathway",
             abstract="In vitro analysis of statin and HMG-CoA "
                      "reductase pathway in cell culture."),
        # off_thesis: no alias, no mechanism
        _hit(doi="10.1/C", title="Marketing of supplements",
             abstract="Survey of consumer behavior in vitamin shops."),
        # reject: hard signal
        _hit(doi="10.1/D",
             title="Cardioversion outcomes in atrial fibrillation",
             abstract="AF patients underwent cardioversion."),
    ]
    report = _wave_report(hits)
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    kept = {e.classification.classification for e in manifest.kept()}
    dropped = {e.classification.classification
               for e in manifest.dropped()}
    assert kept == {"core_on_thesis", "background_mechanism"}
    assert dropped == {"off_thesis", "reject"}


def test_funnel_reports_retrieve_classify_extractable_counts():
    hits = [
        _hit(doi=f"10.1/{i}",
             title="Statin RCT mortality",
             abstract="randomized controlled trial mortality")
        for i in range(5)
    ]
    report = _wave_report(hits)
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    f = manifest.funnel
    assert f["retrieved"] == 5
    assert f["classified_keep"] == 5  # all 5 are core
    assert f["classified_drop"] == 0
    assert f["class_core_on_thesis"] == 5
    assert f["extractable_core"] == 5
    assert f["extractable_background"] == 0


def test_background_class_lands_in_background_pool():
    """background_mechanism classification → pool='background'
    even when wave_report assigned 'core' (the classifier overrides
    the wave assignment when it sees mechanism signals)."""
    h = _hit(doi="10.1/X",
             title="In vitro statin signaling pathway",
             abstract="Cell culture analysis of statin in vitro "
                      "kinase activity in HMG-CoA pathway.")
    report = _wave_report([h], pool_by_key={"doi:10.1/X": "core"})
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    e = manifest.entries[0]
    assert e.classification.classification == "background_mechanism"
    assert e.pool == "background"


def test_dropped_entries_have_dropped_pool_label():
    h = _hit(doi="10.1/Y", title="x", abstract="y")
    report = _wave_report([h])
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    # 'x' / 'y' has neither alias nor mechanism → off_thesis
    e = manifest.entries[0]
    assert not e.keep_for_extraction
    assert e.pool == "_dropped"


def test_manifest_kept_dropped_helpers():
    a = _hit(doi="10.1/A", title="Statin RCT mortality",
             abstract="randomized controlled trial all-cause mortality")
    b = _hit(doi="10.1/B", title="Marketing", abstract="survey")
    report = _wave_report([a, b])
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    assert len(manifest.kept()) == 1
    assert len(manifest.dropped()) == 1


def test_manifest_by_class_helper():
    h = _hit(doi="10.1/A", title="Statin RCT mortality",
             abstract="randomized controlled trial mortality")
    report = _wave_report([h])
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    core = manifest.by_class("core_on_thesis")
    assert len(core) == 1
    assert manifest.by_class("reject") == ()


def test_empty_wave_report_produces_empty_manifest():
    manifest = classify_and_filter(
        _wave_report([]), topic="x", topic_aliases=("x",),
    )
    assert manifest.entries == ()
    assert manifest.funnel["retrieved"] == 0
    assert manifest.funnel["classified_keep"] == 0
