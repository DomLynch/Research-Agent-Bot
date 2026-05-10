"""Tests for agent.effect_row_extractor — quant_claims → EffectRow bridge."""
from __future__ import annotations

import json
import math
from pathlib import Path

from agent.effect_row_extractor import (
    ExtractedRow,
    extract_rows_from_corpus,
    extract_rows_from_paper,
    to_pooler_input,
)


def _write_quant_claims(path: Path, sentences: list[str]) -> None:
    """Helper: synthesize a minimal quant_claims.json with one claim per
    sentence so the extractor sees them on iteration."""
    data = {
        "paper_id": "p-test",
        "doi": None,
        "extracted_at": "2026-05-10",
        "extractor_version": "test",
        "claims_count_by_type": {},
        "claims": [
            {"claim_id": f"c-{i}", "claim_type": "ratio",
             "raw_text": s, "numeric_values": [], "units": "",
             "source_section": "results", "source_offset": 0,
             "sentence": s, "context_window": s, "claim_role": "effect",
             "endpoint": "", "arm": "", "direction": "",
             "binding_confidence": "high"}
            for i, s in enumerate(sentences)
        ],
    }
    path.write_text(json.dumps(data))


def test_extracts_hr_with_curly_dash(tmp_path: Path) -> None:
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [
        "The adjusted HR was 0.85 (95% CI 0.72–1.01).",
    ])
    rows = extract_rows_from_paper(
        p, study_id="Smith 2022", paper_id="p-test",
        outcome_class="cardiometabolic",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.effect_measure == "log_HR"
    assert math.isclose(r.point_estimate, 0.85, rel_tol=1e-9)
    assert math.isclose(r.ci_lower, 0.72, rel_tol=1e-9)
    assert math.isclose(r.ci_upper, 1.01, rel_tol=1e-9)
    assert r.se > 0.0
    # Sanity: log_HR should equal ln(0.85)
    assert math.isclose(r.effect, math.log(0.85), rel_tol=1e-9)


def test_extracts_or_with_to_separator(tmp_path: Path) -> None:
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [
        "Odds ratio 1.27, 95% CI: 1.05 to 1.54.",
    ])
    rows = extract_rows_from_paper(
        p, study_id="Jones 2023", paper_id="p", outcome_class="immune",
    )
    assert len(rows) == 1
    assert rows[0].effect_measure == "log_OR"


def test_extracts_rr_with_equals(tmp_path: Path) -> None:
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [
        "Risk ratio = 0.43 (95% CI, 0.21-0.85).",
    ])
    rows = extract_rows_from_paper(
        p, study_id="Lee 2024", paper_id="p", outcome_class="longevity",
    )
    assert len(rows) == 1
    assert rows[0].effect_measure == "log_RR"


def test_skips_degenerate_ci(tmp_path: Path) -> None:
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [
        "HR 1.0 (95% CI 0.99-0.99).",  # lo == hi
        "HR 0.0 (95% CI 0.0-0.5).",     # eff zero
    ])
    rows = extract_rows_from_paper(
        p, study_id="X 2020", paper_id="p", outcome_class="x",
    )
    assert rows == []


def test_skips_when_point_outside_ci_by_more_than_5pct(tmp_path: Path) -> None:
    """Sanity guard against the regex grabbing two unrelated numbers."""
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [
        "HR 5.0 (95% CI 0.5 to 1.5).",  # 5.0 is far above 1.5*1.05
    ])
    rows = extract_rows_from_paper(
        p, study_id="X", paper_id="p", outcome_class="x",
    )
    assert rows == []


def test_per_paper_dedupes_repeated_sentence(tmp_path: Path) -> None:
    """The same sentence can appear across multiple claim_ids; one row only."""
    sent = "HR 0.80 (95% CI 0.70-0.90)."
    p = tmp_path / "qc.json"
    _write_quant_claims(p, [sent, sent, sent])
    rows = extract_rows_from_paper(
        p, study_id="X", paper_id="p", outcome_class="x",
    )
    assert len(rows) == 1


def test_higher_precedence_pattern_wins_per_sentence(tmp_path: Path) -> None:
    """When a sentence reads as both HR and OR (rare but possible), the HR
    pattern (declared first) wins."""
    p = tmp_path / "qc.json"
    # Compose so HR gets matched first
    _write_quant_claims(p, [
        "Hazard ratio 0.75 (95% CI 0.60-0.94).",
    ])
    rows = extract_rows_from_paper(
        p, study_id="X", paper_id="p", outcome_class="x",
    )
    assert len(rows) == 1
    assert rows[0].effect_measure == "log_HR"


def test_corpus_extraction_resolves_per_paper_files(tmp_path: Path) -> None:
    """extract_rows_from_corpus reads `<base>/<paper_id>.quant_claims.json`."""
    base = tmp_path / "qc"
    base.mkdir()
    _write_quant_claims(
        base / "PMC1.quant_claims.json",
        ["HR 0.90 (95% CI 0.80-1.02)."],
    )
    _write_quant_claims(
        base / "PMC2.quant_claims.json",
        ["OR 1.5, 95% CI 1.1-2.0."],
    )
    receipts = [
        {"paper_id": "PMC1", "citation_token": "Smith 2022",
         "outcome_class": "cardiometabolic"},
        {"paper_id": "PMC2", "citation_token": "Jones 2023",
         "outcome_class": "immune"},
        # Missing file — silently contributes zero rows.
        {"paper_id": "PMC_missing", "citation_token": "Ghost",
         "outcome_class": "x"},
    ]
    rows = extract_rows_from_corpus(receipts, quant_claims_dir=base)
    assert len(rows) == 2
    assert {r.effect_measure for r in rows} == {"log_HR", "log_OR"}


def test_to_pooler_input_shape() -> None:
    """The pool_fixed_effect API consumes Mapping[str, Any] with these keys."""
    rows = [
        ExtractedRow(
            study_id="S1", paper_id="p1", outcome_class="cardiometabolic",
            effect_measure="log_HR", effect=-0.16, se=0.05,
            point_estimate=0.85, ci_lower=0.72, ci_upper=1.01,
            sentence="HR 0.85 (95% CI 0.72-1.01).",
        ),
    ]
    out = to_pooler_input(rows)
    assert out == [{
        "receipt_id": "S1",
        "outcome": "cardiometabolic",
        "effect_measure": "log_HR",
        "effect": -0.16,
        "standard_error": 0.05,
    }]


def test_extractor_is_fail_soft_on_missing_file(tmp_path: Path) -> None:
    """Missing quant_claims file → empty list, no exception."""
    rows = extract_rows_from_paper(
        tmp_path / "does_not_exist.json",
        study_id="X", paper_id="p", outcome_class="x",
    )
    assert rows == []


def test_extractor_is_fail_soft_on_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "qc.json"
    p.write_text("{not json")
    rows = extract_rows_from_paper(
        p, study_id="X", paper_id="p", outcome_class="x",
    )
    assert rows == []
