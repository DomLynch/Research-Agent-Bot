from agent.planner import QueryPlanner, _human_ok


def test_planner_generates_multiple_queries() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity")
    assert len(plan.queries) >= 2
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


def test_default_query_set_is_unique() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="senolytics and healthspan", domain_slug="longevity")
    assert len(plan.queries) == len(set(plan.queries))


def test_general_domain_safety_net_avoids_duplicate_outcomes() -> None:
    planner = QueryPlanner()
    plan = planner.build(topic="rapamycin", domain_slug="anti-aging")
    assert "outcomes outcomes" not in " ".join(plan.queries).lower()


def test_parse_scope_accepts_onwards_post_and_ge_phrasing() -> None:
    planner = QueryPlanner()
    onward = planner.build(topic="metformin", domain_slug="longevity", criteria="2023 onwards human studies relevance")
    post = planner.build(topic="metformin", domain_slug="longevity", criteria="post-2023 human studies")
    ge = planner.build(topic="metformin", domain_slug="longevity", criteria="≥2023 human studies")
    assert onward.scope_signals() == ["year>=2023", "human_only"]
    assert post.scope_signals() == ["year>=2023", "human_only"]
    assert ge.scope_signals() == ["year>=2023", "human_only"]


def test_human_only_rejects_non_human_species_in_title() -> None:
    assert _human_ok(
        {
            "title": "Metformin treatment of diverse Caenorhabditis species extends longevity",
            "excerpt": "Human longevity pathways are discussed for comparison.",
            "query": "metformin human studies longevity",
        }
    ) is False


def test_human_only_keeps_patient_study() -> None:
    assert _human_ok(
        {
            "title": "Metformin and mortality in older adults",
            "excerpt": "Clinical cohort of patients aged 65 and older.",
            "query": "metformin human studies longevity",
        }
    ) is True


def test_human_only_does_not_treat_tolerated_as_rat() -> None:
    assert _human_ok(
        {
            "title": "Metformin and physical performance in older people",
            "excerpt": "Metformin did not improve 4-m walk speed and was poorly tolerated in this population.",
            "query": "metformin human studies longevity",
        }
    ) is True


def test_human_only_recognizes_older_people_as_human_signal() -> None:
    assert _human_ok(
        {
            "title": "Metformin in older people with frailty",
            "excerpt": "Randomised placebo-controlled trial in older people with probable sarcopenia.",
            "query": "metformin human studies longevity",
        }
    ) is True
