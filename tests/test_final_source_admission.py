"""Final-record invariants across intervention, drug and preclinical corpora."""
import importlib
import json
from copy import deepcopy

import pytest

from agent.publication_evidence import attach_bundle_references, ordered_source_rows
from agent.revision_contract import final_source_integrity
from agent.selection_flow import render_admission
from journal_finalizer import _findings_map_section, _phase_d_proactive_findings_map
import source_admission


@pytest.fixture(params=[
    ("resistance_training", "muscle_function", "direct", "A1"),
    ("metformin", "cardiometabolic", "indirect", "B1"),
    ("resveratrol", "mechanistic", "mechanistic", "C1"),
])
def corpus(request):
    topic, outcome, directness, tier = request.param
    rows = [{"receipt_id": f"Study_{n}", "citation_token": f"Study{n} 2025", "source_title": f"{topic} study {n}",
             "source_year": 2025, "outcome_class": outcome, "effect_direction": "positive" if n == 1 else "unclear",
             "directness": directness if n == 1 else "protocol", "evidence_tier": tier if n == 1 else "D1", "n_claims": 1}
            for n in (1, 2)]
    log = source_admission.start(topic, frozenset())
    for row in rows:
        source_admission.record(log, row["receipt_id"], "topic_eligible_with_bound_claims", included=True)
    source_admission.record(log, "excluded_candidate", "no_admissible_bound_claims")
    paper = "## Methods\n\n" + render_admission(log) + "\n\n## Evidence Landscape\n\n" + _findings_map_section(rows)
    return rows, log, attach_bundle_references(paper, ordered_source_rows(rows))


def save_run(tmp_path, corpus):
    rows, log, paper = corpus
    for name, value in {"manifest.json": {"receipts": rows, "receipt_funnel": {"source_admission": log}},
                        "source_admission.json": log, "methods_pack.json": {"source_admission": log},
                        "full_paper.final_verdict.json": {"passed": True}}.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "full_paper.md").write_text(paper)
    return paper


@pytest.mark.parametrize("mutation", ["missing_source", "blank_classification", "wrong_total", "wrong_classification", "wrong_bundle", "protocol_outcomes", "duplicate_source"])
def test_final_structural_mutations_block_every_topic(corpus, tmp_path, mutation):
    rows, _, paper = corpus
    save_run(tmp_path, corpus)
    assert final_source_integrity(paper, rows)
    assert source_admission.check(tmp_path, paper) == "eligible"
    lines = paper.splitlines()
    target = next(line for line in lines if "| direction=" in line)
    if mutation == "missing_source":
        paper = paper.replace(target, "")
    elif mutation == "blank_classification":
        cells = target.split("|")
        cells[4] = " "
        paper = paper.replace(target, "|".join(cells))
    elif mutation == "wrong_total":
        paper = paper.replace("n=2", "n=99")
    elif mutation == "wrong_classification":
        paper = paper.replace(target, target.replace("direction=positive", "direction=null"))
    elif mutation == "wrong_bundle":
        paper = paper.replace(target, target.replace("[bundle:1]", "[bundle:99]"))
    elif mutation == "protocol_outcomes":
        paper = paper.replace("Planned research only; no completed outcomes reported.", "Mortality was reduced.")
    else:
        paper += "\n" + target
    assert not final_source_integrity(paper, rows)
    assert source_admission.check(tmp_path, paper) != "eligible"


def test_repair_restores_complete_table_without_specific_reviewer_ask(corpus, tmp_path):
    rows, _, paper = corpus
    save_run(tmp_path, corpus)
    broken = "\n".join(line for line in paper.splitlines() if "| direction=" not in line)
    fixed, log = _phase_d_proactive_findings_map(broken, tmp_path)
    assert log and final_source_integrity(fixed, rows)
    assert _phase_d_proactive_findings_map(fixed, tmp_path) == (fixed, [])


@pytest.mark.parametrize("mutation", ["paper", "classification", "admission", "missing_ledger"])
def test_post_approval_mutations_cannot_reach_transport(corpus, tmp_path, monkeypatch, mutation):
    daily = importlib.import_module("scripts.publishing.submission")
    paper = save_run(tmp_path, corpus)
    payload = {"body_markdown": paper, "metadata": {}}
    monkeypatch.setattr(daily, "build_payload", lambda *_a, **_kw: payload)
    daily.freeze_submission_package(tmp_path, {"passed": True})
    assert daily._frozen_package_status(tmp_path, payload) == "eligible"
    if mutation == "paper":
        (tmp_path / "full_paper.md").write_text(paper + "\nAn edit after approval.")
    elif mutation == "missing_ledger":
        (tmp_path / "source_admission.json").unlink()
    else:
        path = tmp_path / ("manifest.json" if mutation == "classification" else "source_admission.json")
        changed = json.loads(path.read_text())
        if mutation == "classification":
            changed["receipts"][0]["directness"] = "review"
        else:
            changed["decisions"]["Study_1"]["reason"] = "changed_reason"
        path.write_text(json.dumps(changed))
    assert daily._frozen_package_status(tmp_path, payload) != "eligible"


def test_admission_methods_and_source_membership_are_not_inferred(corpus, tmp_path):
    rows, log, paper = deepcopy(corpus)
    save_run(tmp_path, corpus)
    assert "Assessed 3 candidate sources; included 2; excluded 1" in render_admission(log)
    log["decisions"].pop("Study_1")
    assert not source_admission.validate(log, rows)
    assert source_admission.check(tmp_path, paper.replace("included 2", "included 3")) == "source_admission_methods_mismatch"


def test_dated_admission_history_survives_prose_deduplication(corpus, tmp_path):
    from review_noise_control import _dedupe_repeated_blocks
    from journal_finalizer import _phase_m_strip_surface_duplicate_paragraphs
    rows, log, original = deepcopy(corpus)
    previous = render_admission(log)
    for day in ("2026-09-12", "2026-09-13"):
        log = {**source_admission.start(log["topic"], frozenset(row["receipt_id"] for row in rows)), "assessed_at": day,
               "selection_assessment": deepcopy(log),
               "decisions": {key: row for key, row in log["decisions"].items() if row["included"]}}
    expected = render_admission(log)
    assert "dated 2026-09-12," not in expected
    assert log["selection_assessment"]["assessed_at"] == "2026-09-12"
    assert previous in expected
    paper = original.replace(previous, expected)
    revised, removed = _dedupe_repeated_blocks(paper)
    assert revised == paper
    assert removed == 0
    assert _dedupe_repeated_blocks(revised) == (revised, 0)
    assert _phase_m_strip_surface_duplicate_paragraphs(revised) == (revised, [])
    save_run(tmp_path, (rows, log, paper))
    assert source_admission.check(tmp_path, revised) == "eligible"
    assert source_admission.check(tmp_path, revised.replace("2026-09-13", "2026-09-14")) == "source_admission_methods_mismatch"


def test_readable_notation_preserves_source_numbers_and_rejects_mutations():
    from quant_claim_extract import readable_source_notation
    from agent.publication_evidence import exact_source_quote
    tex = r'\documentclass[12pt]{minimal} \usepackage{amsmath} \begin{document}$$\:{\eta\:}_{p}^{2}$$\end{document}'
    raw = 'The group interaction had ' + tex + ' = 0.08 and <jats:italic>P</jats:italic> = 0.039.'
    rendered = readable_source_notation(raw)
    assert rendered == 'The group interaction had ηₚ² = 0.08 and P = 0.039.'
    assert readable_source_notation(rendered) == rendered
    assert exact_source_quote(rendered, raw)
    assert not exact_source_quote(rendered.replace('0.08', '0.80'), raw)
    assert not exact_source_quote(rendered.replace('P =', 'P >'), raw)
    unknown = tex.replace(r'\eta', r'\unknown')
    assert readable_source_notation(unknown) == unknown


def test_dated_reassessment_cannot_silently_change_the_frozen_corpus(corpus, tmp_path):
    from types import SimpleNamespace
    rows, _, _ = corpus
    source = tmp_path / 'prior'
    source.mkdir()
    lock = SimpleNamespace(errors=[], source_run=source, receipt_ids=frozenset(r['receipt_id'] for r in rows))
    def assess(topic, admission_log):
        source_admission.record(admission_log, 'different_source', 'topic_eligible_with_bound_claims', included=True)
        return []
    with pytest.raises(ValueError, match='changes_included_set'):
        source_admission.prepare_reassessment('topic', lock, tmp_path / 'revision', assess)
    assert not (source / 'source_admission.json').exists()


def test_authorized_exclusion_preserves_assessment_and_passes_final_gate(corpus, tmp_path):
    from types import SimpleNamespace
    from agent.revision_evidence import RevisionEvidenceLock
    from run_v06_synthesis import _without_reviewer_unavailable_sources
    rows, prior, _ = deepcopy(corpus)
    rows[1]["source_doi"] = "10.1234/unavailable"
    source, revision = tmp_path / "prior", tmp_path / "revision"
    source.mkdir()
    prior_path = source / "source_admission.json"
    prior_path.write_text(json.dumps(prior))
    original = prior_path.read_bytes()
    rows[1]["thesis_text"] = "Source evidence authority unavailable: 10.1234/unavailable"
    lock = RevisionEvidenceLock(source, {r["receipt_id"]: r for r in rows}, source, source, None, "snapshot")
    assert _without_reviewer_unavailable_sources(lock, "")[0].receipt_ids == lock.receipt_ids
    reduced, _ = _without_reviewer_unavailable_sources(lock, "Source evidence authority unavailable: 10.1234/unavailable")
    excluded = lock.receipt_ids - reduced.receipt_ids
    source_admission.prepare_reassessment("topic", reduced, revision, None, excluded_receipt_ids=excluded)
    retained = list(reduced.receipt_rows.values())
    current = source_admission.start("topic", reduced.receipt_ids)
    for row in retained:
        source_admission.record(current, row["receipt_id"], "high_confidence_bound_claims", included=True)
    source_admission.finish(current, [SimpleNamespace(**r) for r in retained], {}, revision, excluded_receipt_ids=excluded)
    paper = "## Methods\n\n" + render_admission(current) + "\n\n" + _findings_map_section(retained)
    paper = attach_bundle_references(paper, ordered_source_rows(retained))
    save_run(revision, (retained, current, paper))
    assert source_admission.check(revision, paper) == "eligible"
    assert prior_path.read_bytes() == original
    assert current["selection_assessment"] == prior
    assert current["reviewer_excluded_source_ids"] == sorted(excluded)
    # A later unchanged revision must preserve and validate the entire history.
    later = RevisionEvidenceLock(revision, reduced.receipt_rows, revision, revision, None, "snapshot")
    source_admission.prepare_reassessment("topic", later, tmp_path / "later", None)
    assert json.loads((tmp_path / "later/source_selection_assessment.json").read_text()) == current
    del current["reviewer_excluded_source_ids"]
    save_run(revision, (retained, current, paper))
    assert source_admission.check(revision, paper) == "source_admission_unverified"
    for invalid in (["extra"], ["Study_2", "Study_2"], ["Study_1"], "Study_2", [None]):
        current["reviewer_excluded_source_ids"] = invalid
        save_run(revision, (retained, current, paper))
        assert source_admission.check(revision, paper) == "source_admission_unverified"


@pytest.mark.parametrize("retained,excluded", [({"Study_1"}, set()), ({"Study_1", "extra"}, {"Study_2"}),
    ({"Study_1"}, {"Study_2", "extra"}), ({"Study_1", "Study_2"}, {"Study_2"})])
def test_reassessment_rejects_unauthorized_membership(corpus, tmp_path, retained, excluded):
    from types import SimpleNamespace
    _, prior, _ = corpus
    prior["reviewer_excluded_source_ids"] = ["Study_2"]  # A source ledger cannot authorize removal.
    (tmp_path / "source_admission.json").write_text(json.dumps(prior))
    lock = SimpleNamespace(errors=[], source_run=tmp_path, receipt_ids=frozenset(retained))
    with pytest.raises(ValueError, match="changes_included_set"):
        source_admission.prepare_reassessment("topic", lock, tmp_path / "out", None, excluded_receipt_ids=frozenset(excluded))
    assert not (tmp_path / "out/source_selection_assessment.json").exists()


def test_render_repair_surface_contract_converges_for_every_topic(corpus, tmp_path):
    from agent.journal_surface_gate import evaluate_journal_surface
    from journal_finalizer import _phase_m_relabel_public_metadata_table_headers
    rows, admission, paper = corpus
    save_run(tmp_path, corpus)
    assert "| Dated source eligibility assessment | 3 | 1 | 2 |" in paper
    for _ in range(2):
        paper, _ = _phase_m_relabel_public_metadata_table_headers(paper, tmp_path)
        paper, _ = _phase_d_proactive_findings_map(paper, tmp_path)
        assert final_source_integrity(paper, rows)
        assert source_admission.check(tmp_path, paper) == "eligible"
        issues = evaluate_journal_surface(paper).issues
        assert not any("classification metadata leaked" in i.detail or "source_admission" in i.detail for i in issues)
        assert "| Evidence domain | Source |" in paper
    assert _phase_d_proactive_findings_map(paper, tmp_path) == (paper, [])
    assert render_admission(admission) in paper
    # A public table is still linted: generated headers do not exempt its contents.
    bad = paper.replace("Planned research only; no completed outcomes reported.", "source_admission leaked_internal_slug")
    assert any(i.code == "topic_slug_artifact" for i in evaluate_journal_surface(bad).issues)
