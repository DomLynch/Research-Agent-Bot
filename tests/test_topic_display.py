from __future__ import annotations

from agent.topic_display import humanize_topic, intervention_label


def test_humanize_topic_preserves_biomedical_acronyms() -> None:
    assert humanize_topic("nad_biomarker_effects") == "NAD+ biomarker effects"
    assert humanize_topic("glp1_weight_effects") == "GLP-1 weight effects"
    assert humanize_topic("hrv_autonomic_aging", title_case=True) == "HRV Autonomic Aging"


def test_intervention_label_is_the_entity_not_the_topic_phrase() -> None:
    """#7: the intervention entity is a single compact noun ('resveratrol'),
    NOT the multi-token humanized phrase ('Resveratrol Metabolism Effects')
    nor the underscore slug — so prose names the compound, not the topic."""
    assert intervention_label("resveratrol_metabolism_effects") == "resveratrol"
    assert intervention_label("metformin_longevity") == "metformin"
    # acronym display normalization still applies to the head token
    assert intervention_label("nad_biomarker_effects") == "NAD+"
    # entity is single-token: no underscore, no whitespace
    for slug in ("resveratrol_metabolism_effects", "metformin_longevity"):
        entity = intervention_label(slug)
        assert "_" not in entity and " " not in entity
    assert intervention_label("") == "the intervention"
