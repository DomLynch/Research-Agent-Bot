"""Unit tests for agent/results_table.py — deterministic per-CLAIM
Quantitative Evidence Index (universal Q9 structural fix, Shot 2).

Pure-function tests; no LLM calls, no network IO.
"""
from __future__ import annotations


import json

import pytest

from agent.results_table import (
    EvidenceRow,
    _arm_belongs_to_topic,
    _claim_to_row,
    _confidence_admissible,
    _load_topic_arm_terms,
    _quality_score,
    _short_citation,
    _truncate,
    build_results_table,
    build_results_table_with_diagnostic,
    format_empty_qei_placeholder,
)


def test_equal_statistics_from_different_studies_are_not_duplicate_evidence() -> None:
    from agent.results_table import _select_result_rows
    rows = [EvidenceRow(study, "blood pressure", "treatment", "P < 0.05", "p_value", "P < 0.05", study,
                        "Treatment reduced blood pressure (P < 0.05).", "P < 0.05")
            for study in ("Trial 2020", "Trial 2021")]
    candidates = [(1, "p_value", row, row.source_value) for row in [*rows, rows[0]]]
    assert _select_result_rows(candidates, 40) == rows


# ---------- confidence filter ---------------------------------------

def test_high_confidence_always_admitted():
    assert _confidence_admissible({"binding_confidence": "high",
                                   "claim_type": "p_value"})
    assert _confidence_admissible({"binding_confidence": "high",
                                   "claim_type": "hazard_ratio"})


def test_partial_admitted_for_all_numeric_types():
    """Universal-fix wave 2 (2026-05-04): partial-confidence claims
    admitted regardless of claim type — the value IS in the corpus
    even when the (endpoint, arm, direction) binding is uncertain.
    Aligns table admissibility with audit's _load_corpus_numerics
    so the table can't emit untraceable numerics."""
    for ct in ("sample_size", "hazard_ratio", "p_value", "percentage",
               "confidence_interval", "odds_ratio", "unit_value"):
        assert _confidence_admissible(
            {"binding_confidence": "partial", "claim_type": ct}
        ), f"partial-confidence {ct} should be admitted"


def test_unbound_or_none_rejected():
    assert not _confidence_admissible({"binding_confidence": "none"})
    assert not _confidence_admissible({"binding_confidence": ""})
    assert not _confidence_admissible({})


# ---------- source statistic preservation --------------------------

def test_source_statistics_are_not_rounded_or_reinterpreted():
    for raw, value in (("P < 0.000", 0), ("P > .99", .99), ("p=.044", .044)):
        row = _claim_to_row(
            {"claim_type": "p_value", "endpoint": "glucose", "raw_text": raw,
             "numeric_values": [value], "sentence": f"Glucose differed ({raw})."},
            paper_id="Source 2026",
        )
        assert row is not None
        assert row.source_value == raw


@pytest.mark.parametrize("raw,sentence,keep", [
    ("1.01 kg", "Body weight decreased by -0.95 ± 1.01 kg.", False),
    ("13.6 mg/dL", "Fasting glucose decreased by -7.97±13.6 mg/dL.", False),
    ("7.6%", "Mean body fat was 32.3 ± 7.6%.", False),
    ("P > .05", "The groups were similar at baseline (P > .05).", False),
    ("P > .05", "Change from baseline did not differ between groups (P > .05).", True),
    ("P = .45", "Baseline-adjusted body weight was similar between groups (P = .45).", True),
    ("P > .05", "Baseline weight predicted the outcome without significance (P > .05).", True),
    ("1.01 kg", "After adjustment for baseline BMI, weight decreased by 1.01 kg.", True),
    ("1.01 kg", "Body weight decreased by 1.01 kg.", True),
])
def test_qei_does_not_present_dispersion_or_baseline_balance_as_effect(raw, sentence, keep):
    row = _claim_to_row({
        "claim_type": "p_value" if raw.startswith("P") else "unit_value",
        "endpoint": "body weight", "raw_text": raw, "numeric_values": [1.01],
        "sentence": sentence,
    }, paper_id="Source 2026")
    assert (row is not None) is keep


def test_qei_renders_each_source_result_sentence_once(tmp_path):
    sentence = "Glucose decreased by 2 mg/dL and insulin by 3 mg/dL."
    (tmp_path / "study.quant_claims.json").write_text(json.dumps({
        "paper_id": "study", "claims": [
            {"claim_type": "unit_value", "endpoint": endpoint, "raw_text": f"{value} mg/dL",
             "numeric_values": [value], "sentence": sentence, "binding_confidence": "high"}
            for endpoint, value in (("glucose", 2), ("insulin", 3))
        ],
    }))
    text, diagnostic = build_results_table_with_diagnostic(tmp_path, topic="x")
    assert diagnostic["n_rendered"] == 1
    assert text.count(sentence) == 1


# ---------- citation extraction ------------------------------------

def test_short_citation_extracts_year_from_paper_id():
    assert "2025" in _short_citation("PMC12345_aspirin_study_2025_in_aspree")


def test_short_citation_falls_back_when_no_year():
    out = _short_citation("PMC12345_unfinished_study_no_date")
    # Just make sure it doesn't crash and returns something
    assert isinstance(out, str)
    assert len(out) > 0


# ---------- claim → row --------------------------------------------

def test_claim_to_row_skips_no_numeric():
    """Claim with empty numeric_values returns None."""
    assert _claim_to_row({"raw_text": "no number"}, paper_id="x") is None


def test_claim_to_row_drops_background_and_protocol_numerics():
    for role in ("background", "protocol", "population_descriptor"):
        assert _claim_to_row(
            {
                "claim_type": "percentage",
                "raw_text": "70%",
                "numeric_values": [70],
                "endpoint": "mortality",
                "claim_role": role,
            },
            paper_id="x",
        ) is None


def test_claim_to_row_drops_ci_prefix_percentage():
    assert _claim_to_row(
        {
            "claim_type": "percentage",
            "raw_text": "95%",
            "numeric_values": [95],
            "endpoint": "HbA1c",
            "claim_role": "effect",
            "sentence": "The estimate was 95% CI = 0.06-0.93.",
        },
        paper_id="x",
    ) is None


def test_claim_to_row_drops_i2_heterogeneity_percentages():
    assert _claim_to_row(
        {
            "claim_type": "percentage",
            "raw_text": "65.6%",
            "numeric_values": [65.6],
            "units": "%",
            "binding_confidence": "high",
            "endpoint": "body weight",
            "arm": "placebo",
            "claim_role": "effect",
            "sentence": "The I2 was 65.6%, indicating heterogeneity.",
        },
        paper_id="x",
    ) is None


def test_claim_to_row_drops_nondose_endpoint_dose_thresholds():
    assert _claim_to_row(
        {
            "claim_type": "unit_value",
            "raw_text": "45 kg",
            "numeric_values": [45],
            "units": "kg",
            "binding_confidence": "partial",
            "endpoint": "body weight",
            "claim_role": "dose",
            "sentence": "Children below 45 kg received a lower dose.",
        },
        paper_id="x",
    ) is None


def test_claim_to_row_renders_confidence_interval_once():
    row = _claim_to_row(
        {
            "claim_type": "confidence_interval",
            "raw_text": "95% CI -28.97 to 19.71",
            "numeric_values": [-28.97, 19.71],
            "units": "95%CI",
            "endpoint": "muscle strength",
            "claim_role": "effect",
        },
        paper_id="x",
    )
    assert row is not None
    assert row.value == "95% CI -28.97 to 19.71"
    assert row.unit_or_type == "95%CI"
    assert row.source_value == "95% CI -28.97 to 19.71"
    assert row.statistic == "—"


def test_claim_to_row_drops_ambiguous_multi_endpoint_p_value():
    row = _claim_to_row(
        {
            "claim_type": "p_value",
            "raw_text": "p < 0.001",
            "numeric_values": [0.001],
            "endpoint": "HbA1c",
            "claim_role": "effect",
            "sentence": (
                "Mean corpuscular volume was lower (p < 0.001), "
                "whereas LDL cholesterol (p = 0.036) and HbA1c "
                "(p = 0.030) were elevated."
            ),
        },
        paper_id="x",
    )
    assert row is None


def test_claim_to_row_keeps_locally_bound_multi_endpoint_p_value():
    row = _claim_to_row(
        {
            "claim_type": "p_value",
            "raw_text": "p = 0.030",
            "numeric_values": [0.03],
            "endpoint": "HbA1c",
            "claim_role": "effect",
            "sentence": (
                "Mean corpuscular volume was lower (p < 0.001), "
                "whereas LDL cholesterol (p = 0.036) and HbA1c "
                "(p = 0.030) were elevated."
            ),
        },
        paper_id="x",
    )
    assert row is not None
    assert row.endpoint == "HbA1c"


def test_claim_to_row_collapses_newlines_inside_table_cells():
    row = _claim_to_row(
        {
            "claim_type": "mean_sd",
            "raw_text": "15.4\n±1.2",
            "numeric_values": [15.4, 1.2],
            "endpoint": "insulin sensitivity",
            "claim_role": "effect",
            "binding_confidence": "high",
        },
        paper_id="x",
        citation_token="Kim 2020",
    )
    assert row is not None
    assert row.value == "15.4 ±1.2"


def test_claim_to_row_drops_dose_unit_bound_to_outcome_endpoint():
    row = _claim_to_row(
        {
            "claim_type": "unit_value",
            "raw_text": "5 mg",
            "numeric_values": [5],
            "units": "mg",
            "endpoint": "HbA1c",
            "claim_role": "effect",
        },
        paper_id="x",
    )
    assert row is None


def test_claim_to_row_drops_sample_size_bound_to_outcome_endpoint():
    row = _claim_to_row(
        {
            "claim_type": "sample_size",
            "raw_text": "n = 30",
            "numeric_values": [30],
            "endpoint": "body mass index",
            "claim_role": "effect",
            "binding_confidence": "high",
        },
        paper_id="x",
    )
    assert row is None


def test_claim_to_row_keeps_sample_size_endpoint():
    row = _claim_to_row(
        {
            "claim_type": "sample_size",
            "raw_text": "n = 30",
            "numeric_values": [30],
            "endpoint": "sample size",
            "claim_role": "population",
            "binding_confidence": "high",
        },
        paper_id="x",
    )
    assert row is not None
    assert row.value == "n = 30"


def test_claim_to_row_drops_partial_ratio_without_direction():
    row = _claim_to_row(
        {
            "claim_type": "hazard_ratio",
            "raw_text": "HR=2.45",
            "numeric_values": [2.45],
            "endpoint": "incident cv event",
            "arm": "statin",
            "claim_role": "dose",
            "binding_confidence": "partial",
            "direction": "",
        },
        paper_id="x",
    )
    assert row is None


def test_claim_to_row_keeps_high_confidence_ratio_without_direction():
    row = _claim_to_row(
        {
            "claim_type": "hazard_ratio",
            "raw_text": "HR=0.72",
            "numeric_values": [0.72],
            "endpoint": "mortality",
            "arm": "statin",
            "claim_role": "effect",
            "binding_confidence": "high",
            "direction": "",
        },
        paper_id="x",
    )
    assert row is not None
    assert row.value == "HR=0.72"


def test_claim_to_row_drops_ratio_bound_to_bmi_endpoint():
    row = _claim_to_row(
        {
            "claim_type": "hazard_ratio",
            "raw_text": "HR = 2.54",
            "numeric_values": [2.54],
            "endpoint": "body mass index",
            "arm": "ret",
            "claim_role": "effect",
            "binding_confidence": "high",
            "direction": "positive",
        },
        paper_id="x",
    )
    assert row is None


def test_claim_to_row_assembles_full_row():
    claim = {
        "claim_type": "sample_size",
        "raw_text": "n=19,114",
        "numeric_values": [19114],
        "binding_confidence": "high",
        "endpoint": "sample size",
        "arm": "aspirin",
        "claim_role": "population",
    }
    row = _claim_to_row(claim, paper_id="PMC12345_aspirin_2025_paper")
    assert row is not None
    assert "2025" in row.study_label
    assert "sample size" in row.endpoint
    assert row.arm == "aspirin"


def test_truncate_replaces_pipe_chars():
    """| would break the markdown table — must be sanitized."""
    assert "|" not in _truncate("a|b|c", 20)


def test_truncate_caps_long_strings():
    assert _truncate("x" * 100, 10) == "xxxxxxxxx…"


def test_truncate_prefers_word_boundary():
    assert _truncate("resistance training protocol", 16) == "resistance…"


def test_claim_to_row_keeps_resistance_training_arm_untruncated():
    row = _claim_to_row(
        {
            "claim_type": "p_value",
            "raw_text": "p = 0.04",
            "numeric_values": [0.04],
            "endpoint": "muscle strength",
            "arm": "resistance training",
            "claim_role": "effect",
            "binding_confidence": "high",
        },
        paper_id="x",
    )
    assert row is not None
    assert row.arm == "resistance training"


# ---------- quality score ------------------------------------------

def test_quality_score_prefers_effect_estimates():
    """HR/OR > sample_size > p_value > percentage."""
    hr = _quality_score({"claim_type": "hazard_ratio"})
    n = _quality_score({"claim_type": "sample_size"})
    p = _quality_score({"claim_type": "p_value"})
    pct = _quality_score({"claim_type": "percentage"})
    assert hr > n > p > pct


def test_quality_score_rewards_bound_endpoint_and_arm():
    bound = _quality_score({
        "claim_type": "p_value",
        "endpoint": "mortality",
        "arm": "aspirin",
    })
    unbound = _quality_score({"claim_type": "p_value"})
    assert bound > unbound


# ---------- end-to-end on synthetic corpus -------------------------

def test_build_results_table_renders_rows(tmp_path):
    """Realistic round-trip: write a synthetic quant_claims.json,
    invoke build_results_table, assert markdown output shape."""
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    payload = {
        "paper_id": "PMC1_aspree_2018_landmark",
        "claims": [
            {
                "claim_type": "sample_size",
                "raw_text": "n=19,114",
                "numeric_values": [19114],
                "binding_confidence": "high",
                "endpoint": "disability-free survival",
                "arm": "aspirin",
            },
            {
                "claim_type": "hazard_ratio",
                "raw_text": "HR 1.01",
                "sentence": "The mortality comparison yielded HR 1.01.",
                "numeric_values": [1.01],
                "binding_confidence": "high",
                "endpoint": "mortality",
                "arm": "aspirin",
            },
            {
                "claim_type": "p_value",
                "raw_text": "p=0.32",
                "sentence": "Mortality did not differ (p=0.32).",
                "numeric_values": [0.32],
                "binding_confidence": "high",
                "endpoint": "mortality",
                "arm": "aspirin",
            },
        ],
    }
    (claims_dir / "PMC1_aspree.quant_claims.json").write_text(
        json.dumps(payload),
    )
    md = build_results_table(claims_dir, topic="aspirin")
    assert "Quantitative Evidence Index — aspirin" in md
    assert "Quantitative Evidence Index: source excerpts" in md
    assert "| Study | Source context | Raw statistic |" in md
    # Endpoint-bound sample-size rows are quarantined from public QEI;
    # ratio and p-value rows still render.
    assert "19,114" not in md and "n=19,114" not in md
    assert "HR" in md or "1.01" in md


def test_build_results_table_empty_when_no_claims(tmp_path):
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    assert build_results_table(claims_dir, topic="x") == ""


def test_build_results_table_handles_missing_dir(tmp_path):
    """Non-existent quant_claims dir → empty string, no crash."""
    assert build_results_table(tmp_path / "nope", topic="x") == ""


def test_build_results_table_caps_rows():
    """Verify max_rows enforces."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        d = Path(td)
        # 50 fake claims in one paper — should cap to per-paper limit
        # AND overall limit
        payload = {
            "paper_id": "PMC1_test_2020",
            "claims": [
                {"claim_type": "p_value", "raw_text": f"p={i}",
                 "numeric_values": [0.01 * i],
                 "binding_confidence": "high",
                 "endpoint": f"endpoint_{i % 3}"}  # only 3 unique endpoints
                for i in range(1, 51)
            ],
        }
        (d / "PMC1.quant_claims.json").write_text(json.dumps(payload))
        md = build_results_table(d, topic="test", max_rows=5)
        n_data_rows = md.count("\n| PMC")
        assert n_data_rows <= 5


# ---------- cross-topic arm filter (P1 reviewer fix) ---------------

def test_topic_arm_terms_loads_from_pack():
    """Verify the topic-arm filter pulls active+placebo synonyms from
    the topic pack TOML."""
    rapa = _load_topic_arm_terms("rapamycin")
    metf = _load_topic_arm_terms("metformin")
    asp = _load_topic_arm_terms("aspirin")
    # Each pack contains its drug name as an active-arm synonym
    assert "rapamycin" in rapa
    assert "metformin" in metf
    assert "aspirin" in asp
    # Generic comparator terms are always present (cross-topic safe)
    for terms in (rapa, metf, asp):
        assert "placebo" in terms
        assert "control" in terms


def test_topic_arm_terms_missing_pack_returns_empty():
    """No topic pack → empty set → filter is a no-op (back-compat)."""
    assert _load_topic_arm_terms("nonexistent_topic_xyz") == frozenset()


def test_arm_belongs_drops_cross_topic_leak():
    """The reviewer-flagged P1: a rapamycin paper's metformin-arm row.
    With the rapamycin topic-arm set loaded, an arm='metformin' claim
    must be DROPPED to prevent leaking metformin numerics into a
    rapamycin paper's Quantitative Evidence Index."""
    rapa_terms = _load_topic_arm_terms("rapamycin")
    cross_topic = {"arm": "metformin"}
    on_topic = {"arm": "rapamycin"}
    placebo = {"arm": "placebo"}
    empty = {"arm": ""}
    assert not _arm_belongs_to_topic(cross_topic, rapa_terms)
    assert _arm_belongs_to_topic(on_topic, rapa_terms)
    assert _arm_belongs_to_topic(placebo, rapa_terms)
    # Empty-arm claims kept conservatively (no cross-topic signal)
    assert _arm_belongs_to_topic(empty, rapa_terms)


def test_arm_belongs_substring_match_handles_modifiers():
    """'low-dose aspirin' ↔ 'aspirin' should match either direction —
    so a paper saying 'low-dose aspirin treatment group' isn't dropped
    just because the synonym list has the bare 'aspirin'."""
    asp_terms = _load_topic_arm_terms("aspirin")
    assert _arm_belongs_to_topic({"arm": "low-dose aspirin"}, asp_terms)
    assert _arm_belongs_to_topic({"arm": "aspirin treatment"}, asp_terms)


def test_arm_belongs_no_filter_when_pack_missing():
    """Empty topic_arm_terms (e.g. unconfigured topic) → all claims
    pass through. Back-compat for topics without a pack."""
    assert _arm_belongs_to_topic({"arm": "anything"}, frozenset())


def test_evidence_row_immutable():
    """Frozen dataclass — assignment raises FrozenInstanceError."""
    from dataclasses import FrozenInstanceError
    import pytest
    r = EvidenceRow(
        study_label="X 2024", endpoint="ep", arm="—", value="1",
        unit_or_type="t", statistic="—", citation="X 2024",
    )
    with pytest.raises(FrozenInstanceError):
        r.value = "999"  # type: ignore[misc]


# ---------- Slice-1 closeout: empty-QEI diagnostic ----------------

def test_diagnostic_counts_for_normal_corpus(tmp_path):
    """Counter math on a populated corpus: every claim that survives
    each gate should bump exactly one counter."""
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    payload = {
        "paper_id": "PMC1_demo_2024",
        "claims": [
            # 1 high-conf, on-topic, meaningful → renders
            {"claim_type": "p_value", "raw_text": "p=0.04",
             "numeric_values": [0.04], "binding_confidence": "high",
             "sentence": "The comparison yielded p=0.04.",
             "endpoint": "mortality", "arm": "metformin"},
            # 1 high-conf, off-topic arm (drops at arm filter)
            {"claim_type": "p_value", "raw_text": "p=0.05",
             "numeric_values": [0.05], "binding_confidence": "high",
             "endpoint": "mortality", "arm": "rapamycin"},
            # 1 below confidence (drops before arm)
            {"claim_type": "p_value", "raw_text": "p=0.06",
             "numeric_values": [0.06], "binding_confidence": "none",
             "endpoint": "mortality", "arm": "metformin"},
        ],
    }
    (claims_dir / "PMC1.quant_claims.json").write_text(
        json.dumps(payload),
    )
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="metformin",
    )
    assert diag["n_quant_files"] == 1
    assert diag["n_total_claims"] == 3
    assert diag["n_admissible"] == 2  # high+high (none dropped)
    assert diag["n_topic_matched"] == 1  # metformin only
    assert diag["drop_off_topic_arm"] == 1  # rapamycin dropped
    assert diag["n_meaningful"] >= 1
    assert diag["n_rendered"] == diag["n_after_quotas"]
    assert "metformin" in md.lower()


def test_surface_gate_drops_unpublishable_qei_rows(tmp_path):
    """Traceable but semantically unsafe rows should not render in
    the public QEI table."""
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    payload = {
        "paper_id": "PMC1_cheung_2024_intermittent",
        "claims": [
            {"claim_type": "unit_value", "raw_text": "2.86 mg/dL",
             "numeric_values": [2.86], "units": "mg/dL",
             "binding_confidence": "high", "endpoint": "mortality",
             "arm": "pooled"},
            {"claim_type": "unit_value", "raw_text": "89 mg/dL",
             "numeric_values": [89], "units": "mg/dL",
             "sentence": "Fasting glucose was 89 mg/dL.",
             "binding_confidence": "high", "endpoint": "fasting glucose",
             "arm": "pooled"},
        ],
    }
    (claims_dir / "PMC1.quant_claims.json").write_text(json.dumps(payload))
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="intermittent_fasting",
    )
    assert "2.86 mg/dL" not in md
    assert "89 mg/dL" in md
    assert diag["drop_surface_gate"] == 1


def test_frozen_gubensek_mortality_value_is_not_exported_as_a_trial_outcome(tmp_path):
    # Frozen public excerpt and erroneous QEI value from the 2026-09-07 audit.
    sentence = "Hospital length of stay was also comparable in both groups and survival was 100%."
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    claims = [{
        "claim_type": "percentage", "raw_text": raw, "numeric_values": [value],
        "sentence": sentence, "binding_confidence": "high", "endpoint": "mortality", "arm": "pooled",
    } for raw, value in (("48%", 48), ("100%", 100))]
    (claims_dir / "gubensek.quant_claims.json").write_text(json.dumps({
        "paper_id": "gubensek", "claims": claims,
    }))
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="plasma_exchange_adverse_rates",
        citation_tokens_by_paper_id={"gubensek": "Gubensek 2022"},
    )
    assert diag["drop_surface_gate"] == 1
    assert diag["n_rendered"] == 1
    assert "| Gubensek 2022 | mortality |" not in md
    assert "48%" not in md
    assert f"| Gubensek 2022 | {sentence} | 100% |" in md


@pytest.mark.parametrize("case", [
    "range_dash", "whitespace", "contradicted", "leading_negation",
    "trailing_qualification", "missing", "wrong_paper", "metadata_only",
    "changed_sign", "changed_operator", "changed_range",
    "complete_negation", "complete_qualification", "background_cohort",
])
def test_qei_checks_complete_parsed_source_and_preserves_authoritative_text(tmp_path, case):
    background_source = (
        "Furthermore, large cohorts treated conservatively without PE, have recently been "
        "reported with a median reduction in triglycerides of 48% (IQR 29\u201363%) within "
        "the first 24 h and comparable clinical outcomes (median hospital stay of 6 days "
        "and mortality of 1.7%) to the published PE cohorts ( 9 )."
    )
    source = "Our participants had a median reduction in triglycerides of 48% (IQR 29\u201363%) within the first 24 h and mortality of 1.7%."
    if case == "background_cohort":
        source = background_source
    sentence = source.replace("\u2013", "-")
    record_id = "gubensek"
    if case == "whitespace":
        source = source.replace("within the", "within\n  the")
    elif case == "contradicted":
        source = "Survival was 100% in both groups."
    elif case == "leading_negation":
        source = "We found no evidence that " + source
    elif case == "trailing_qualification":
        sentence = "Mortality was 48% in the intervention group"
        source = sentence + " only in previous reports, not in this trial."
    elif case == "wrong_paper":
        record_id = "another_paper"
    elif case == "changed_sign":
        source = "The triglyceride change was -48% in the intervention group."
        sentence = source.replace("-48%", "48%")
    elif case == "changed_operator":
        source = "Triglycerides fell by 48% without significance (P > 0.05)."
        sentence = source.replace(">", "<")
    elif case == "changed_range":
        sentence = sentence.replace("29-63", "29-64")
    elif case == "complete_negation":
        sentence = source = "We found no evidence that mortality was 48% in this trial."
    elif case == "complete_qualification":
        sentence = source = (
            "Mortality was 48% in the intervention group only in previous reports, not in this trial."
        )
    claims_dir, parsed_dir = tmp_path / "qc", tmp_path / "parsed"
    claims_dir.mkdir()
    parsed_dir.mkdir()
    (claims_dir / "gubensek.quant_claims.json").write_text(json.dumps({
        "paper_id": "gubensek", "claims": [{
            "claim_type": "percentage", "raw_text": "48%", "numeric_values": [48],
            "sentence": sentence, "binding_confidence": "partial",
            "endpoint": "mortality", "arm": "", "claim_role": "unknown",
        }],
    }))
    if case != "missing":
        (parsed_dir / f"{record_id}.paper_sections.json").write_text(json.dumps({
            "paper_id": record_id, "title": source,
            "sections": {"results": "" if case == "metadata_only" else source},
        }))
    md, diag = build_results_table_with_diagnostic(
        claims_dir, parsed_dir=parsed_dir, topic="plasma_exchange_adverse_rates",
        accepted_paper_ids=frozenset({"gubensek"}),
        citation_tokens_by_paper_id={"gubensek": "Gubensek 2022"},
    )
    if case in {"range_dash", "whitespace"}:
        assert diag["n_rendered"] == 1
        assert f"| Gubensek 2022 | {' '.join(source.split())} | 48% |" in md
        assert "29-63%" not in md
    else:
        assert md == ""
        assert diag["drop_unowned_result" if case in {"complete_negation", "complete_qualification", "background_cohort"} else "drop_surface_gate"] == 1


@pytest.mark.parametrize("section,sentence,owned", [
    ("discussion", "Additionally, 75 mg trans-resveratrol increased FMD from 5.83% to 7.21% in 28 adults [ 9 ].", False),
    ("results", "Abdollahi et al. reported improved insulin resistance (p = 0.01).", False),
    ("abstract", "Previous studies reported a 17% improvement.", False),
    ("introduction", "Resveratrol increased responsiveness by 17%.", False),
    ("results", "Resveratrol increased responsiveness by 17%.", True),
    ("abstract", "Resveratrol increased responsiveness by 17%.", True),
    ("discussion", "We observed a 17% increase in responsiveness.", True),
    ("discussion", "Resveratrol increased responsiveness by 17%.", False),
])
def test_qei_requires_result_ownership_not_merely_source_containment(section, sentence, owned):
    from agent.results_table import _owned_result_sentence

    assert _owned_result_sentence(sentence, {"sections": {section: sentence}}) is owned


def test_qei_uses_canonical_citation_token(tmp_path):
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    paper_id = "PMC1_palmer_2021ucos_glp1_trial"
    (claims_dir / "PMC1.quant_claims.json").write_text(json.dumps({
        "paper_id": paper_id,
        "claims": [{"claim_type": "p_value", "raw_text": "p=0.04",
                    "sentence": "The weight comparison yielded p=0.04.",
                    "numeric_values": [0.04],
                    "binding_confidence": "high",
                    "endpoint": "body weight", "arm": "pooled"}],
    }))
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="glp1",
        citation_tokens_by_paper_id={paper_id: "Palmer 2021"},
    )
    assert diag["n_rendered"] == 1
    assert "Palmer 2021" in md
    assert "2021ucos" not in md


def test_qei_quarantines_rows_without_canonical_token(tmp_path):
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    paper_id = "PMC1_cameron_2016amma_metformin"
    (claims_dir / "PMC1.quant_claims.json").write_text(json.dumps({
        "paper_id": paper_id,
        "claims": [{"claim_type": "p_value", "raw_text": "p=0.04",
                    "numeric_values": [0.04],
                    "binding_confidence": "high",
                    "endpoint": "inflammation", "arm": "metformin"}],
    }))
    quarantine = tmp_path / "qei_quarantined.json"
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="metformin",
        citation_tokens_by_paper_id={}, quarantine_path=quarantine,
    )
    rows = json.loads(quarantine.read_text())
    assert md == ""
    assert diag["drop_missing_canonical_citation"] == 1
    assert rows[0]["paper_id"] == paper_id
    assert rows[0]["reason"] == "missing_canonical_citation"


def test_diagnostic_empty_dir_returns_zeroed_counts(tmp_path):
    """Missing dir → all counters zero, no crash, empty md."""
    md, diag = build_results_table_with_diagnostic(
        tmp_path / "nope", topic="x",
    )
    assert md == ""
    assert diag["n_quant_files"] == 0
    assert diag["n_total_claims"] == 0
    assert diag["n_rendered"] == 0


def test_diagnostic_non_receipt_filter_increments_drop_counter(tmp_path):
    """Receipt-scope guard: paper not in accepted_paper_ids increments
    drop_non_receipt_paper, not n_total_claims (we never opened the
    file's claim list)."""
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    (claims_dir / "PMC_outsider.quant_claims.json").write_text(
        json.dumps({
            "paper_id": "PMC_outsider",
            "claims": [{"claim_type": "p_value", "raw_text": "p=0.04",
                        "numeric_values": [0.04],
                        "binding_confidence": "high",
                        "endpoint": "x", "arm": "metformin"}],
        }),
    )
    md, diag = build_results_table_with_diagnostic(
        claims_dir, topic="metformin",
        accepted_paper_ids=frozenset({"only_this_one"}),
    )
    assert md == ""
    assert diag["drop_non_receipt_paper"] == 1
    assert diag["n_total_claims"] == 0  # never reached the claims


def test_format_empty_qei_placeholder_shows_diagnostic_numbers():
    """The placeholder text must surface the breakdown so reviewers
    see *why* the table is empty (universal across topics)."""
    diag = {
        "n_quant_files": 8, "n_total_claims": 47, "n_admissible": 12,
        "n_topic_matched": 0, "n_meaningful": 0,
        "drop_off_topic_arm": 12, "drop_non_receipt_paper": 3,
    }
    md = format_empty_qei_placeholder(diag, topic="rapamycin")
    assert "rapamycin" in md
    assert "8" in md       # n_quant_files
    assert "47" in md      # n_total_claims
    assert "12" in md      # n_admissible / drop_off_topic_arm
    assert "Corpus Expansion To-Do" in md  # forward-points to verdict


def test_format_empty_qei_placeholder_missing_keys_default_to_zero():
    """An incomplete diag dict must not raise — uses .get(key, 0)."""
    md = format_empty_qei_placeholder({}, topic="any_topic")
    assert "any_topic" in md
    assert "**0**" in md  # all counters render as 0


def test_back_compat_build_results_table_still_returns_str(tmp_path):
    """The thin wrapper preserves the pre-Slice-1 signature: str only,
    no tuple. All existing callers + tests keep working."""
    claims_dir = tmp_path / "qc"
    claims_dir.mkdir()
    out = build_results_table(claims_dir, topic="x")
    assert isinstance(out, str)
    assert out == ""
