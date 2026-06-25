"""Tests for agent/query_builder.py — Slice 6 step 3.

Verifies per-source advanced-query translation from a RetrievalSpec.
Universal across topics + domains; assertions use synthetic
RetrievalSpecs to keep tests independent of any specific topic pack.
"""
from __future__ import annotations

from typing import Any

from agent.query_builder import (
    build_europepmc_query,
    build_fullraw_query,
    build_keyword_query,
    build_pubmed_query,
    build_query_for_source,
)
from agent.topic_pack import RetrievalSpec


def _spec(**kw) -> RetrievalSpec:
    """Build a RetrievalSpec with sensible defaults for tests."""
    base: dict[str, Any] = dict(
        topic_terms=("alpha", "beta"),
        scope_terms=("aging", "longevity"),
        evidence_types=("clinical trial", "cohort study"),
        exclude_terms=(),
        date_from=2010,
        languages=("English",),
        species=("humans",),
    )
    base.update(kw)
    return RetrievalSpec(**base)


# ---------- PubMed builder ------------------------------------------

def test_pubmed_uses_field_tags():
    """Topic + scope terms must be wrapped in [tiab]; evidence types
    in [pt]; species [MeSH]; languages [lang]; dates [dp]."""
    q = build_pubmed_query(_spec())
    assert "alpha[tiab]" in q
    assert "aging[tiab]" in q
    assert '"clinical trial"[pt]' in q
    assert "humans[MeSH]" in q
    assert "English[lang]" in q
    assert '"2010"[dp]' in q


def test_pubmed_quotes_multiword_terms():
    """Multi-word terms must be quoted so PubMed parses them as
    phrases, not separate ANDed words."""
    q = build_pubmed_query(_spec(
        topic_terms=("mTOR inhibitor", "rapamycin"),
    ))
    assert '"mTOR inhibitor"[tiab]' in q
    assert "rapamycin[tiab]" in q  # single word, no quotes


def test_pubmed_excludes_use_NOT_clause():
    q = build_pubmed_query(_spec(
        exclude_terms=("transplant rejection", "tumor regression"),
    ))
    assert " NOT " in q
    assert '"transplant rejection"[tiab]' in q
    assert '"tumor regression"[tiab]' in q


def test_pubmed_omits_empty_conjuncts():
    """A spec with empty fields produces a clean query — no dangling
    AND, no empty parens."""
    q = build_pubmed_query(_spec(
        topic_terms=("rapamycin",), scope_terms=(),
        evidence_types=(), exclude_terms=(), species=(),
        languages=(), date_from=None, date_to=None,
    ))
    assert q == "rapamycin[tiab]"
    assert "()" not in q
    assert " AND " not in q


def test_pubmed_query_size_under_3000_chars():
    """A realistic calibrated query (rapamycin-shaped) must fit
    under the source-adapter limit of 3000 chars (raised from 240)."""
    spec = _spec(
        topic_terms=("rapamycin", "sirolimus", "Rapamune",
                     "mTOR inhibitor", "mTORC1 inhibitor", "RAD001"),
        scope_terms=("aging", "longevity", "healthspan",
                     "older adults", "elderly", "geriatric",
                     "geroscience", "senescence", "frailty"),
        evidence_types=("clinical trial", "randomized controlled trial",
                        "cohort study", "observational study",
                        "meta-analysis", "systematic review"),
        exclude_terms=("transplant rejection", "allograft survival",
                       "oncology only", "kidney transplant only",
                       "tumor regression", "neoplasm therapy",
                       "in vitro only", "yeast", "drosophila",
                       "c. elegans", "pediatric only"),
    )
    q = build_pubmed_query(spec)
    assert 200 < len(q) < 3000


# ---------- Europe PMC builder --------------------------------------

def test_europepmc_uses_pubtype_lang_pubyear_no_kw_field_tag():
    """Slice 6 step 5 finding: KW: tag is too strict (controlled-
    vocabulary only). Topic + scope terms run bare; only structural
    filters carry tags."""
    q = build_europepmc_query(_spec())
    # No KW: field tag on topic terms
    assert "KW:alpha" not in q
    assert "alpha" in q  # but term still present
    # Structural filters still use field tags
    assert 'PUB_TYPE:"clinical trial"' in q
    assert "LANG:eng" in q
    assert "PUB_YEAR:[2010 TO 2100]" in q


def test_europepmc_quotes_multiword_topic_terms():
    q = build_europepmc_query(_spec(
        topic_terms=("mTOR inhibitor", "rapamycin"),
    ))
    # Multi-word terms still quoted (so EPMC parses as phrase)
    assert '"mTOR inhibitor"' in q
    assert "rapamycin" in q


def test_europepmc_humans_emits_has_human_available():
    q = build_europepmc_query(_spec(species=("humans",)))
    assert "HAS_HUMAN_AVAILABLE:Y" in q


def test_europepmc_excludes_with_NOT_no_kw_tag():
    """Excludes also use bare terms (same KW: avoidance)."""
    q = build_europepmc_query(_spec(
        exclude_terms=("transplant rejection",),
    ))
    assert ' NOT ' in q
    assert "KW:" not in q
    assert '"transplant rejection"' in q


# ---------- Keyword fallback ----------------------------------------

def test_keyword_query_has_no_field_tags():
    """Plain boolean — no [tiab] / KW: / etc. Used by sources that
    pass filters via separate URL params."""
    q = build_keyword_query(_spec())
    assert "[tiab]" not in q
    assert "KW:" not in q
    assert "alpha OR beta" in q
    assert "aging OR longevity" in q


def test_keyword_query_drops_date_and_pub_type():
    """Keyword query is for sources where dates / pub_type are passed
    out-of-band — only the topic + scope intent goes in the string."""
    q = build_keyword_query(_spec())
    assert "2010" not in q
    assert "[pt]" not in q


def test_fullraw_query_is_ranked_text_not_boolean():
    q = build_fullraw_query(_spec(
        topic_terms=("low dose lithium", "low dose lithium"),
        scope_terms=("aging", "older adults"),
        exclude_terms=("animal only",),
    ))
    assert q == "low dose lithium aging older adults"
    assert " OR " not in q
    assert " AND " not in q
    assert " NOT " not in q


# ---------- Dispatcher ----------------------------------------------

def test_dispatcher_routes_pubmed_to_pubmed_builder():
    spec = _spec()
    assert build_query_for_source("pubmed", spec) == build_pubmed_query(spec)


def test_dispatcher_routes_europepmc_to_europepmc_builder():
    spec = _spec()
    out = build_query_for_source("europepmc", spec)
    assert out == build_europepmc_query(spec)


def test_dispatcher_routes_v5_fullraw_to_ranked_text_builder():
    spec = _spec()
    assert build_query_for_source("v5_fullraw", spec) == build_fullraw_query(spec)


def test_dispatcher_routes_unknown_to_keyword():
    """Unknown source → safe keyword fallback (no field tags)."""
    spec = _spec()
    out = build_query_for_source("not_a_real_source", spec)
    assert out == build_keyword_query(spec)


def test_dispatcher_handles_uppercase_source_name():
    spec = _spec()
    out = build_query_for_source("PubMed", spec)
    assert out == build_pubmed_query(spec)
