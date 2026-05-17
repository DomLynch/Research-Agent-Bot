"""Reviewer repair-loop tests.

The runtime keeps one final reviewer. If a proposed P1 patch fails the
deterministic smart gate, the reviewer gets a bounded repair attempt; any
remaining unique offending region is deleted fail-closed.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # type: ignore[import-not-found]  # noqa: E402
import grok_reviewer as gr  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as orch  # type: ignore[import-not-found]  # noqa: E402


def test_repair_prompt_lists_each_rejected_patch() -> None:
    @dataclass
    class _P:
        id: str = "P-X"
        patch_type: str = "claim"
        severity: str = "P1"
        before: str = "metformin extended lifespan"
        after: str = "metformin reduced mortality"

    system, user = gr._build_repair_prompt(
        [(_P(), "AFTER introduces new content word(s) ['mortality']")],
        "## Test\n\nfoo.\n",
    )
    assert "smart-gate REJECTED" in system
    assert "deletions" in system or "deletion" in system.lower()
    assert "P-X" in user
    assert "metformin extended lifespan" in user
    assert "introduces new content word" in user


def test_repair_prompt_allows_unfixable_response() -> None:
    @dataclass
    class _P:
        id: str = "P-X"
        patch_type: str = "claim"
        severity: str = "P1"
        before: str = "x"
        after: str = "y"

    system, _user = gr._build_repair_prompt([(_P(), "test")], "paper")
    assert "unfixable" in system


def test_repair_returns_empty_for_no_input() -> None:
    assert asyncio.run(gr.repair_flagged_patches([], "paper")) == []


def test_repair_prompt_accepts_patch_result_id_field() -> None:
    pr = ap.PatchResult(
        patch_id="P-FROM-RESULT",
        patch_type="claim",
        severity="P1",
        decision="flagged",
        reason_for_decision="ambiguous",
        before="some text",
        after="",
    )
    _system, user = gr._build_repair_prompt([(pr, "test rejection reason")], "paper")
    assert "P-FROM-RESULT" in user
    assert "test rejection reason" in user


def test_repair_loop_returns_input_when_no_flagged() -> None:
    results = [
        ap.PatchResult(
            patch_id="P1",
            patch_type="formatting",
            severity="P3",
            decision="applied",
            reason_for_decision="ok",
            before="x",
            after="y",
        ),
    ]

    async def _go():
        return await orch._agent_repair_loop(
            paper_md="paper",
            results=results,
            manifest={},
        )

    paper, results_out = asyncio.run(_go())
    assert paper == "paper"
    assert results_out is results


def test_repair_loop_auto_strips_remaining_flagged_p1(monkeypatch) -> None:
    paper = (
        "## Discussion\n\n"
        "Metformin clearly extends lifespan in humans. Other content here.\n"
    )
    results = [
        ap.PatchResult(
            patch_id="P-flag",
            patch_type="claim",
            severity="P1",
            decision="flagged",
            reason_for_decision="claim smart-gate: simplification FAIL",
            before="Metformin clearly extends lifespan in humans.",
            after="Metformin extends lifespan in mice.",
        ),
    ]

    async def _stub(*_args, **_kwargs):
        return []

    monkeypatch.setattr(orch._final_reviewer, "repair_flagged_patches", _stub)

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper,
            results=results,
            manifest={},
        )

    new_paper, new_results = asyncio.run(_go())
    assert "Metformin clearly extends lifespan in humans." not in new_paper
    stripped = [r for r in new_results if r.decision == "auto_stripped"]
    assert len(stripped) == 1
    assert "AGENT-AUTO-STRIP" in stripped[0].reason_for_decision


def test_repair_loop_skips_strip_when_before_not_unique(monkeypatch) -> None:
    paper = "## A\n\nrepeated text here.\n\n## B\n\nrepeated text here.\n"
    results = [
        ap.PatchResult(
            patch_id="P-amb",
            patch_type="claim",
            severity="P1",
            decision="flagged",
            reason_for_decision="ambiguous",
            before="repeated text here.",
            after="",
        ),
    ]

    async def _stub(*_args, **_kwargs):
        return []

    monkeypatch.setattr(orch._final_reviewer, "repair_flagged_patches", _stub)

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper,
            results=results,
            manifest={},
        )

    new_paper, new_results = asyncio.run(_go())
    assert new_paper == paper
    assert new_results[0].decision == "flagged"


def test_repair_loop_caps_at_max_rounds(monkeypatch) -> None:
    paper = "## Test\n\nx.\n"
    results = [
        ap.PatchResult(
            patch_id="P-stuck",
            patch_type="claim",
            severity="P1",
            decision="flagged",
            reason_for_decision="test",
            before="x.",
            after="y.",
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
            after: str = "y."
            reason: str = "stuck"
            auto_applicable: bool = False
            requires_trace: bool = False

        return [_TP()]

    monkeypatch.setattr(orch._final_reviewer, "repair_flagged_patches", _stuck_stub)

    async def _go():
        return await orch._agent_repair_loop(
            paper_md=paper,
            results=results,
            manifest={},
        )

    asyncio.run(_go())
    assert call_count["n"] <= orch._MAX_REPAIR_ROUNDS
