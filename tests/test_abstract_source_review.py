import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent import paper_writer, prose_grounding
from agent.paper_writer_builders import build_anchored_from_parsed


@pytest.mark.parametrize("change", [None, "text", "count", "citation", "section", "unreviewed"])
def test_own_abstract_record_requires_exact_review_and_documented_count(change):
    text = "This map analyzes 37 retained sources."
    reviewed = frozenset({(text, ())})
    proposed = text
    if change == "text":
        proposed = text.replace("analyzes", "randomized")
    elif change == "count":
        proposed = text.replace("37", "38")
        reviewed = frozenset({(proposed, ())})
    elif change == "citation":
        proposed += " [External 2020]"
        reviewed = frozenset({(proposed, ())})
    result = build_anchored_from_parsed({"paragraphs": [{"text": proposed, "receipt_ids": []}]},
        name="results" if change == "section" else "abstract", heading="## Abstract", accepted=[],
        reviewed=frozenset() if change == "unreviewed" else reviewed, author_numerics=frozenset({"37"}))
    assert (result is not None) is (change is None)


@pytest.mark.parametrize("supported", [True, False])
def test_native_abstract_writer_uses_author_records_and_respects_negative_review(monkeypatch, supported):
    records = {"source_count": 37, "question": "How do study designs affect interpretation?"}
    proposed = {"paragraphs": [{"text": "This map analyzes 37 retained sources.", "receipt_ids": []}]}
    calls = []
    async def writer(**kwargs):
        return deepcopy(proposed)
    async def reviewer(**kwargs):
        packet = json.loads(kwargs["messages"][1]["content"])
        calls.append(packet)
        return SimpleNamespace(model="configured-reviewer", parsed={"assessments": [
            {"row": 0, "supported": supported, "reason": "Checked against author records."}]})
    monkeypatch.setattr(paper_writer, "_call_llm_section", writer)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 0)
    monkeypatch.setattr(paper_writer, "SECTION_WORD_FLOORS", {"abstract": 0})
    monkeypatch.setattr(prose_grounding, "chat_json", reviewer)
    kwargs = dict(name="abstract", heading="## Abstract", system_prompt="Abstract", user_prompt="Records",
        accepted=[], chain=[], client=None, ledger=None, seed=7, fallback_body="", author_context=records)
    if supported:
        section = asyncio.run(paper_writer._write_anchored_section(**kwargs))
        assert proposed["paragraphs"][0]["text"] in section.body_md
    else:
        with pytest.raises(ValueError, match="writer_section_unavailable:abstract"):
            asyncio.run(paper_writer._write_anchored_section(**kwargs))
    assert calls[0]["sources"]["author_context"] == records
    assert len(calls) == 1
