"""Tests for agent/corpus_pipeline.py — Slice 6 step 4c.

Verifies the classify-before-extract gate: classify every retrieved
hit on metadata, drop reject + off_thesis from the extraction pool,
emit a corpus manifest with funnel breakdown.
"""
from __future__ import annotations

import asyncio

import agent.corpus_pipeline as cp
from agent.corpus_pipeline import (
    CorpusManifest, build_corpus_manifest, classify_and_filter,
)
from agent.sources.aggregator import AggregatedHit
from agent.topic_pack import RetrievalSpec, TopicPack
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
    assert f["extractable_adjacent"] == 0


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


def test_adjacent_class_lands_in_adjacent_pool():
    h = _hit(
        doi="10.1/Z",
        title="Statin prescribing review",
        abstract="A narrative review of prescribing patterns.",
    )
    manifest = classify_and_filter(
        _wave_report([h]), topic="statins", topic_aliases=("statin",),
    )
    e = manifest.entries[0]
    assert e.classification.classification == "adjacent_clinical"
    assert e.pool == "adjacent"
    assert manifest.funnel["extractable_adjacent"] == 1


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


# ---------- format_funnel_md (Slice 4d) -----------------------------

def test_format_funnel_md_shows_each_stage():
    """The funnel md must surface every stage (retrieved → keep →
    drop → core / background / adjacent) so an operator sees where papers
    were dropped."""
    from agent.corpus_pipeline import format_funnel_md
    a = _hit(doi="10.1/A",
             title="Statin RCT mortality",
             abstract="randomized controlled trial mortality")
    report = _wave_report([a])
    manifest = classify_and_filter(
        report, topic="statins", topic_aliases=("statin",),
    )
    md = format_funnel_md(manifest)
    assert "Corpus funnel" in md
    assert "Retrieved" in md
    assert "Classified" in md
    assert "core pool" in md
    assert "background pool" in md
    assert "adjacent pool" in md
    assert "core_on_thesis" in md


def test_format_funnel_md_flags_safety_cap_when_triggered():
    """When the GLOBAL_SAFETY_CAP fires, the markdown must call
    it out so the operator knows to tighten the calibrated query."""
    from agent.corpus_pipeline import format_funnel_md
    manifest = CorpusManifest(
        topic="x", entries=(),
        funnel={"retrieved": 200_000, "cap_triggered": 1},
    )
    md = format_funnel_md(manifest)
    assert "GLOBAL_SAFETY_CAP" in md or "truncated" in md.lower()


def test_build_manifest_uses_active_and_mechanism_aliases(monkeypatch):
    """Tiered certification needs both direct intervention names and
    mechanism aliases during classify-before-extract."""
    async def fake_run_waves(*_args, **_kwargs):
        return _wave_report([
            _hit(
                doi="10.1/m",
                title="mTOR inhibition improves immune function in the elderly",
                abstract="A randomized controlled trial tested mTOR inhibition.",
            ),
        ])

    monkeypatch.setattr(cp, "run_waves", fake_run_waves)
    pack = TopicPack(
        topic="rapamycin",
        drug_class="mtor_inhibitor",
        aliases=frozenset(("mtor inhibitor",)),
        aliases_display=("mTOR inhibitor",),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(),
        canonical_trials=(),
        known_role_overrides={},
        active_arm_synonyms=frozenset(("rapamycin", "sirolimus")),
        retrieval=RetrievalSpec(topic_terms=("rapamycin",)),
    )
    manifest = asyncio.run(build_corpus_manifest(pack))
    assert manifest.entries[0].classification.classification == "core_on_thesis"


def test_topic_aliases_for_classification_merges_active_and_display_aliases():
    pack = TopicPack(
        topic="rapamycin",
        drug_class="mtor_inhibitor",
        aliases=frozenset(("mtor inhibitor",)),
        aliases_display=("mTOR inhibitor",),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(),
        canonical_trials=(),
        known_role_overrides={},
        active_arm_synonyms=frozenset(("rapamycin", "sirolimus")),
    )
    aliases = cp.topic_aliases_for_classification(pack)
    assert "rapamycin" in aliases
    assert "sirolimus" in aliases
    assert "mTOR inhibitor" in aliases


def test_extraction_pools_include_background_when_inference_enabled():
    pack = TopicPack(
        topic="rapamycin",
        drug_class="mtor_inhibitor",
        aliases=frozenset(("rapamycin",)),
        aliases_display=("rapamycin",),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(),
        canonical_trials=(),
        known_role_overrides={},
        active_arm_synonyms=frozenset(("rapamycin",)),
    )
    assert cp.extraction_pools_for_pack(pack) == frozenset((
        "adjacent", "background", "core",
    ))


def test_primary_tier_off_thesis_paper_is_rescued_into_adjacent_pool():
    """A rigorous trial that misses thesis keywords must still be extracted.

    The 5-class gate scores topical fit, so primary-tier trials were dropped
    before extraction and could never become receipts, while keyword-matching
    mechanistic reviews survived. Publication needs 3 primary-tier / 4 direct
    receipts, so starving that class stalls publishing. Rescued papers are
    adjacent evidence, never core — they are off-thesis by the classifier.
    """
    hits = [
        _hit(doi="10.1/RESCUE",
             title="Randomized controlled trial of supervised walking",
             abstract="In this randomized controlled trial, participants "
                      "were randomly assigned to supervised walking or "
                      "usual care and followed for 12 months."),
    ]
    manifest = classify_and_filter(
        _wave_report(hits), topic="statins", topic_aliases=("statin",),
    )
    entry = manifest.entries[0]
    assert entry.classification.classification == "off_thesis"
    assert entry.keep_for_extraction, "primary-tier evidence must reach extraction"
    assert entry.pool == "adjacent", "rescued papers must not inflate the core pool"
    assert manifest.funnel["primary_tier_rescued"] == 1


def test_hard_reject_is_not_rescued_even_when_primary_tier():
    """`reject` means wrong species/topic outright, not merely off-thesis."""
    hits = [
        _hit(doi="10.1/REJECT",
             title="Randomized trial of cardioversion in atrial fibrillation",
             abstract="AF patients underwent cardioversion in a randomized "
                      "controlled trial."),
    ]
    manifest = classify_and_filter(
        _wave_report(hits), topic="statins", topic_aliases=("statin",),
    )
    entry = manifest.entries[0]
    assert entry.classification.classification == "reject"
    assert not entry.keep_for_extraction
    assert manifest.funnel["primary_tier_rescued"] == 0
