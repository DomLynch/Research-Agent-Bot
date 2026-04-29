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
import pytest

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
    # source_quote is a verbatim span of the default abstract
    # "Metformin reduced HbA1c by 0.5% (p=0.003)."
    proposed = {"source_quote": "Metformin reduced HbA1c by 0.5% (p=0.003)"}
    fact, reason = _validate_proposed(
        proposed, item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.ref == 42  # pinned from item.source.ref
    assert fact.kind == "result"  # pinned from item.role
    assert fact.claim == "Metformin reduced HbA1c by 0.5% (p=0.003)"


def test_validate_proposed_pins_kind_even_if_llm_attempts_override() -> None:
    """A malicious / confused LLM emits {'kind': 'protocol'} on a published_results
    item. The validator IGNORES it and pins kind='result' from the role."""
    item = _item(ref=1, role="published_results")
    proposed = {"source_quote": "reduced X.", "kind": "protocol", "ref": 999}  # both are noise
    fact, reason = _validate_proposed(
        proposed, item=item, pack=_pack(), require_source_trace=False,
    )
    assert reason is None
    assert fact is not None
    assert fact.kind == "result"  # NOT protocol
    assert fact.ref == 1          # NOT 999


def test_validate_proposed_missing_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {}, item=item, pack=_pack(), require_source_trace=False,
    )
    assert fact is None
    assert reason == "missing_or_empty_source_quote"


def test_validate_proposed_empty_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {"source_quote": "   "}, item=item, pack=_pack(), require_source_trace=False,
    )
    assert fact is None
    assert reason == "missing_or_empty_source_quote"


def test_validate_proposed_oversized_claim_rejects() -> None:
    item = _item()
    fact, reason = _validate_proposed(
        {"source_quote": "x" * 501}, item=item, pack=_pack(),
        require_source_trace=False,
    )
    assert fact is None
    assert reason == "source_quote_too_long"


def test_validate_proposed_off_domain_rejects_no_kind() -> None:
    """Defense-in-depth: even if caller didn't skip, validator rejects."""
    item = _item(role="off_domain")
    fact, reason = _validate_proposed(
        {"source_quote": "anything"}, item=item, pack=_pack(),
        require_source_trace=False,
    )
    assert fact is None
    assert reason is not None
    assert reason.startswith("no_kind_for_role")


def test_validate_proposed_verb_ban_on_protocol_role_rejects() -> None:
    """Planted case 1's 5th defense: protocol-role item gets a claim with
    'demonstrated' — verb-ban catches it BEFORE the fact enters the graph."""
    item = _item(role="registered_pending")
    fact, reason = _validate_proposed(
        {"source_quote": "TAME demonstrated cardiovascular benefit."},
        item=item, pack=_pack(), require_source_trace=False,
    )
    assert fact is None
    assert reason is not None
    assert reason.startswith("verb_ban:")


def test_validate_proposed_p_value_trace_can_be_disabled() -> None:
    """`require_source_trace=False` lets the fact through even when the
    source_quote doesn't appear in the abstract. Used for tests/dev
    flows; production uses True."""
    item = _item(abstract="Some effect was observed.")
    fact, reason = _validate_proposed(
        {"source_quote": "metformin had a totally novel effect."},
        item=item, pack=_pack(), require_source_trace=False,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_coerces_optional_field_types() -> None:
    """Non-string p_value/estimate/ci/outcome (e.g. JSON null, numeric) → None."""
    item = _item()  # default abstract: "Metformin reduced HbA1c by 0.5% (p=0.003)."
    fact, reason = _validate_proposed(
        {
            "source_quote": "Metformin reduced HbA1c by 0.5% (p=0.003)",
            "outcome": None, "estimate": None, "p_value": None, "ci": None,
        },
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.outcome is None
    assert fact.estimate is None


# --- Field-level source tracing (closes 3.2c P1/P2) ----------------------


def test_validate_proposed_p_value_field_not_in_source_rejects() -> None:
    """3.2c P1: separate p_value field (not embedded in source_quote)
    must trace back to abstract. The source_quote is verbatim in the
    abstract; the structured p_value field is fabricated."""
    item = _item(abstract="Some effect was observed (p=0.08).")
    fact, reason = _validate_proposed(
        {"source_quote": "Some effect was observed", "p_value": "<0.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert fact is None
    assert reason == "p_value_field_not_in_source"


def test_validate_proposed_p_value_field_in_source_accepts() -> None:
    """Same field, p-value present in abstract → accepted."""
    item = _item(abstract="Metformin had a significant effect (p<0.001).")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin had a significant effect", "p_value": "<0.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.p_value == "<0.001"


def test_validate_proposed_p_value_field_with_p_prefix_accepts() -> None:
    """LLM emits p_value='p<0.001' (with prefix); synthetic builder strips
    the prefix and re-applies, matching the abstract's verbatim form."""
    item = _item(abstract="Metformin had a significant effect (p<0.001).")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin had a significant effect", "p_value": "p<0.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_p_value_field_bare_number_in_source_accepts() -> None:
    """LLM emits bare '0.003'; synthesizer wraps as 'p=0.003'."""
    item = _item(abstract="Effect reported (p=0.003).")
    fact, reason = _validate_proposed(
        {"source_quote": "Effect reported", "p_value": "0.003"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.p_value == "0.003"


def test_validate_proposed_nulls_untraced_estimate_keeps_fact() -> None:
    """Day 8.2 (reviewer P2): the LLM's `estimate` is kept only when it
    appears as a substring of the verified source_quote. When it doesn't,
    the field is NULLED — not rejected. This preserves the verified
    quote while keeping unverified metadata out of fact_extraction_log.
    Pre-fix the field flowed into the audit log as if it were
    source-backed."""
    item = _item(abstract="Metformin reduced X by a small reduction.")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin reduced X", "estimate": "HR 0.10"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.estimate is None, (
        "estimate must be nulled when not a substring of source_quote — "
        "the audit log shouldn't contain LLM-fabricated numerics"
    )


def test_validate_proposed_keeps_estimate_when_in_source_quote() -> None:
    """When the LLM's estimate IS a substring of the verified source_quote,
    keep it — that's source-backed metadata."""
    item = _item(abstract="Metformin reduced X with hazard ratio HR 0.79.")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin reduced X with hazard ratio HR 0.79", "estimate": "HR 0.79"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.estimate == "HR 0.79"


def test_validate_proposed_nulls_untraced_ci_keeps_fact() -> None:
    """Same contract for `ci` — nulled when not in source_quote, fact
    survives with the verified quote."""
    item = _item(abstract="Metformin reduced X but no CI was reported.")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin reduced X", "ci": "0.01-0.02"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.ci is None


def test_validate_proposed_keeps_ci_when_in_source_quote() -> None:
    item = _item(abstract="Metformin reduced X (95% CI 0.66-0.95).")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin reduced X (95% CI 0.66-0.95)", "ci": "0.66-0.95"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None
    assert fact.ci == "0.66-0.95"


def test_validate_proposed_source_trace_disabled_bypasses_all_field_traces() -> None:
    """`require_source_trace=False` bypasses ALL four trace layers — claim
    p-values, p_value field, estimate field, ci field. Useful for dev
    flows; production always passes True."""
    item = _item(abstract="A small effect was reported.")
    fact, reason = _validate_proposed(
        {
            "source_quote": "metformin had an effect.",
            "p_value": "<0.001",
            "estimate": "HR 0.10",
            "ci": "0.01-0.02",
        },
        item=item, pack=_pack(), require_source_trace=False,
    )
    assert reason is None
    assert fact is not None
    assert fact.p_value == "<0.001"
    assert fact.estimate == "HR 0.10"
    assert fact.ci == "0.01-0.02"


def test_validate_proposed_novel_claim_outside_abstract_rejects() -> None:
    """5.2-fix P1: closes the novel-claim hole structurally. Pre-fix
    (Day 5.1-fix bag-of-words gate), an LLM-proposed `claim` like
    'Metformin reduced dementia.' (endpoint swap) passed because it
    shared two of three content tokens with `Metformin reduced HbA1c`.
    Now `source_quote` MUST appear verbatim in the abstract — endpoint
    swaps reject because the swapped endpoint is not in the source
    text by definition."""
    item = _item(abstract="Metformin reduced HbA1c by 0.5% (p=0.003).")
    fact, reason = _validate_proposed(
        # Endpoint-swapped claim — content tokens overlap with abstract
        # (metformin, reduced) but the SPAN is not verbatim in the source.
        {"source_quote": "Metformin reduced dementia."},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert fact is None
    assert reason == "source_quote_not_in_abstract"


def test_validate_proposed_verbatim_quote_accepts() -> None:
    """Happy path: a verbatim span of the abstract passes the source-trace
    gate. Whitespace-normalized + case-insensitive comparison handles the
    LLM's typical reformatting (sentence-case, collapsed whitespace)."""
    item = _item(
        abstract="Metformin reduced HbA1c by 0.5% (p=0.003) significantly."
    )
    fact, reason = _validate_proposed(
        # Verbatim span; case-insensitive match → accepted
        {"source_quote": "metformin reduced HbA1c by 0.5%"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_quote_trace_skipped_when_flag_off() -> None:
    """`require_source_trace=False` bypasses the verbatim-quote gate
    along with the field-level traces. Used for dev / testing flows."""
    item = _item(abstract="Metformin reduced HbA1c by 0.5%.")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin prevents dementia in healthy older adults."},
        item=item, pack=_pack(), require_source_trace=False,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_endpoint_swap_rejects() -> None:
    """Day 5.2-fix P1 specific reproduction: the reviewer's exact bypass
    cases. Each shares 2/3 content tokens with the abstract (`metformin`
    + `reduced`) — the bag-of-words 50% threshold accepted them. The
    verbatim-quote gate rejects all three."""
    abstract = "Metformin reduced HbA1c by 0.5% (p=0.003)."
    item = _item(abstract=abstract)
    for endpoint_swap in (
        "Metformin reduced dementia.",
        "Metformin reduced cancer risk.",
        "Metformin reduced mortality.",
    ):
        fact, reason = _validate_proposed(
            {"source_quote": endpoint_swap},
            item=item, pack=_pack(), require_source_trace=True,
        )
        assert fact is None, f"endpoint swap {endpoint_swap!r} accepted!"
        assert reason == "source_quote_not_in_abstract"


def test_validate_proposed_field_trace_runs_when_quote_has_no_pvalue() -> None:
    """Direct exercise of the P1 bug: source_quote has NO p-value, so the
    quote-text p-value check returns None. The structured `p_value` field
    trace must still catch a fabricated value."""
    item = _item(abstract="Metformin reported a modest signal in this study.")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin reported a modest signal", "p_value": "0.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert fact is None
    assert reason == "p_value_field_not_in_source"


# --- Malformed p_value grammar gate (3.2c-fix-2) -------------------------


@pytest.mark.parametrize("malformed", [
    "not reported",
    "NS",
    "ns",
    "n.s.",
    "0",          # no decimal point
    "1.2",        # > 1 and no leading zero — not a p-value form
    "1.0",        # > 1 (also: real abstracts never report p=1.0)
    "abc",        # non-numeric
    "-0.05",      # negative
    "0.",         # decimal point with no digits after
    "p=",         # bare prefix
    "<",          # bare operator
    "0.05.5",     # multiple decimal points
    "3e-5",       # scientific notation — not the verbatim form abstracts use
    "p<.001 (NS)", # extra trailing prose
])
def test_validate_proposed_malformed_p_value_field_rejects(malformed: str) -> None:
    """3.2c-fix-2: malformed p_value field MUST be rejected before source-trace.
    Pre-fix: synthesized 'p=<malformed>' was passed to check_p_value_in_source,
    which returned None (vacuous success) because PVALUE_RE found no
    recognizable tuple. Bypass — the field entered Fact.p_value with no
    actual source check. New grammar gate rejects these before tracing."""
    item = _item(abstract="Effect reported (p=0.003) significantly.")
    fact, reason = _validate_proposed(
        {"source_quote": "Effect reported", "p_value": malformed},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert fact is None, f"expected reject for p_value={malformed!r}"
    assert reason == "p_value_field_not_in_source"


def test_validate_proposed_p_value_field_must_match_operator() -> None:
    """Tracing requires both operator AND digits to match. Abstract has
    `p<0.001`; LLM proposes p_value='=0.001' (different operator)."""
    item = _item(abstract="Effect was significant (p<0.001).")
    fact, reason = _validate_proposed(
        {"source_quote": "Effect was significant", "p_value": "=0.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert fact is None
    assert reason == "p_value_field_not_in_source"


def test_validate_proposed_p_value_field_normalizes_whitespace() -> None:
    """LLM emits 'p = 0.003' with spaces; grammar gate strips them."""
    item = _item(abstract="Effect (p=0.003) was significant.")
    fact, reason = _validate_proposed(
        {"source_quote": "Effect (p=0.003) was significant", "p_value": "p = 0.003"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None


def test_validate_proposed_p_value_field_dot_only_form_accepts() -> None:
    """LLM emits '.001' (no leading zero); grammar gate accepts via 0?\\.NNN."""
    item = _item(abstract="Metformin had a significant effect (p<.001).")
    fact, reason = _validate_proposed(
        {"source_quote": "Metformin had a significant effect", "p_value": "<.001"},
        item=item, pack=_pack(), require_source_trace=True,
    )
    assert reason is None
    assert fact is not None


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
    """Anchored constant — cost_log.json records this for reproducibility.
    Day 10.11 bumped after objective-as-claim filter + prompt strengthening."""
    assert PROMPT_VERSION == "fact-extractor/2026-04-29-day10-12-mechanism-inflation"


# --- extract_facts_from_item ---------------------------------------------


def test_extract_facts_from_item_happy_path() -> None:
    abstract = "Metformin reduced HbA1c by 0.5% (p=0.003) over 12 weeks."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                {
                    "source_quote": "Metformin reduced HbA1c by 0.5%",
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
    accepted gets the valid one; rejected lists the rest with reasons.
    Abstract includes both the "valid" span and the "verb-ban" span as
    verbatim text so each rejection reason fires AT THE EXPECTED layer
    (not at source_quote_not_in_abstract)."""
    item = _item(
        role="registered_pending",
        abstract=(
            "Trial registered older adults at risk of CV events; "
            "investigators recall an earlier paper claimed "
            "'metformin demonstrated benefit' but this trial is "
            "still in the planning stage."
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                # Valid: verbatim span; doesn't trip verb-ban
                {"source_quote": "Trial registered older adults at risk of CV events"},
                {},  # missing source_quote
                "not a dict",
                # Verb-ban: 'demonstrated' is forbidden for registered_pending;
                # this span is verbatim in the abstract so source-quote check
                # passes, then verb-ban catches it.
                {"source_quote": "metformin demonstrated benefit"},
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
    assert accepted[0].claim.startswith("Trial registered")
    assert accepted[0].kind == "protocol"  # pinned from registered_pending
    reasons = sorted(r.reason for r in rejected)
    assert any(r.startswith("verb_ban:") for r in reasons)
    assert "missing_or_empty_source_quote" in reasons
    assert "not_a_dict" in reasons


def test_extract_facts_from_item_dedupes_within_item() -> None:
    """LLM emits two case-different versions of the same verbatim span.
    One survives; the duplicate is logged as 'duplicate_claim'. The
    source_quote check is case-insensitive so both pass that gate."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body({
            "facts": [
                {"source_quote": "Metformin reduced HbA1c"},
                {"source_quote": "METFORMIN REDUCED HBA1C"},  # case-only diff
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
                "facts": [{"source_quote": "aspirin reduced X (p=0.01).", "p_value": "0.01"}],
            }))
        return httpx.Response(200, json=_ok_body({
            "facts": [{"source_quote": "metformin reduced Y (p=0.02).", "p_value": "0.02"}],
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
    # Day 6.1c: ref=1 (published_results) with empty LLM facts list
    # produces a synthetic rejection so the orchestrator can tolerate
    # it as a documented orphan. ref=3 (review) does NOT — review
    # items don't require facts. ref=2 was off_domain (skipped pre-call).
    assert [r.item_ref for r in rejected] == [1]
    assert rejected[0].reason == "llm_returned_empty_facts_for_results_role"
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
            "facts": [{"source_quote": "demonstrated CV benefit."}],
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
