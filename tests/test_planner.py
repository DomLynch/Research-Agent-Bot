from agent.planner import QueryPlanner


def test_planner_generates_multiple_queries() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity")
    assert len(plan.queries) == 3
    assert any("systematic review" in q.lower() for q in plan.queries)


def test_criteria_is_prioritized_when_it_contains_real_scope() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity", criteria="human studies safety 2020+")
    assert plan.queries[0].lower().startswith("senolytics and healthspan human studies safety 2020+")
    assert plan.scope_signals() == ["year>=2020", "human_only", "safety_focus"]


def test_noise_criteria_does_not_replace_default_query() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity", criteria="hey")
    assert any("systematic review" in q.lower() for q in plan.queries)
    assert not any(plan.scope.values())


def test_topic_token_scoring_prefers_exact_overlap() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity")
    evidence = [
        {"title": "Senolytics and healthspan in older adults", "excerpt": "review evidence", "year": 2024, "evidence_type": "review", "url": "https://pubmed.test/1/"},
        {"title": "General geroprotector framework", "excerpt": "framework paper", "year": 2024, "evidence_type": "review", "url": "https://pubmed.test/2/"},
        {"title": "Senolytics review 2024", "excerpt": "single token match", "year": 2024, "evidence_type": "review", "url": "https://pubmed.test/3/"},
    ]
    filtered = plan.filter_evidence(evidence)
    assert filtered[0]["url"] == "https://pubmed.test/1/"
