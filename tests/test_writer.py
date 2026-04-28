"""Tests for agent/writer.py — deterministic ClaimGraph renderer.

The writer is now PURELY DETERMINISTIC (Day 4-fix P1) — no LLM call
at write time. Every sentence in the output is a `Claim.text` from the
graph, attached to its `supporting_refs`. The previous LLM-driven
design had a hole the reviewer caught: self-declared `claim_ids`
binding could be valid while the sentence text expressed a novel
claim outside the graph. The deterministic renderer eliminates that
hole entirely.

Tests cover:
- `_make_title` — thesis-derived title formatting
- `_render_claim_with_cites` — claim text + citation appending
- `_sort_key` / `_claims_for_bucket` — within-section ordering
- `_spar_banner` — all 4 verdict shapes + gate_override prominence
- `_render_paper` — full deterministic paper layout
- `_render_rejection` — verdict-driven rejection notice
- `write_paper` end-to-end — verdict routing + return shape
- The reviewer's exact reproduction case: an LLM trying to inject
  "Metformin prevents dementia" can no longer reach the writer at
  all — it's not a Claim.text in the graph, so it's never rendered.
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from agent.schemas import (
    Claim,
    CitationTrace,
    ClaimGraph,
    GateOverride,
    JudgeReview,
    SPARReview,
)
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, Source
from agent.writer import (
    RENDER_VERSION,
    WriterError,
    WriterRejection,
    _claims_for_bucket,
    _make_title,
    _render_claim_with_cites,
    _render_paper,
    _render_rejection,
    _sort_key,
    _spar_banner,
    write_paper,
)


# --- Fixtures -------------------------------------------------------------


def _src(ref: int = 1, *, year: int = 2024, title: str = "Trial paper") -> Source:
    return Source(ref=ref, title=title, year=year, url="https://x", source="pubmed")


def _item(
    ref: int = 1, *,
    role: str = "published_results",
    abstract: str = "Metformin reduced HbA1c by 0.5% (p=0.003).",
    title: str = "Trial paper",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, title=title), abstract=abstract,
        design="rct", role=role,  # type: ignore[arg-type]
        tier="A1", direct=True, strict=True,
    )


def _claim(
    cid: str = "C001", *,
    refs: tuple[int, ...] = (1,),
    text: str = "metformin reduced HbA1c.",
    claim_type: str = "efficacy",
    directness: str = "direct",
    tier: str = "A1",
    confidence: str = "high",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type=claim_type,  # type: ignore[arg-type]
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier=tier,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        attack_surface=(),
    )


def _graph(*claims: Claim) -> ClaimGraph:
    cs = claims or (_claim(),)
    return ClaimGraph(claims=cs, edges=(), thesis_claim_id=cs[0].claim_id)


def _pack() -> TopicPack:
    return TopicPack(
        topic="metformin",
        drug_class="biguanide",
        aliases=frozenset({"metformin", "biguanide", "glucophage"}),
        aliases_display=("metformin", "biguanide", "Glucophage"),
        expected_evidence_slots=(),
        special_rules=(),
        forbidden_verbs_for_protocol_role=frozenset(
            {"demonstrated", "showed", "reduced", "improved"}
        ),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(
            {"planned", "pending", "will assess"}
        ),
        canonical_trials=(),
        known_role_overrides=MappingProxyType({}),
    )


def _judge(role: str, verdict: str, *, rationale: str = "ok rationale") -> JudgeReview:
    return JudgeReview(
        judge_role=role,  # type: ignore[arg-type]
        model="m",
        verdict=verdict,  # type: ignore[arg-type]
        score=8, rationale=rationale, flagged_claims=(),
    )


def _spar(
    verdict: str = "accept_clean",
    *,
    reviews: tuple[JudgeReview, ...] | None = None,
    dissent: JudgeReview | None = None,
    gate_override: GateOverride | None = None,
) -> SPARReview:
    if reviews is None:
        if verdict == "accept_clean":
            reviews = (
                _judge("evidence_auditor", "accept"),
                _judge("domain_skeptic", "accept"),
                _judge("final_judge", "accept"),
            )
        elif verdict == "accept_caveated":
            d = _judge("domain_skeptic", "reject", rationale="confounded")
            reviews = (
                _judge("evidence_auditor", "accept"),
                d,
                _judge("final_judge", "accept"),
            )
            dissent = d
        elif verdict == "reject_majority":
            d = _judge("final_judge", "accept", rationale="hopeful but...")
            reviews = (
                _judge("evidence_auditor", "reject"),
                _judge("domain_skeptic", "reject"),
                d,
            )
            dissent = d
        else:  # reject_critical
            reviews = (
                _judge("evidence_auditor", "reject"),
                _judge("domain_skeptic", "reject"),
                _judge("final_judge", "reject"),
            )
    return SPARReview(
        submission_id="run-001",
        reviews=reviews,
        verdict=verdict,  # type: ignore[arg-type]
        dissent=dissent,
        final_judge_resolution="resolution prose",
        gate_override=gate_override,
    )


# --- _make_title ---------------------------------------------------------


def test_make_title_strips_trailing_period_and_capitalizes() -> None:
    thesis = _claim(text="metformin reduced HbA1c.")
    assert _make_title(thesis, "metformin") == "Metformin reduced HbA1c"


def test_make_title_falls_back_to_topic_when_thesis_empty() -> None:
    """Defensive: empty thesis text → use topic. Schema requires
    non-empty text but this guards against degenerate inputs."""
    thesis = _claim(text=".")  # only the trailing period; strip → empty
    assert _make_title(thesis, "metformin") == "Metformin"


def test_make_title_already_capitalized_unchanged() -> None:
    thesis = _claim(text="Metformin reduced HbA1c")
    assert _make_title(thesis, "metformin") == "Metformin reduced HbA1c"


# --- _render_claim_with_cites --------------------------------------------


def test_render_claim_appends_citations_to_period() -> None:
    """Claim text without [N] gets its supporting_refs appended before
    the trailing period. Output: 'metformin reduced HbA1c [1].'"""
    c = _claim(text="metformin reduced HbA1c.", refs=(1,))
    assert _render_claim_with_cites(c) == "metformin reduced HbA1c [1]."


def test_render_claim_appends_multiple_citations() -> None:
    c = _claim(text="metformin reduced X.", refs=(1, 2, 3))
    assert _render_claim_with_cites(c) == "metformin reduced X [1] [2] [3]."


def test_render_claim_preserves_existing_inline_cites() -> None:
    """If Claim.text already has [N], leave them alone — fact_extractor
    pinned the prose at extraction time; double-citing would corrupt it."""
    c = _claim(text="metformin reduced HbA1c [1].", refs=(1,))
    assert _render_claim_with_cites(c) == "metformin reduced HbA1c [1]."


def test_render_claim_no_period_appends_cite_then_period() -> None:
    c = _claim(text="metformin reduced X", refs=(1,))
    assert _render_claim_with_cites(c) == "metformin reduced X [1]."


def test_render_claim_no_supporting_refs_returns_text_unchanged() -> None:
    """Edge case: a Claim with empty supporting_refs (shouldn't happen
    via compile_claims, but defensive) → render text as-is."""
    c = _claim(text="metformin reduced X.", refs=())
    assert _render_claim_with_cites(c) == "metformin reduced X."


# --- _sort_key + _claims_for_bucket --------------------------------------


def test_sort_key_orders_by_directness_then_tier_then_confidence() -> None:
    direct_a1 = _claim("C001", directness="direct", tier="A1")
    indirect_a1 = _claim("C002", directness="indirect", tier="A1")
    direct_a2 = _claim("C003", directness="direct", tier="A2")
    # direct A1 < direct A2 < indirect A1 — directness dominates
    assert _sort_key(direct_a1) < _sort_key(direct_a2) < _sort_key(indirect_a1)


def test_claims_for_bucket_filters_by_claim_type() -> None:
    g = _graph(
        _claim("C001", claim_type="efficacy"),
        _claim("C002", claim_type="context"),
        _claim("C003", claim_type="safety"),
    )
    findings = _claims_for_bucket(g, ("efficacy", "safety"))
    assert {c.claim_id for c in findings} == {"C001", "C003"}
    background = _claims_for_bucket(g, ("context",))
    assert [c.claim_id for c in background] == ["C002"]


def test_claims_for_bucket_excludes_thesis_when_requested() -> None:
    g = _graph(
        _claim("C001", claim_type="efficacy"),
        _claim("C002", claim_type="efficacy"),
    )
    out = _claims_for_bucket(g, ("efficacy",), exclude_ids={"C001"})
    assert [c.claim_id for c in out] == ["C002"]


# --- _spar_banner --------------------------------------------------------


def test_spar_banner_accept_clean_short() -> None:
    banner = _spar_banner(_spar("accept_clean"))
    assert "accept_clean" in banner
    assert "3-0" in banner
    assert "DRAFT REJECTED" not in banner
    assert "TRUST-SPINE" not in banner


def test_spar_banner_accept_caveated_includes_dissent() -> None:
    banner = _spar_banner(_spar("accept_caveated"))
    assert "accept_caveated" in banner
    assert "Dissent" in banner
    assert "domain_skeptic" in banner
    assert "confounded" in banner


def test_spar_banner_reject_majority_emphasizes_rejection_with_minority() -> None:
    banner = _spar_banner(_spar("reject_majority"))
    assert "DRAFT REJECTED" in banner
    assert "reject_majority" in banner
    assert "Minority accept" in banner


def test_spar_banner_reject_critical_unanimous() -> None:
    banner = _spar_banner(_spar("reject_critical"))
    assert "DRAFT REJECTED" in banner
    assert "reject_critical" in banner
    assert "Dissent" not in banner


def test_spar_banner_gate_override_displayed_prominently() -> None:
    """The reviewer's audit-trail requirement: gate_override is the most
    architecturally consequential SPARReview shape, must be prominent."""
    spar = _spar(
        verdict="reject_critical",
        reviews=(
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=2,
            rationale="MASTERS NCT mismatch + p-value not in source",
        ),
    )
    banner = _spar_banner(spar)
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in banner
    assert "reject_critical" in banner  # canonical
    assert "accept_clean" in banner  # panel's original
    assert "Failed citation traces:** 2" in banner
    assert "MASTERS NCT mismatch" in banner


# --- _render_paper -------------------------------------------------------


def test_render_paper_uses_thesis_text_as_title() -> None:
    g = _graph(_claim("C001", text="metformin reduced HbA1c."))
    items = [_item(1)]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    assert md.startswith("# Metformin reduced HbA1c\n")


def test_render_paper_thesis_section_always_present() -> None:
    g = _graph(_claim("C001", text="metformin reduced HbA1c.", refs=(1,)))
    items = [_item(1)]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    assert "## Thesis" in md
    assert "metformin reduced HbA1c [1]." in md


def test_render_paper_groups_efficacy_into_findings_context_into_background() -> None:
    g = _graph(
        _claim("C001", text="thesis claim.", claim_type="efficacy"),
        _claim("C002", text="another efficacy.", claim_type="efficacy", refs=(2,)),
        _claim("C003", text="background mechanism.", claim_type="mechanism", refs=(3,)),
        _claim("C004", text="background context.", claim_type="context", refs=(4,)),
    )
    items = [_item(1), _item(2), _item(3), _item(4)]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    assert "## Findings" in md
    assert "## Background" in md
    assert "another efficacy [2]." in md
    assert "background mechanism [3]." in md
    assert "background context [4]." in md
    # Thesis claim appears in Thesis section, NOT in Findings
    findings_idx = md.index("## Findings")
    background_idx = md.index("## Background")
    findings_block = md[findings_idx:background_idx]
    assert "thesis claim." not in findings_block


def test_render_paper_omits_empty_sections() -> None:
    g = _graph(_claim("C001"))  # only the thesis
    items = [_item(1)]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    assert "## Findings" not in md
    assert "## Background" not in md


def test_render_paper_references_only_cited_refs() -> None:
    g = _graph(_claim("C001", refs=(1,)))
    items = [_item(1, title="Cited paper"), _item(2, title="Uncited paper")]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    assert "## References" in md
    assert "[1] Cited paper" in md
    assert "Uncited paper" not in md


def test_render_paper_raises_when_thesis_id_not_in_claims() -> None:
    """Defense-in-depth: schema invariants should prevent this, but the
    writer raises WriterError if it ever slips through."""
    bad = ClaimGraph(
        claims=(_claim("C001"),), edges=(),
        thesis_claim_id="C999",  # not in claims
    )
    # ClaimGraph itself doesn't enforce; assert_claim_graph_invariants does.
    # The writer must defend even against unvalidated graphs.
    with pytest.raises(WriterError, match="thesis_claim_id"):
        _render_paper(bad, [_item(1)], _spar("accept_clean"), "metformin")


def test_render_paper_within_section_ordering_visible_in_text() -> None:
    """Distinct texts make ordering observable. C003 (direct A2) renders
    BEFORE C002 (indirect A1) within Findings, because directness
    dominates over tier in the within-section sort key (matches the
    thesis_tournament priority order)."""
    g = _graph(
        _claim("C001", text="thesis text.", claim_type="efficacy",
               directness="direct", tier="A1"),
        _claim("C002", text="weak indirect text.", claim_type="efficacy",
               directness="indirect", tier="A1", refs=(2,)),
        _claim("C003", text="strong direct text.", claim_type="efficacy",
               directness="direct", tier="A2", refs=(3,)),
    )
    items = [_item(1), _item(2), _item(3)]
    md = _render_paper(g, items, _spar("accept_clean"), "metformin")
    findings = md[md.index("## Findings"):md.index("## References")]
    # `_render_claim_with_cites` inserts cites before the period, so the
    # rendered forms are 'strong direct text [3].' and 'weak indirect
    # text [2].' — search for the bare phrase instead.
    assert findings.index("strong direct text") < findings.index("weak indirect text")


# --- _render_rejection ---------------------------------------------------


def test_render_rejection_includes_banner_thesis_traces_panel() -> None:
    g = _graph(_claim("C001", text="metformin reduces mortality."))
    items = [_item(1, title="Trial X")]
    spar = _spar("reject_critical")
    traces = [
        CitationTrace(
            claim_id="C001", ref=1, trace_type="nct_exists",  # type: ignore[arg-type]
            passed=False, detail="NCT not found",
        ),
    ]
    md = _render_rejection(g, items, spar, traces)
    assert "Submission rejected" in md
    assert "DRAFT REJECTED" in md
    assert "metformin reduces mortality." in md
    assert "Failed citation traces" in md
    assert "NCT not found" in md
    assert "evidence_auditor" in md
    assert "domain_skeptic" in md
    assert "final_judge" in md


def test_render_rejection_with_gate_override_prominent() -> None:
    g = _graph(_claim())
    items = [_item(1)]
    spar = _spar(
        verdict="reject_critical",
        reviews=(
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=1,
            rationale="failed trace gate fired",
        ),
    )
    md = _render_rejection(g, items, spar, [])
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in md
    assert "accept_clean" in md  # panel's original visible
    assert "failed trace gate fired" in md


# --- write_paper end-to-end (sync, no LLM) -------------------------------


def test_write_paper_accept_clean_renders_without_llm_call() -> None:
    """Sanity: write_paper is sync, takes no chain/client, and renders
    the paper deterministically. The Day 4-fix architectural shift —
    the LLM is no longer in the writer's loop."""
    g = _graph(_claim("C001", text="metformin reduced HbA1c.", refs=(1,)))
    md, rejections = write_paper(
        g, [_item(1)], [], _spar("accept_clean"),
        pack=_pack(), topic="metformin",
    )
    assert "# Metformin reduced HbA1c" in md
    assert "## Thesis" in md
    assert "## References" in md
    assert "metformin reduced HbA1c [1]." in md
    assert rejections == []  # always [] on deterministic path


def test_write_paper_reject_critical_renders_rejection_notice() -> None:
    g = _graph(_claim("C001"))
    md, rejections = write_paper(
        g, [_item(1)], [], _spar("reject_critical"),
        pack=_pack(), topic="metformin",
    )
    assert "Submission rejected" in md
    assert "reject_critical" in md
    assert rejections == []


def test_write_paper_gate_override_renders_with_gate_banner() -> None:
    """Gate-override path: rejection notice with gate banner prominent."""
    spar = _spar(
        verdict="reject_critical",
        reviews=(
            _judge("evidence_auditor", "accept"),
            _judge("domain_skeptic", "accept"),
            _judge("final_judge", "accept"),
        ),
        gate_override=GateOverride(
            pre_gate_verdict="accept_clean",
            failed_trace_count=1,
            rationale="MASTERS NCT failed trace",
        ),
    )
    g = _graph(_claim("C001"))
    md, rejections = write_paper(
        g, [_item(1)], [], spar,
        pack=_pack(), topic="metformin",
    )
    assert "TRUST-SPINE TRACE GATE TRIGGERED" in md
    assert "accept_clean" in md  # panel's original
    assert "reject_critical" in md  # canonical
    assert rejections == []


def test_write_paper_novel_claim_cannot_be_injected_via_llm() -> None:
    """4-fix P1 architectural proof: the previous LLM-driven writer
    could be tricked into rendering `Metformin prevents dementia in
    healthy older adults.` even with strict claim_ids binding (the LLM
    declared a valid claim_id and cited a valid `[N]`, but the sentence
    text was novel). The deterministic writer eliminates this entirely
    — the only sentences in the output are `Claim.text` strings from
    the graph. There's no LLM input layer to inject through."""
    # Reproduction: a graph where the only claim is about HbA1c.
    # The writer renders that claim and ONLY that claim. There's no
    # mechanism by which "prevents dementia" could appear in the output.
    g = _graph(_claim("C001", text="metformin reduced HbA1c.", refs=(1,)))
    md, _ = write_paper(
        g, [_item(1)], [], _spar("accept_clean"),
        pack=_pack(), topic="metformin",
    )
    assert "metformin reduced HbA1c" in md
    assert "dementia" not in md  # claim was never in the graph
    assert "prevents" not in md


# --- Misc ---------------------------------------------------------------


def test_render_version_anchored() -> None:
    assert RENDER_VERSION == "writer/2026-04-28-deterministic"


def test_writer_rejection_dataclass_is_frozen() -> None:
    r = WriterRejection(section="abstract", sentence="x", reason="y")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        r.section = "findings"  # type: ignore[misc]
