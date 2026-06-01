from source_topic_specificity import generated_pack_publishable, is_source_topic_specific  # type: ignore[import-not-found]


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
