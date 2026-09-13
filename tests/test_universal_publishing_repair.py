"""Regression evidence from Core submission 9d8747ec and cross-topic controls."""
import importlib
import json
import re
from pathlib import Path

import pytest

from agent.evidence_lanes import unisolated_combination
from agent.publication_evidence import attach_bundle_references

SOURCES = json.loads((Path(__file__).parent / "fixtures/universal_publishing_review.json").read_text())["sources"]


@pytest.mark.parametrize("endpoint,estimate,interval,significance", [
    ("forward lunge", "4.50 W", "95% CI −2.94 to 11.94 W", "P =.23"),
    ("side lunge", "9.24 W", "95% CI 2.99-15.49 W", "P <.01"),
    ("forward lunge with row", "15.25 W", "95% CI −0.63 to 31.13 W", "P =.06"),
])
def test_actual_arroniz_outgoing_decimal_format_preserves_source_binding(endpoint, estimate, interval, significance):
    from agent.qei_facts import HEADERS, quoted_table_row_supported
    source = next(s for s in SOURCES if s["receipt"]["citation_token"] == "Arroniz 2025")
    abstract = source["record"]["sections"]["abstract"]
    quote = re.search(r"(?:For|for) " + re.escape(endpoint) + r", between-group difference[^)]+\)", abstract).group()
    comparison = re.search(r"This study aims[^.]+\.", abstract).group()
    cells = ["Arroniz 2025 [bundle:1]", endpoint, comparison, estimate, interval, significance, quote]
    header = [h.lower() for h in HEADERS]
    rendered = [c.replace("=.", "= 0.").replace("<.", "< 0.") for c in cells]
    assert quoted_table_row_supported(rendered, header, abstract)
    assert not quoted_table_row_supported([c.replace(estimate, "99.99 W") for c in rendered], header, abstract)
    assert not quoted_table_row_supported([c.replace("P =", "P >").replace("P <", "P >") for c in rendered], header, abstract)
    assert not quoted_table_row_supported([*rendered[:1], "unreported endpoint", *rendered[2:]], header, abstract)


@pytest.fixture
def synthesis():
    module = importlib.import_module("run_v06_synthesis")
    previous = module._get_active_topic()
    module._set_topic("resistance_training")
    yield module
    module._set_topic(previous)


def test_actual_lai_outcomes_are_not_a_null_bmi_balance_result(synthesis):
    source = next(row for row in SOURCES if row["receipt"]["citation_token"] == "Lai 2023")
    assert source["receipt"]["effect_direction"] == "null"
    claims = [c for c in source["claims"] if c["binding_confidence"] in {"high", "partial"}]
    result = synthesis._aggregate_paper(claims, paper_meta=source["record"])
    assert result["effect_direction"] == "positive"
    assert dict(result["endpoint_directions"])["muscle strength"] == "positive"


@pytest.mark.parametrize("citation", ["Salter 2024", "Hwang 2018", "Chen 2026"])
def test_actual_supplement_contrasts_do_not_isolate_training(synthesis, citation):
    source = next(row for row in SOURCES if row["receipt"]["citation_token"] == citation)
    assert source["receipt"]["directness"] == "direct"
    assert synthesis._classify_paper_tier("", len(source["claims"]), source["record"]) == ("A1", "indirect")


@pytest.mark.parametrize("target", ["resistance training", "metformin", "cognitive therapy"])
def test_shared_background_intervention_is_not_randomized_contrast(target):
    abstract = f"Participants were randomly assigned to supplement or placebo while also receiving {target}."
    assert unisolated_combination("Randomized trial", abstract, target)
    direct = f"Participants were randomly assigned to {target} or placebo. Both groups completed assessments."
    assert not unisolated_combination("Randomized trial", direct, target)


@pytest.mark.parametrize("topic,endpoint,movement", [
    ("resistance_training", "muscle strength", "increased"),
    ("metformin", "blood glucose", "decreased"),
])
def test_source_outcome_signal_is_not_borrowed_from_background_or_other_p_value(synthesis, topic, endpoint, movement):
    synthesis._set_topic(topic)
    statement = f"The intervention significantly {movement} {endpoint} in the participants compared with the control group."
    record = {"title": "Randomized clinical trial", "sections": {"abstract": statement}}
    assert synthesis._aggregate_paper([], paper_meta=record)["effect_direction"] == "positive"
    for invalid in (
        statement.replace("significantly", "did not significantly"),
        "Previous studies reported that " + statement.lower(),
        statement.replace("significantly", "could significantly"),
        statement.replace("significantly", "slightly"),
    ):
        record["sections"]["abstract"] = invalid
        assert synthesis._aggregate_paper([], paper_meta=record)["effect_direction"] != "positive"


def test_claussen_outgoing_evidence_contains_the_actual_quoted_statistics(tmp_path):
    submission = importlib.import_module("scripts.publishing.submission")
    source = next(row for row in SOURCES if row["receipt"]["citation_token"] == "Claussen 2025")
    receipt = source["receipt"]
    (tmp_path / f"{receipt['receipt_id']}.paper_sections.json").write_text(json.dumps(source["record"]))
    old = submission._parsed_receipt_excerpt(tmp_path, receipt["receipt_id"], receipt)
    assert "β = 0.42" in old
    quote = "β = 0.42, 95% CI [0.19, 0.65]"
    selected = submission._parsed_receipt_excerpt(tmp_path, receipt["receipt_id"], receipt, (quote,))
    assert quote in selected
    assert selected == " ".join(source["record"]["sections"]["abstract"].split())
    assert "invented 99.99" not in submission._parsed_receipt_excerpt(tmp_path, receipt["receipt_id"], receipt, ("invented 99.99",))


def test_source_markers_cover_tables_and_remain_idempotent():
    paper = "## Quantitative Evidence Index\n| Study | Result |\n|---|---|\n| Example 2025 | β = 0.42 |\n## References\nExample 2025.\n"
    rows = [{"cited_as": "Example 2025"}]
    marked = attach_bundle_references(paper, rows)
    assert "| Example 2025 [bundle:1] |" in marked
    assert marked.endswith("## References\nExample 2025.")
    assert attach_bundle_references(marked, rows) == marked


def test_global_review_recode_preserves_identity_and_unrequested_fields():
    coverage = importlib.import_module("scripts.revision_coverage")
    rows = {"a": {"source_title": "Trial A"}, "b": {"source_title": "Trial B"}}
    feedback = "The source-level direction profile is materially mis-coded: favorable findings are unclear.\nDirectness coding is internally inconsistent and inflates the direct evidence count."
    assert coverage.authorized_receipt_contract_fields_by_receipt(feedback, rows) == {
        key: {"effect_direction", "directness"} for key in rows
    }
    assert coverage.authorized_receipt_contract_fields_by_receipt("Do not change the source-level direction profile.", rows) == {}
    assert coverage.authorized_receipt_contract_fields_by_receipt("Directness coding is consistent.", rows) == {}


@pytest.mark.parametrize("citation,expected", [("Salter 2024", "positive"), ("Hwang 2018", "mixed"), ("Claussen 2025", "positive"), ("Chen 2026", "mixed"), ("Longrak 2024", "positive")])
def test_actual_qualitative_outcomes_keep_favourable_and_null_findings(synthesis, citation, expected):
    source = next(row for row in SOURCES if row["receipt"]["citation_token"] == citation)
    claims = [c for c in source["claims"] if c["binding_confidence"] in {"high", "partial"}]
    assert synthesis._aggregate_paper(claims, paper_meta=source["record"])["effect_direction"] == expected


@pytest.mark.parametrize("target", ["resistance training", "metformin", "cognitive therapy"])
def test_combined_program_against_usual_care_does_not_isolate_one_component(target):
    title = f"Combined nutritional support and {target}: a randomized trial"
    abstract = f"Participants were randomized to intervention or control. The intervention received nutritional support and {target}. Controls maintained usual care."
    assert unisolated_combination(title, abstract, target)
    assert not unisolated_combination(title, abstract, f"nutritional support and {target}")
    assert not unisolated_combination(title, abstract.replace("intervention or control", f"{target}, nutritional support, or control"), target)


@pytest.mark.parametrize("target", ["resistance training", "metformin", "cognitive therapy"])
def test_comparison_of_adjuncts_cannot_prove_shared_intervention_effect(target):
    abstract = f"This randomized study investigated the effects of cooling compared to no cooling on performance during {target}."
    assert unisolated_combination("Randomized study", abstract, target)
    assert not unisolated_combination("Randomized study", abstract.replace("cooling compared to no cooling", f"{target} compared to placebo"), target)


def test_own_p_value_does_not_get_overruled_by_conflicting_qualitative_word(synthesis):
    record = {"sections": {"abstract": "Muscle strength significantly increased compared with control (p = 0.8)."}}
    assert synthesis._aggregate_paper([], paper_meta=record)["effect_direction"] == "unclear"


def test_favourable_nominal_results_and_null_secondary_outcomes_remain_separate(synthesis):
    source = next(row for row in SOURCES if row["receipt"]["citation_token"] == "Chen 2026")
    result = synthesis._aggregate_paper([], paper_meta=source["record"])
    endpoints = dict(result["endpoint_directions"])
    assert endpoints["fat mass"] == "positive"
    assert endpoints["muscle strength"] == "positive"
    assert endpoints["muscle hypertrophy"] == "null"
    assert result["effect_direction"] == "mixed"


@pytest.mark.parametrize("statement,expected", [
    ("Muscle strength showed significant increases compared with placebo.", "positive"),
    ("Fat mass showed significant reductions compared with placebo.", "positive"),
    ("Muscle area showed statistically significant increases after training.", "positive"),
    ("Muscle area changes were not statistically significant (p = 0.001).", "unclear"),
])
def test_nominal_outcome_phrases_and_conflicting_null_statement(synthesis, statement, expected):
    assert synthesis._aggregate_paper([], paper_meta={"sections": {"abstract": statement}})["effect_direction"] == expected


@pytest.mark.parametrize("statement,expected", [
    ("Thigh muscle mass significantly increased compared with control (p = 0.8).", "unclear"),
    ("Thigh muscle mass significantly increased compared with control (p = 0.001).", "positive"),
    ("Muscle strength significantly increased and fat mass decreased (p = 0.8).", "unclear"),
    ("Muscle strength increased in controls and muscle strength decreased in treatment (p = 0.01).", "unclear"),
])
def test_alias_overlap_and_multiple_comparisons_do_not_borrow_significance(synthesis, statement, expected):
    assert synthesis._aggregate_paper([], paper_meta={"sections": {"abstract": statement}})["effect_direction"] == expected


@pytest.mark.parametrize("reported,expected", [("p = 1.2e-5", "positive"), ("P_adjusted = 8e-1", "unclear"), ("p = 1", "unclear")])
def test_qualitative_significance_uses_shared_p_value_parser(synthesis, reported, expected):
    record = {"sections": {"abstract": f"Muscle strength significantly increased compared with control ({reported})."}}
    assert synthesis._aggregate_paper([], paper_meta=record)["effect_direction"] == expected


@pytest.mark.parametrize('citation,expected', [('Jacob 2025', 'positive'), ('Arroniz 2025', 'mixed'),
    ('Expanding Access to Strength 2025', 'mixed'), ('Zhang 2025', 'mixed')])
def test_remaining_source_profiles_keep_favorable_and_null_outcomes(synthesis, citation, expected):
    source = next(row for row in SOURCES if row['receipt']['citation_token'] == citation)
    claims = [c for c in source['claims'] if c.get('binding_confidence') in {'high', 'partial'}]
    assert synthesis._aggregate_paper(claims, paper_meta=source['record'])['effect_direction'] == expected


@pytest.mark.parametrize('topic,endpoint', [('metformin', 'blood glucose'), ('resistance_training', 'muscle strength')])
def test_markup_keeps_p_values_and_shared_null_outcomes(synthesis, topic, endpoint):
    synthesis._set_topic(topic)
    direction = 'decreased' if topic == 'metformin' else 'increased'
    record = {'title': 'Randomized intervention trial', 'sections': {'abstract':
        f'<jats:p>The intervention significantly {direction} {endpoint} (<jats:italic>p</jats:italic> < .05). '
        'No significant changes in body composition were observed.</jats:p>'}}
    result = synthesis._aggregate_paper([], paper_meta=record)
    assert result['effect_direction'] == 'mixed'
    assert ('body composition', 'null') in result['endpoint_directions']


@pytest.mark.parametrize('wording,expected', [('significantly improved', 'positive'),
    ('significantly increased', 'negative'), ('did not significantly improve', 'null')])
def test_improvement_does_not_invert_an_adverse_endpoint(synthesis, wording, expected):
    record = {'title': 'Randomized intervention trial', 'sections': {'abstract':
        f'The intervention {wording} frailty.'}}
    assert synthesis._aggregate_paper([], paper_meta=record)['effect_direction'] == expected


def test_demographic_balance_does_not_become_a_null_outcome(synthesis):
    record = {'title': 'Randomized intervention trial', 'sections': {'abstract':
        'There were no significant differences in age, sex, height and body weight among groups. '
        'Muscle strength significantly increased after the intervention.'}}
    result = synthesis._aggregate_paper([], paper_meta=record)
    assert result['effect_direction'] == 'positive'
    assert 'body weight' not in dict(result['endpoint_directions'])


def test_protocol_findings_do_not_publish_planned_followup_as_a_result():
    from agent.revision_quality import manifest_row_finding
    source = next(row for row in SOURCES if row['receipt']['citation_token'] == 'Kang 2025')
    row = {**source['receipt'], 'verified_source_sections':source['record']['sections']}
    assert '6–12 months' in str(row['source_result_excerpts'])
    assert '6–12 months' not in manifest_row_finding(row)


@pytest.mark.parametrize('label', ['receipt', 'source'])
def test_rendered_claim_count_is_metadata_but_effect_estimates_still_need_proof(label):
    from agent.qei_facts import untyped_table_cells_supported
    from agent.revision_quality import _EFFECT_STAT_RE
    header = ['source', 'finding']
    count = f'finding=6 extracted claim(s); {label}-level direction is the coded finding'
    assert untyped_table_cells_supported(['Smith 2020', count], header, '', _EFFECT_STAT_RE)
    assert not untyped_table_cells_supported(['Smith 2020', 'finding=6 participants improved'], header, '', _EFFECT_STAT_RE)


@pytest.mark.parametrize("citation,expected", [("Denben 2023", "mixed"), ("Kenville 2024", "mixed"), ("EVALUATION of ONLINE AEROBIC 2023", "positive")])
def test_remaining_live_profiles_use_source_defined_outcomes(synthesis, citation, expected):
    rows = json.loads((Path(__file__).parent / "fixtures/revision_remaining_profiles.json").read_text())
    row = next(r for r in rows if r["receipt"]["citation_token"] == citation)
    claims = [c for c in row["claims"] if c.get("binding_confidence") in {"high", "partial"}]
    before = json.dumps(row, sort_keys=True)
    result = synthesis._aggregate_paper(claims, paper_meta=row["record"])
    assert result["effect_direction"] == expected
    assert json.dumps(row, sort_keys=True) == before
    if citation == "Denben 2023":
        assert dict(result["endpoint_directions"])["cortisol"] == "unclear"
        assert dict(result["endpoint_directions"])["muscle strength"] == "null"
    if citation.startswith("EVALUATION"):
        assert dict(result["endpoint_directions"])["verbal learning score"] == "unclear"
        assert dict(result["endpoint_directions"])["ADAS-Cog score"] == "positive"


@pytest.mark.parametrize("endpoint,movement", [("blood glucose", "decreased"), ("muscle strength", "increased")])
def test_comparative_estimate_is_descriptive_and_never_supplies_significance(synthesis, endpoint, movement):
    text = f"The {endpoint} in the intervention group {movement} by 3 more than the control group."
    record = {"sections": {"abstract": text}}
    claims = synthesis._direction.source_outcome_claims(record)
    assert claims and not synthesis._direction._reports_significance(claims[0])
    assert claims[0]["source_p_value"] is None
    assert synthesis._aggregate_paper([], paper_meta=record)["effect_direction"] == "positive"
    for invalid in (text.replace("by 3", "by 0"), text.replace("by 3", "by -3"),
                    text.replace("more than the control group", "relative to baseline"),
                    text.replace("by 3", "by 3 (p = 0.8)"),
                    text.replace("by 3", "by 3 (95% CI -2 to 8)"),
                    text.replace(movement, "not " + movement)):
        assert synthesis._aggregate_paper([], paper_meta={"sections": {"abstract": invalid}})["effect_direction"] != "positive"


def test_endpoint_abbreviations_are_source_local_and_conflicts_fail_closed(synthesis):
    ed = synthesis._direction
    sentence = "The intervention resulted in less TR compared to placebo (p < .001)."
    assert ed.source_outcome_claims({"sections": {"abstract": sentence}}) == []
    definition = "We measured the total number of repetitions (TR). "
    rows = ed.source_outcome_claims({"sections": {"abstract": definition + sentence}})
    assert rows[0]["endpoint"] == "exercise repetitions"
    assert rows[0]["source_sentence"] == sentence
    conflicting = definition + "We also measured cortisol (TR). " + sentence
    assert ed._source_endpoint_aliases({"sections": {"abstract": conflicting}}) == {}


def test_real_receipt_builder_gives_writer_outcomes_without_extracted_statistics(synthesis, tmp_path, monkeypatch):
    from agent.paper_writer_builders import receipt_evidence_text
    rows = json.loads((Path(__file__).parent / 'fixtures/revision_remaining_profiles.json').read_text())
    row = next(r for r in rows if r['receipt']['citation_token'].startswith('EVALUATION'))
    rid = row['receipt']['receipt_id']
    quant, parsed = tmp_path / 'quant', tmp_path / 'parsed'
    quant.mkdir()
    parsed.mkdir()
    (quant / f'{rid}.quant_claims.json').write_text(json.dumps({'paper_id': rid, 'claims': row['claims']}))
    (parsed / f'{rid}.paper_sections.json').write_text(json.dumps(row['record']))
    monkeypatch.setattr(synthesis, 'QUANT_DIR', quant)
    monkeypatch.setattr(synthesis, 'PARSED_DIR', parsed)
    receipt, = synthesis.build_receipts_from_quant_claims('resistance_training', receipt_ids=frozenset({rid}),
        receipt_contracts={rid: row['receipt']}, authorized_contract_fields={rid: {'effect_direction'}})
    packet = receipt_evidence_text(receipt, 1800)
    assert 'resistance group decreased by1.43' in packet
    assert 'Stroop time interference in resistance group' in packet
    assert 'p = 0.065' in packet
    assert receipt.n_claims == row['receipt']['n_claims']
    assert tuple(receipt.p_values) == tuple(row['receipt']['p_values'])


@pytest.mark.parametrize("direction,prefix", [
    ("positive", "Positive signals appear in: "),
    ("negative", "Negative signals appear in: "),
    ("null", "Null findings are recorded in: "),
])
def test_thesis_reports_every_recorded_outcome_class(synthesis, direction, prefix):
    from agent.synthesis_schemas import ReceiptSummary, TensionMatrix
    outcomes = ["muscle_function", "muscle_function", "contextual_other", "contextual_other", "cognitive_function"]
    receipts = [ReceiptSummary(str(i), "", "resistance_training", "Source finding", "accept_clean", 1, 0,
        None, "A1", "direct", outcome, direction, (), "Adults") for i, outcome in enumerate(outcomes)]
    matrix = TensionMatrix(tuple(receipts), ())
    thesis = synthesis.build_thesis(receipts, matrix, topic="resistance_training")
    clause = thesis.text.split(prefix)[1].split(".")[0]
    assert clause == "muscle function, contextual other, cognitive function"
    assert len(thesis.receipt_ids_referenced) == len(receipts)
