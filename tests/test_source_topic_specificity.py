from source_topic_specificity import generated_pack_publishable, is_source_topic_specific, topic_aliases  # type: ignore[import-not-found]


def test_hydrogen_water_rejects_chemistry_drift() -> None:
    text = "Cheminform abstract hydrogen evolving systems formation on silicon oxide catalyst"
    assert not is_source_topic_specific("hydrogen_water", text, aliases=("hydrogen water", "molecular hydrogen"))


def test_hydrogen_water_rejects_plant_cell_drift() -> None:
    text = "Molecular hydrogen improves blueberry plant fruit traits via cell signaling"
    assert not is_source_topic_specific("hydrogen_water", text, aliases=("hydrogen water", "molecular hydrogen"))


def test_hydrogen_water_accepts_biomedical_molecular_hydrogen() -> None:
    text = "Randomized clinical trial of molecular hydrogen water in human metabolic health"
    assert is_source_topic_specific("hydrogen_water", text, aliases=("hydrogen water", "molecular hydrogen"))


def test_single_token_biomedical_topic_accepts_anchor() -> None:
    text = "Rapamycin intervention trial in aged mice"
    assert is_source_topic_specific("rapamycin", text, aliases=("rapamycin",))


def test_generated_pack_publishable_uses_structural_specificity() -> None:
    assert generated_pack_publishable({
        "candidate_count": 12,
        "pack_data": {"topic": "telomere_biomarker_effects", "aliases": ["telomere biomarker effects", "telomere"]},
    })
    assert not generated_pack_publishable({
        "candidate_count": 12,
        "pack_data": {"topic": "biomarker_effects", "aliases": ["biomarker effects", "biomarker"]},
    })
    assert not generated_pack_publishable({
        "candidate_count": 12,
        "pack_data": {"topic": "biomarker_effects_aging_evidence", "aliases": ["biomarker effects aging evidence", "biomarker"]},
    })


def test_generated_pack_publishable_uses_peer_relative_specificity() -> None:
    broad = {
        "candidate_count": 5,
        "pack_data": {"topic": "biomarker_effects", "aliases": ["biomarker effects", "biomarker"]},
    }
    specific = {
        "candidate_count": 3,
        "pack_data": {"topic": "metformin_biomarker_subgroups", "aliases": ["metformin biomarker subgroups", "metformin", "biomarker"]},
    }
    peers = [
        broad,
        specific,
        {"candidate_count": 4, "pack_data": {"topic": "cardiovascular_subgroups", "aliases": ["cardiovascular subgroups", "cardiovascular"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_subgroups", "aliases": ["cancer subgroups", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "fasting_subgroups", "aliases": ["fasting subgroups", "fasting"]}},
        {"candidate_count": 4, "pack_data": {"topic": "rapamycin_subgroups", "aliases": ["rapamycin subgroups", "rapamycin"]}},
    ]

    assert generated_pack_publishable(specific, peer_records=peers)
    assert not generated_pack_publishable(broad, peer_records=peers)


def test_generated_pack_scope_axis_is_not_enough_for_specificity() -> None:
    broad_scope_only = {
        "candidate_count": 25,
        "pack_data": {
            "topic": "cancer_mortality_effects",
            "aliases": ["cancer mortality effects", "cancer", "mortality"],
            "retrieval": {
                "topic_terms": ["cancer mortality effects", "cancer", "mortality"],
                "scope_terms": ["mortality", "biomarkers", "frailty"],
            },
        },
    }
    specific = {
        "candidate_count": 12,
        "pack_data": {
            "topic": "telomere_biomarker_effects",
            "aliases": ["telomere biomarker effects", "telomere", "biomarker"],
            "retrieval": {
                "topic_terms": ["telomere biomarker effects", "telomere", "biomarker"],
                "scope_terms": ["mortality", "biomarkers", "frailty"],
            },
        },
    }
    peers = [
        broad_scope_only,
        specific,
        {"candidate_count": 4, "pack_data": {"topic": "cancer_biomarker_effects", "aliases": ["cancer biomarker effects", "cancer", "biomarker"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_rates", "aliases": ["cancer rates", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_safety", "aliases": ["cancer safety", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_frailty", "aliases": ["cancer frailty", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_survival", "aliases": ["cancer survival", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "fasting_mortality", "aliases": ["fasting mortality", "fasting", "mortality"]}},
    ]

    assert not generated_pack_publishable(broad_scope_only, peer_records=peers)
    assert generated_pack_publishable(specific, peer_records=peers)


def test_topic_aliases_loads_local_and_generated_terms(tmp_path) -> None:
    (tmp_path / "topic_packs").mkdir()
    (tmp_path / "topic_packs" / "hydrogen_water.toml").write_text(
        'aliases = ["molecular hydrogen"]\n',
        encoding="utf-8",
    )
    (tmp_path / "topic_packs_db" / "hydrogen_water").mkdir(parents=True)
    (tmp_path / "topic_packs_db" / "hydrogen_water" / "latest.json").write_text(
        '{"pack_data":{"aliases":["hydrogen-rich water"],"retrieval":{"topic_terms":["H2"]}}}',
        encoding="utf-8",
    )

    assert topic_aliases("hydrogen_water", root=tmp_path) == (
        "hydrogen_water",
        "hydrogen water",
        "molecular hydrogen",
        "hydrogen-rich water",
        "h2",
    )
