"""Fix #49 — Grok agent-to-agent repair loop.

When the smart-gate flags a Grok P1 patch, the orchestrator
re-prompts Grok with the rejection reason and asks for a safer
alternative. After _MAX_REPAIR_ROUNDS rounds, any still-flagged P1
gets auto-stripped (BEFORE region deleted). Pipeline never resigns
to 'human review'."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402
import grok_reviewer as gr  # noqa: E402
import run_v06_synthesis as orch  # noqa: E402


# ============ _build_repair_prompt ====================================


def test_repair_prompt_lists_each_rejected_patch() -> None:
    """The repair prompt lists every rejected patch with its
    rejection reason so Grok can target a fix."""
    @dataclass
    class _P:
        id: str = "P-X"
        patch_type: str = "claim"
        severity: str = "P1"
        before: str = "metformin extended lifespan"
        after: str = "metformin reduced mortality"
    flagged = [
        (_P(), "AFTER introduces new content word(s) ['mortality']"),
    ]
    system, user = gr._build_repair_prompt(flagged, "## Test\n\nfoo.\n")
    # System lists the smart-gate constraints
    assert "smart-gate REJECTED" in system
    assert "deletions" in system or "deletion" in system.lower()
    # User has the rejected patch + its rejection reason
    assert "P-X" in user
    assert "metformin extended lifespan" in user
    assert "introduces new content word" in user


def test_repair_prompt_allows_unfixable_response() -> None:
    """The prompt explicitly tells Grok it can return
    `patch_type='unfixable'` if no safe edit exists."""
    @dataclass
    class _P:
        id: str = "P-X"
        patch_type: str = "claim"
        severity: str = "P1"
        before: str = "x"
        after: str = "y"
    system, _user = gr._build_repair_prompt(
        [(_P(), "test")], "paper",
    )
    assert "unfixable" in system


def test_repair_returns_empty_for_no_input() -> None:
    """Empty flagged list → returns empty list immediately
    (no LLM call)."""
    out = asyncio.run(gr.repair_flagged_patches([], "paper"))
    assert out == []


def test_repair_prompt_accepts_patch_result_id_field() -> None:
    """Fix #51: the repair prompt builder must accept BOTH
    apply_patches.PatchResult (`.patch_id`) and TypedPatch (`.id`).
    Pre-Fix-#51 the orchestrator crashed with `'PatchResult' object
    has no attribute 'id'` because the helper used `p.id`."""
    pr = ap.PatchResult(
        patch_id="P-FROM-RESULT", patch_type="claim",
        severity="P1", decision="flagged",
        reason_for_decision="ambiguous",
        before="some text", after="",
    )
    flagged = [(pr, "test rejection reason")]
    # Should not crash — uses .patch_id when .id is missing
    system, user = gr._build_repair_prompt(flagged, "paper")
    assert "P-FROM-RESULT" in user
    assert "test rejection reason" in user


# ============ _agent_repair_loop ======================================


def test_repair_loop_returns_input_when_no_flagged() -> None:
    """No flagged P1s → repair loop is a no-op."""
    results = [
        ap.PatchResult(
            patch_id="P1", patch_type="formatting",
            severity="P3", decision="applied",
            reason_for_decision="ok",
            before="x", after="y",
        ),
    ]

    async def _go():
        return await orch._agent_repair_loop(
            paper_md="paper", results=results, manifest={},
        )
    paper, results_out = asyncio.run(_go())
    assert paper == "paper"
    assert results_out is results


def test_repair_loop_auto_strips_remaining_flagged_p1(monkeypatch) -> None:
    """End-of-loop fallback: if Grok's repair attempts also fail
    (or no API key), the loop auto-strips the BEFORE region for
    each still-flagged P1. Pure deletion; the BEFORE must appear
    exactly once in the paper."""
    paper = (
        "## Discussion\n\n"
        "Metformin clearly extends lifespan in humans. "
        "Other content here.\n"
    )
    results = [
        ap.PatchResult(
            patch_id="P-flag", patch_type="claim", severity="P1",
            decision="flagged",
            reason_for_decision="claim smart-gate: simplification FAIL",
            before="Metformin clearly extends lifespan in humans.",
            after="Metformin extends lifespan in mice.",
        ),
    ]

    # Stub out the Grok call so the repair loop falls straight
    # through to the auto-strip pass.
    async def _stub(*_args, **_kwargs):
        return []  # Grok says 'no fix possible'
    monkeypatch.setattr(
        orch._final_reviewer, "repair_flagged_patches", _stub,
    )

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper, results=results, manifest={},
        )
    new_paper, new_results = asyncio.run(_go())
    # BEFORE region was stripped
    assert "Metformin clearly extends lifespan in humans." not in (
        new_paper
    )
    # The result is tagged auto_stripped
    stripped = [r for r in new_results if r.decision == "auto_stripped"]
    assert len(stripped) == 1
    assert "AGENT-AUTO-STRIP" in stripped[0].reason_for_decision


def test_repair_loop_skips_strip_when_before_not_unique(
    monkeypatch,
) -> None:
    """Safety: if BEFORE appears multiple times in the paper, the
    auto-strip refuses (would over-delete). Result stays 'flagged'
    so the verdict honestly reflects the unresolved state."""
    paper = (
        "## A\n\nrepeated text here.\n\n"
        "## B\n\nrepeated text here.\n"
    )
    results = [
        ap.PatchResult(
            patch_id="P-amb", patch_type="claim", severity="P1",
            decision="flagged",
            reason_for_decision="ambiguous",
            before="repeated text here.",
            after="",
        ),
    ]

    async def _stub(*_args, **_kwargs):
        return []
    monkeypatch.setattr(
        orch._final_reviewer, "repair_flagged_patches", _stub,
    )

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper, results=results, manifest={},
        )
    new_paper, new_results = asyncio.run(_go())
    # Paper unchanged — strip refused
    assert new_paper == paper
    # Result still flagged
    assert new_results[0].decision == "flagged"


def test_repair_loop_caps_at_max_rounds(monkeypatch) -> None:
    """Safety: the loop stops after _MAX_REPAIR_ROUNDS to prevent
    runaway LLM cost on a stubborn Grok."""
    paper = "## Test\n\nx.\n"
    results = [
        ap.PatchResult(
            patch_id="P-stuck", patch_type="claim", severity="P1",
            decision="flagged",
            reason_for_decision="test",
            before="x.", after="y.",  # introduces 'y' = new content
        ),
    ]
    call_count = {"n": 0}

    async def _stuck_stub(flagged, paper_md, **_kwargs):
        call_count["n"] += 1

        @dataclass
        class _TP:
            id: str = "P-stuck"
            patch_type: str = "claim"
            severity: str = "P1"
            location: str = ""
            before: str = "x."
            after: str = "y."  # still new content; gate re-rejects
            reason: str = "stuck"
            auto_applicable: bool = False
            requires_trace: bool = False
        return [_TP()]

    monkeypatch.setattr(
        orch._final_reviewer, "repair_flagged_patches", _stuck_stub,
    )

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper, results=results, manifest={},
        )
    asyncio.run(_go())
    # Capped at _MAX_REPAIR_ROUNDS calls
    assert call_count["n"] <= orch._MAX_REPAIR_ROUNDS
