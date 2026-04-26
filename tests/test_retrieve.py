"""Tests for retrieve.py — query plan, dedup, ref assignment."""
from __future__ import annotations

from agent.retrieve import normalize_and_dedup, plan_queries
from agent.types import RawHit


def _hit(**kw) -> RawHit:
    base = dict(source="pubmed", title="t", abstract="a", year=2024, url="")
    base.update(kw)
    return RawHit(**base)


# --- plan_queries ----------------------------------------------------------


def test_plan_queries_returns_topic_only():
    """Criteria must NOT join into the retrieval query — that broke CT.gov on
    'RCT' tokens in the first capture run."""
    assert plan_queries("rapamycin", "RCT older adults") == ["rapamycin"]


def test_plan_queries_strips_whitespace():
    assert plan_queries("  rapamycin  ", "") == ["rapamycin"]


def test_plan_queries_empty_topic_returns_empty():
    assert plan_queries("", "anything") == []


# --- dedup: identity-key precedence ----------------------------------------


def test_dedup_collapses_doi_case_insensitive():
    hits = [_hit(doi="10.1/X", pmid="111"), _hit(doi="10.1/x", source="openalex")]
    sources, _, _ = normalize_and_dedup(hits)
    assert len(sources) == 1
    assert sources[0].source == "pubmed"  # first wins


def test_dedup_falls_back_to_pmid_when_no_doi():
    hits = [_hit(pmid="123"), _hit(pmid="123", source="europepmc", title="other title")]
    sources, _, _ = normalize_and_dedup(hits)
    assert len(sources) == 1


def test_dedup_falls_back_to_nct():
    hits = [
        _hit(source="clinicaltrials", nct="NCT123"),
        _hit(source="clinicaltrials", nct="nct123", title="case"),
    ]
    sources, _, _ = normalize_and_dedup(hits)
    assert len(sources) == 1
    assert sources[0].nct == "NCT123"


def test_dedup_uses_normalized_title_when_no_ids():
    hits = [
        _hit(title="The Effect of X on Y!"),
        _hit(title="the  effect of x on y", source="openalex"),
    ]
    sources, _, _ = normalize_and_dedup(hits)
    assert len(sources) == 1


def test_dedup_keeps_distinct_when_keys_differ():
    hits = [_hit(doi="10.1/A"), _hit(doi="10.1/B"), _hit(pmid="999")]
    sources, _, _ = normalize_and_dedup(hits)
    assert len(sources) == 3


# --- ref assignment + abstract pass-through --------------------------------


def test_refs_are_one_indexed_and_dense():
    hits = [_hit(doi="10.1/A"), _hit(doi="10.1/B"), _hit(doi="10.1/C")]
    sources, abstracts, _ = normalize_and_dedup(hits)
    assert [s.ref for s in sources] == [1, 2, 3]
    assert sorted(abstracts) == [1, 2, 3]


def test_raw_signals_propagate_clinicaltrials_has_results():
    hits = [
        _hit(
            source="clinicaltrials",
            nct="NCT001",
            raw={"has_results": True, "study_type": "Interventional"},
        )
    ]
    _, _, raw_signals = normalize_and_dedup(hits)
    assert raw_signals[1] == {"has_results": True, "study_type": "Interventional"}
