"""Tests for qa.py — typed validation gates."""
from __future__ import annotations


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
        sections={"findings": ["The trial conclusively demonstrated efficacy [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "mechanistic_definitive_claim" for f in fails)


def test_role_consistency_does_not_fire_on_legitimate_hedging():
    """Tightened mechanistic regex: 'definitive human trials are needed' is
    a legitimate limitation, not a banned efficacy claim."""
    item = _item(1, "mechanistic", "in vitro study.")
    d = _draft(
        sections={"limitations": ["Definitive human trials are needed [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert not any(f.code == "mechanistic_definitive_claim" for f in fails)


# --- gate_role_prose_consistency: INVERSE direction (P0 audit fix) --------


def test_role_consistency_blocks_results_described_as_pending():
    """Inverse rapamycin bug: a published_results paper described as if its
    results are still pending/awaited. Both directions must be caught."""
    item = _item(1, "published_results", "Trial reported mortality reduction.")
    d = _draft(
        sections={"findings": ["The trial results are not yet reported [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "results_described_as_pending" for f in fails), (
        f"expected results_described_as_pending, got {[f.code for f in fails]}"
    )


def test_role_consistency_blocks_results_called_upcoming():
    item = _item(1, "published_results", "Trial reported X.")
    d = _draft(
        sections={"findings": ["This upcoming trial will examine X [1]."]},
        bundle=[item],
    )
    fails = gate_role_prose_consistency(d, {1: item})
    assert any(f.code == "results_described_as_pending" for f in fails)


def test_role_consistency_passes_for_published_results_described_as_results():
    item = _item(1, "published_results", "Trial reduced X by 22% (p=0.01).")
    d = _draft(
        sections={"findings": ["The trial showed X fell by 22% [1]."]},
        bundle=[item],
    )
    assert not gate_role_prose_consistency(d, {1: item})


# --- gate_invariants_hold: type-level spine (P1 audit fix) ----------------


def test_invariants_block_when_prose_kind_disagrees_with_role_protocol():
    """Prose says outcome ('22% (p=0.01)') -> infers kind=result. Bundle says
    role=published_protocol. assert_invariants raises -> gate fails."""
    item = _item(1, "published_protocol", "study protocol.")
    d = _draft(
        sections={"findings": ["The trial reduced X by 22% (p=0.01) [1]."]},
        bundle=[item],
    )
    from agent.qa import gate_invariants_hold
    fails = gate_invariants_hold(d, {1: item})
    assert any(f.code == "invariant_violation" for f in fails)


def test_invariants_block_when_prose_kind_disagrees_with_role_results():
    """Prose says pending -> infers kind=protocol. Bundle says
    role=published_results. assert_invariants raises -> gate fails."""
    item = _item(1, "published_results", "Trial reported X.")
    d = _draft(
        sections={"findings": ["Trial results are not yet reported [1]."]},
        bundle=[item],
    )
    from agent.qa import gate_invariants_hold
    fails = gate_invariants_hold(d, {1: item})
    assert any(f.code == "invariant_violation" for f in fails)


def test_invariants_pass_when_prose_kind_matches_role():
    item = _item(1, "published_results", "Trial reduced X by 22% (p=0.01).")
    d = _draft(
        sections={"findings": ["Trial showed X fell 22% [1]."]},
        bundle=[item],
    )
    from agent.qa import gate_invariants_hold
    assert not gate_invariants_hold(d, {1: item})
    # Bonus: facts populated as a side effect
    assert d.facts
    assert d.facts[0].kind == "result"
    assert d.facts[0].ref == 1


def test_invariants_allow_pending_lang_on_mechanistic():
    """A mechanistic ref correctly hedged as 'pending/investigating' is
    legitimate context, not an invariant violation. Caught live in the
    metformin run where the classifier mis-classified a real RCT as
    mechanistic — the LLM hedged correctly and shouldn't be punished."""
    item = _item(1, "mechanistic", "trial of metformin in older adults.")
    d = _draft(
        sections={"findings": ["A pilot trial is investigating metformin's effect on epigenetic age, with results pending [1]."]},
        bundle=[item],
    )
    from agent.qa import gate_invariants_hold
    assert not gate_invariants_hold(d, {1: item})


def test_invariants_skip_uncited_bundle_items():
    """Reverse-direction completeness check applies only to CITED refs,
    so a bundle with 5 results papers and the LLM only cites 1 doesn't fail."""
    bundle = [
        _item(1, "published_results", "trial 1 reduced X by 22%."),
        _item(2, "published_results", "trial 2 reduced Y by 18%."),
        _item(3, "published_results", "trial 3 reduced Z by 12%."),
    ]
    d = _draft(
        sections={"findings": ["Only [1] reduced X by 22%."]},  # only [1] cited
        bundle=bundle,
    )
    from agent.qa import gate_invariants_hold
    assert not gate_invariants_hold(d, {it.source.ref: it for it in bundle})


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
