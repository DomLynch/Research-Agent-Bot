"""Tests for agent/fact_extractor.py — first LLM in the trust spine.

Verifies the four code-disposes layers:
  1. ref/kind pinning (LLM never proposes either)
  2. schema check (claim required, length-bounded, types coerced)
  3. verb-ban (planted case 1 — protocol-role can't say 'demonstrated')
  4. p-value trace (planted case 3 — claim p-value must be in abstract)
plus skip-on-off_domain, parallel fan-out, dedupe, and rejection logging.
"""
from __future__ import annotations

import asyncio
import json
from types import MappingProxyType

import httpx

from agent.fact_extractor import (
    PROMPT_VERSION,
    _kind_for_role,
    _validate_proposed,
    build_user_prompt,
    extract_facts_from_bundle,
    extract_facts_from_item,
)
from agent.llm_client import CallSpec
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, Source


# --- Fixtures -------------------------------------------------------------


def _src(ref: int = 1, *, title: str = "T", year: int = 2024) -> Source:
    return Source(
        ref=ref, title=title, year=year, url="", source="pubmed",
    )


def _item(
    *,
    ref: int = 1,
    role: str = "published_results",
    design: str = "rct",
    tier: str = "A1",
    direct: bool = True,
    abstract: str = "Metformin reduced HbA1c by 0.5% (p=0.003).",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref), abstract=abstract, design=design,  # type: ignore[arg-type]
        role=role, tier=tier,  # type: ignore[arg-type]
        direct=direct, strict=direct,
    )


def _pack(
    *,
    topic: str = "metformin",
    aliases: tuple[str, ...] = ("metformin", "biguanide"),
    forbid_protocol: tuple[str, ...] = ("demonstrated", "showed", "reduced", "improved"),
    forbid_results: tuple[str, ...] = ("planned", "pending", "will assess"),
) -> TopicPack:
    return TopicPack(
        topic=topic,
        drug_class="biguanide",
        aliases=frozenset(a.lower() for a in aliases),
        aliases_display=aliases,
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(forbid_protocol),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(forbid_results),
        canonical_trials=(),
        known_role_overrides=MappingProxyType({}),
    )


def _ok_body(payload: dict, prompt_tok: int = 100, comp_tok: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": prompt_tok, "completion_tokens": comp_tok},
    }


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _run(coro):
    return asyncio.run(coro)


# --- _kind_for_role -------------------------------------------------------


def test_kind_for_role_published_results_to_result() -> None:
    assert _kind_for_role("published_results") == "result"


def test_kind_for_role_protocol_roles_to_protocol() -> None:
    assert _kind_for_role("published_protocol") == "protocol"
    assert _kind_for_role("registered_pending") == "protocol"


def test_kind_for_role_review_and_mechanistic_to_context() -> None:
    assert _kind_for_role("review") == "context"
    assert _kind_for_role("mechanistic") == "context"


def test_kind_for_role_off_domain_returns_none() -> None:
    assert _kind_for_role("off_domain") is None


# --- _validate_proposed: ref/kind pinning + verb-ban + p-value -----------


def test_validate_proposed_happy_path_pins_ref_and_kind() -> None:
    """The LLM dict has no `ref` or `kind` field; the validator pins both
    from the EvidenceItem. This is the core LLM-PROPOSES/CODE-DISPOSES test."""
    item = _item(ref=42, role="published_results")
    proposed = {"claim": "metformin lowered HbA1c by 0.5% (p=0.003)."}
    fact, reason = _validate_proposed(
        proposed, item=item, pack=_pack(), require_p_value_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.ref == 42  # pinned from item.source.ref
    assert fact.kind == "result"  # pinned from item.role
    assert fact.claim == "metformin lowered HbA1c by 0.5% (p=0.003)."


def test_validate_proposed_pins_kind_even_if_llm_attempts_override() -> None:
    """A malicious / confused LLM emits {'kind': 'protocol'} on a published_results
    item. The validator IGNORES it and pins kind='result' from the role."""
    item = _item(ref=1, role="published_results")
    proposed = {"claim": "reduced X.", "kind": "protocol", "ref": 999}  # both are noise
    fact, reason = _validate_proposed(
        proposed, item=item, pack=_pack(), require_p_value_trace=False,
    )
    assert reason is None
    assert fact is not None
    assert fact.kind == "result"  # NOT protocol
    assert fact.ref == 1          # NOT 999


def test_validate_proposed_missing_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {}, item=item, pack=_pack(), require_p_value_trace=False,
    )
    assert fact is None
    assert reason == "missing_or_empty_claim"


def test_validate_proposed_empty_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {"claim": "   "}, item=item, pack=_pack(), require_p_value_trace=False,
    )
    assert fact is None
    assert reason == "missing_or_empty_claim"


def test_validate_proposed_oversized_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {"claim": "x" * 501}, item=item, pack=_pack(),
        require_p_value_trace=False,
    )
    assert fact is None
    assert reason == "claim_too_long"


def test_validate_proposed_off_domain_rejects_no_kind() -> None:
    """Defense-in-depth: even if caller didn't skip, validator rejects."""
    item = _item(role="off_domain")
    fact, reason = _validate_proposed(
        {"claim": "anything"}, item=item, pack=_pack(),
        require_p_value_trace=False,
    )
    assert fact is None
    assert reason is not None
    assert reason.startswith("no_kind_for_role")


def test_validate_proposed_verb_ban_on_protocol_role_rejects() -> None:
    """Planted case 1's 5th defense: protocol-role item gets a claim with
    'demonstrated' — verb-ban catches it BEFORE the fact enters the graph."""
    item = _item(role="registered_pending")
    fact, reason = _validate_proposed(
        {"claim": "TAME demonstrated cardiovascular benefit."},
        item=item, pack=_pack(), require_p_value_trace=False,
    )
    assert fact is None
    assert reason is not None
    assert reason.startswith("verb_ban:")


def test_validate_proposed_p_value_not_in_source_rejects() -> None:
    """Planted case 3 at extraction time: claim cites p<0.001 but abstract
    says p=0.08. P-value trace catches it before the value enters the graph."""
    item = _item(abstract="Some effect was observed (p=0.08).")
    fact, reason = _validate_proposed(
        {"claim": "metformin lowered HbA1c (p<0.001)."},
        item=item, pack=_pack(), require_p_value_trace=True,
    )
    assert fact is None
    assert reason is not None
    assert reason.startswith("p_value_not_in_source:")


def test_validate_proposed_p_value_trace_can_be_disabled() -> None:
    """`require_p_value_trace=False` lets the fact through even with a
    mismatched p-value. Used for tests/dev flows; production uses True."""
    item = _item(abstract="Some effect was observed (p=0.08).")
    fact, reason = _validate_proposed(
        {"claim": "metformin lowered HbA1c (p<0.001)."},
        item=item, pack=_pack(), require_p_value_trace=False,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_coerces_optional_field_types() -> None:
    """Non-string p_value/estimate/ci/outcome (e.g. JSON null, numeric) → None."""
    item = _item()
    fact, reason = _validate_proposed(
        {
            "claim": "x reduced (p=0.003).",
            "outcome": None, "estimate": None, "p_value": None, "ci": None,
        },
        item=item, pack=_pack(), require_p_value_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.outcome is None
    assert fact.estimate is None


# --- build_user_prompt ----------------------------------------------------


def test_build_user_prompt_includes_topic_and_ref_and_abstract() -> None:
    item = _item(ref=7, abstract="A reduced B by 5%.")
    prompt = build_user_prompt(item, "metformin")
    assert "metformin" in prompt
    assert "[7]" in prompt
    assert "A reduced B by 5%." in prompt
    assert "role=published_results" in prompt


def test_build_user_prompt_is_deterministic() -> None:
    """Same item + topic → same prompt string (no time-of-day / random)."""
    item = _item()
    assert build_user_prompt(item, "metformin") == build_user_prompt(item, "metformin")


def test_prompt_version_is_anchored() -> None:
    """Anchored constant — cost_log.json records this for reproducibility."""
    assert PROMPT_VERSION == "fact-extractor/2026-04-27"


# --- extract_facts_from_item ---------------------------------------------


def test_extract_facts_from_item_happy_path() -> None:
    abstract = "Metformin reduced HbA1c by 0.5% (p=0.003) over 12 weeks."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                {
                    "claim": "metformin reduced HbA1c by 0.5% (p=0.003).",
                    "outcome": "HbA1c", "estimate": "0.5%",
                    "p_value": "0.003", "ci": None,
                },
            ],
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(abstract=abstract), pack=_pack(),
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert len(accepted) == 1
    assert rejected == []
    f = accepted[0]
    assert f.kind == "result"
    assert f.ref == 1
    assert f.p_value == "0.003"
    assert f.outcome == "HbA1c"


def test_extract_facts_from_item_skips_off_domain_no_llm_call() -> None:
    """off_domain items short-circuit before HTTP — verify zero calls."""
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        return httpx.Response(200, json=_ok_body({"facts": []}))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(role="off_domain"), pack=_pack(),
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert rejected == []
    assert http_calls["n"] == 0


def test_extract_facts_from_item_empty_abstract_rejects_no_llm_call() -> None:
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        return httpx.Response(200, json=_ok_body({"facts": []}))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(abstract="   "), pack=_pack(),
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0].reason == "empty_abstract"
    assert http_calls["n"] == 0


def test_extract_facts_from_item_missing_facts_field_rejects() -> None:
    """LLM emits valid JSON but no 'facts' key → single rejection."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({"some_other_key": "value"}))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(), pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0].reason == "missing_facts_field"


def test_extract_facts_from_item_facts_not_a_list_rejects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({"facts": {"not": "a list"}}))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(), pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0].reason == "facts_field_not_a_list"


def test_extract_facts_from_item_mix_of_valid_and_invalid() -> None:
    """One valid, one missing claim, one not-a-dict, one verb-ban —
    accepted gets the valid one; rejected lists the rest with reasons."""
    item = _item(role="registered_pending", abstract="Trial registered, p=0.05 reported in plan.")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                {"claim": "trial enrolls older adults at risk of CV events."},
                {},  # missing claim
                "not a dict",
                {"claim": "metformin demonstrated CV benefit (p=0.05)."},  # verb-ban
            ],
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                item, pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert len(accepted) == 1
    assert accepted[0].claim.startswith("trial enrolls")
    assert accepted[0].kind == "protocol"  # pinned from registered_pending
    reasons = sorted(r.reason for r in rejected)
    assert any(r.startswith("verb_ban:") for r in reasons)
    assert "missing_or_empty_claim" in reasons
    assert "not_a_dict" in reasons


def test_extract_facts_from_item_dedupes_within_item() -> None:
    """LLM emits two paraphrases of the same claim. One survives; the
    duplicate is logged as 'duplicate_claim'."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                {"claim": "metformin reduced HbA1c."},
                {"claim": "Metformin Reduced HbA1c."},  # case-only diff
            ],
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(), pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert len(accepted) == 1
    assert any(r.reason == "duplicate_claim" for r in rejected)


def test_extract_facts_from_item_llm_chain_failure_returns_rejection() -> None:
    """All specs in the chain return 500 → LLMError → single rejection
    with the wrapped error message, not a raised exception."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_item(
                _item(), pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0].reason.startswith("llm_error:")


# --- extract_facts_from_bundle -------------------------------------------


def test_extract_facts_from_bundle_empty_input() -> None:
    async def go():
        return await extract_facts_from_bundle(
            [], pack=_pack(), chain=(_spec(),),
        )

    accepted, rejected = _run(go())
    assert accepted == []
    assert rejected == []


def test_extract_facts_from_bundle_preserves_item_order() -> None:
    """Item 1 emits 1 fact; item 2 emits 1 fact. Output is item-ordered."""
    items = [
        _item(ref=1, abstract="aspirin reduced X (p=0.01)."),
        _item(ref=2, abstract="metformin reduced Y (p=0.02)."),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # Decode which item this is by checking the user message
        user_msg = next(m for m in body["messages"] if m["role"] == "user")
        if "aspirin" in user_msg["content"]:
            return httpx.Response(200, json=_ok_body({
                "facts": [{"claim": "aspirin reduced X (p=0.01).", "p_value": "0.01"}],
            }))
        return httpx.Response(200, json=_ok_body({
            "facts": [{"claim": "metformin reduced Y (p=0.02).", "p_value": "0.02"}],
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_bundle(
                items, pack=_pack(), chain=(_spec(),), client=client,
                max_concurrency=2,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert [f.ref for f in accepted] == [1, 2]
    assert rejected == []


def test_extract_facts_from_bundle_skips_off_domain_no_call_for_those() -> None:
    items = [
        _item(ref=1, role="published_results"),
        _item(ref=2, role="off_domain"),
        _item(ref=3, role="review", abstract="reviews report mixed effects."),
    ]
    http_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        http_calls["n"] += 1
        return httpx.Response(200, json=_ok_body({"facts": []}))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_bundle(
                items, pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert rejected == []
    # 2 items hit the LLM (refs 1, 3); ref 2 skipped pre-call
    assert http_calls["n"] == 2


def test_extract_facts_from_bundle_aggregates_rejections() -> None:
    """Two items, each with a verb-ban'd claim → 2 rejections."""
    items = [
        _item(ref=1, role="registered_pending"),
        _item(ref=2, role="registered_pending"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [{"claim": "demonstrated CV benefit."}],
        }))

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await extract_facts_from_bundle(
                items, pack=_pack(), chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    accepted, rejected = _run(go())
    assert accepted == []
    assert len(rejected) == 2
    assert all(r.reason.startswith("verb_ban:") for r in rejected)
    assert {r.item_ref for r in rejected} == {1, 2}
