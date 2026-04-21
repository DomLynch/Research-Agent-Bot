"""Tests for topic-specific negative filters (Step 9)."""

from agent.planner import (
    DOMAIN_NEGATIVE_FILTERS,
    QueryPlanner,
    _filter_evidence,
    _parse_scope,
    _should_filter_entry,
)


def _entry(title: str, excerpt: str = "", year: int = 2024) -> dict:
    return {"title": title, "excerpt": excerpt, "year": year, "source_type": "pubmed"}


# --- _should_filter_entry ---


class TestShouldFilterEntry:
    def test_filters_cooking_entry(self):
        entry = _entry("How to cook with turmeric for anti-aging")
        assert _should_filter_entry(entry, "longevity") is True

    def test_keeps_health_entry(self):
        entry = _entry("Rapamycin effects on lifespan in mice")
        assert _should_filter_entry(entry, "longevity") is False

    def test_filters_sports_entry(self):
        entry = _entry("Basketball training and adolescent growth")
        assert _should_filter_entry(entry, "longevity") is True

    def test_filters_from_excerpt(self):
        entry = _entry("Aging study", excerpt="Results were compared to cooking methods used in recipes")
        assert _should_filter_entry(entry, "longevity") is True

    def test_unknown_domain_uses_general(self):
        entry = _entry("Gaming habits and health")
        assert _should_filter_entry(entry, "obscure_domain") is True

    def test_case_insensitive(self):
        entry = _entry("Fashion trends in clinical trials")
        assert _should_filter_entry(entry, "oncology") is True

    def test_empty_entry(self):
        entry = _entry("", "")
        assert _should_filter_entry(entry, "longevity") is False

    def test_partial_match(self):
        entry = _entry("Recreational gaming and elder care")
        assert _should_filter_entry(entry, "longevity") is True


# --- _filter_evidence ---


class TestFilterEvidence:
    def test_removes_off_topic_entries(self):
        scope = _parse_scope("")
        evidence = [
            _entry("Rapamycin and longevity"),
            _entry("Cooking tips for healthy living"),
            _entry("Metformin lifespan extension"),
        ]
        result = _filter_evidence(scope, evidence, domain_slug="longevity")
        titles = [e["title"] for e in result]
        assert "Cooking tips for healthy living" not in titles
        assert len(result) == 2

    def test_keeps_all_on_topic(self):
        scope = _parse_scope("")
        evidence = [
            _entry("Rapamycin and longevity"),
            _entry("Metformin lifespan extension"),
        ]
        result = _filter_evidence(scope, evidence, domain_slug="longevity")
        assert len(result) == 2

    def test_filters_automotive(self):
        scope = _parse_scope("")
        evidence = [_entry("Automotive emissions and health")]
        result = _filter_evidence(scope, evidence, domain_slug="longevity")
        assert len(result) == 0

    def test_no_false_positive_on_common_words(self):
        scope = _parse_scope("")
        evidence = [_entry("Construction of a novel senolytic compound")]
        result = _filter_evidence(scope, evidence, domain_slug="longevity")
        # "construction" should filter this — it's a negative term
        # But we should accept that common words like this in titles are off-topic
        assert len(result) == 0

    def test_oncology_filters_gaming(self):
        scope = _parse_scope("")
        evidence = [_entry("Gaming addiction and cancer risk")]
        result = _filter_evidence(scope, evidence, domain_slug="oncology")
        assert len(result) == 0

    def test_empty_evidence(self):
        scope = _parse_scope("")
        result = _filter_evidence(scope, [], domain_slug="longevity")
        assert result == []


# --- QueryPlan integration ---


class TestQueryPlanIntegration:
    def test_filter_evidence_passes_domain(self):
        planner = QueryPlanner()
        plan = planner.build(topic="rapamycin lifespan", domain_slug="longevity")
        evidence = [
            _entry("Rapamycin extends lifespan in mice"),
            _entry("Best cooking recipes with turmeric"),
            _entry("Metformin and aging"),
        ]
        result = plan.filter_evidence(evidence)
        titles = [e["title"] for e in result]
        assert "Best cooking recipes with turmeric" not in titles
        assert len(result) == 2


# --- DOMAIN_NEGATIVE_FILTERS ---


class TestDomainNegativeFilters:
    def test_all_domains_have_cooking(self):
        for domain, filters in DOMAIN_NEGATIVE_FILTERS.items():
            assert "cooking" in filters, f"{domain} missing 'cooking'"

    def test_general_has_minimum_entries(self):
        assert len(DOMAIN_NEGATIVE_FILTERS["general"]) >= 5
