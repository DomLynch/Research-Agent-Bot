from copy import deepcopy
import json

import pytest

from agent.qei_facts import render_rows, row_issue, saved_table, source_entries, validated_rows
from agent.revision_evidence import create_revision_evidence_snapshot


QUOTE = "Compared with placebo, resveratrol reduced fasting glucose (-7.97±13.6 mg/dL, p=0.05) and increased HDL cholesterol (3.62±8.75 mg/dL, p=0.01)."
COMPARISON = "Participants were randomly assigned to resveratrol or placebo for eight weeks."


@pytest.fixture
def source():
    return {"receipt_id": "trial", "own_result_sentences": [QUOTE], "abstract": COMPARISON + " " + QUOTE, "methods": ""}


@pytest.fixture
def row():
    return {"receipt_id": "trial", "source_result_quote": QUOTE,
            "result_span": "increased HDL cholesterol (3.62±8.75 mg/dL, p=0.01).",
            "endpoint": "HDL cholesterol", "comparison": COMPARISON,
            "estimate": "3.62±8.75 mg/dL", "uncertainty": "±8.75 mg/dL", "significance": "p=0.01"}


def test_source_fields_and_signed_estimates_are_kept(row, source):
    assert not row_issue(row, {"trial": source})
    negative = {**row, "result_span": "Compared with placebo, resveratrol reduced fasting glucose (-7.97±13.6 mg/dL, p=0.05)",
                "endpoint": "fasting glucose", "estimate": "-7.97±13.6 mg/dL", "uncertainty": "±13.6 mg/dL", "significance": "p=0.05"}
    assert not row_issue(negative, {"trial": source})
    assert row_issue({**negative, "estimate": "7.97±13.6 mg/dL"}, {"trial": source}) == "unverified_field_span"


@pytest.mark.parametrize("field,value", [
    ("receipt_id", "other"), ("source_result_quote", QUOTE.replace("reduced", "increased")),
    ("result_span", "HDL cholesterol improved by 3.62 mg/dL."), ("endpoint", "fasting glucose"),
    ("estimate", "8.75 mg/dL"), ("estimate", "p=0.01"), ("estimate", "±8.75 mg/dL"),
    ("uncertainty", "95% CI 1 to 3"), ("significance", "p=0.05"), ("significance", None),
    ("comparison", "Resveratrol versus vitamin C."), ("estimate", 3.62),
])
def test_changed_ambiguous_or_detached_values_fail(row, source, field, value):
    assert row_issue({**row, field: value}, {"trial": source})


def test_dense_sentence_cannot_supply_a_different_endpoint_p_value(row, source):
    assert row_issue({**row, "result_span": QUOTE}, {"trial": source}) == "ambiguous_significance"


def test_missing_uncertainty_remains_unknown_and_rounded_zero_is_rejected(row, source):
    row = {**row, "source_result_quote": "Resveratrol reduced glucose by 12% (p=0.00).",
           "result_span": "Resveratrol reduced glucose by 12% (p=0.00).", "endpoint": "glucose",
           "estimate": "12%", "uncertainty": None, "significance": "p=0.00"}
    source["own_result_sentences"] = [row["source_result_quote"]]
    assert row_issue(row, {"trial": source}) == "rounded_zero_p"
    row = {key: value.replace("p=0.00", "p=0.04") if isinstance(value, str) else value for key, value in row.items()}
    source["own_result_sentences"] = [row["source_result_quote"]]
    assert not row_issue(row, {"trial": source})
    assert "Not reported in quoted result" in render_rows([row], "resveratrol", {"trial": "Smith 2020"})


def test_duplicate_quarantine_does_not_merge_identical_numbers_across_studies(row, source):
    second = {**row, "receipt_id": "other"}
    accepted, rejected = validated_rows({"rows": [row, deepcopy(row), second]}, [source, {**source, "receipt_id": "other"}])
    assert accepted == [row, second]
    assert rejected == [{"row": 1, "reason": "duplicate_or_row_limit"}]


def test_saved_table_revalidates_source_hashes_and_citations(tmp_path, row, source):
    run, quant, parsed = (tmp_path / name for name in ("run", "quant", "parsed"))
    for path in (run, quant, parsed):
        path.mkdir()
    (parsed / "trial.paper_sections.json").write_text(json.dumps({"paper_id": "trial", "title": "Resveratrol trial",
                                                                "sections": {"abstract": source["abstract"], "results": QUOTE}}))
    (quant / "trial.quant_claims.json").write_text(json.dumps({"paper_id": "trial", "claims": []}))
    contracts = [{"receipt_id": "trial", "topic": "resveratrol", "n_claims": 1}]
    registry = run / "citation_registry.json"
    registry.write_text(json.dumps({"trial": {"body_citation": "Smith 2020"}}))
    report = create_revision_evidence_snapshot(run, quant_dir=quant, parsed_dir=parsed, citation_registry=registry,
                                              receipt_ids=["trial"], receipt_contracts=contracts, topic="resveratrol")
    assert report["passed"]
    (run / "manifest.json").write_text(json.dumps({"topic": "resveratrol", "receipts": contracts}))
    tokens = {"trial": "Smith 2020"}
    entries = source_entries(run, "resveratrol", tokens)
    assert QUOTE in entries[0]["own_result_sentences"]
    (run / "qei_facts.json").write_text(json.dumps({"rows": [row]}))
    table = saved_table(run, "resveratrol", tokens)
    assert "HDL cholesterol |" in table and "3.62±8.75 mg/dL" in table
    from agent.journal_surface_gate import _qei_shape_issue_messages, _extract_qei_rows, qei_row_issue_messages
    assert not _qei_shape_issue_messages(table)
    assert all(not qei_row_issue_messages(value) for value in _extract_qei_rows(table))
    with pytest.raises(ValueError, match="identity"):
        saved_table(run, "resveratrol", {"trial": "Jones 2021"})
    with pytest.raises(ValueError, match="snapshot"):
        saved_table(run, "metformin", tokens)
    frozen = run / "revision_evidence_snapshot/parsed/trial.paper_sections.json"
    frozen.write_text(frozen.read_text().replace("3.62", "9.62"))
    with pytest.raises(ValueError, match="snapshot"):
        saved_table(run, "resveratrol", tokens)
