from __future__ import annotations

import asyncio
from typing import cast

import pytest

from agent import paper_writer_backstop as backstop
from agent.synthesis_schemas import SectionName, SynthesisSection, SynthesisThesis


def _section(name: str, words: int) -> SynthesisSection:
    section_name = cast(SectionName, name)
    return SynthesisSection(
        name=section_name,
        body_md=f"## {name}\n\n" + "word " * words,
        anchors=(),
    )


def test_discussion_quality_repair_adds_required_markers() -> None:
    section = SynthesisSection(
        name="discussion",
        body_md="## Discussion\n\nThe evidence remains mixed across outcomes.\n",
        anchors=(),
    )
    thesis = SynthesisThesis(
        text="carnosine has bounded anti-glycation evidence",
        receipt_ids_referenced=(),
        tensions_addressed=(),
        rejected_candidates=(),
        picker_rationale="test",
    )

    repaired = backstop.repair_discussion_minimum_quality(section, thesis)

    assert "**Thesis:** carnosine has bounded anti-glycation evidence." in repaired.body_md
    assert "**Resolution criteria:**" in repaired.body_md


@pytest.mark.asyncio
async def test_backstop_timeout_keeps_existing_section(monkeypatch) -> None:
    monkeypatch.setattr(backstop, "BACKSTOP_CALL_TIMEOUT_SEC", 0.01)

    async def slow_write_scoped(**_kwargs):
        await asyncio.sleep(1)
        return _section("discussion", 1000)

    sections: dict[SectionName, SynthesisSection] = {"discussion": _section("discussion", 10)}
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

    sections: dict[SectionName, SynthesisSection] = {"discussion": _section("discussion", 10)}
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
