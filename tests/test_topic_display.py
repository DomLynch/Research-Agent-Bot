from __future__ import annotations

from agent.topic_display import humanize_topic


def test_humanize_topic_preserves_biomedical_acronyms() -> None:
    assert humanize_topic("nad_biomarker_effects") == "NAD+ biomarker effects"
    assert humanize_topic("glp1_weight_effects") == "GLP-1 weight effects"
    assert humanize_topic("hrv_autonomic_aging", title_case=True) == "HRV Autonomic Aging"
