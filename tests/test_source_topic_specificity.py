from source_topic_specificity import generated_pack_publishable, is_source_topic_specific, source_gate_aliases, topic_aliases  # type: ignore[import-not-found]


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


def test_multi_token_topic_rejects_single_generic_biomed_token() -> None:
    text = "Randomized exercise intervention reduced inflammation in older adults"
    assert not is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        text,
        aliases=("low dose naltrexone", "naltrexone"),
    )


def test_multi_token_topic_accepts_named_intervention_and_context() -> None:
    text = "Low-dose naltrexone trial in adults with inflammatory symptoms"
    assert is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        text,
        aliases=("low dose naltrexone", "naltrexone"),
    )


def test_multi_token_topic_accepts_named_intervention_without_generic_outcome() -> None:
    text = "Partial efficacy of low-dose naltrexone in chronic pain management"
    assert is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        text,
        aliases=("low dose naltrexone inflammation",),
    )


def test_source_gate_aliases_drop_generic_biomed_alias_for_composite_topic() -> None:
    aliases = source_gate_aliases(
        "low_dose_naltrexone_inflammation",
        ("low dose naltrexone inflammation", "low-dose naltrexone", "ldn", "inflammation", "immune modulation"),
    )

    assert aliases == ("low dose naltrexone inflammation", "low-dose naltrexone")
    assert not is_source_topic_specific("low_dose_naltrexone_inflammation", "LDN chronic pain trial", aliases=aliases)
    assert not is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        "LDN laparoscopic donor nephrectomy cohort",
        aliases=aliases,
    )
    assert is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        "Low-dose naltrexone chronic pain trial",
        aliases=aliases,
    )
    assert not is_source_topic_specific("low_dose_naltrexone_inflammation", "exercise inflammation cohort", aliases=aliases)


def test_source_gate_aliases_drop_pathway_only_alias_for_composite_topic() -> None:
    aliases = source_gate_aliases(
        "sulforaphane_nrf2",
        ("sulforaphane nrf2", "sulforaphane", "nrf2"),
    )

    assert aliases == ("sulforaphane nrf2",)
    assert is_source_topic_specific("sulforaphane_nrf2", "sulforaphane activates NRF2 in adults", aliases=aliases)
    assert not is_source_topic_specific("sulforaphane_nrf2", "serum NRF2 levels in traumatic injury", aliases=aliases)


def test_source_gate_aliases_drop_broad_one_token_aliases_for_composite_topics() -> None:
    aliases = source_gate_aliases(
        "digital_frailty_index",
        ("digital frailty index", "digital biomarkers", "frailty prediction", "wearable frailty"),
    )

    assert aliases == ("digital frailty index",)


def test_longevity_topic_rejects_generic_entity_disease_source() -> None:
    assert not is_source_topic_specific(
        "microbiome_longevity",
        "Microbiome and response to therapy in triple negative breast cancer: a systematic review",
        aliases=source_gate_aliases("microbiome_longevity", ("microbiome longevity", "microbiome")),
    )


def test_longevity_topic_accepts_entity_with_longevity_scope() -> None:
    assert is_source_topic_specific(
        "microbiome_longevity",
        "Gut microbiome signatures of longevity and healthy aging in older adults",
        aliases=source_gate_aliases("microbiome_longevity", ("microbiome longevity", "microbiome")),
    )


def test_scope_only_topic_requires_its_full_scope_not_generic_longevity() -> None:
    assert not is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Longevity of dental restorations in clinical practice",
    )
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Lifespan and longevity among older adult subgroups",
    )
    assert not is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Lifespan and longevity of dental restorations",
    )
    assert not is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Lifespan and longevity of dental restorations in human patients",
    )
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Exceptional longevity in centenarian subgroups",
    )
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "C. elegans lifespan varies across genetic subgroups",
    )
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Longevity among older adults",
    )
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Saccharomyces cerevisiae lifespan",
    )
    assert not is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Dental implant longevity among older adults",
    )
    for title in (
        "Machine learning model lifespan",
        "Battery cell lifespan in human patients",
        "Computer mouse lifespan under heavy use",
        "Human battery lifespan under rapid charging",
        "Router lifespan study",
        "Software lifespan study",
        "Turbine lifespan study",
        "Concrete lifespan study",
        "Router lifespan under dietary restriction",
        "Software longevity in aging populations",
        "Turbine lifespan after protein treatment",
        "Concrete lifespan under metabolic stress",
        "Engine lifespan in a mortality model",
        "Router lifespan compared with Saccharomyces cerevisiae",
        "Lifespan of routers among Saccharomyces cerevisiae samples",
        "Human evaluation of router lifespan under load",
        "An analysis of router lifespan compared with Saccharomyces cerevisiae",
        "Human software lifespan",
        "Biological model router lifespan",
        "Digital accessory lifespan in mice",
        "Library lifespan in mice",
        "Directory lifespan in mice",
        "Factory lifespan in mice",
        "Lifespan study of wearable sensors in mice",
        "Lifespan analysis of laboratory equipment in mice",
    ):
        assert not is_source_topic_specific("longevity_lifespan_subgroups", title)
    for title in (
        "Zebrafish lifespan under dietary restriction",
        "Killifish lifespan after intervention",
        "Coral lifespan under thermal stress",
        "Bacteria longevity under nutrient restriction",
        "Octopuses lifespan across environments",
        "Fruit fly lifespan under dietary restriction",
        "Neural network control of C. elegans lifespan",
        "Macaque lifespan across populations",
        "Rabbit lifespan under dietary restriction",
        "Hamster longevity after protein restriction",
        "Guppy lifespan across reproductive conditions",
        "Study reports lifespan in mice",
        "Trial measures lifespan in mice",
        "A lifespan study in mice",
        "Longitudinal lifespan analysis in mice",
        "Comparative lifespan study in Drosophila",
        "Lifespan study of mice",
    ):
        assert is_source_topic_specific("longevity_lifespan_subgroups", title)

    assert not is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "Lifespan mortality forecasting models for insurance portfolios",
    )
    assert not is_source_topic_specific("longevity_lifespan_subgroups", "Contract lifespan")
    assert not is_source_topic_specific("longevity_lifespan_subgroups", "Brand longevity")
    assert is_source_topic_specific(
        "longevity_lifespan_subgroups",
        "A lifespan study of yeast evaluates longevity.",
    )


def test_generated_scope_only_pack_is_not_structurally_specific() -> None:
    assert not generated_pack_publishable({
        "candidate_count": 20,
        "pack_data": {
            "topic": "longevity_lifespan_subgroups",
            "aliases": ["longevity lifespan", "longevity", "lifespan"],
            "retrieval": {"topic_terms": ["longevity", "lifespan"]},
        },
    })
    assert not generated_pack_publishable({
        "candidate_count": 20,
        "pack_data": {
            "topic": "generic_aging",
            "aliases": ["anti-aging", "healthy aging"],
            "retrieval": {"topic_terms": ["anti-aging", "healthy aging"]},
        },
    })
    assert not generated_pack_publishable({
        "candidate_count": 20,
        "pack_data": {
            "topic": "healthy_aging",
            "aliases": ["Healthy Aging"],
            "retrieval": {"topic_terms": ["Healthy Aging"]},
        },
    })
    assert not generated_pack_publishable({
        "candidate_count": 20,
        "pack_data": {
            "topic": "anti_aging",
            "aliases": ["anti-aging"],
            "retrieval": {"topic_terms": ["anti-aging"]},
        },
    })
    assert not generated_pack_publishable({
        "candidate_count": 30,
        "pack_data": {
            "topic": "normal_aging",
            "aliases": ["normal aging", "typical aging"],
            "retrieval": {"topic_terms": ["normal aging", "typical aging"]},
        },
    }, peer_records=[
        {"candidate_count": 20, "pack_data": {"topic": "healthy_aging", "aliases": ["healthy aging"]}},
        {"candidate_count": 20, "pack_data": {"topic": "exceptional_longevity", "aliases": ["exceptional longevity"]}},
    ])
    assert not generated_pack_publishable({
        "candidate_count": 30,
        "pack_data": {
            "topic": "normal_aging",
            "aliases": ["normal", "typical", "aging"],
            "retrieval": {"topic_terms": ["normal", "typical", "aging"]},
        },
    }, peer_records=[
        {"candidate_count": 20, "pack_data": {"topic": "healthy_aging", "aliases": ["healthy aging"]}},
        {"candidate_count": 20, "pack_data": {"topic": "exceptional_longevity", "aliases": ["exceptional longevity"]}},
    ])
    assert generated_pack_publishable({
        "candidate_count": 30,
        "pack_data": {"topic": "metformin_aging", "aliases": ["metformin aging"]},
    }, peer_records=[
        {"candidate_count": 20, "pack_data": {"topic": "healthy_aging", "aliases": ["healthy aging"]}},
        {"candidate_count": 20, "pack_data": {"topic": "exceptional_longevity", "aliases": ["exceptional longevity"]}},
    ])


def test_composite_topic_rejects_broad_alias_only_source() -> None:
    aliases = source_gate_aliases(
        "digital_frailty_index",
        ("digital frailty index", "digital biomarkers", "frailty prediction"),
    )

    assert not is_source_topic_specific(
        "digital_frailty_index",
        "Digital biomarkers for Alzheimer speech analysis in older adults",
        aliases=aliases,
    )
    assert is_source_topic_specific(
        "digital_frailty_index",
        "Validation of a digital frailty index using wearable sensors",
        aliases=aliases,
    )


def test_age_clock_topics_accept_scientific_morphology_variants() -> None:
    aliases = source_gate_aliases(
        "metabolomic_age_clocks",
        ("metabolomic age clocks", "metabolomic aging signature"),
    )

    assert is_source_topic_specific(
        "metabolomic_age_clocks",
        "Estimation of biological aging clocks based on NMR metabolomics",
        aliases=aliases,
    )


def test_age_clock_topics_reject_broad_omics_without_age_clock_context() -> None:
    aliases = source_gate_aliases(
        "metabolomic_age_clocks",
        ("metabolomic age clocks", "metabolomic aging signature"),
    )

    assert not is_source_topic_specific(
        "metabolomic_age_clocks",
        "Untargeted metabolomics biomarkers of frailty in adults",
        aliases=aliases,
    )


def test_age_clock_source_gate_drops_broad_platform_aliases() -> None:
    aliases = source_gate_aliases(
        "plasma_proteomic_age_clocks",
        (
            "plasma proteomic age clocks",
            "plasma proteomics",
            "proteomic aging clock",
            "blood protein age",
        ),
    )

    assert "plasma proteomics" not in aliases
    assert "proteomic aging clock" in aliases
    assert not is_source_topic_specific(
        "plasma_proteomic_age_clocks",
        "Plasma Proteomics Identifies Potential Pancreatic Cancer Risk Indicators in Type 2 Diabetes",
        aliases=aliases,
    )
    assert is_source_topic_specific(
        "plasma_proteomic_age_clocks",
        "A plasma proteomic age clock for multimorbidity risk in older adults",
        aliases=aliases,
    )


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


def test_generated_suffix_terms_are_not_required_for_entity_specificity() -> None:
    assert is_source_topic_specific(
        "aspirin_use_effects",
        "Randomized trial of aspirin for cardiovascular prevention outcomes",
        aliases=source_gate_aliases("aspirin_use_effects", ("aspirin use effects",)),
    )
    assert is_source_topic_specific(
        "statin_therapy_rates",
        "Statin therapy was associated with vascular event rates in adults",
        aliases=source_gate_aliases("statin_therapy_rates", ("statin therapy rates",)),
    )
    assert not is_source_topic_specific(
        "low_dose_naltrexone_inflammation",
        "Exercise intervention reduced inflammatory markers in older adults",
        aliases=source_gate_aliases(
            "low_dose_naltrexone_inflammation",
            ("low dose naltrexone inflammation", "low-dose naltrexone"),
        ),
    )


def test_biomedical_axis_does_not_hide_named_intervention() -> None:
    topic = "liraglutide_cardiovascular_subgroups"
    aliases = source_gate_aliases(topic, ("liraglutide cardiovascular subgroups",))

    assert is_source_topic_specific(
        topic,
        "Effects of liraglutide on diastolic function in coronary artery disease",
        aliases=aliases,
    )
    assert not is_source_topic_specific(
        topic,
        "Cardiovascular outcomes in adults with type 2 diabetes",
        aliases=aliases,
    )


def test_compound_generated_topic_accepts_redundant_acronym_phrase() -> None:
    assert is_source_topic_specific(
        "immune_checkpoint_inhibitors_icis_rates",
        "Patients treated with immune checkpoint inhibitors for advanced cancer",
        aliases=source_gate_aliases("immune_checkpoint_inhibitors_icis_rates", ("immune checkpoint inhibitors icis rates",)),
    )


def test_compound_generated_topic_accepts_expanded_acronym() -> None:
    assert is_source_topic_specific(
        "hpv_vaccination_rates",
        "Human papillomavirus vaccination uptake in adolescent cohorts",
        aliases=source_gate_aliases("hpv_vaccination_rates", ("hpv vaccination rates",)),
    )


def test_post_acronym_axis_does_not_zero_entity_source() -> None:
    assert is_source_topic_specific(
        "nicotinamide_riboside_nr_nad_effects",
        "Randomized trial of nicotinamide riboside supplementation in older adults",
        aliases=source_gate_aliases("nicotinamide_riboside_nr_nad_effects", ("nicotinamide riboside nr nad effects",)),
    )


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


def test_generated_pack_publishable_allows_high_support_single_rare_topic() -> None:
    records = [
        {"candidate_count": 65, "pack_data": {"topic": "metformin_effects", "aliases": ["metformin effects", "metformin"]}},
        {"candidate_count": 30, "pack_data": {"topic": "metabolism_effects", "aliases": ["metabolism effects", "metabolism"]}},
        {"candidate_count": 20, "pack_data": {"topic": "metabolism_rates", "aliases": ["metabolism rates", "metabolism"]}},
        {"candidate_count": 20, "pack_data": {"topic": "metabolism_biomarkers", "aliases": ["metabolism biomarkers", "metabolism"]}},
        {"candidate_count": 20, "pack_data": {"topic": "metabolism_thresholds", "aliases": ["metabolism thresholds", "metabolism"]}},
    ]

    assert generated_pack_publishable(records[0], peer_records=records)
    assert not generated_pack_publishable(records[1], peer_records=records)


def test_generated_pack_publishable_rejects_fragments_and_placeholders() -> None:
    for topic in (
        "senescence_the_expression_effects",
        "metformin_metformin_and_effects",
        "resveratrol_and_respectively_effects",
        "longevity_intervention_n_a_rates",
        "telomere_telomere_length_effects",
        "of_metformin_effects",
        "blood_pressure_in",
    ):
        assert not generated_pack_publishable({
            "candidate_count": 50,
            "pack_data": {"topic": topic, "aliases": [topic.replace("_", " ")]},
        })


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


def test_generated_pack_plural_scope_terms_are_not_specificity() -> None:
    broad = {
        "candidate_count": 21,
        "pack_data": {
            "topic": "cancer_mortality_rates",
            "aliases": ["cancer mortality rates", "cancer", "mortality"],
            "retrieval": {
                "topic_terms": ["cancer mortality rates", "cancer", "mortality"],
                "scope_terms": ["mortality", "biomarkers", "frailty", "rates"],
            },
        },
    }
    specific = {
        "candidate_count": 24,
        "pack_data": {
            "topic": "telomere_cancer_rates",
            "aliases": ["telomere cancer rates", "telomere", "cancer"],
            "retrieval": {
                "topic_terms": ["telomere cancer rates", "telomere", "cancer"],
                "scope_terms": ["mortality", "biomarkers", "frailty", "rates"],
            },
        },
    }
    peers = [
        broad,
        specific,
        {"candidate_count": 4, "pack_data": {"topic": "cancer_rates", "aliases": ["cancer rates", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "cancer_subgroups", "aliases": ["cancer subgroups", "cancer"]}},
        {"candidate_count": 4, "pack_data": {"topic": "fasting_mortality", "aliases": ["fasting mortality", "fasting", "mortality"]}},
    ]

    assert not generated_pack_publishable(broad, peer_records=peers)
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


def test_axis_token_optional_when_subject_matches() -> None:
    """Sources rarely echo the analytical angle in a topic slug verbatim.

    liraglutide_adverse_effects requires "adverse", but real trials say
    "safety". Demanding it rejected 1,943 of 1,944 candidate sources, including
    all 920 primary-tier ones, so no topic could reach the 3-primary floor.
    """
    assert is_source_topic_specific(
        "liraglutide_adverse_effects",
        "Efficacy and safety of liraglutide in type 2 diabetes",
    )
    assert is_source_topic_specific(
        "liraglutide_adverse_effects",
        "Liraglutide and renal outcomes: a randomized trial",
    )
    assert is_source_topic_specific(
        "metformin_measurement_methods",
        "Serum metformin concentrations in older adults",
    )


def test_axis_token_never_admits_a_different_subject() -> None:
    """The subject stays mandatory, so cross-subject leakage stays blocked."""
    assert not is_source_topic_specific(
        "liraglutide_adverse_effects", "Metformin and cardiovascular outcomes",
    )
    assert not is_source_topic_specific(
        "liraglutide_adverse_effects",
        "Adverse events of chemotherapy in breast cancer",
    )
