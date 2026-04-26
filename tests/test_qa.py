"""Tests for qa.py — typed validation gates."""
from __future__ import annotations

import pytest

from agent.qa import (
    REQUIRED_SECTIONS,
    correction_prompt,
    gate_citations_resolve,
    gate_completeness,
    gate_numbers_traceable,
    gate_role_prose_consistency,
    qa,
)
from agent.types import Draft, EvidenceItem, Source


def _src(ref: int) -> Source:
    return Source(ref=ref, title=f"S{ref}", year=2024, url="", source="pubmed")


def _item(ref: int, role, abstract: str = "") -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref),
        abstract=abstract,
        design="rct" if role == "published_results" else "protocol",
        role=role,
        tier="A2",
        direct=True,
        strict=True,
    )


def _draft(
    *,
    title: str = "T",
    abstract: list[str] | None = None,
    sections: dict[str, list[str]] | None = None,
    bundle: list[EvidenceItem] | None = None,
) -> Draft:
    full_sections = {k: ["x [1]."] for k in REQUIRED_SECTIONS}
    if sections:
        full_sections.update(sections)
    return Draft(
        topic="t", domain="d", criteria="",
        title=title,
        abstract=abstract if abstract is not None else ["abstract sentence [1]."],
        sections=full_sections,
        bundle=bundle if bundle is not None else [_item(1, "published_results", "trial reduced X by 22% (p=0.01).")],
        facts=[],
    )


# --- gate_citations_resolve ------------------------------------------------


def test_citations_resolve_passes_for_known_ref():
    d = _draft()
    assert not gate_citations_resolve(d, {1: d.bundle[0]})


def test_citations_resolve_blocks_unknown_ref():
    d = _draft(sections={"introduction": ["this cites [42]."]})
    fails = gate_citations_resolve(d, {1: d.bundle[0]})
    assert any(f.code == "citation_unresolved" for f in fails)


# --- gate_role_prose_consistency (the rapamycin bug class) -----------------


def test_role_consistency_blocks_protocol_described_as_results():
    item = _item(1, "published_protocol", "this is a study protocol.")
    d = _draft(
        sections={"findings": ["The trial showed a 22% reduction [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "protocol_described_as_results" for f in fails)


def test_role_consistency_blocks_registered_described_as_results():
    item = _item(1, "registered_pending", "registered trial.")
    d = _draft(
        sections={"findings": ["The intervention reduced X [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "protocol_described_as_results" for f in fails)


def test_role_consistency_passes_when_protocol_described_as_pending():
    item = _item(1, "published_protocol", "study protocol.")
    d = _draft(
        sections={"findings": ["The trial is pending results [1]."]},
        bundle=[item],
    )
    assert not gate_role_prose_consistency(d, {1: item})


def test_role_consistency_blocks_mechanistic_definitive_claim():
    item = _item(1, "mechanistic", "in vitro study.")
    d = _draft(
        sections={"findings": ["The mechanism is conclusively established [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "mechanistic_definitive_claim" for f in fails)


# --- gate_numbers_traceable ------------------------------------------------


def test_numbers_traceable_passes_when_number_in_abstract():
    item = _item(1, "published_results", "Mortality reduced by 22% (p=0.01).")
    d = _draft(
        sections={"findings": ["Mortality fell by 22% in the cited trial [1]."]},
        bundle=[item],
    )
    assert not gate_numbers_traceable(d, {1: item})


def test_numbers_traceable_blocks_invented_number():
    item = _item(1, "published_results", "Mortality reduced by 22% (p=0.01).")
    d = _draft(
        sections={"findings": ["Mortality fell by 47% [1]."]},  # 47% not in abstract
        bundle=[item],
    )
    fails = gate_numbers_traceable(d, {1: item})
    assert any(f.code == "number_not_in_source" for f in fails)


def test_numbers_traceable_blocks_uncited_number():
    item = _item(1, "published_results", "abstract.")
    d = _draft(
        sections={"findings": ["Mortality fell by 22%."]},  # no [N]
        bundle=[item],
    )
    fails = gate_numbers_traceable(d, {1: item})
    assert any(f.code == "number_uncited" for f in fails)


# --- gate_completeness -----------------------------------------------------


def test_completeness_blocks_empty_title():
    d = _draft(title="")
    fails = gate_completeness(d)
    assert any(f.code == "title_empty" for f in fails)


def test_completeness_blocks_missing_section():
    d = _draft(sections={"introduction": []})  # empty intro
    fails = gate_completeness(d)
    assert any(f.code == "section_missing" for f in fails)


def test_completeness_passes_when_all_present():
    d = _draft()
    assert not gate_completeness(d)


# --- qa() integration ------------------------------------------------------


def test_qa_approves_clean_draft():
    item = _item(1, "published_results", "trial reduced mortality 22% (p=0.01).")
    d = _draft(
        sections={"findings": ["Mortality fell 22% [1]."]},
        bundle=[item],
    )
    result = qa(d)
    assert result.approved is True
    assert result.score["citations"] == 10


def test_qa_rejects_protocol_results_inversion():
    """End-to-end: the rapamycin bug class is rejected by qa()."""
    item = _item(1, "published_protocol", "study protocol.")
    d = _draft(
        sections={"findings": ["The trial showed reduced mortality [1]."]},
        bundle=[item],
    )
    result = qa(d)
    assert result.approved is False


def test_correction_prompt_is_compact_and_actionable():
    item = _item(1, "published_protocol", "protocol.")
    d = _draft(sections={"findings": ["The trial showed X [1]."]}, bundle=[item])
    result = qa(d)
    text = correction_prompt(result.failures)
    assert "[protocol_described_as_results]" in text
    assert "[1]" in text
