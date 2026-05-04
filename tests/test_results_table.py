"""Unit tests for agent/results_table.py — deterministic per-study
quantitative results table (universal Q9 structural fix).

Pure-function tests; no LLM calls, no network IO.
"""
from __future__ import annotations

from agent.results_table import (
    StudyRow,
    extract_study_row,
    render_table_md,
    _format_p,
    _largest_sample_size,
    _smallest_p_value,
)
from agent.synthesis_schemas import ReceiptSummary


def _r(rid: str = "r1", *, verdict: str = "accept_clean",
       year: int | None = 2024, trial: str | None = None,
       outcome: str = "longevity") -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"/p/{rid}", topic="aspirin",
        thesis_text="t", spar_verdict=verdict,
        n_claims=3, n_failed_traces=0,
        canonical_trial_id=trial, evidence_tier="A1",
        directness="direct", outcome_class=outcome,
        effect_direction="no_change", p_values=(),
        population_summary="older adults",
        source_year=year,
    )


# ---------- formatting helpers -------------------------------------

def test_format_p_renders_three_tiers():
    assert _format_p(0.0001) == "p<0.001"
    assert _format_p(0.003) == "p=0.003"
    assert _format_p(0.04) == "p=0.04"
    assert _format_p(0.5) == "p=0.50"


def test_largest_sample_size_picks_max():
    claims = [
        {"claim_type": "sample_size", "numeric_values": [120]},
        {"claim_type": "sample_size", "numeric_values": [19114]},
        {"claim_type": "sample_size", "numeric_values": [500]},
        {"claim_type": "p_value", "numeric_values": [0.03]},  # ignored
    ]
    assert _largest_sample_size(claims) == "n=19,114"


def test_largest_sample_size_handles_missing():
    """No sample_size claims → '—'."""
    assert _largest_sample_size([]) == "—"
    assert _largest_sample_size([
        {"claim_type": "p_value", "numeric_values": [0.5]},
    ]) == "—"


def test_smallest_p_value_picks_min():
    claims = [
        {"claim_type": "p_value", "numeric_values": [0.04]},
        {"claim_type": "p_value", "numeric_values": [0.0001]},
        {"claim_type": "p_value", "numeric_values": [0.5]},
    ]
    assert _smallest_p_value(claims) == "p<0.001"


# ---------- extract_study_row --------------------------------------

def test_extract_skips_rejected_receipts():
    """SPAR-rejected receipts must NOT show up in the table."""
    r = _r(verdict="reject_low_evidence")
    assert extract_study_row(r, []) is None


def test_extract_returns_none_when_no_quantitative_data():
    """Receipt with no n / no effect / no p → not enough to put in table."""
    r = _r()
    # No numeric claims
    assert extract_study_row(r, []) is None


def test_extract_assembles_full_row():
    r = _r(trial="ASPREE", year=2025)
    claims = [
        {"claim_type": "sample_size", "numeric_values": [19114]},
        {"claim_type": "hazard_ratio", "numeric_values": [1.00]},
        {"claim_type": "p_value", "numeric_values": [0.04]},
    ]
    row = extract_study_row(r, claims)
    assert row is not None
    assert row.sample_size == "n=19,114"
    assert "ASPREE" in row.study_label
    # Effect string contains HR
    assert "HR" in row.effect


# ---------- render_table_md ----------------------------------------

def test_render_returns_empty_for_no_rows():
    """Caller decides whether to skip the section when no rows; we
    return empty string to make that detection cheap."""
    assert render_table_md([], topic="aspirin") == ""


def test_render_includes_topic_in_title_and_caption():
    rows = [StudyRow(
        study_label="ASPREE 2018", sample_size="n=19,114",
        effect="HR 0.96", ci="(0.81–1.13)", p_value="p=0.43",
        endpoint="cv events",
    )]
    md = render_table_md(rows, topic="aspirin")
    assert "## Quantitative Results Summary — aspirin" in md
    assert "ASPREE 2018" in md
    assert "n=19,114" in md
    assert "HR 0.96" in md
    assert "p=0.43" in md
    # Markdown table syntax
    assert "| Study | n | Effect | 95% CI | p | Endpoint |" in md
    # Legend / caption is appended
    assert "traces to a high-confidence claim" in md
