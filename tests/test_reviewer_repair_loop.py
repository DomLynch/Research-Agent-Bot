"""Reviewer repair-loop tests.

The runtime keeps one final reviewer. If a proposed P1 patch fails the
deterministic smart gate, the reviewer gets a bounded repair attempt; any
remaining unique offending region is deleted fail-closed.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # type: ignore[import-not-found]  # noqa: E402
import final_reviewer as gr  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as orch  # type: ignore[import-not-found]  # noqa: E402


def test_post_pipeline_passes_configured_final_reviewer_model(tmp_path: Path, monkeypatch) -> None:
    class _StopAfterReviewer(Exception):
        pass

    captured: dict[str, str | None] = {}
    paper_path = tmp_path / "full_paper.md"
    paper_path.write_text("## Abstract\n\nBounded paper.\n")
    monkeypatch.setenv("FINAL_LAYER_REVIEWER_MODEL", "google/gemma-4-31b-it")
    monkeypatch.setattr(orch._audit_v06, "audit", lambda *_a, **_k: {"checks": []})
    monkeypatch.setattr(orch._audit_v06, "_format_summary", lambda *_a, **_k: "audit")
    monkeypatch.setattr(orch._paper_quality, "apply_template_repairs", lambda paper: (paper, []))

    async def _review(*_args, **kwargs):
        captured["model"] = kwargs.get("model")
        raise _StopAfterReviewer

    monkeypatch.setattr(orch._final_reviewer, "review_paper", _review)

    async def _go() -> None:
        await orch._run_post_paper_pipeline(
            paper_path=paper_path,
            manifest={"review_type": "thin_corpus_brief"},
            out_dir=tmp_path,
        )

    try:
        asyncio.run(_go())
    except _StopAfterReviewer:
        pass

    assert captured["model"] == "google/gemma-4-31b-it"


def test_revision_feedback_env_writes_sidecar_before_finalizer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "  Add severity-level explanation.   ")

    orch._write_revision_feedback_sidecar(tmp_path)

    assert json.loads((tmp_path / "researka_revision_request.json").read_text()) == {
        "feedback": "Add severity-level explanation.",
    }


def test_revision_feedback_env_does_not_overwrite_existing_sidecar(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "researka_revision_request.json"
    path.write_text(json.dumps({"feedback": "existing", "artifactId": "art_1"}))
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "new feedback")

    orch._write_revision_feedback_sidecar(tmp_path)

    assert json.loads(path.read_text()) == {"feedback": "existing", "artifactId": "art_1"}


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
