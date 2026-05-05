"""Tests for agent/extraction_queue.py — Slice 8 step C.

Verifies classify-before-extract gate + funnel telemetry. Uses a
fake extractor script so no subprocess actually runs the real
quant_claim_extract.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.corpus_classifier import CorpusClassification
from agent.corpus_pipeline import CorpusEntry, CorpusManifest
from agent.extraction_queue import (
    ExtractionFunnel, ExtractionResult,
    run_extraction_queue, write_funnel_sidecar,
)
from agent.sources.aggregator import AggregatedHit


def _entry(*, paper_id: str, classification: str,
           keep: bool = True, pool: str = "core") -> CorpusEntry:
    return CorpusEntry(
        hit=AggregatedHit(
            title="T", abstract="A", doi=None, pmid=None,
            nct=None, year=2024, url="https://x", venue=None,
            sources=("test",), n_sources=1,
        ),
        classification=CorpusClassification(
            paper_id=paper_id, classification=classification,
            score=80, reason="test", signals=(),
        ),
        pool=pool,
        keep_for_extraction=keep,
    )


def _manifest(entries, funnel_dict=None) -> CorpusManifest:
    return CorpusManifest(
        topic="test_topic",
        entries=tuple(entries),
        funnel=funnel_dict or {
            "retrieved": len(entries),
            "classified_keep": sum(
                1 for e in entries if e.keep_for_extraction
            ),
            "classified_drop": sum(
                1 for e in entries if not e.keep_for_extraction
            ),
        },
    )


def _make_extractor_script(tmp_path: Path) -> Path:
    """Fake extractor that emits a quant_claims.json with 3 claims."""
    script = tmp_path / "fake_extractor.py"
    script.write_text(
        '#!/usr/bin/env python3\n'
        'import argparse, json\n'
        'p = argparse.ArgumentParser()\n'
        'p.add_argument("input")\n'
        'p.add_argument("--out", required=True)\n'
        'a = p.parse_args()\n'
        'open(a.out, "w").write(json.dumps('
        '{"claims": [{"x": 1}, {"x": 2}, {"x": 3}]}'
        '))\n'
    )
    return script


def _make_parsed_file(parsed_dir: Path, paper_id: str) -> Path:
    parsed_dir.mkdir(parents=True, exist_ok=True)
    p = parsed_dir / f"{paper_id}.paper_sections.json"
    p.write_text(json.dumps({"paper_id": paper_id, "sections": {}}))
    return p


# ---------- queue runs only on kept entries ---------------------------

def test_queue_skips_dropped_entries(tmp_path):
    parsed_dir = tmp_path / "parsed"
    quant_dir = tmp_path / "quant"
    extractor = _make_extractor_script(tmp_path)
    _make_parsed_file(parsed_dir, "P_keep")
    _make_parsed_file(parsed_dir, "P_drop")

    manifest = _manifest([
        _entry(paper_id="P_keep", classification="core_on_thesis",
               keep=True),
        _entry(paper_id="P_drop", classification="off_thesis",
               keep=False),
    ])
    results, f = run_extraction_queue(
        manifest, parsed_dir=parsed_dir, quant_dir=quant_dir,
        extractor_script=extractor,
    )
    # Only the kept entry was processed — dropped entries don't
    # appear in results at all (queue iterates kept() helper).
    assert len(results) == 1
    assert results[0].paper_id == "P_keep"
    assert results[0].status == "extracted"
    assert results[0].n_claims == 3
    assert f.extracted_ok == 1


def test_cached_entry_not_re_extracted(tmp_path):
    parsed_dir = tmp_path / "parsed"
    quant_dir = tmp_path / "quant"
    quant_dir.mkdir()
    extractor = _make_extractor_script(tmp_path)
    _make_parsed_file(parsed_dir, "P_cached")
    # Pre-create the target so the queue should skip extract
    (quant_dir / "P_cached.quant_claims.json").write_text(
        json.dumps({"claims": [{"a": 1}, {"b": 2}]}),
    )
    manifest = _manifest([
        _entry(paper_id="P_cached", classification="core_on_thesis"),
    ])
    results, f = run_extraction_queue(
        manifest, parsed_dir=parsed_dir, quant_dir=quant_dir,
        extractor_script=extractor,
    )
    assert results[0].status == "cached"
    assert results[0].n_claims == 2
    assert f.extracted_cached == 1
    assert f.extracted_ok == 0


def test_skipped_when_no_parsed_file(tmp_path):
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    quant_dir = tmp_path / "quant"
    extractor = _make_extractor_script(tmp_path)
    manifest = _manifest([
        _entry(paper_id="P_missing", classification="core_on_thesis"),
    ])
    results, f = run_extraction_queue(
        manifest, parsed_dir=parsed_dir, quant_dir=quant_dir,
        extractor_script=extractor,
    )
    assert results[0].status == "skipped"
    assert "no parsed_sections" in (results[0].error or "")


def test_extractor_failure_is_recorded_not_fatal(tmp_path):
    """A failing extractor on one paper doesn't kill the queue —
    other papers still run."""
    parsed_dir = tmp_path / "parsed"
    quant_dir = tmp_path / "quant"
    # Failing extractor: writes nothing, exits 1
    extractor = tmp_path / "fail_extractor.py"
    extractor.write_text(
        '#!/usr/bin/env python3\nimport sys; sys.exit(1)\n'
    )
    _make_parsed_file(parsed_dir, "P_a")
    _make_parsed_file(parsed_dir, "P_b")
    manifest = _manifest([
        _entry(paper_id="P_a", classification="core_on_thesis"),
        _entry(paper_id="P_b", classification="core_on_thesis"),
    ])
    results, f = run_extraction_queue(
        manifest, parsed_dir=parsed_dir, quant_dir=quant_dir,
        extractor_script=extractor,
    )
    assert len(results) == 2
    assert all(r.status == "failed" for r in results)
    assert f.extracted_failed == 2


# ---------- ExtractionFunnel ------------------------------------------

def test_funnel_carries_classify_stage_counts():
    """The funnel pulls retrieved + classified_keep / drop from the
    upstream CorpusManifest funnel."""
    parsed_dir = Path("/tmp/nope")
    manifest = _manifest(
        [],
        funnel_dict={
            "retrieved": 583,
            "classified_keep": 428,
            "classified_drop": 155,
        },
    )
    f = ExtractionFunnel(topic="test")
    f.retrieved = manifest.funnel.get("retrieved", 0)
    f.classified_keep = manifest.funnel.get("classified_keep", 0)
    f.classified_drop = manifest.funnel.get("classified_drop", 0)
    d = f.to_dict()
    assert d["stages"]["retrieved"] == 583
    assert d["stages"]["classified_keep"] == 428
    assert d["stages"]["classified_drop"] == 155


def test_funnel_dict_has_all_six_stages():
    """The funnel surface is fixed: 6+ stages from retrieve through
    synthesize. Slice 8 step F dashboard renders these directly."""
    f = ExtractionFunnel(topic="t")
    d = f.to_dict()
    for stage in (
        "retrieved", "classified_keep", "classified_drop",
        "extracted_ok", "extracted_cached", "extracted_failed",
        "spar_accepted", "clustered_into_n", "synthesized",
    ):
        assert stage in d["stages"]


def test_write_funnel_sidecar(tmp_path):
    f = ExtractionFunnel(
        topic="rapamycin", retrieved=583, classified_keep=428,
        extracted_ok=200, spar_accepted=11,
    )
    out = tmp_path / "funnel.json"
    write_funnel_sidecar(f, out_path=out)
    data = json.loads(out.read_text())
    assert data["topic"] == "rapamycin"
    assert data["stages"]["retrieved"] == 583
    assert data["stages"]["spar_accepted"] == 11
