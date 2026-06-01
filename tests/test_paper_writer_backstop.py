from __future__ import annotations

import asyncio
from typing import cast

import pytest

from agent import paper_writer_backstop as backstop
from agent.synthesis_schemas import ReceiptSummary, SectionName, SynthesisSection, SynthesisThesis, TensionMatrix


def _section(name: str, words: int) -> SynthesisSection:
    section_name = cast(SectionName, name)
    return SynthesisSection(
        name=section_name,
        body_md=f"## {name}\n\n" + "word " * words,
        anchors=(),
    )


def _receipt(rid: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid,
        receipt_path=f"runs/{rid}",
        topic="glycation_ages",
        thesis_text="bounded glycation evidence",
        spar_verdict="accept_clean",
        n_claims=4,
        n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier="A1",
        directness="direct",
        outcome_class="cardiometabolic",
        effect_direction="mixed",
        p_values=("p=0.01",),
        population_summary="older adults",
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


def test_discussion_quality_repair_handles_empty_discussion() -> None:
    section = SynthesisSection(
        name="discussion",
        body_md="## Discussion\n\n",
        anchors=(),
    )
    thesis = SynthesisThesis(
        text="",
        receipt_ids_referenced=(),
        tensions_addressed=(),
        rejected_candidates=(),
        picker_rationale="test",
    )

    repaired = backstop.repair_discussion_minimum_quality(section, thesis)

    assert repaired.body_md.startswith("## Discussion\n\n**Thesis:**")
    assert "bounded interpretation" in repaired.body_md
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


@pytest.mark.asyncio
async def test_backstop_appends_conclusion_anchor_when_rerender_does_not_improve() -> None:
    async def write_scoped(**kwargs):
        return _section(kwargs["name"], 10)

    sections: dict[SectionName, SynthesisSection] = {"conclusion": _section("conclusion", 10)}
    receipts = (_receipt("r1"), _receipt("r2"))
    out = await backstop.apply_section_backstop(
        sections,
        user_prompt="u",
        section_prompts={"conclusion": "s"},
        topic="glycation_ages",
        accepted=receipts,
        matrix=TensionMatrix(receipts=receipts, pairs=()),
        chain=(),
        client=None,
        ledger=None,
        seed=None,
        background_lit_entries=None,
        write_anchored_fn=None,
        write_scoped_fn=write_scoped,
    )

    assert "### Bounded conclusion" in out["conclusion"].body_md
    assert backstop._section_word_count(out["conclusion"]) >= backstop.AUDIT_GATED_FLOORS["conclusion"]
