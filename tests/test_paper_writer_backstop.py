from __future__ import annotations

import asyncio

import pytest

from agent import paper_writer_backstop as backstop
from agent.synthesis_schemas import SynthesisSection


def _section(name: str, words: int) -> SynthesisSection:
    return SynthesisSection(
        name=name,
        body_md=f"## {name}\n\n" + "word " * words,
        anchors=(),
    )


@pytest.mark.asyncio
async def test_backstop_timeout_keeps_existing_section(monkeypatch) -> None:
    monkeypatch.setattr(backstop, "BACKSTOP_CALL_TIMEOUT_SEC", 0.01)

    async def slow_write_scoped(**_kwargs):
        await asyncio.sleep(1)
        return _section("discussion", 1000)

    sections = {"discussion": _section("discussion", 10)}
    out = await backstop.apply_section_backstop(
        sections,
        user_prompt="u",
        section_prompts={"discussion": "s"},
        topic="rapamycin",
        accepted=(),
        matrix=None,
        chain=(),
        client=None,
        ledger=None,
        seed=None,
        background_lit_entries=None,
        write_anchored_fn=None,
        write_scoped_fn=slow_write_scoped,
    )

    assert out["discussion"].body_md == sections["discussion"].body_md


@pytest.mark.asyncio
async def test_backstop_accepts_longer_section() -> None:
    async def write_scoped(**_kwargs):
        return _section("discussion", 900)

    sections = {"discussion": _section("discussion", 10)}
    out = await backstop.apply_section_backstop(
        sections,
        user_prompt="u",
        section_prompts={"discussion": "s"},
        topic="rapamycin",
        accepted=(),
        matrix=None,
        chain=(),
        client=None,
        ledger=None,
        seed=None,
        background_lit_entries=None,
        write_anchored_fn=None,
        write_scoped_fn=write_scoped,
    )

    assert "word " * 900 in out["discussion"].body_md
