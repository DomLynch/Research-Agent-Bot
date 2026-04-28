"""Tests for agent/writer.py — claim-graph-gated prose drafter.

Covers:
- Sentence-level gating (cite-in-bundle, verb-ban, p-value, alias drift)
- _filter_sentences walk + non-string skip
- _spar_banner for all 4 SPARVerdict shapes + the gate_override path
- _render_paper structure (title, banner, sections, references)
- _render_rejection (no LLM call needed)
- write_paper routing: accept_* → LLM call; reject_* / gate_override → no LLM
"""
from __future__ import annotations

import asyncio
import json
from types import MappingProxyType

import httpx
import pytest

from agent.llm_client import CallSpec
from agent.schemas import (
    Claim,
    CitationTrace,
    ClaimGraph,
    GateOverride,
    JudgeReview,
    SPARReview,
)
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, Source
from agent.writer import (
    PROMPT_VERSION,
    WriterError,
    WriterRejection,
    _filter_sentences,
    _render_paper,
    _render_rejection,
    _spar_banner,
    _validate_sentence,
    write_paper,
)


# --- Fixtures -------------------------------------------------------------


def _src(ref: int = 1, *, year: int = 2024, title: str = "Trial paper") -> Source:
    return Source(ref=ref, title=title, year=year, url="https://x", source="pubmed")


def _item(
    ref: int = 1, *,
    role: str = "published_results",
    abstract: str = "Metformin reduced HbA1c by 0.5% (p=0.003).",
    title: str = "Trial paper",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, title=title), abstract=abstract,
        design="rct", role=role,  # type: ignore[arg-type]
        tier="A1", direct=True, strict=True,
    )


def _claim(cid: str = "C001", *, refs: tuple[int, ...] = (1,), text: str = "metformin reduced HbA1c.") -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )


def _graph(*claims: Claim) -> ClaimGraph:
    cs = claims or (_claim(),)
    return ClaimGraph(claims=cs, edges=(), thesis_claim_id=cs[0].claim_id)


def _pack() -> TopicPack:
    return TopicPack(
        topic="metformin",
        drug_class="biguanide",
        aliases=frozenset({"metformin", "biguanide", "glucophage"}),
        aliases_display=("metformin", "biguanide", "Glucophage"),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(
            {"demonstrated", "showed", "reduced", "improved"}
        ),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(
            {"planned", "pending", "will assess"}
        ),
        canonical_trials=(),
        known_role_overrides=MappingProxyType({}),
    )


def _judge(role: str, verdict: str, *, rationale: str = "ok rationale") -> JudgeReview:
    return JudgeReview(
        judge_role=role,  # type: ignore[arg-type]
        model="m",
        verdict=verdict,  # type: ignore[arg-type]
        score=8, rationale=rationale, flagged_claims=(),
    )


def _spar(
    verdict: str = "accept_clean",
    *,
    reviews: tuple[JudgeReview, ...] | None = None,
    dissent: JudgeReview | None = None,
    gate_override: GateOverride | None = None,
) -> SPARReview:
    if reviews is None:
        if verdict == "accept_clean":
            reviews = (
                _judge("evidence_auditor", "accept"),
                _judge("domain_skeptic", "accept"),
                _judge("final_judge", "accept"),
            )
        elif verdict == "accept_caveated":
            d = _judge("domain_skeptic", "reject", rationale="confounded")
            reviews = (
                _judge("evidence_auditor", "accept"),
                d,
                _judge("final_judge", "accept"),
            )
            dissent = d
        elif verdict == "reject_majority":
            d = _judge("final_judge", "accept", rationale="hopeful but...")
            reviews = (
                _judge("evidence_auditor", "reject"),
                _judge("domain_skeptic", "reject"),
                d,
            )
            dissent = d
        else:  # reject_critical
            reviews = (
                _judge("evidence_auditor", "reject"),
                _judge("domain_skeptic", "reject"),
                _judge("final_judge", "reject"),
            )
    return SPARReview(
        submission_id="run-001",
        reviews=reviews,
        verdict=verdict,  # type: ignore[arg-type]
        dissent=dissent,
        final_judge_resolution="resolution prose",
        gate_override=gate_override,
    )


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _writer_response(payload: dict) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 100},
    }


def _run(coro):
    return asyncio.run(coro)


# --- _validate_sentence --------------------------------------------------


def test_validate_sentence_happy_path() -> None:
    """Cite in bundle, no verb-ban, p-value matches abstract → passes."""
    items = {1: _item(1)}
    sentence = "metformin reduced HbA1c (p=0.003) [1]."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is None


def test_validate_sentence_cite_not_in_bundle_rejects() -> None:
    """LLM hallucinated [99] — not in graph's supporting_refs."""
    items = {1: _item(1)}
    sentence = "metformin reduced X [99]."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is not None
    assert "cite_not_in_bundle" in reason
    assert "99" in reason


def test_validate_sentence_verb_ban_on_protocol_role_rejects() -> None:
    """[1] is registered_pending; sentence uses 'demonstrated' → reject."""
    items = {1: _item(1, role="registered_pending")}
    sentence = "metformin demonstrated cardiovascular benefit [1]."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is not None
    assert reason.startswith("verb_ban:")
    assert ":ref=1" in reason


def test_validate_sentence_p_value_not_in_source_rejects() -> None:
    """Sentence cites p<0.001 but abstract only has p=0.08."""
    items = {1: _item(1, abstract="Some effect was observed (p=0.08).")}
    sentence = "metformin lowered X (p<0.001) [1]."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is not None
    assert reason.startswith("p_value_not_in_source:")


def test_validate_sentence_alias_drift_rejects() -> None:
    """Sentence presents 'Glufomin' (planted case 4) as a metformin alias."""
    items = {1: _item(1)}
    sentence = "Glufomin, a metformin alias, was tested [1]."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is not None
    assert reason.startswith("alias_drift:")


def test_validate_sentence_with_no_cites_passes() -> None:
    """A sentence without [N] cites is just prose; no membership check
    fires. Verb-ban / p-value / alias still apply but don't fail here."""
    items = {1: _item(1)}
    sentence = "the field of geroscience is rapidly evolving."
    reason = _validate_sentence(
        sentence, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert reason is None


# --- _filter_sentences ---------------------------------------------------


def test_filter_sentences_keeps_valid_drops_invalid() -> None:
    items = {1: _item(1), 2: _item(2)}
    parsed = {
        "title": "Test",
        "abstract": [
            "good [1].",
            "metformin reduced X [99].",
            "Glufomin, a metformin alias, was tested [2].",  # apposition → alias_drift
        ],
        "sections": {
            "findings": ["another good [1].", 42],  # 42 is non-string, silently skipped
            "limitations": ["bad cite [99]."],
        },
    }
    filtered, rejections = _filter_sentences(
        parsed, valid_refs={1, 2}, items_by_ref=items, pack=_pack(),
    )
    assert filtered["title"] == "Test"
    assert filtered["abstract"] == ["good [1]."]
    assert filtered["sections"]["findings"] == ["another good [1]."]
    assert filtered["sections"]["limitations"] == []
    reasons = [r.reason for r in rejections]
    assert any("cite_not_in_bundle" in r for r in reasons)
    assert any("alias_drift" in r for r in reasons)


def test_filter_sentences_handles_missing_keys() -> None:
    """LLM emits an object without abstract / sections — no crash."""
    items = {1: _item(1)}
    parsed: dict = {"title": "Bare"}
    filtered, rejections = _filter_sentences(
        parsed, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert filtered["title"] == "Bare"
    assert filtered["abstract"] == []
    assert filtered["sections"] == {}
    assert rejections == []


def test_filter_sentences_strips_title_whitespace() -> None:
    items = {1: _item(1)}
    parsed = {"title": "   Padded   ", "abstract": [], "sections": {}}
    filtered, _ = _filter_sentences(
        parsed, valid_refs={1}, items_by_ref=items, pack=_pack(),
    )
    assert filtered["title"] == "Padded"


# --- _spar_banner --------------------------------------------------------


def test_spar_banner_accept_clean_short() -> None:
    banner = _spar_banner(_spar("accept_clean"))
    assert "accept_clean" in banner
    assert "3-0" in banner
    assert "DRAFT REJECTED" not in banner
    assert "TRUST-SPINE" not in banner


def test_spar_banner_accept_caveated_includes_dissent() -> None:
    banner = _spar_banner(_spar("accept_caveated"))
    assert "accept_caveated" in banner
    assert "Dissent" in banner
    assert "domain_skeptic" in banner
    assert "confounded" in banner


def test_spar_banner_reject_majority_emphasizes_rejection_with_minority() -> None:
    banner = _spar_banner(_spar("reject_majority"))
    assert "DRAFT REJECTED" in banner
    assert "reject_majority" in banner
    assert "Minority accept" in banner
    assert "final_judge" in banner


def test_spar_banner_reject_critical_unanimous() -> None:
    banner = _spar_banner(_spar("reject_critical"))
    assert "DRAFT REJECTED" in banner
    assert "reject_critical" in banner
    assert "Dissent" not in banner  # unanimous reject has no panel dissent


def test_spar_banner_gate_override_displayed_prominently() -> None:
    """The reviewer's audit-trail requirement: gate_override is the most
    architecturally consequential SPARReview shape, must be prominent."""
    spar = _spar(
        verdict="reject_critical",
        reviews=(  # accept votes preserved verbatim
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=2,
            rationale="MASTERS NCT mismatch + p-value not in source",
        ),
    )
    banner = _spar_banner(spar)
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in banner
    # Both verdicts visible — canonical AND panel's original
    assert "reject_critical" in banner
    assert "accept_clean" in banner
    assert "Failed citation traces:** 2" in banner
    assert "MASTERS NCT mismatch" in banner


# --- _render_paper -------------------------------------------------------


def test_render_paper_includes_title_banner_and_sections() -> None:
    items = [_item(1, title="Source One")]
    filtered = {
        "title": "A Paper",
        "abstract": ["abstract sentence [1]."],
        "sections": {
            "introduction": ["intro [1]."],
            "findings": ["findings [1]."],
            "conclusion": ["concl [1]."],
        },
    }
    md = _render_paper(filtered, items, _spar("accept_clean"))
    assert md.startswith("# A Paper")
    assert "## Abstract" in md
    assert "abstract sentence [1]." in md
    assert "## Introduction" in md
    assert "## Findings" in md
    assert "## Conclusion" in md
    assert "accept_clean" in md  # banner present


def test_render_paper_omits_empty_sections() -> None:
    items = [_item(1)]
    filtered = {
        "title": "T",
        "abstract": ["abs [1]."],
        "sections": {
            "introduction": [],  # empty → omitted
            "findings": ["finds [1]."],
        },
    }
    md = _render_paper(filtered, items, _spar("accept_clean"))
    assert "## Introduction" not in md
    assert "## Findings" in md


def test_render_paper_references_only_cited_refs() -> None:
    """References section lists only refs that appear in sentences."""
    items = [_item(1, title="Cited"), _item(2, title="Uncited")]
    filtered = {
        "title": "T", "abstract": ["only cites one [1]."], "sections": {},
    }
    md = _render_paper(filtered, items, _spar("accept_clean"))
    assert "## References" in md
    assert "[1] Cited" in md
    assert "Uncited" not in md
    assert "[2]" not in md


# --- _render_rejection ---------------------------------------------------


def test_render_rejection_includes_banner_thesis_traces_panel() -> None:
    graph = _graph(_claim("C001", text="metformin reduces mortality."))
    items = [_item(1, title="Trial X")]
    spar = _spar("reject_critical")
    traces = [
        CitationTrace(
            claim_id="C001", ref=1, trace_type="nct_exists",  # type: ignore[arg-type]
            passed=False, detail="NCT not found",
        ),
    ]
    md = _render_rejection(graph, items, spar, traces)
    assert "Submission rejected" in md
    assert "DRAFT REJECTED" in md
    assert "metformin reduces mortality." in md  # thesis quoted
    assert "Failed citation traces" in md
    assert "NCT not found" in md
    assert "evidence_auditor" in md
    assert "domain_skeptic" in md
    assert "final_judge" in md


def test_render_rejection_with_gate_override_prominent() -> None:
    graph = _graph(_claim())
    items = [_item(1)]
    spar = _spar(
        verdict="reject_critical",
        reviews=(
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=1,
            rationale="failed trace gate fired",
        ),
    )
    md = _render_rejection(graph, items, spar, [])
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in md
    assert "accept_clean" in md  # panel's original visible
    assert "failed trace gate fired" in md


# --- write_paper end-to-end ---------------------------------------------


def test_write_paper_accept_clean_calls_llm_and_renders() -> None:
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_writer_response({
            "title": "Metformin and HbA1c",
            "abstract": ["metformin reduced HbA1c (p=0.003) [1]."],
            "sections": {
                "findings": ["the trial reported a reduction (p=0.003) [1]."],
                "limitations": ["small sample size."],
            },
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                _graph(_claim("C001", refs=(1,))), [_item(1)], [], _spar("accept_clean"),
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert rejections == []
    assert "# Metformin and HbA1c" in md
    assert "## Abstract" in md
    assert "## Findings" in md
    assert "accept_clean" in md  # banner
    # Verify LLM was called with system + user
    assert any(m["role"] == "system" for m in captured["payload"]["messages"])
    assert any(m["role"] == "user" for m in captured["payload"]["messages"])


def test_write_paper_reject_critical_skips_llm() -> None:
    """No LLM call on reject path. handler should never fire."""
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        pytest.fail("LLM should not be called on reject path")
        return httpx.Response(500)  # unreachable but typed

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                _graph(_claim("C001", refs=(1,))), [_item(1)], [],
                _spar("reject_critical"),
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert http_calls["n"] == 0
    assert rejections == []
    assert "Submission rejected" in md
    assert "reject_critical" in md


def test_write_paper_gate_override_skips_llm_and_displays_gate() -> None:
    """Gate-override path: no LLM call; markdown carries the gate banner
    front and center per the reviewer's audit-trail requirement."""
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        pytest.fail("LLM should not be called on gate-override path")
        return httpx.Response(500)

    spar = _spar(
        verdict="reject_critical",
        reviews=(
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=1,
            rationale="MASTERS NCT failed trace",
        ),
    )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                _graph(_claim("C001", refs=(1,))), [_item(1)], [], spar,
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, _ = _run(go())
    assert http_calls["n"] == 0
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in md
    assert "accept_clean" in md  # panel's original
    assert "reject_critical" in md  # canonical


def test_write_paper_drops_invalid_sentences_and_records_rejections() -> None:
    """LLM proposes one valid + one invalid sentence; valid is rendered,
    invalid is dropped + recorded in WriterRejection."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_writer_response({
            "title": "T",
            "abstract": ["good cite [1].", "bad cite [99]."],
            "sections": {},
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await write_paper(
                _graph(_claim("C001", refs=(1,))), [_item(1)], [],
                _spar("accept_clean"),
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    md, rejections = _run(go())
    assert "good cite [1]." in md
    assert "bad cite [99]." not in md
    assert len(rejections) == 1
    assert rejections[0].section == "abstract"
    assert "cite_not_in_bundle" in rejections[0].reason


def test_write_paper_non_object_response_raises() -> None:
    """LLM returns valid JSON that's an array, not an object."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(["not", "an", "object"])}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await write_paper(
                _graph(_claim("C001", refs=(1,))), [_item(1)], [],
                _spar("accept_clean"),
                pack=_pack(), topic="metformin",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    # extract_json in chat_json raises ValueError on non-object root,
    # which propagates as an LLMError chain failure. write_paper itself
    # would only see this through chain failure — the relevant guard
    # in writer is for when LLM returns a parse-able non-Mapping shape
    # via fallback. For this test, the LLMError shape is fine.
    from agent.llm_client import LLMError
    with pytest.raises((LLMError, WriterError)):
        _run(go())


# --- Misc ---------------------------------------------------------------


def test_prompt_version_anchored() -> None:
    assert PROMPT_VERSION == "writer/2026-04-28"


def test_writer_rejection_dataclass_is_frozen() -> None:
    r = WriterRejection(section="abstract", sentence="x", reason="y")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        r.section = "findings"  # type: ignore[misc]
