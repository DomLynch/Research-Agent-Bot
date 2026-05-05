"""Unit tests for agent/results_table.py — deterministic per-CLAIM
Quantitative Evidence Index (universal Q9 structural fix, Shot 2).

Pure-function tests; no LLM calls, no network IO.
"""
from __future__ import annotations

import json

from agent.results_table import (
    EvidenceRow,
    _arm_belongs_to_topic,
    _claim_to_row,
    _confidence_admissible,
    _format_value,
    _format_statistic,
    _load_topic_arm_terms,
    _quality_score,
    _short_citation,
    _truncate,
    build_results_table,
    build_results_table_with_diagnostic,
    format_empty_qei_placeholder,
)


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
        "paper_id": "PMC1_demo",
        "claims": [
            # 1 high-conf, on-topic, meaningful → renders
            {"claim_type": "p_value", "raw_text": "p=0.04",
             "numeric_values": [0.04], "binding_confidence": "high",
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
