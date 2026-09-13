import asyncio
import json
from types import SimpleNamespace

import pytest

from agent import prose_grounding
import final_reviewer
from scripts import review_batches as batches


def test_batch_limits_and_stable_original_source_indexes(monkeypatch):
    monkeypatch.setattr(batches, 'MAX_REVIEW_CHARS', 6000)
    sources = {'bundle': [{'cited_as': f'Study {i}', 'excerpt': 'evidence ' * 200} for i in range(9)],
               'own_results': [{'citation_token': f'Study {i}', 'verified_source_sections': {'results': f'Contradiction {i}'}} for i in range(9)],
               'author_context': {'source_count': 9}}
    statements = [{'text': f'Claim {i}', 'sources': [8-i]} for i in range(9)]
    calls = []
    async def call(**kw):
        assert sum(len(m['content']) for m in kw['messages']) <= 6000
        packet = json.loads(kw['messages'][1]['content'])
        calls.append(packet)
        for row in packet['statements']:
            assert set(row['sources']) <= {r['source_index'] for r in packet['sources']['bundle']}
            for index in row['sources']:
                assert {'citation_token': f'Study {index}', 'verified_source_sections': {'results': f'Contradiction {index}'}} in packet['sources']['own_results']
        return SimpleNamespace(model='primary', parsed={'assessments': [
            {'row': r['row'], 'supported': False, 'reason': 'Unsupported.'} for r in packet['statements']]})
    monkeypatch.setattr(prose_grounding, 'chat_json', call)
    report = asyncio.run(prose_grounding.review_statements(statements, sources))
    assert len(calls) > 1
    assert sorted(r['row'] for r in report['assessments']) == list(range(9))
    assert all(r['supported'] is False for r in report['assessments'])
    assert report['statements'] == statements
    assert {r['source_index'] for call in calls for r in call['sources']['bundle']} == set(range(9))


def test_uncited_author_claims_have_methods_but_no_uncited_effect_evidence():
    sources = {'bundle': [{'cited_as': 'Study', 'excerpt': 'Clinical improvement'}],
               'own_results': [{'citation_token': 'Study', 'results': 'Clinical improvement'}],
               'author_context': {'source_count': 1, 'methods_record': {'selection': 'Recorded rule'}}}
    packet = batches._sources_for([{'text': 'This map included one source.', 'sources': []}], sources)
    assert packet['author_context'] == sources['author_context']
    assert packet['bundle'] == packet['own_results'] == []
    assert len(packet['source_catalog']) == 1


def test_oversized_late_item_blocks_before_any_provider_call(monkeypatch):
    calls = []
    async def call(**kw):
        calls.append(kw)
    monkeypatch.setattr(prose_grounding, 'chat_json', call)
    with pytest.raises(ValueError, match='review_input_exceeds_budget'):
        asyncio.run(prose_grounding.review_statements([{'text': 'Small'}, {'text': 'x' * 300_001}], []))
    assert calls == []


def test_late_invalid_batch_cannot_return_partial_approval(monkeypatch):
    monkeypatch.setattr(batches, 'MAX_STATEMENTS', 1)
    calls = []
    async def call(**kw):
        calls.append(kw)
        return SimpleNamespace(model='primary', parsed={'assessments': [] if len(calls) == 2 else [
            {'row': 0, 'supported': True, 'reason': 'Checked.'}]})
    monkeypatch.setattr(prose_grounding, 'chat_json', call)
    with pytest.raises(ValueError, match='semantic_review_invalid'):
        asyncio.run(prose_grounding.review_statements([{'text': 'One'}, {'text': 'Two'}], []))
    assert len(calls) == 2


def test_final_review_batches_keep_whole_paper_all_sources_and_first_negative(monkeypatch, tmp_path):
    monkeypatch.setattr(batches, 'MAX_REVIEW_CHARS', 20000)
    packet = {'source_bundle': [{'id': str(i), 'cited_as': str(i), 'excerpt': 'evidence ' * 800} for i in range(5)],
              'own_result_passages': [{'citation': str(i), 'methods': f'Comparator {i}'} for i in range(5)], 'retrieval_record': {}}
    monkeypatch.setattr(final_reviewer, '_review_evidence', lambda *_: packet)
    calls = []
    async def review(system, user, *_):
        assert len(system) + len(user) <= 20000
        assert 'UNIQUE COMPLETE MANUSCRIPT' in user
        calls.append(user)
        return {'patches': [{'id': 'P1', 'patch_type': 'claim', 'severity': 'P1', 'location': 'Abstract',
                            'before': 'UNIQUE COMPLETE MANUSCRIPT', 'after': '', 'reason': 'Unsupported.'}]}, 'primary', 0.0
    monkeypatch.setattr(final_reviewer, '_call_with_fallback', review)
    patches, raw, _, _ = asyncio.run(final_reviewer.review_paper('UNIQUE COMPLETE MANUSCRIPT', {'receipts': []}, {},
                                                               run_dir=tmp_path, client=object(), max_cost_usd=100))
    assert len(calls) > 1 and len(patches) == 1 and patches[0].severity == 'P1'
    assert len(raw['batch_reviews']) == len(calls)
    assert all(f'Comparator {i}' in ''.join(calls) for i in range(5))


@pytest.mark.parametrize('last', [False, [], True])
def test_revision_batches_preserve_all_evidence_and_never_override_late_failure(monkeypatch, last):
    import revision_coverage as coverage
    monkeypatch.setattr(batches, 'MAX_REVIEW_CHARS', 14000)
    monkeypatch.setattr(coverage, 'build_judge_chain', lambda _: ['primary'])
    rows = [{'receipt_id': str(i), 'citation_token': f'Study {i}', 'verified_source_sections': {'results': 'Evidence ' * 1000}} for i in range(4)]
    bundle = [{'cited_as': f'Study {i}', 'excerpt': f'Exact source {i}'} for i in range(4)]
    calls = []
    async def review(**kwargs):
        assert sum(len(m['content']) for m in kwargs['messages']) <= 14000
        text = kwargs['messages'][1]['content']
        assert 'COMPLETE PAPER' in text
        evidence = json.loads(text.split('=== SOURCE EVIDENCE ===\n')[1].split('\n\n=== OUTGOING PAYLOAD')[0])
        payload = json.loads(text.split('=== OUTGOING PAYLOAD FIELDS ===\n')[1])
        assert len(evidence['source_catalog']) == 4
        assert {r['citation_token'] for r in evidence['batch']} == {r['cited_as'] for r in payload['source_bundle']}
        calls.extend(r['receipt_id'] for r in evidence['batch'])
        value = last if len(calls) == 4 else True
        return SimpleNamespace(parsed={'addressed': [] if value == [] else [value]})
    result = coverage.unmet_asks('COMPLETE PAPER', ['Correct every source.'], evidence_rows=rows,
                                submission_payload={'body_markdown': 'COMPLETE PAPER', 'source_bundle': bundle}, chat=review)
    assert sorted(calls) == ['0', '1', '2', '3']
    assert result == ([] if last is True else ['Correct every source.'])


def test_revision_payload_source_not_in_evidence_cannot_disappear(monkeypatch):
    import revision_coverage as coverage
    calls = []
    async def review(**kwargs):
        calls.append(kwargs)
    assert coverage.unmet_asks('Paper', ['Verify evidence.'], evidence_rows=[{'citation_token': 'One'}],
        submission_payload={'source_bundle': [{'cited_as': 'Missing'}]}, chat=review) == ['Verify evidence.']
    assert calls == []


def test_revision_transport_references_only_identical_outgoing_text():
    import revision_coverage as coverage
    paper = '## Results\n\nSame result.\n\n## Conclusion\n\nOriginal conclusion.'
    payload = {'body_markdown': paper, 'sections': {'Results': 'Same result.', 'Conclusion': 'ALTERED conclusion.'},
               'source_bundle': [{'cited_as': 'Study', 'excerpt': 'Exact evidence', 'evidence_span': 'Exact evidence'}]}
    rows = [{'citation_token': 'Study', 'verified_source_sections': {'results': 'Exact evidence'}}]
    text = batches.revision_inputs(paper, ['Check changes.'], rows, payload, coverage._SYS, coverage._USER)[0]
    fields = json.loads(text.split('=== OUTGOING PAYLOAD FIELDS ===\n')[1])
    assert fields['body_markdown'] == {'review_reference': 'MANUSCRIPT'}
    assert fields['sections']['Results'] == {'review_reference': 'MANUSCRIPT section Results'}
    assert fields['sections']['Conclusion'] == 'ALTERED conclusion.'
    assert fields['source_bundle'][0]['excerpt'] == 'Exact evidence'
    assert fields['source_bundle'][0]['evidence_span'] == {'review_reference': "this source's excerpt"}
    assert payload['body_markdown'] == paper and payload['source_bundle'][0]['evidence_span'] == 'Exact evidence'


def test_prose_batch_entrypoint_imports_without_test_scripts_path():
    import subprocess
    import sys
    from pathlib import Path
    subprocess.run([sys.executable, "-c", "import asyncio; from agent.prose_grounding import review_statements; assert asyncio.run(review_statements([], []))['assessments'] == []"],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
