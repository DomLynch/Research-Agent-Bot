"""Unit tests for agent/results_table.py — deterministic per-CLAIM
Quantitative Evidence Index (universal Q9 structural fix, Shot 2).

Pure-function tests; no LLM calls, no network IO.
"""
from __future__ import annotations

import json

from agent.results_table import (
    EvidenceRow,
    _claim_to_row,
    _confidence_admissible,
    _format_value,
    _format_statistic,
    _quality_score,
    _short_citation,
    _truncate,
    build_results_table,
)


# ---------- confidence filter ---------------------------------------

def test_high_confidence_always_admitted():
    assert _confidence_admissible({"binding_confidence": "high",
                                   "claim_type": "p_value"})
    assert _confidence_admissible({"binding_confidence": "high",
                                   "claim_type": "hazard_ratio"})


def test_partial_admitted_only_for_objective_facts():
    """Partial-confidence sample_size / unit_value / year passes;
    interpretive claim types (HR/p_value/percentage) blocked at
    partial."""
    objective = {"binding_confidence": "partial", "claim_type": "sample_size"}
    interpretive = {"binding_confidence": "partial", "claim_type": "hazard_ratio"}
    assert _confidence_admissible(objective)
    assert not _confidence_admissible(interpretive)


def test_unbound_or_none_rejected():
    assert not _confidence_admissible({"binding_confidence": "none"})
    assert not _confidence_admissible({"binding_confidence": ""})
    assert not _confidence_admissible({})


# ---------- formatting ---------------------------------------------

def test_format_value_integer_uses_commas():
    assert _format_value(19114.0) == "19,114"


def test_format_value_decimal_keeps_3_sig_figs():
    assert _format_value(0.85) == "0.85"
    assert _format_value(0.001234) == "0.00123"


def test_format_statistic_p_value():
    assert _format_statistic({"claim_type": "p_value"}, 0.0001) == "p<0.001"
    assert _format_statistic({"claim_type": "p_value"}, 0.04) == "p=0.04"


def test_format_statistic_confidence_interval():
    s = _format_statistic(
        {"claim_type": "confidence_interval",
         "numeric_values": [0.81, 1.13]}, 0.81,
    )
    assert s == "(0.81–1.13)"


def test_format_statistic_default_dash():
    """For HR/OR, the value column already shows the ratio; statistic
    column gets em-dash."""
    assert _format_statistic({"claim_type": "hazard_ratio"}, 0.85) == "—"


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


def test_claim_to_row_assembles_full_row():
    claim = {
        "claim_type": "sample_size",
        "raw_text": "n=19,114",
        "numeric_values": [19114],
        "binding_confidence": "high",
        "endpoint": "frailty status",
        "arm": "aspirin",
    }
    row = _claim_to_row(claim, paper_id="PMC12345_aspirin_2025_paper")
    assert row is not None
    assert "2025" in row.study_label
    assert "frailty" in row.endpoint
    assert row.arm == "aspirin"


def test_truncate_replaces_pipe_chars():
    """| would break the markdown table — must be sanitized."""
    assert "|" not in _truncate("a|b|c", 20)


def test_truncate_caps_long_strings():
    assert _truncate("x" * 100, 10) == "xxxxxxxxx…"


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
                "numeric_values": [1.01],
                "binding_confidence": "high",
                "endpoint": "mortality",
                "arm": "aspirin",
            },
            {
                "claim_type": "p_value",
                "raw_text": "p=0.32",
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
    assert "| Study | Endpoint | Arm | Value | Type | Statistic |" in md
    # All 3 rows should appear (different endpoints, different types)
    assert "19,114" in md or "n=19,114" in md
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
