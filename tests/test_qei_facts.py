from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace

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


@pytest.mark.parametrize('estimate,span,label', [
    ('r = 0.327', 'correlated with CVR (r = 0.327)', 'Correlation, not a treatment-effect estimate.'),
    ('from 88.75 to 87.54 kg', 'weight decreased from 88.75 to 87.54 kg', 'Reported before/after values'),
    ('resveratrol -0.95 kg vs placebo -0.16 kg', 'weight: resveratrol -0.95 kg vs placebo -0.16 kg', 'Reported arm values'),
    ('from -0.5 to 0.5', 'confidence interval from -0.5 to 0.5', 'Analysis context remains as quoted'),
])
def test_rendered_analysis_context_keeps_verbatim_estimate(row, estimate, span, label):
    record = {**row, 'estimate': estimate, 'result_span': span}
    before = deepcopy(record)
    rendered = render_rows([record], 'topic', {'trial':'Trial 2020'})
    assert label in rendered and estimate in rendered
    assert 'no SD, SE or confidence-interval interpretation inferred' in rendered
    assert record == before


def test_new_analysis_labels_preserve_legacy_row_quarantine(tmp_path, row):
    raw = '| ' + ' | '.join(['Trial 2020', *(row[k] for k in ('endpoint','comparison','estimate','uncertainty','significance','result_span'))]) + ' |'
    (tmp_path/'numeric_claim_quarantine.json').write_text(json.dumps([{'issue_type':'reviewer_numeric_auto_strip','severity':'P1','sentence':raw}]))
    with pytest.raises(ValueError, match='qei_no_semantically_supported_estimates'):
        render_rows([row], 'topic', {'trial':'Trial 2020'}, run=tmp_path)


@pytest.mark.parametrize("kind", ["complete", "partial", "other_issue", "advisory"])
@pytest.mark.parametrize("directory", ["", "debug"])
def test_table_regeneration_respects_only_exact_p1_reviewed_row_removals(tmp_path, row, kind, directory):
    tokens = {"trial": "Smith 2020", "other": "Jones 2021"}
    other = {**row, "receipt_id": "other"}
    complete = render_rows([row], "resveratrol", tokens).splitlines()[-1]
    item = {"issue_type": "reviewer_numeric_auto_strip", "severity": "P1", "sentence": complete}
    if kind == "partial":
        item["sentence"] = "| Smith 2020 | HDL cholesterol |"
    if kind == "other_issue":
        item["issue_type"] = "unrelated"
    if kind == "advisory":
        item["severity"] = "P2"
    destination = tmp_path/directory
    destination.mkdir(exist_ok=True)
    (destination/'numeric_claim_quarantine.json').write_text(json.dumps([item]))
    table = render_rows([row, other], "resveratrol", tokens, run=tmp_path)
    assert ("| Smith 2020 |" in table) is (kind != "complete")
    assert "| Jones 2021 |" in table
    if kind == "complete":
        with pytest.raises(ValueError, match="qei_no_semantically_supported_estimates"):
            render_rows([row], "resveratrol", tokens, run=tmp_path)


def test_semantic_review_quarantines_conflicts_and_binds_cache_to_sources(tmp_path, row, source, monkeypatch):
    from agent import qei_facts as qei
    other = {**row, "receipt_id": "other"}
    calls = []
    async def judge(**kwargs):
        calls.append(kwargs)
        supplied = json.loads(kwargs["messages"][1]["content"])["rows"]
        return SimpleNamespace(model="configured-judge", parsed={"assessments": [
            {"row": index, "supported": value["receipt_id"] == "other", "reason": "Supported" if value["receipt_id"] == "other" else "Source passages disagree about the same treatment and endpoint."}
            for index, value in enumerate(supplied)
        ]})
    monkeypatch.setattr(qei, "chat_json", judge)
    monkeypatch.setattr(qei, "build_judge_chain", lambda _settings: ["configured-judge"])
    accepted = asyncio.run(qei._review_rows(tmp_path, [row, other], [source], chain=["writer"]))
    assert accepted == [other]
    assert calls[0]["chain"] == ["configured-judge"]
    report = json.loads((tmp_path / "qei_review.json").read_text())
    assert report["reviewed_rows"] == [row, other] and report["assessments"][0]["supported"] is False
    assert asyncio.run(qei._review_rows(tmp_path, accepted, [source])) == accepted
    assert len(calls) == 1
    changed = {**source, "abstract": source["abstract"] + " A source correction changes the interpretation."}
    assert asyncio.run(qei._review_rows(tmp_path, accepted, [changed])) == accepted
    assert len(calls) == 2


@pytest.mark.parametrize("policy", ["PROMPT", "REVIEW_PROMPT"])
def test_changed_quantitative_policy_cannot_reuse_an_old_approval(tmp_path, row, source, monkeypatch, policy):
    from agent import qei_facts as qei
    calls = []
    async def judge(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model="configured-judge", parsed={"assessments": [
            {"row": 0, "supported": len(calls) == 1, "reason": "Initial approval" if len(calls) == 1 else "Multiple outcomes under one endpoint label."}
        ]})
    monkeypatch.setattr(qei, "chat_json", judge)
    assert asyncio.run(qei._review_rows(tmp_path, [row], [source])) == [row]
    assert asyncio.run(qei._review_rows(tmp_path, [row], [source])) == [row]
    assert len(calls) == 1
    monkeypatch.setattr(qei, policy, getattr(qei, policy, "") + " Require one endpoint per estimate.", raising=False)
    assert asyncio.run(qei._review_rows(tmp_path, [row], [source])) == []
    assert len(calls) == 2


@pytest.mark.parametrize("assessments", [[], [{"row": 0, "supported": "true", "reason": "yes"}],
    [{"row": 1, "supported": True, "reason": "yes"}], [{"row": 0, "supported": True, "reason": ""}]])
def test_incomplete_or_malformed_semantic_review_fails_closed(tmp_path, row, source, monkeypatch, assessments):
    from agent import qei_facts as qei
    async def judge(**_kwargs):
        return SimpleNamespace(model="configured-judge", parsed={"assessments": assessments})
    monkeypatch.setattr(qei, "chat_json", judge)
    with pytest.raises(ValueError, match="qei_semantic_review_invalid"):
        asyncio.run(qei._review_rows(tmp_path, [row], [source]))
    assert not (tmp_path / "qei_review.json").exists()


def test_saved_table_revalidates_source_hashes_and_citations(tmp_path, row, source):
    run, quant, parsed = (tmp_path / name for name in ("run", "quant", "parsed"))
    for path in (run, quant, parsed):
        path.mkdir()
    (parsed / "trial.paper_sections.json").write_text(json.dumps({"paper_id": "trial", "title": "Resveratrol trial",
                                                                "sections": {"abstract": source["abstract"], "results": QUOTE}}))
    (quant / "trial.quant_claims.json").write_text(json.dumps({"paper_id": "trial", "claims": []}))
    contracts = [{"receipt_id": "trial", "topic": "resveratrol", "n_claims": 1}]
    registry = run / "citation_registry.json"
    registry.write_text(json.dumps({"trial": {"receipt_id": "trial", "body_citation": "Smith 2020"}}))
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
    from publishing.submission import _prepare_qei_section
    manifest = json.loads((run / "manifest.json").read_text())
    bundle = [{"cited_as": "Smith 2020"}]
    paper = "# Synthesis\n\n## Methods\n\nFrozen source selection.\n\n## Results\n\nFindings.\n"
    prepared = _prepare_qei_section(paper, run, "resveratrol", bundle, manifest)
    assert prepared.count("## Quantitative Evidence Index") == 1
    assert prepared.index("## Quantitative Evidence Index") < prepared.index("## Methods")
    assert table.strip() in prepared
    assert _prepare_qei_section(prepared, run, "resveratrol", bundle, manifest) == prepared
    assert _prepare_qei_section(prepared + "\n" + table, run, "resveratrol", bundle, manifest).count("## Quantitative Evidence Index") == 1
    (run / "qei_facts.json").write_text(json.dumps({"rows": [{**row, "estimate": "9.62±8.75 mg/dL"}]}))
    with pytest.raises(ValueError):
        _prepare_qei_section(paper, run, "resveratrol", bundle, manifest)
    (run / "qei_facts.json").write_text(json.dumps({"rows": [row]}))
    with pytest.raises(ValueError, match="identity"):
        saved_table(run, "resveratrol", {"trial": "Jones 2021"})
    with pytest.raises(ValueError, match="snapshot"):
        saved_table(run, "metformin", tokens)
    frozen = run / "revision_evidence_snapshot/parsed/trial.paper_sections.json"
    frozen.write_text(frozen.read_text().replace("3.62", "9.62"))
    with pytest.raises(ValueError, match="qei_source_snapshot_unverified"):
        _prepare_qei_section(paper, run, "resveratrol", bundle, manifest)
    with pytest.raises(ValueError, match="snapshot"):
        saved_table(run, "resveratrol", tokens)


def test_only_evidence_sent_to_core_can_support_a_comparison(row, source):
    source["publication_excerpt"] = QUOTE
    assert row_issue(row, {"trial": source}) == "unverified_comparison"
    source["publication_excerpt"] = source["abstract"]
    assert not row_issue(row, {"trial": source})


@pytest.mark.parametrize("field,value", [(1, "fasting glucose"), (2, "Randomized treatment versus vitamin C."),
    (3, "9.62±8.75 mg/dL"), (4, "95% CI [0.19, 0.99]"), (5, "p=0.05"), (6, "Unsupported endpoint changed by 3.62±8.75 mg/dL (p=0.01).")])
def test_final_outgoing_table_rejects_cell_mutations_and_accepts_rendering(row, source, field, value):
    from agent.qei_facts import quoted_table_row_supported, HEADERS
    from agent.revision_quality import _quantitative_table_rows, _table_cells, _statistics_are_source_bound
    paper = render_rows([row], "resveratrol", {"trial": "Smith 2020"})
    rows = [{"citation_token": "Smith 2020", "verified_abstract": source["abstract"]}]
    assert _statistics_are_source_bound(paper, rows, tables_only=True)
    line, header = list(_quantitative_table_rows(paper))[0]
    cells = _table_cells(line)
    assert quoted_table_row_supported([cell.replace("p=", "P=") for cell in cells], header, source["abstract"])
    cells[field] = value
    assert not quoted_table_row_supported(cells, header, source["abstract"])
    assert not quoted_table_row_supported(cells[:2], [h.lower() for h in HEADERS[:2]], source["abstract"])
    assert not _statistics_are_source_bound(paper.replace("Smith 2020", "Jones 2021"), rows, tables_only=True)
    assert not _statistics_are_source_bound(paper, [{**rows[0], "verified_abstract": COMPARISON}], tables_only=True)


def test_numeric_table_checks_are_not_limited_to_named_sections():
    from agent.revision_quality import _statistics_are_source_bound
    text = "The intervention increased muscle strength by 12 kg compared with placebo."
    rows = [{"citation_token": "Smith 2020", "verified_abstract": text}]
    for heading in ("Results", "Supplementary estimates", "Unusual table heading"):
        paper = f"## {heading}\n| Study | Result |\n|---|---|\n| Smith 2020 | {text} |"
        assert _statistics_are_source_bound(paper, rows, tables_only=True)
        assert not _statistics_are_source_bound(paper.replace("12 kg", "99 kg"), rows, tables_only=True)


def test_untyped_numeric_columns_cannot_bypass_source_verification():
    from agent.revision_quality import _statistics_are_source_bound
    rows = [{"citation_token": "Smith 2020", "verified_abstract": "Participants experienced improvements in fasting glucose."}]
    for column in ("Result", "Fasting glucose", "Reported estimate"):
        paper = f"| Study | {column} |\n|---|---|\n| Smith 2020 | 35 |"
        assert not _statistics_are_source_bound(paper, rows, tables_only=True)
    text = "The intervention increased muscle strength by 12 kg compared with placebo."
    legacy = f"| Study | Source context | Raw statistic |\n|---|---|---|\n| Smith 2020 | {text} | 12 kg |"
    rows[0]["verified_abstract"] = text
    assert _statistics_are_source_bound(legacy, rows, tables_only=True)
    assert not _statistics_are_source_bound(legacy.replace("| 12 kg |", "| 99 kg |"), rows, tables_only=True)


def test_source_finding_prefix_does_not_break_untyped_source_quote():
    from agent.revision_quality import _statistics_are_source_bound
    text = "Muscle area increased (HI: Δ12%, MIX: Δ9.2%) after the intervention."
    paper = f"| Source | Finding |\n|---|---|\n| Smith 2020 | finding={text} |"
    rows = [{"citation_token": "Smith 2020", "verified_abstract": text}]
    assert _statistics_are_source_bound(paper, rows, tables_only=True)
    assert not _statistics_are_source_bound(paper.replace("Δ12%", "Δ99%"), rows, tables_only=True)
