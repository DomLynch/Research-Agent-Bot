"""Tests for coverage audit script."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Unit tests — pure logic (no mocks needed)
# ---------------------------------------------------------------------------

class TestNormalizeDoi:
    def test_lowercase(self):
        from scripts.coverage_audit import normalize_doi
        assert normalize_doi("10.1000/ABC") == "10.1000/abc"

    def test_strip_https_prefix(self):
        from scripts.coverage_audit import normalize_doi
        assert normalize_doi("https://doi.org/10.1000/xyz") == "10.1000/xyz"

    def test_strip_HTTPS_prefix(self):
        from scripts.coverage_audit import normalize_doi
        assert normalize_doi("HTTPS://DOI.ORG/10.1000/XYZ") == "10.1000/xyz"

    def test_whitespace(self):
        from scripts.coverage_audit import normalize_doi
        assert normalize_doi("  10.1000/abc  ") == "10.1000/abc"

    def test_no_prefix(self):
        from scripts.coverage_audit import normalize_doi
        assert normalize_doi("10.1000/abc") == "10.1000/abc"


class TestLoadGoldTopics:
    def test_returns_tuples(self):
        from scripts.coverage_audit import load_gold_topics
        topics = load_gold_topics()
        assert len(topics) == 10
        for slug, data in topics:
            assert isinstance(slug, str)
            assert isinstance(data, dict)

    def test_expected_slugs(self):
        from scripts.coverage_audit import load_gold_topics
        slugs = [s for s, _ in load_gold_topics()]
        assert "rapamycin" in slugs
        assert "metformin" in slugs

    def test_topic_has_required_fields(self):
        from scripts.coverage_audit import load_gold_topics
        for slug, data in load_gold_topics():
            assert "included_dois" in data, f"{slug} missing included_dois"
            assert "domain" in data, f"{slug} missing domain"
            assert "criteria" in data, f"{slug} missing criteria"


# ---------------------------------------------------------------------------
# Unit tests — audit_topic with mocked retrieval
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_gold():
    return {
        "title": "Test Topic",
        "domain": "metabolic",
        "criteria": "human adults",
        "included_dois": [
            "https://doi.org/10.1000/a",
            "https://doi.org/10.1000/b",
            "https://doi.org/10.1000/c",
            "10.1000/d",
        ],
    }


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_perfect_match(mock_collect, fake_gold):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = {"10.1000/a", "10.1000/b", "10.1000/c", "10.1000/d"}
    result = audit_topic("test", fake_gold)
    assert result["matched_count"] == 4
    assert result["gold_count"] == 4
    assert result["match_rate"] == 1.0
    assert result["missing_sample"] == []


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_partial_match(mock_collect, fake_gold):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = {"10.1000/a", "10.1000/b"}
    result = audit_topic("test", fake_gold)
    assert result["matched_count"] == 2
    assert result["gold_count"] == 4
    assert result["match_rate"] == 0.5
    assert result["missing_sample"] == ["10.1000/c", "10.1000/d"]


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_no_match(mock_collect, fake_gold):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = set()
    result = audit_topic("test", fake_gold)
    assert result["matched_count"] == 0
    assert result["gold_count"] == 4
    assert result["match_rate"] == 0.0
    assert len(result["missing_sample"]) == 4


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_retrieved_has_extra(mock_collect, fake_gold):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = {"10.1000/a", "10.1000/x", "10.1000/y"}
    result = audit_topic("test", fake_gold)
    assert result["matched_count"] == 1
    assert result["retrieved_count"] == 3
    assert result["match_rate"] == 0.25


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_empty_gold(mock_collect):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = {"10.1000/a"}
    gold = {"title": "empty", "domain": "general", "criteria": "", "included_dois": []}
    result = audit_topic("empty", gold)
    assert result["gold_count"] == 0
    assert result["match_rate"] == 0.0


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_audit_topic_missing_sample_capped_at_5(mock_collect):
    from scripts.coverage_audit import audit_topic

    mock_collect.return_value = set()
    gold = {
        "title": "many",
        "domain": "general",
        "criteria": "",
        "included_dois": [f"10.1000/{i}" for i in range(8)],
    }
    result = audit_topic("many", gold)
    assert len(result["missing_sample"]) == 5


# ---------------------------------------------------------------------------
# Unit tests — collect_retrieved_dois with mocked clients
# ---------------------------------------------------------------------------

@patch("scripts.coverage_audit.ClinicalTrialsClient")
@patch("scripts.coverage_audit.RxivClient")
@patch("scripts.coverage_audit.OpenAlexClient")
@patch("scripts.coverage_audit.PubMedClient")
@patch("scripts.coverage_audit.QueryPlanner")
def test_collect_retrieved_dois_merges_sources(
    mock_planner_cls, mock_pubmed_cls, mock_openalex_cls, mock_rxiv_cls, mock_ct_cls
):
    from scripts.coverage_audit import collect_retrieved_dois

    # Mock QueryPlanner to return two queries
    mock_plan = MagicMock()
    mock_plan.primary_queries.return_value = ["query A", "query B"]
    mock_planner_cls.return_value.build.return_value = mock_plan

    # PubMed returns one DOI
    pubmed_client = MagicMock()
    pubmed_client.search.return_value = [
        {"doi": "10.1000/p", "title": "pub"},
    ]
    mock_pubmed_cls.return_value = pubmed_client

    # OpenAlex returns one DOI
    openalex_client = MagicMock()
    openalex_client.search.return_value = [
        {"doi": "10.1000/o", "title": "open"},
    ]
    mock_openalex_cls.return_value = openalex_client

    # Rxiv returns one DOI
    rxiv_client = MagicMock()
    rxiv_client.search.return_value = [
        {"doi": "https://doi.org/10.1000/r", "title": "rxiv"},
    ]
    mock_rxiv_cls.return_value = rxiv_client

    # ClinicalTrials returns doi=None (always)
    ct_client = MagicMock()
    ct_client.search.return_value = [
        {"doi": None, "title": "NCT12345"},
    ]
    mock_ct_cls.return_value = ct_client

    dois = collect_retrieved_dois("test topic", "metabolic", "human adults")
    # Each client called once per query → 2 queries × 4 clients = 8 calls
    assert pubmed_client.search.call_count == 2
    assert openalex_client.search.call_count == 2
    assert rxiv_client.search.call_count == 2
    assert ct_client.search.call_count == 2
    # DOIs should be normalized and merged (ctgov contributes no DOIs)
    assert dois == {"10.1000/p", "10.1000/o", "10.1000/r"}


@patch("scripts.coverage_audit.ClinicalTrialsClient")
@patch("scripts.coverage_audit.RxivClient")
@patch("scripts.coverage_audit.OpenAlexClient")
@patch("scripts.coverage_audit.PubMedClient")
@patch("scripts.coverage_audit.QueryPlanner")
def test_collect_retrieved_dois_skips_none_doi(
    mock_planner_cls, mock_pubmed_cls, mock_openalex_cls, mock_rxiv_cls, mock_ct_cls
):
    from scripts.coverage_audit import collect_retrieved_dois

    mock_plan = MagicMock()
    mock_plan.primary_queries.return_value = ["q1"]
    mock_planner_cls.return_value.build.return_value = mock_plan

    pubmed_client = MagicMock()
    pubmed_client.search.return_value = [
        {"doi": None, "title": "no doi"},
        {"doi": "10.1000/yes", "title": "has doi"},
    ]
    mock_pubmed_cls.return_value = pubmed_client

    openalex_client = MagicMock()
    openalex_client.search.return_value = []
    mock_openalex_cls.return_value = openalex_client

    rxiv_client = MagicMock()
    rxiv_client.search.return_value = []
    mock_rxiv_cls.return_value = rxiv_client

    ct_client = MagicMock()
    ct_client.search.return_value = [{"doi": None, "title": "trial"}]
    mock_ct_cls.return_value = ct_client

    dois = collect_retrieved_dois("topic", "general", "")
    assert dois == {"10.1000/yes"}


@patch("scripts.coverage_audit.ClinicalTrialsClient")
@patch("scripts.coverage_audit.RxivClient")
@patch("scripts.coverage_audit.OpenAlexClient")
@patch("scripts.coverage_audit.PubMedClient")
@patch("scripts.coverage_audit.QueryPlanner")
def test_collect_retrieved_dois_handles_client_exception(
    mock_planner_cls, mock_pubmed_cls, mock_openalex_cls, mock_rxiv_cls, mock_ct_cls
):
    from scripts.coverage_audit import collect_retrieved_dois

    mock_plan = MagicMock()
    mock_plan.primary_queries.return_value = ["q1"]
    mock_planner_cls.return_value.build.return_value = mock_plan

    pubmed_client = MagicMock()
    pubmed_client.search.side_effect = Exception("network error")
    mock_pubmed_cls.return_value = pubmed_client

    openalex_client = MagicMock()
    openalex_client.search.return_value = [{"doi": "10.1000/ok"}]
    mock_openalex_cls.return_value = openalex_client

    rxiv_client = MagicMock()
    rxiv_client.search.return_value = []
    mock_rxiv_cls.return_value = rxiv_client

    ct_client = MagicMock()
    ct_client.search.return_value = []
    mock_ct_cls.return_value = ct_client

    dois = collect_retrieved_dois("topic", "general", "")
    assert dois == {"10.1000/ok"}


# ---------------------------------------------------------------------------
# Integration test — run_audit with mocked retrieval
# ---------------------------------------------------------------------------

@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_run_audit_single_topic(mock_collect):
    from scripts.coverage_audit import run_audit

    mock_collect.return_value = {"10.1000/a"}
    results = run_audit(topic="metformin", limit=5)
    assert len(results) == 1
    assert results[0]["slug"] == "metformin"


@patch("scripts.coverage_audit.collect_retrieved_dois")
def test_run_audit_all_topics(mock_collect):
    from scripts.coverage_audit import run_audit

    mock_collect.return_value = set()
    results = run_audit(limit=5)
    assert len(results) == 10
    slugs = {r["slug"] for r in results}
    assert "rapamycin" in slugs
    assert "metformin" in slugs


# ---------------------------------------------------------------------------
# Main block
# ---------------------------------------------------------------------------

def test_main_no_args():
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "scripts/coverage_audit.py"],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 0


def test_main_unknown_topic():
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "scripts/coverage_audit.py", "--topic", "nonexistent"],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 1
    assert "Unknown topic slug" in result.stderr


# ---------------------------------------------------------------------------
# ClinicalTrialsClient integration
# ---------------------------------------------------------------------------

@patch("scripts.coverage_audit.ClinicalTrialsClient")
@patch("scripts.coverage_audit.RxivClient")
@patch("scripts.coverage_audit.OpenAlexClient")
@patch("scripts.coverage_audit.PubMedClient")
@patch("scripts.coverage_audit.QueryPlanner")
def test_collect_retrieved_dois_includes_clinicaltrials(
    mock_planner_cls, mock_pubmed_cls, mock_openalex_cls, mock_rxiv_cls, mock_ct_cls
):
    """ClinicalTrialsClient is called even though doi is always None."""
    from scripts.coverage_audit import collect_retrieved_dois

    mock_plan = MagicMock()
    mock_plan.primary_queries.return_value = ["q1"]
    mock_planner_cls.return_value.build.return_value = mock_plan

    pubmed_client = MagicMock()
    pubmed_client.search.return_value = []
    mock_pubmed_cls.return_value = pubmed_client

    openalex_client = MagicMock()
    openalex_client.search.return_value = []
    mock_openalex_cls.return_value = openalex_client

    rxiv_client = MagicMock()
    rxiv_client.search.return_value = []
    mock_rxiv_cls.return_value = rxiv_client

    ct_client = MagicMock()
    ct_client.search.return_value = [
        {"id": "NCT12345", "title": "Trial A", "doi": None},
        {"id": "NCT67890", "title": "Trial B", "doi": None},
    ]
    mock_ct_cls.return_value = ct_client

    dois = collect_retrieved_dois("topic", "general", "")
    assert dois == set()  # No DOIs from ctgov
    assert ct_client.search.call_count == 1  # But client WAS called


# ---------------------------------------------------------------------------
# _write_results
# ---------------------------------------------------------------------------

def test_write_results(tmp_path):
    import json
    from scripts.coverage_audit import _write_results
    from scripts.coverage_audit import _RUNS_DIR

    results = [
        {"slug": "test", "gold_count": 3, "retrieved_count": 5,
         "matched_count": 2, "match_rate": 0.6667, "missing_sample": ["10.1000/z"]},
    ]

    _write_results(results)

    md = (_RUNS_DIR / "coverage-audit.md").read_text()
    assert "Coverage Audit" in md
    assert "test" in md

    js = json.loads((_RUNS_DIR / "coverage-audit.json").read_text())
    assert js[0]["slug"] == "test"
    assert js[0]["match_rate"] == 0.6667
