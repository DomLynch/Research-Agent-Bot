"""Fix #20 — section-level citation re-prompt.

Trust spine: when MiMo writes a section that uses background-literature
numerics WITHOUT including the canonical citation in the same sentence,
the writer must do ONE re-prompt asking MiMo to add the citation IN
the same sentence (rather than letting the Stage-2 auto-fixer strip
the sentence and tank Q9 numeric density).

Tests use `asyncio.run()` rather than @pytest.mark.asyncio so they
do NOT require pytest-asyncio in the dev environment — the prior
decorator-based tests silently no-op'd on machines without
pytest-asyncio installed (6 failures in
tests/test_paper_writer_citations.py)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from agent.paper_writer_citations import (
    build_background_lit_block,
    build_citation_fix_prompt,
    check_unsourced_background_uses,
    run_citation_fix_pass,
)
from agent.synthesis_schemas import SynthesisSection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import background_literature as bg  # noqa: E402


def _run_async(coro):
    """Wrap an async coroutine for sync test execution. Avoids
    requiring pytest-asyncio in the dev environment."""
    return asyncio.run(coro)


def _entry(
    *, key: str = "gait", numeric: str = "0.8 m/s",
    citation_token: str = "Studenski 2011",
    context: str = "frailty walk-speed cutoff",
) -> bg.BackgroundLitEntry:
    return bg.BackgroundLitEntry(
        key=key, numeric=numeric, context=context,
        citation_token=citation_token,
        canonical_reference="Studenski et al. JAMA 2011.",
    )


# ----- check_unsourced_background_uses -----------------------------------


def test_unsourced_check_returns_empty_when_no_entries() -> None:
    """No registry → no checks possible. Pure no-op."""
    paper = "Walk-speed below 0.8 m/s indicates frailty."
    assert check_unsourced_background_uses(paper, None) == []
    assert check_unsourced_background_uses(paper, []) == []


def test_unsourced_check_finds_uncited_use() -> None:
    """Numeric in body, citation NOT in same sentence → flagged."""
    paper = "Walk-speed below 0.8 m/s indicates frailty risk."
    issues = check_unsourced_background_uses(paper, [_entry()])
    assert len(issues) == 1
    numeric, cite, _snippet = issues[0]
    assert numeric == "0.8 m/s"
    assert cite == "Studenski 2011"


def test_unsourced_check_admits_when_cited_in_same_sentence() -> None:
    """Numeric + citation in same sentence → admitted (clean)."""
    paper = "Walk-speed below 0.8 m/s (Studenski 2011) indicates frailty."
    assert check_unsourced_background_uses(paper, [_entry()]) == []


# ----- build_citation_fix_prompt -----------------------------------------


def test_fix_prompt_includes_every_issue() -> None:
    """Each (numeric, cite, snippet) tuple must appear in the prompt
    so MiMo can match its prior text against the required fix."""
    base = "Topic: metformin\n\nReceipts: ..."
    issues = [
        ("0.8 m/s", "Studenski 2011", "Walk-speed below 0.8 m/s ..."),
        ("7%", "ADA 2024", "HbA1c targets below 7% ..."),
    ]
    prompt = build_citation_fix_prompt(base, issues)
    assert base in prompt  # original prompt preserved
    assert "0.8 m/s" in prompt
    assert "Studenski 2011" in prompt
    assert "7%" in prompt
    assert "ADA 2024" in prompt
    assert "SAME sentence" in prompt
    # Concrete example matters — without one MiMo gets clever
    assert "Walk-speed below 0.8 m/s" in prompt


def test_fix_prompt_tells_writer_not_to_delete_numerics() -> None:
    """Load-bearing — the WHOLE POINT of Fix #20 is to KEEP the
    numeric in (so Q9 density holds) while adding the citation. If
    MiMo deletes the numeric, we lose density and gain nothing over
    the auto-fixer's strip behaviour."""
    prompt = build_citation_fix_prompt(
        "base", [("0.8 m/s", "Studenski 2011", "snippet")],
    )
    # Should explicitly instruct against deletion
    assert "do NOT delete" in prompt or "KEEP the numerics" in prompt


# ----- run_citation_fix_pass ---------------------------------------------


def test_fix_pass_returns_input_when_no_entries() -> None:
    """Empty registry → no work done, return original section."""
    section = SynthesisSection(
        name="background", body_md="## Background\n\nfine.",
        anchors=(),
    )

    async def _never_called(**_kwargs):
        raise AssertionError("LLM must not be called when no entries")

    result = _run_async(run_citation_fix_pass(
        section, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: None,
        background_lit_entries=None,
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_never_called,
    ))
    assert result is section


def test_fix_pass_returns_input_when_section_clean() -> None:
    """Clean section (citation present) → no LLM call, return as-is."""
    section = SynthesisSection(
        name="background",
        body_md="## Background\n\nWalk-speed below 0.8 m/s "
                "(Studenski 2011) indicates frailty.",
        anchors=(),
    )

    async def _never_called(**_kwargs):
        raise AssertionError("LLM must not be called when section clean")

    result = _run_async(run_citation_fix_pass(
        section, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: None,
        background_lit_entries=[_entry()],
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_never_called,
    ))
    assert result is section


def test_fix_pass_returns_improved_when_llm_fixes_it() -> None:
    """Bad section → LLM called → improved section returned."""
    bad = SynthesisSection(
        name="background",
        body_md="## Background\n\nWalk-speed below 0.8 m/s "
                "indicates frailty.",
        anchors=(),
    )
    fixed_md = ("## Background\n\nWalk-speed below 0.8 m/s "
                "(Studenski 2011) indicates frailty.")
    fixed = SynthesisSection(
        name="background", body_md=fixed_md, anchors=(),
    )

    call_count = {"n": 0}

    async def _fake_llm(**_kwargs):
        call_count["n"] += 1
        return {"parsed": "ok"}

    result = _run_async(run_citation_fix_pass(
        bad, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: fixed,
        background_lit_entries=[_entry()],
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_fake_llm,
    ))
    assert result is fixed
    assert call_count["n"] == 1, "should be exactly 1 fix-pass call"


def test_fix_pass_returns_original_when_llm_fails_to_improve() -> None:
    """LLM returns a section that's just-as-bad → keep original.

    Defends against the LLM rewriting in a way that changes meaning
    but doesn't actually fix the citation problem."""
    bad = SynthesisSection(
        name="background",
        body_md="## Background\n\n0.8 m/s walk-speed cutoff applies.",
        anchors=(),
    )
    still_bad = SynthesisSection(
        name="background",
        body_md="## Background\n\nGait speed of 0.8 m/s is the cutoff.",
        anchors=(),
    )

    async def _fake_llm(**_kwargs):
        return {"parsed": "ok"}

    result = _run_async(run_citation_fix_pass(
        bad, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: still_bad,
        background_lit_entries=[_entry()],
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_fake_llm,
    ))
    # Same issue count → keep original (don't accept LLM rewrite)
    assert result is bad


def test_fix_pass_returns_original_when_llm_returns_none() -> None:
    """LLM timeout / malformed JSON → fall back to original section."""
    bad = SynthesisSection(
        name="background",
        body_md="## Background\n\n0.8 m/s walk-speed cutoff.",
        anchors=(),
    )

    async def _fake_llm(**_kwargs):
        return None  # timeout / malformed

    result = _run_async(run_citation_fix_pass(
        bad, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: None,
        background_lit_entries=[_entry()],
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_fake_llm,
    ))
    assert result is bad


def test_fix_pass_only_calls_llm_once() -> None:
    """Cap = 1 attempt. Even if the fix attempt also fails to improve,
    we don't loop. Cost containment + Stage-2 auto-fixer still acts as
    safety net."""
    bad = SynthesisSection(
        name="background",
        body_md="## Background\n\n0.8 m/s used badly.",
        anchors=(),
    )
    call_count = {"n": 0}

    async def _fake_llm(**_kwargs):
        call_count["n"] += 1
        return {"parsed": "ok"}

    _run_async(run_citation_fix_pass(
        bad, base_user_prompt="x", system_prompt="y",
        builder_fn=lambda _p: bad,  # builder returns original = no improvement
        background_lit_entries=[_entry()],
        chain=(), client=None, ledger=None, seed=None,
        call_llm_fn=_fake_llm,
    ))
    assert call_count["n"] == 1


# ----- regression: background-block formatting (Fix #18a coverage) --------


def test_background_lit_block_empty_for_no_entries() -> None:
    """Re-export check after extraction to paper_writer_citations."""
    assert build_background_lit_block(None) == ""
    assert build_background_lit_block([]) == ""


def test_background_lit_block_emits_required_fields() -> None:
    """Each entry surfaces numeric + citation_token + use rule."""
    block = build_background_lit_block([_entry()])
    assert "0.8 m/s" in block
    assert "Studenski 2011" in block
    assert "frailty walk-speed cutoff" in block
    assert "SAME sentence" in block or "same sentence" in block
