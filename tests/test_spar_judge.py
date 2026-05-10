"""Tests for agent.spar_judge — universal SPAR adjudicator.

All tests use deterministic mock callers. No live LLM, no spend.
"""
from __future__ import annotations

import json

import pytest

from agent.spar_judge import (  # type: ignore[import-not-found]
    adjudicate_receipt,
    adjudicate_receipts,
    judge_receipt_prompt,
    parse_judge_response,
)
from agent.synthesis_schemas import ReceiptSummary


def _receipt(rid: str = "PMC1", **kw: object) -> ReceiptSummary:
    """Compact fixture builder. Defaults are domain-agnostic."""
    base: dict = dict(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="generic-topic", thesis_text="A claim summary.",
        spar_verdict="accept_clean",
        n_claims=4, n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function",
        effect_direction="positive",
        p_values=("p<0.05",),
        population_summary="adults aged 18+",
    )
    base.update(kw)
    return ReceiptSummary(**base)  # type: ignore[arg-type]


# ---- Prompt builder ------------------------------------------------------


def test_prompt_is_domain_agnostic() -> None:
    """The system prompt must NOT hardcode biomedical examples — it
    should list multiple domains as anchors per the universal-no-
    hardcoding rule. Whitespace-collapsed match so multi-line wrapped
    domain examples (e.g. 'social\\nscience') still register."""
    import re
    sys_p, user_p = judge_receipt_prompt(_receipt())
    flat = re.sub(r"\s+", " ", sys_p.lower())
    # Cross-domain anchors present (pinned for regression).
    assert "biomedical" in flat
    assert "climate" in flat
    assert "materials" in flat
    assert "economics" in flat
    assert "social science" in flat
    # User block contains the receipt content.
    assert "PMC1" in user_p
    assert "tier=A1" in user_p or "study_design_tier: A1" in user_p
    assert "muscle_function" in user_p


def test_prompt_truncates_thesis_text() -> None:
    """A pathological 10000-char thesis must not blow up the prompt."""
    long = "x" * 10000
    _, user_p = judge_receipt_prompt(_receipt(thesis_text=long))
    # Thesis truncates to 1500 chars per implementation.
    assert len(user_p) < 4000


# ---- Response parser -----------------------------------------------------


def test_parse_accept_clean() -> None:
    raw = json.dumps({"verdict": "accept_clean", "rationale": "no red flags"})
    v = parse_judge_response("PMC1", raw, model="gemma-4")
    assert v.verdict == "accept_clean"
    assert v.fail_soft_default is False
    assert v.judge_model == "gemma-4"


def test_parse_accept_caveated() -> None:
    raw = json.dumps({
        "verdict": "accept_caveated",
        "rationale": "small n=12; downstream prose must hedge",
    })
    v = parse_judge_response("PMC1", raw, model="gemma-4")
    assert v.verdict == "accept_caveated"


def test_parse_each_reject_tag() -> None:
    """All 5 reject tags pass through cleanly."""
    for tag in (
        "reject_fabricated_numbers",
        "reject_direction_mismatch",
        "reject_design_misclassified",
        "reject_internal_contradiction",
        "reject_other",
    ):
        raw = json.dumps({"verdict": tag, "rationale": "x"})
        v = parse_judge_response("PMC1", raw, model="gemma-4")
        assert v.verdict == tag


def test_parse_strips_code_fences() -> None:
    raw = "```json\n" + json.dumps({
        "verdict": "accept_clean", "rationale": "ok"
    }) + "\n```"
    v = parse_judge_response("PMC1", raw, model="g")
    assert v.verdict == "accept_clean"


def test_parse_unknown_verdict_falls_back() -> None:
    raw = json.dumps({"verdict": "maybe", "rationale": "x"})
    v = parse_judge_response("PMC1", raw, model="g")
    assert v.verdict == "accept_clean"
    assert v.fail_soft_default is True
    assert "unknown verdict" in v.rationale


def test_parse_invalid_json_falls_back() -> None:
    v = parse_judge_response("PMC1", "{not json", model="g")
    assert v.verdict == "accept_clean"
    assert v.fail_soft_default is True
    assert "not parseable" in v.rationale


def test_parse_non_object_falls_back() -> None:
    v = parse_judge_response("PMC1", json.dumps(["nope"]), model="g")
    assert v.verdict == "accept_clean"
    assert v.fail_soft_default is True


def test_parse_missing_rationale_uses_placeholder() -> None:
    """Missing rationale shouldn't reject the response — synthesis
    pipeline can still run with an empty rationale."""
    raw = json.dumps({"verdict": "accept_clean"})
    v = parse_judge_response("PMC1", raw, model="g")
    assert v.verdict == "accept_clean"
    assert v.rationale  # non-empty


# ---- adjudicate_receipt with mocked caller -------------------------------


def _mock_caller(verdict: str, rationale: str = "test") -> object:
    """Build an async mock that returns a fixed verdict."""

    async def caller(*, system: str, user: str) -> tuple[str, str, float]:  # noqa: ARG001
        return json.dumps({
            "verdict": verdict, "rationale": rationale,
        }), "mock-model", 0.0001

    return caller


@pytest.mark.asyncio
async def test_adjudicate_receipt_success() -> None:
    v = await adjudicate_receipt(
        _receipt("PMC1"), call=_mock_caller("accept_caveated", "small n"),
    )
    assert v.verdict == "accept_caveated"
    assert v.judge_model == "mock-model"
    assert v.fail_soft_default is False


@pytest.mark.asyncio
async def test_adjudicate_receipt_handles_caller_exception() -> None:
    """LLM down / network blip / API rate limit → fail-soft to accept_clean."""

    async def broken_caller(*, system: str, user: str) -> tuple[str, str, float]:  # noqa: ARG001
        raise RuntimeError("network timeout")

    v = await adjudicate_receipt(_receipt("PMC1"), call=broken_caller)
    assert v.verdict == "accept_clean"
    assert v.fail_soft_default is True
    assert "fail_soft" in v.rationale
    assert "network timeout" in v.rationale


# ---- adjudicate_receipts batch -------------------------------------------


@pytest.mark.asyncio
async def test_adjudicate_batch_returns_new_receipts_with_verdicts() -> None:
    """Batch path returns NEW ReceiptSummary objects with updated
    spar_verdict; originals are not mutated (frozen dataclass).
    Fix #60: also returns the verdict list so callers can compute
    honest n_real_calls / n_fail_soft / verdict_counts."""
    receipts = [_receipt(f"PMC{i}") for i in range(5)]
    out_receipts, out_verdicts = await adjudicate_receipts(
        receipts, call=_mock_caller("accept_caveated"), concurrency=2,
    )
    assert len(out_receipts) == 5
    assert len(out_verdicts) == 5
    for r_in, r_out, v in zip(receipts, out_receipts, out_verdicts):
        assert r_out.receipt_id == r_in.receipt_id
        assert r_out.spar_verdict == "accept_caveated"
        assert v.fail_soft_default is False
    # Originals untouched (frozen → can't even mutate; verify no aliasing).
    for r_in in receipts:
        assert r_in.spar_verdict == "accept_clean"


@pytest.mark.asyncio
async def test_adjudicate_batch_mix_of_verdicts() -> None:
    """A real run will have a distribution of verdicts. The batch driver
    must preserve per-receipt mapping under concurrency."""

    async def per_id_caller(*, system: str, user: str) -> tuple[str, str, float]:  # noqa: ARG001
        if "PMC0" in user:
            v = "accept_clean"
        elif "PMC1" in user:
            v = "accept_caveated"
        elif "PMC2" in user:
            v = "reject_direction_mismatch"
        else:
            v = "accept_clean"
        return json.dumps({"verdict": v, "rationale": "test"}), "mock", 0.0
    receipts = [_receipt(f"PMC{i}") for i in range(3)]
    out_receipts, _ = await adjudicate_receipts(
        receipts, call=per_id_caller, concurrency=3,
    )
    assert out_receipts[0].spar_verdict == "accept_clean"
    assert out_receipts[1].spar_verdict == "accept_caveated"
    assert out_receipts[2].spar_verdict == "reject_direction_mismatch"


@pytest.mark.asyncio
async def test_adjudicate_batch_one_failure_doesnt_break_others() -> None:
    """Per-receipt fail-soft: one broken call does not abort the batch.
    The verdict list distinguishes real verdicts from fail-soft
    fallbacks so the runner can report n_real_calls honestly."""
    call_count = {"n": 0}

    async def flaky_caller(*, system: str, user: str) -> tuple[str, str, float]:  # noqa: ARG001
        call_count["n"] += 1
        if call_count["n"] == 2:  # second call fails
            raise RuntimeError("transient")
        return json.dumps({
            "verdict": "accept_clean", "rationale": "ok",
        }), "mock", 0.0
    receipts = [_receipt(f"PMC{i}") for i in range(3)]
    out_receipts, out_verdicts = await adjudicate_receipts(
        receipts, call=flaky_caller, concurrency=1,
    )
    assert len(out_receipts) == 3
    # All three got verdicts; the failed one is accept_clean (fail-soft).
    assert all(r.spar_verdict == "accept_clean" for r in out_receipts)
    n_fail_soft = sum(1 for v in out_verdicts if v.fail_soft_default)
    assert n_fail_soft == 1, "exactly one fail-soft expected"
    n_real = sum(1 for v in out_verdicts if not v.fail_soft_default)
    assert n_real == 2


@pytest.mark.asyncio
async def test_adjudicate_batch_cache_skips_llm_calls() -> None:
    """Fix #60: cached verdicts must not trigger any LLM call. Cost
    discipline on iterative reruns."""
    from agent.spar_judge import SparJudgeVerdict  # type: ignore[import-not-found]

    call_count = {"n": 0}

    async def counting_caller(*, system: str, user: str) -> tuple[str, str, float]:  # noqa: ARG001
        call_count["n"] += 1
        return json.dumps({
            "verdict": "accept_clean", "rationale": "should not be called",
        }), "mock", 0.0
    cache = {
        "PMC0": SparJudgeVerdict(
            receipt_id="PMC0", verdict="accept_caveated",
            rationale="cached", judge_model="mock-cached",
            fail_soft_default=False,
        ),
    }
    receipts = [_receipt("PMC0"), _receipt("PMC1")]
    out_receipts, _ = await adjudicate_receipts(
        receipts, call=counting_caller, concurrency=2, cache=cache,
    )
    # Only PMC1 hit the LLM; PMC0 served from cache.
    assert call_count["n"] == 1
    assert out_receipts[0].spar_verdict == "accept_caveated"
    assert out_receipts[1].spar_verdict == "accept_clean"


@pytest.mark.asyncio
async def test_adjudicate_batch_empty_input() -> None:
    out_receipts, out_verdicts = await adjudicate_receipts(
        [], call=_mock_caller("accept_clean"),
    )
    assert out_receipts == []
    assert out_verdicts == []


# ---- Judge ≠ writer regression guard -------------------------------------


def test_judge_chain_default_uses_gemma_not_mimo() -> None:
    """The 'judge ≠ writer' memory rule: SPAR judge primary must not
    be the same model family as the writer (MiMo). Guard against a
    settings refactor accidentally pointing JUDGE_MODEL at a MiMo SKU.

    Source-level check: read agent/settings.py and verify the
    JUDGE_MODEL default is not in the MiMo family. Avoids constructing
    Settings (which has many required fields) — the regression we care
    about is the default value, not runtime instantiation."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "agent" / "settings.py"
    text = src.read_text()
    m = re.search(
        r"judge_model\s*=\s*os\.environ\.get\(\s*['\"]JUDGE_MODEL['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        text,
    )
    assert m is not None, "JUDGE_MODEL default not found in agent/settings.py"
    default_judge = m.group(1).lower()
    assert "mimo" not in default_judge, (
        f"JUDGE_MODEL default {default_judge!r} is in the writer's family "
        "— violates the 'never let MiMo grade MiMo' rule."
    )
    assert default_judge, "JUDGE_MODEL default is empty"
