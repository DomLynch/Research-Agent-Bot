import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent import prose_grounding as grounding
from agent.revision_evidence import create_revision_evidence_snapshot
from publishing import submission

CLAIM = "Resveratrol reduced fasting glycaemia in older adults, while the comparator was placebo [Smith 2020]."


@pytest.fixture
def run(tmp_path):
    quant, parsed, run = (tmp_path / name for name in ("quant", "parsed", "run"))
    for path in (quant, parsed, run):
        path.mkdir()
    (parsed / "trial.paper_sections.json").write_text(json.dumps({"paper_id": "trial", "title": "Resveratrol trial",
        "sections": {"abstract": "Resveratrol reduced fasting glucose in older adults compared with placebo.",
                     "results": "Resveratrol reduced fasting glucose by 12% compared with placebo."}}))
    (quant / "trial.quant_claims.json").write_text(json.dumps({"paper_id": "trial", "claims": []}))
    contracts = [{"receipt_id": "trial", "topic": "resveratrol", "n_claims": 1,
                  "source_doi": "10.1234/trial", "evidence_tier": "A1", "directness": "direct"}]
    registry = run / "citation_registry.json"
    registry.write_text(json.dumps({"trial": {"receipt_id": "trial", "body_citation": "Smith 2020", "source_doi": "10.1234/trial"}}))
    assert create_revision_evidence_snapshot(run, quant_dir=quant, parsed_dir=parsed, citation_registry=registry,
        receipt_ids=["trial"], receipt_contracts=contracts, topic="resveratrol")["passed"]
    (run / "manifest.json").write_text(json.dumps({"topic": "resveratrol", "receipts": contracts, "n_receipts": 1}))
    (run / "full_paper.md").write_text(f"# Resveratrol findings\n\n## Abstract\n\n{CLAIM}\n\n## Conclusion\n\n{CLAIM}\n")
    return run


def install_judge(monkeypatch, *, supported=True):
    calls = []
    async def judge(**kwargs):
        calls.append(kwargs)
        statements = json.loads(kwargs["messages"][1]["content"])["statements"]
        return SimpleNamespace(model="configured-reviewer", parsed={"assessments": [
            {"row": i, "supported": supported, "reason": "Source comparison checked."} for i in range(len(statements))]})
    monkeypatch.setattr(grounding, "chat_json", judge)
    monkeypatch.setattr(grounding, "build_judge_chain", lambda _: ["configured-reviewer"])
    return calls


def test_review_omits_blank_lines_but_keeps_short_unsupported_claims(run, monkeypatch):
    paper = run / "full_paper.md"
    paper.write_text(paper.read_text().replace("## Abstract\n\n", "## Abstract\n\n \t\nMortality decreased.\n\n"))
    calls = install_judge(monkeypatch, supported=False)
    asyncio.run(grounding.review_manuscript(run))
    reviewed = [row for call in calls for row in json.loads(call["messages"][1]["content"])["statements"]]
    assert all(row["text"].strip() for row in reviewed)
    assert "Mortality decreased." in {row["text"] for row in reviewed}
    with grounding.grounding_context(run):
        assert not grounding.approved("Mortality decreased.", grounding._verified_bundle(run), set())


@pytest.mark.parametrize("supported", [True, False])
def test_findings_map_labels_require_review_of_the_displayed_row(run, monkeypatch, supported):
    paper = run / "full_paper.md"
    table = (
        "\n## Evidence Landscape\n\n### Findings Map\n\n"
        "| Evidence domain | Source | Direction | Directness | Tier | Evidence role | Finding |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| Cardiometabolic | Smith 2020 [bundle:1] | positive | direct | A1 | clinical | "
        "Resveratrol reduced fasting glucose in older adults compared with placebo. |\n"
    )
    paper.write_text(paper.read_text() + table)
    seen = []
    async def judge(**kwargs):
        entries = json.loads(kwargs["messages"][1]["content"])["statements"]
        seen.extend(entries)
        return SimpleNamespace(model="configured-reviewer", parsed={"assessments": [
            {"row": i, "supported": supported if "Direction:" in entry["text"] else True,
             "reason": "Checked displayed finding, treatment comparison and labels."}
            for i, entry in enumerate(entries)]})
    monkeypatch.setattr(grounding, "chat_json", judge)
    asyncio.run(grounding.review_manuscript(run))
    reviewed = [row for row in seen if "Direction:" in row["text"]]
    assert len(reviewed) == 1
    assert reviewed[0]["sources"] == [0]
    assert all(value in reviewed[0]["text"] for value in ("Direction: positive", "Directness: direct", "older adults", "placebo"))
    bundle = grounding._verified_bundle(run)
    payload = {"body_markdown": paper.read_text()}
    with grounding.grounding_context(run):
        status = submission._researka_core_claim_trace_status(payload, bundle)
        assert (status == "eligible") is supported
        if supported:
            payload["body_markdown"] = payload["body_markdown"].replace("| positive |", "| negative |")
            assert submission._researka_core_claim_trace_status(payload, bundle) == "researka_core_claims_unresolved:findings_map_labels_unverified"


@pytest.mark.parametrize("supported", [True, False])
def test_final_review_refreshes_approval_before_freezing_package(run, monkeypatch, supported):
    import run_v06_synthesis as pipeline
    install_judge(monkeypatch, supported=supported)
    (run / "full_paper.final_verdict.json").write_text('{"verdict":"L5"}')
    frozen = []
    def freeze(path, verdict):
        with grounding.grounding_context(path):
            frozen.append((verdict, grounding.approved(CLAIM, grounding._verified_bundle(path), {0})))
    monkeypatch.setattr(submission, "freeze_submission_package", freeze)
    asyncio.run(pipeline._review_final_source_claims(run, {"gate": SimpleNamespace(passed=True)}))
    assert frozen == [({"verdict": "L5"}, supported)]


def test_reviewed_paraphrase_survives_cleanup_payload_and_context_reset(run, monkeypatch):
    calls = install_judge(monkeypatch)
    bundle = grounding._verified_bundle(run)
    assert not submission._cited_claim_aligns(CLAIM, bundle, {0})
    asyncio.run(grounding.review_manuscript(run))
    assert calls[0]["chain"] == ["configured-reviewer"]
    with grounding.grounding_context(run):
        assert submission._cited_claim_aligns(CLAIM, bundle, {0})
        assert CLAIM in submission._attach_aligned_claim_references("## Conclusion\n\n" + CLAIM, bundle)
    assert not grounding.approved(CLAIM, bundle, {0})
    submission.prepare_submission_manuscript(run, enrich_sources=False)
    payload = submission.build_payload(run, enrich_sources=False)
    assert "reduced fasting glycaemia" in payload["body_markdown"]
    assert payload["core_claims_resolved"] is True
    assert "prose_grounding" not in json.dumps(payload)
    assert not grounding.approved(CLAIM, bundle, {0})


@pytest.mark.parametrize("change", ["number", "direction", "citation", "source", "body", "new_topic"])
def test_text_citation_source_or_topic_changes_cannot_borrow_review(run, monkeypatch, tmp_path, change):
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    claim = CLAIM
    if change == "number":
        claim = claim.replace("reduced", "reduced by 12%")
    elif change == "direction":
        claim = claim.replace("reduced", "increased")
    elif change == "citation":
        claim = claim.replace("Smith 2020", "Jones 2021")
    elif change == "source":
        bundle[0]["excerpt"] += " Correction: the result was null."
    elif change == "body":
        claim = claim.replace("older adults", "children")
    with grounding.grounding_context(tmp_path if change == "new_topic" else run):
        assert not grounding.approved(claim, bundle, {0})


@pytest.mark.parametrize("locator,expected", [("https://doi.org/10.1234/trial", True), ("https://doi.org/10.1234/TRIAL", True), ("https://doi.org/10.1234/other", False), ("https://doi.org/10.1234/OTHER", False)])
def test_generated_locator_preserves_only_the_same_reviewed_source(run, monkeypatch, locator, expected):
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    rendered = CLAIM[:-1] + f" [bundle:1] [exact source: {locator}]."
    with grounding.grounding_context(run):
        assert grounding.approved(rendered, bundle, {0}) is expected
        assert not grounding.approved(rendered.replace("reduced", "increased"), bundle, {0})
        assert not grounding.approved(rendered.replace("Resveratrol", "RESVERATROL"), bundle, {0})
        assert not grounding.approved(rendered, bundle, set())


def test_negative_review_and_corrupted_snapshot_fail_closed(run, monkeypatch):
    calls = install_judge(monkeypatch, supported=False)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert not grounding.approved(CLAIM, bundle, {0})
    assert len(calls) == 1
    (run / "revision_evidence_snapshot/parsed/trial.paper_sections.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot_unverified"):
        with grounding.grounding_context(run):
            pass


def test_changed_review_policy_invalidates_cached_support(run, monkeypatch):
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    monkeypatch.setattr(grounding, "_PROMPT", grounding._PROMPT + " New review requirement.")
    with grounding.grounding_context(run):
        assert not grounding.approved(CLAIM, bundle, {0})


@pytest.mark.parametrize("question_field", ["thesis", "research_question"])
def test_own_question_uses_run_records_without_external_attribution(run, monkeypatch, question_field):
    own = "This map compares how population and endpoint differences limit interpretation of the supplied records."
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["thesis"] = "Earlier integrating thesis."
    manifest[question_field] = own
    (run / "manifest.json").write_text(json.dumps(manifest))
    paper = run / "full_paper.md"
    paper.write_text(paper.read_text().replace("## Abstract\n\n", "## Abstract\n\n" + own + "\n\n"))
    calls = install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    supplied = json.loads(calls[0]["messages"][1]["content"])
    assert supplied["sources"]["author_context"]["source_count"] == 1
    assert supplied["sources"]["author_context"]["question"] == own
    submission.prepare_submission_manuscript(run, enrich_sources=False)
    payload = submission.build_payload(run, enrich_sources=False)
    assert own + "\n" in payload["body_markdown"]
    assert payload["core_claims_resolved"] is True
    assert "author_context" not in json.dumps(payload)
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert grounding.approved(own, bundle, set())
        altered = deepcopy(bundle)
        altered[0]["excerpt"] = "Different evidence."
        assert not grounding.approved(own, altered, set())
    manifest[question_field] = "A different analytic question."
    (run / "manifest.json").write_text(json.dumps(manifest))
    with grounding.grounding_context(run):
        assert not grounding.approved(own, bundle, set())
    manifest[question_field] = own
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "methods_pack.json").write_text(json.dumps({"search_dates": "Changed methods record"}))
    with grounding.grounding_context(run):
        assert not grounding.approved(own, bundle, set())


def test_author_wording_cannot_bypass_negative_scientific_review(run, monkeypatch):
    claim = "This map found that resveratrol prevented mortality in all older adults without uncertainty."
    paper = run / "full_paper.md"
    paper.write_text(paper.read_text().replace(CLAIM, claim))
    install_judge(monkeypatch, supported=False)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert not submission._cited_claim_aligns(claim, bundle, set())


@pytest.mark.parametrize("assessments", [[], [{"row": 0, "supported": "true", "reason": "yes"}],
    [{"row": 1, "supported": True, "reason": "yes"}], [{"row": 0, "supported": True, "reason": ""}],
    [{"row": 0, "supported": True, "reason": "yes"}] * 2])
def test_malformed_review_cannot_certify_prose(monkeypatch, assessments):
    async def judge(**kwargs):
        return SimpleNamespace(model="reviewer", parsed={"assessments": deepcopy(assessments)})
    monkeypatch.setattr(grounding, "chat_json", judge)
    with pytest.raises(ValueError, match="prose_semantic_review_invalid"):
        asyncio.run(grounding.review_statements([{"text": CLAIM}], []))


def test_curated_map_keeps_full_length_policy():
    from agent.review_type import COMPACT_REVIEW_TYPES, formal_appraisal_required, parse_review_type
    from agent.publishing.policy import publication_surface
    assert parse_review_type("curated_evidence_map") == "curated_evidence_map"
    assert "curated_evidence_map" not in COMPACT_REVIEW_TYPES
    assert not formal_appraisal_required("curated_evidence_map")
    assert publication_surface("curated_evidence_map") == publication_surface("prisma_scr_scoping_synthesis")


@pytest.mark.parametrize("altered", [False, True])
def test_payload_exports_the_verified_section_containing_its_findings_map_quote(run, altered):
    from agent.publication_evidence import source_proof_is_valid
    finding = "Resveratrol reduced fasting glucose by 12% compared with placebo."
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["receipts"][0]["source_result_excerpts"] = [finding.replace("12%", "13%") if altered else finding]
    (run / "manifest.json").write_text(json.dumps(manifest))
    bundle = submission._source_bundle(run, limit=37, enrich=False)
    assert len(bundle) == 1 and source_proof_is_valid(bundle[0])
    assert (finding in bundle[0]["excerpt"]) is (not altered)
    paper = "### Findings Map\n\n| Source | Finding |\n|---|---|\n| Smith 2020 | finding=" + finding + " |\n"
    status = submission._researka_quantitative_trace_status({"body_markdown": paper}, bundle)
    assert (status == "eligible") is (not altered)


def test_preparation_reviews_uncited_scope_before_cleanup(run, monkeypatch):
    scope = "Background: We asked what intervention findings show and how populations and comparators constrain their interpretation across outcome classes."
    paper = run / "full_paper.md"
    paper.write_text(paper.read_text().replace("## Abstract\n\n", "## Abstract\n\n" + scope + "\n\n"))
    calls = install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    reviewed = json.loads(calls[0]["messages"][1]["content"])["statements"]
    assert scope in {row["text"] for row in reviewed}
    submission.prepare_submission_manuscript(run, enrich_sources=False)
    assert scope in paper.read_text()


def test_prose_review_includes_sources_without_numeric_abstract_results(run, monkeypatch):
    # This source has only qualitative abstract results, so QEI omits it.
    from agent.qei_facts import source_entries
    assert source_entries(run, "resveratrol", {"trial": "Smith 2020"}) == []
    calls = install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    sources = json.loads(calls[0]["messages"][1]["content"])["sources"]
    rows = sources["own_results"]
    assert len(rows) == 1
    assert rows[0]["receipt_id"] == "trial"
    assert rows[0]["citation_token"] == "Smith 2020"
    assert rows[0]["verified_source_sections"]["abstract"] == "Resveratrol reduced fasting glucose in older adults compared with placebo."
    assert "12%" in rows[0]["verified_source_sections"]["results"]


@pytest.mark.parametrize('label', ['admitted', 'retained', 'included', 'curated reference'])
def test_method_source_counts_are_not_external_effect_statistics(label):
    text = f'Methods: We produced a curated evidence map of 19 {label} sources without pooling effects.'
    assert submission._quantitative_claim_candidates(text) == []
    assert submission._quantity_tokens(f'We studied 19 {label} patients.') == {('19', '')}
    effect = text + ' The intervention improved outcomes by 19%.'
    assert submission._quantity_tokens(effect) == {('19', '%')}


def test_incorrect_author_count_cannot_borrow_a_positive_prose_review(run, monkeypatch):
    text = 'Methods: We produced a curated evidence map of 1 admitted source without pooling effects.'
    paper = run / 'full_paper.md'
    paper.write_text(paper.read_text().replace('## Abstract\n\n', '## Abstract\n\n' + text + '\n\n'))
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert grounding.approved(text, bundle, set())
        assert not grounding.approved(text.replace('1 admitted', '19 admitted'), bundle, set())


@pytest.mark.parametrize("verb", ["reassessed", "examined", "evaluated"])
def test_uncited_methods_count_uses_current_author_record_review(run, monkeypatch, verb):
    text = f"Methods: This curated evidence map {verb} 1 frozen source, requiring bound claims; historical screening was not reconstructed and no pooling was performed."
    (run / "full_paper.md").write_text("## Abstract\n\n" + text)
    bundle = grounding._verified_bundle(run)
    payload = {"abstract": text}
    assert submission._quantitative_claim_candidates(text) == [text]
    assert submission._researka_quantitative_trace_status(payload, bundle) != "eligible"
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    with grounding.grounding_context(run):
        assert submission._researka_quantitative_trace_status(payload, bundle) == "eligible"
        assert submission._researka_quantitative_trace_status({"abstract": text.replace("1 frozen", "19 frozen")}, bundle) != "eligible"
    (run / "methods_pack.json").write_text(json.dumps({"selection": "changed"}))
    with grounding.grounding_context(run):
        assert submission._researka_quantitative_trace_status(payload, bundle) != "eligible"


@pytest.mark.parametrize("citation", ["", " [Smith 2020]"])
def test_prose_approval_does_not_replace_source_support_for_effect_numbers(run, monkeypatch, citation):
    claim = "This review found that treatment reduced mortality by 99%" + citation + "."
    (run / "full_paper.md").write_text("## Abstract\n\n" + claim)
    install_judge(monkeypatch)
    asyncio.run(grounding.review_manuscript(run))
    bundle = grounding._verified_bundle(run)
    with grounding.grounding_context(run):
        assert grounding.approved(claim, bundle, submission._citation_indexes(claim, bundle))
        assert submission._researka_quantitative_trace_status({"abstract": claim}, bundle) != "eligible"


@pytest.mark.parametrize("gap", ["", " ", "  "])
def test_adjacent_reviewed_citations_survive_real_bundle_rendering(gap):
    from agent.publication_evidence import attach_bundle_references
    bundle = [{"cited_as": "Smith 2020", "doi": "10.1234/first"},
              {"cited_as": "Jones 2021", "doi": "10.1234/second"}]
    claim = f"Conclusions: The populations and endpoints limit comparison [Smith 2020]{gap}[Jones 2021]."
    rendered = attach_bundle_references(claim, bundle)
    assert "[bundle:1]" in rendered and "[bundle:2]" in rendered
    key = grounding.claim_key(claim, bundle, {0, 1})
    token = grounding._APPROVED.set(frozenset({key}))
    try:
        assert grounding.approved(rendered, bundle, {0, 1})
        kept = submission._attach_aligned_claim_references("## Abstract\n\n" + rendered, bundle)
        assert "The populations and endpoints limit comparison" in kept
        assert not grounding.approved(rendered.replace("limit", "permit"), bundle, {0, 1})
        assert not grounding.approved(rendered.replace("Jones 2021", "Jones 2022"), bundle, {0, 1})
        assert not grounding.approved(rendered, bundle, {0})
        assert not grounding.approved(rendered.replace("[Smith 2020]", "").replace("populations", "populations [Smith 2020]"), bundle, {0, 1})
    finally:
        grounding._APPROVED.reset(token)


@pytest.mark.parametrize("statement,blocked", [
    ("This is a curated evidence map, not a systematic scoping review or pooled analysis.", False),
    ("We conducted no systematic review.", False),
    ("This is a narrative review, not a meta-analysis.", False),
    ("This is a systematic scoping review, not a curated map.", True),
    ("We conducted not only a systematic review but also an evidence map.", True),
    ("This is a curated map, not a systematic review; we performed a meta-analysis.", True),
    ("We conducted no systematic review initially; this is a systematic review now.", True),
])
def test_negated_method_names_do_not_create_or_hide_self_claims(statement, blocked):
    from agent.review_type import review_type_overclaim_issue_messages
    assert bool(review_type_overclaim_issue_messages(statement, "", "curated_evidence_map")) is blocked


@pytest.mark.parametrize("alteration", [None, "number", "operator", "endpoint", "comparator"])
def test_findings_map_decimal_layout_preserves_exact_numeric_context(alteration):
    from agent.revision_quality import _statistics_are_source_bound
    source = "For side lunge, the training versus control difference was 9.24 W (95% CI 2.99-15.49 W; P <.01)."
    rendered = source.replace("P <.01", "P < 0.01")
    if alteration == "number":
        rendered = rendered.replace("9.24", "9.25")
    elif alteration == "operator":
        rendered = rendered.replace("P <", "P >")
    elif alteration == "endpoint":
        rendered = rendered.replace("side lunge", "forward lunge")
    elif alteration == "comparator":
        rendered = rendered.replace("training versus control", "training versus supplement")
    rows = [{"cited_as": "Smith 2020", "thesis_text": source}]
    paper = "### Findings Map\n\n| Source | Finding |\n|---|---|\n| Smith 2020 [bundle:1] | finding=" + rendered + " |\n"
    assert _statistics_are_source_bound(paper, rows, tables_only=True) is (alteration is None)


def test_evidence_snapshot_numeric_claims_are_reviewed(run, monkeypatch):
    paper = run / "full_paper.md"
    paper.write_text(paper.read_text() + "\n## Evidence Snapshot\n\nA representative result was P = 0.01.\n")
    calls = install_judge(monkeypatch, supported=False)
    asyncio.run(grounding.review_manuscript(run))
    reviewed = [row["text"] for call in calls for row in json.loads(call["messages"][1]["content"])["statements"]]
    assert "A representative result was P = 0.01." in reviewed
