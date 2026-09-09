"""Tests for agent/paper_writer.py — full-paper rendering helpers.

Day 10.17 Fix A coverage: _build_user_prompt must not include
rejected (SPAR-quarantined) receipts in the LLM prompt context. The
LLM should physically not see what it's not allowed to cite.
"""
from __future__ import annotations

import asyncio
import pytest

import agent.paper_writer_backstop as writer_backstop
from agent import paper_writer
from agent.paper_writer_helpers import strip_rendered_citation_markers
from agent.paper_writer import _build_user_prompt, write_results_section
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)


def _summary(
    rid: str,
    *,
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    tier: str = "A1",
    directness: str = "direct",
    spar_verdict: str = "accept_clean",
    source_title: str | None = None,
    source_year: int | None = None,
    thesis_text: str | None = None,
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=thesis_text or f"thesis for {rid}",
        spar_verdict=spar_verdict,
        n_claims=4, n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=("p=0.003",), population_summary="older adults",
        source_title=source_title,
        source_year=source_year,
    )


def _thesis() -> SynthesisThesis:
    return SynthesisThesis(
        text="metformin shows mixed evidence",
        receipt_ids_referenced=("r-A",),
        tensions_addressed=(),
        rejected_candidates=(),
        picker_rationale="test",
    )


def _matrix(receipts) -> TensionMatrix:
    return TensionMatrix(receipts=tuple(receipts), pairs=())


# ============================================================
# Day 10.17 Fix A — accepted-only LLM writer context
# ============================================================
# Empirical bug from the 10.17 e2e run: rejected receipt cfab-c02
# leaked into the Background section of full_paper.md. Q8 caught it
# at audit time, but by then the LLM had already cited it. The fix
# is to remove rejected receipts from the LLM prompt context entirely
# — the writer cannot cite what it does not see.
#
# Trust-spine layer is preserved: the deterministic Methods,
# References, and Rejected/Contested Evidence sections still render
# rejected receipts (those don't go through the LLM). Only the
# LLM-anchored prompt is restricted.


def test_build_user_prompt_does_not_include_rejected_receipt_ids() -> None:
    """The load-bearing test: a rejected receipt's id must NOT appear
    anywhere in the prompt the LLM sees."""
    accepted = [_summary("r-A"), _summary("r-B")]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-rej-X" not in prompt, (
        "rejected receipt id leaked into LLM prompt context — "
        "Fix A regression"
    )


def test_build_user_prompt_does_not_emit_quarantined_block_header() -> None:
    """Pre-Fix-A code emitted a 'QUARANTINED (SPAR-rejected) RECEIPTS:'
    block. Fix A removes that header entirely — there's no LLM-visible
    quarantine block at all."""
    accepted = [_summary("r-A")]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "QUARANTINED" not in prompt
    assert "SPAR-rejected" not in prompt


def test_build_user_prompt_includes_accepted_receipt_ids() -> None:
    """Sanity: the prompt MUST still include accepted receipts —
    Fix A is about suppressing only the rejected ones."""
    long_excerpt = "x" * 350 + " exact-result " + "y" * 10_000
    accepted = [
        _summary("r-A", thesis_text=long_excerpt),
        _summary("r-B", thesis_text=long_excerpt),
        *(_summary(f"r-{i}", thesis_text=long_excerpt) for i in range(48)),
    ]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-A" in prompt
    assert "r-B" in prompt
    assert "exact-result" in prompt
    assert len(prompt) < 100_000


def test_build_user_prompt_no_rejected_input_still_works() -> None:
    """The function must handle an empty rejected list cleanly —
    the e2e pipeline always passes one, but defensive."""
    accepted = [_summary("r-A")]
    prompt = _build_user_prompt(
        accepted, [], _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-A" in prompt
    assert "QUARANTINED" not in prompt


@pytest.mark.parametrize("padding", ["", " Preserve source attribution." * 180], ids=["short", "over-4000"])
def test_build_user_prompt_includes_revision_feedback_as_guidance(monkeypatch, padding) -> None:
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", f"Revise headline{padding}; remove unsupported mechanistic overclaim.; Add the missing source-quality field.")
    accepted = [_summary("r-A")]

    prompt = _build_user_prompt(
        accepted, [], _matrix(accepted), _thesis(),
        topic="metformin",
    )

    assert "REVISION FEEDBACK — address EACH point below" in prompt
    assert "1. Revise headline" in prompt
    assert "2. remove unsupported mechanistic overclaim" in prompt
    assert "3. Add the missing source-quality field." in prompt
    assert "Treat this as reviewer guidance, not evidence" in prompt


def test_build_user_prompt_single_revision_ask_renders_one_checklist_item(monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "Complete the truncated sentence in the abstract.")
    accepted = [_summary("r-A")]

    prompt = _build_user_prompt(
        accepted, [], _matrix(accepted), _thesis(),
        topic="metformin",
    )

    assert "REVISION FEEDBACK — address EACH point below" in prompt
    assert "1. Complete the truncated sentence" in prompt
    assert "2." not in prompt.split("REVISION FEEDBACK", 1)[1][:200]  # one ask → no second item


def test_build_user_prompt_keeps_semicolon_examples_inside_revision_ask(monkeypatch) -> None:
    monkeypatch.setenv(
        "RESEARKA_REVISION_FEEDBACK",
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the claim; "
        "Resolve the coding note.",
    )
    accepted = [_summary("r-A")]

    prompt = _build_user_prompt(
        accepted, [], _matrix(accepted), _thesis(),
        topic="young_plasma_parabiosis",
    )
    revision = prompt.split("REVISION FEEDBACK", 1)[1]

    assert "1. Differentiate the 17-source bundle" in revision
    assert "preclinical rodent n=, human n=) so readers can audit the claim" in revision
    assert "2. Resolve the coding note." in revision
    assert "render a clearly labelled markdown table" in revision


def test_results_writer_preserves_outcome_headings_and_source_isolation(monkeypatch) -> None:
    receipts = [
        _summary("r-immune", outcome="immune", thesis_text="Trial - source excerpts: Immune evidence remains mixed across included sources."),
        _summary("r-longevity", outcome="longevity", thesis_text="Trial - source excerpts: Longevity evidence discusses lifespan and offspring context."),
    ]
    parsed_by_call = iter([
        {"subsections": [{
            "outcome_class": "immune",
            "paragraphs": [{
                "text": "Immune evidence remains mixed across included sources [r-immune].",
                "receipt_ids": ["r-immune"],
            }],
        }]},
        {"subsections": [{
            "outcome_class": "longevity",
            "paragraphs": [{
                "text": "Longevity evidence discusses lifespan and offspring context [r-longevity].",
                "receipt_ids": ["r-longevity"],
            }],
        }]},
    ])

    prompts: list[str] = []

    async def fake_call(**kwargs):
        prompts.append(str(kwargs.get("user_prompt") or ""))
        return next(parsed_by_call)

    monkeypatch.setattr(paper_writer, "_call_llm_section", fake_call)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 0)

    section = asyncio.run(write_results_section(
        receipts, [], _matrix(receipts), _thesis(),
        topic="caloric_restriction", chain=(),
    ))

    assert "### Immune and Inflammation Outcomes" in section.body_md
    assert "### Longevity Outcomes" in section.body_md
    assert "r-longevity" not in prompts[0]
    assert "r-immune" not in prompts[1]
    immune_body = section.body_md.split("### Immune and Inflammation Outcomes", 1)[1].split("###", 1)[0]
    assert "lifespan" not in immune_body


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("bad_text,reason", [("Fasting glucose decreased by 999% among older adults [r-a].", "novel_numeric:"), ("Metformin prevented pancreatic cancer [r-a].", "source_grounding:")])
def test_results_retry_reports_validation_errors_not_fallback_length(monkeypatch, mixed, bad_text, reason) -> None:
    receipts = [_summary("r-a", outcome="cardiometabolic", thesis_text=(
        "Trial - source excerpts: Fasting glucose decreased among older adults."
    ))]
    prompts = []

    async def call(**kwargs):
        prompts.append(kwargs["user_prompt"])
        text = "Fasting glucose decreased among older adults [r-a]."
        if len(prompts) == 1 or mixed:
            text = bad_text
        paragraphs = [{"text": text, "receipt_ids": ["r-a"]}]
        if mixed:
            paragraphs.append({"text": "Fasting glucose decreased among older adults [r-a].", "receipt_ids": ["r-a"]})
        return {"subsections": [{"outcome_class": "cardiometabolic", "paragraphs": paragraphs}]}

    async def no_fix(section, **kwargs):
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", call)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", no_fix)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 1)
    result = asyncio.run(write_results_section(
        receipts, [], _matrix(receipts), _thesis(), topic="metformin", chain=(),
    ))
    assert len(prompts) == 2
    assert "RESULTS WORD TARGET: 500-600" in prompts[0]
    assert reason in prompts[1]
    assert "Fasting glucose decreased among older adults [r-a]." in result.body_md
    assert "999" not in result.body_md
    assert "pancreatic cancer" not in result.body_md


@pytest.mark.parametrize("name", ["abstract", "conclusion", "results"])
@pytest.mark.parametrize("response", [None, {"subsections": None}, {"subsections": [{"paragraphs": None}]},
                                     {"subsections": [{"paragraphs": ["junk", {"text": ["junk"]}]}]},
                                     {"subsections": [{"paragraphs": [{"text": "Trial result", "receipt_ids": "r-a"}]}]}])
def test_exhausted_writer_stops_without_placeholder(monkeypatch, name, response) -> None:
    async def no_response(**kwargs):
        return response

    monkeypatch.setattr(paper_writer, "_call_llm_section", no_response)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 0)
    receipts = [_summary("r-a")]
    if name == "results":
        call = write_results_section(receipts, [], _matrix(receipts), _thesis(), topic="metformin", chain=())
    else:
        kwargs = {"topic": "metformin"} if name == "conclusion" else {}
        fn = paper_writer._write_scoped_section if kwargs else paper_writer._write_anchored_section
        call = fn(name=name, heading=f"## {name.title()}", system_prompt="", user_prompt="", accepted=receipts,
                  chain=(), client=None, ledger=None, seed=None, fallback_body="placeholder", **kwargs)
    with pytest.raises(ValueError, match=f"writer_section_unavailable:{name}"):
        asyncio.run(call)


@pytest.mark.parametrize("name", ["conclusion", "results"])
def test_retry_keeps_valid_findings_and_requests_only_missing_text(monkeypatch, name) -> None:
    receipts = [_summary("r-a", outcome="cardiometabolic", thesis_text=(
        "Trial - source excerpts: Metformin reduced fasting glucose among older adults. | "
        "Metformin benefit remains uncertain among older adults."
    ))]
    texts = ["Metformin reduced fasting glucose among older adults [r-a].",
             "Metformin benefit remains uncertain among older adults [r-a]."]
    prompts = []

    async def call(**kwargs):
        prompts.append(kwargs["user_prompt"])
        row = {"text": texts[len(prompts)-1], "receipt_ids": ["r-a"]}
        return {"paragraphs": [row]} if name == "conclusion" else {"subsections": [{"outcome_class": "cardiometabolic", "paragraphs": [row]}]}

    monkeypatch.setattr(paper_writer, "_call_llm_section", call)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 1)
    if name == "results":
        result = asyncio.run(write_results_section(receipts, [], _matrix(receipts), _thesis(), topic="metformin", chain=()))
    else:
        result = asyncio.run(paper_writer._write_scoped_section(
            name=name, heading="## Conclusion", system_prompt="", user_prompt="", topic="metformin",
            accepted=receipts, chain=(), client=None, ledger=None, seed=None, fallback_body="placeholder"))
    assert all(text in result.body_md for text in texts)
    assert texts[0] in prompts[1]
    assert "Do not repeat" in prompts[1]


def test_retention_deduplicates_normalized_prose_without_rewriting_sources() -> None:
    row = {"text": "Metformin may help.", "receipt_ids": ["r-a"]}
    rows = paper_writer._retained_paragraphs(None, [row, {**row, "text": "  Metformin  may help. "}, None])
    assert rows == [row]
    assert paper_writer._retained_paragraphs(None, None) == []


@pytest.mark.parametrize("wrong_first", [False, True])
@pytest.mark.parametrize("name", ["conclusion", "results"])
def test_citation_candidate_order_cannot_hide_supported_prose(monkeypatch, name, wrong_first) -> None:
    text = "Metformin may lower glucose while metformin effects remain uncertain [r-a]."
    receipts = [_summary("r-a", thesis_text="Trial - source excerpts: " + text.replace(" [r-a]", "")),
                _summary("r-b", thesis_text="Trial - source excerpts: The intervention harmed muscle strength.")]
    rows = [{"text": text, "receipt_ids": [rid]} for rid in (["r-b", "r-a"] if wrong_first else ["r-a", "r-b"])]
    async def call(**kwargs):
        return {"paragraphs": rows} if name == "conclusion" else {"subsections": [{"paragraphs": rows}]}
    monkeypatch.setattr(paper_writer, "_call_llm_section", call)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 0)
    if name == "results":
        section = asyncio.run(write_results_section(receipts, [], _matrix(receipts), _thesis(), topic="metformin", chain=()))
    else:
        section = asyncio.run(paper_writer._write_scoped_section(
            name=name, heading="## Conclusion", system_prompt="", user_prompt="", topic="metformin",
            accepted=receipts, chain=(), client=None, ledger=None, seed=None, fallback_body=""))
    assert len(section.anchors) == 1
    assert section.anchors[0].receipt_ids == ("r-a",)


def test_anchored_writer_materializes_missing_inline_receipts(monkeypatch) -> None:
    prompts: list[str] = []

    async def fake_call(**kwargs):
        prompt = str(kwargs["user_prompt"])
        prompts.append(prompt)
        if len(prompts) > 1:
            return {"paragraphs": [
                {"text": "The measured endpoint improved.", "receipt_ids": ["r-a"]},
                {"text": "The measured endpoint remained null.", "receipt_ids": ["r-b"]},
            ]}
        return {"paragraphs": [
            {"text": "The measured endpoint improved. The population was bounded.", "receipt_ids": ["r-a"]},
            {"text": "The measured endpoint remained null. Follow-up was short.", "receipt_ids": ["r-b"]},
        ]}

    async def no_citation_fix(section, **_kwargs):
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", fake_call)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", no_citation_fix)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 2)
    monkeypatch.setattr(paper_writer, "SECTION_WORD_FLOORS", {"abstract": 5})

    section = asyncio.run(paper_writer._write_anchored_section(
        name="abstract", heading="## Abstract", system_prompt="system",
        user_prompt="base", accepted=[
            _summary("r-a", direction="positive", thesis_text="Trial - source excerpts: The measured endpoint improved. The population was bounded."),
            _summary("r-b", direction="null", thesis_text="Trial - source excerpts: The measured endpoint remained null. Follow-up was short."),
        ], chain=(), client=None,
        ledger=None, seed=None, fallback_body="fallback",
    ))

    assert "[r-a]" in section.body_md and "[r-b]" in section.body_md
    assert len(prompts) == 1


def test_citation_only_repair_rejects_content_or_source_changes() -> None:
    before = {"paragraphs": [
        {"text": "Bounded finding [r-a].", "receipt_ids": ["r-a"]},
        {"text": "Outcome [not assessed] remained uncertain.", "receipt_ids": ["r-b"]},
    ]}
    assert paper_writer.citation_only_repair(
        before,
        {"paragraphs": [
            {"text": "Bounded finding [r-a].", "receipt_ids": ["r-a"]},
            {"text": "Outcome [not assessed] remained uncertain [r-b].", "receipt_ids": ["r-b"]},
        ]},
        {"r-a", "r-b"},
    )
    for invalid in (
        {"paragraphs": [{"text": "Bounded finding [r-b].", "receipt_ids": ["r-a"]}, *before["paragraphs"][1:]]},
        {"paragraphs": [{"text": "Changed finding [r-a].", "receipt_ids": ["r-a"]}, *before["paragraphs"][1:]]},
        {"paragraphs": [before["paragraphs"][0], {"text": "Outcome [fabricated] remained uncertain [r-b].", "receipt_ids": ["r-b"]}]},
    ):
        assert not paper_writer.citation_only_repair(before, invalid, {"r-a", "r-b"})
    assert paper_writer.citation_only_repair(
        {"text": "Evidence improved. Outcome remained null.", "receipt_ids": ["r-a"]},
        {"text": "Evidence improved [r-a]. Outcome remained null [r-a].", "receipt_ids": ["r-a"]},
        {"r-a"},
    )
    assert not paper_writer.citation_only_repair(
        {"text": "Evidence improved [r-a]. Outcome remained null [r-b].", "receipt_ids": ["r-a", "r-b"]},
        {"text": "Evidence improved [r-b]. Outcome remained null [r-a].", "receipt_ids": ["r-a", "r-b"]},
        {"r-a", "r-b"},
    )
    assert not paper_writer.citation_only_repair_eligible(
        {"text": "Evidence improved. Outcome remained null.", "receipt_ids": ["r-a", "r-b"]},
    )
    assert paper_writer.citation_only_repair(
        {"text": "The combined evidence remained mixed.", "receipt_ids": ["r-a", "r-b"]},
        {"text": "The combined evidence remained mixed [r-a] [r-b].", "receipt_ids": ["r-a", "r-b"]},
        {"r-a", "r-b"},
    )


@pytest.mark.parametrize("failed_text,source_failure", [
    ("Unsupported result was 999 percent [r-a].", False),
    ("Cardiovascular mortality improved after treatment [r-a].", True),
])
def test_anchored_writer_regenerates_non_citation_failure(monkeypatch, failed_text, source_failure) -> None:
    prompts: list[str] = []

    async def fake_call(**kwargs):
        prompts.append(str(kwargs["user_prompt"]))
        text = failed_text if len(prompts) == 1 else "Result remained bounded [r-a]."
        return {"paragraphs": [{"text": text, "receipt_ids": ["r-a"]}]}

    async def no_citation_fix(section, **_kwargs):
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", fake_call)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", no_citation_fix)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 1)

    section = asyncio.run(paper_writer._write_anchored_section(
        name="abstract", heading="## Abstract", system_prompt="system",
        user_prompt="base", accepted=[_summary(
            "r-a", thesis_text="Study - source excerpts: Result remained bounded.",
        )], chain=(), client=None,
        ledger=None, seed=None, fallback_body="fallback",
    ))

    assert "Result remained bounded" in section.body_md
    assert len(prompts) == 2
    assert "ANCHOR REPAIR REQUIRED" not in prompts[1]
    assert ("source-exact" in prompts[1]) is source_failure
    assert prompts[1].startswith("base")
    assert failed_text not in section.body_md


def test_cross_domain_writer_regenerates_sentence_level_records(monkeypatch) -> None:
    prompts: list[str] = []

    async def fake_call(**kwargs):
        prompts.append(str(kwargs["user_prompt"]))
        if len(prompts) == 1:
            return {"paragraphs": [{
                "text": "Davies improved. Khamis remained null.",
                "receipt_ids": ["r-a", "r-b"],
            }]}
        return {"paragraphs": [
            {
                "paragraph_index": group,
                "text": "Davies improved [r-a]." if row % 2 else "Khamis remained null [r-b].",
                "receipt_ids": ["r-a"] if row % 2 else ["r-b"],
            }
            for group in range(1, 5)
            for row in range(6)
        ]}

    async def no_citation_fix(section, **_kwargs):
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", fake_call)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", no_citation_fix)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 1)

    section = asyncio.run(paper_writer._write_anchored_section(
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis", system_prompt="system",
        user_prompt="base", accepted=[_summary("r-a"), _summary("r-b", outcome="frailty")], chain=(), client=None,
        ledger=None, seed=None, fallback_body="fallback",
    ))

    assert "Davies improved [r-a]. Khamis remained null [r-b]." in section.body_md
    assert section.body_md.count("_Cited:") == 4
    assert len(prompts) == 2
    assert "FORMAT RETRY REQUIRED" in prompts[1]
    assert "ANCHOR REPAIR REQUIRED" not in prompts[1]


def test_cross_domain_retry_names_unsupported_numerics() -> None:
    prompt = paper_writer.cross_domain_retry_prompt(
        "base", "cross_domain_synthesis",
        ["novel_numeric:'50'", "missing_inline_anchor", "invalid_sentence_record_contract"],
    )
    assert "FORMAT RETRY REQUIRED" in prompt
    assert "4-6 paragraph_index groups" in prompt
    assert "6-9 entries per group" in prompt
    assert "NUMERIC RETRY REQUIRED" in prompt
    assert "'50'" in prompt and "state the point qualitatively" in prompt
    prompt = paper_writer.cross_domain_retry_prompt("base", "limitations_full", ["novel_numeric:'50'", "missing_inline_anchor"])
    assert "NUMERIC RETRY REQUIRED" in prompt and "FORMAT RETRY REQUIRED" in prompt
    assert "four paragraph_index groups" in prompt
    assert "one sentence per JSON paragraph entry" in prompt


def test_retry_prompt_requires_mapped_source_language() -> None:
    prompt = paper_writer.cross_domain_retry_prompt(
        "base", "results", ["source_grounding:r-cardio"],
    )
    assert "SOURCE-GROUNDING RETRY REQUIRED" in prompt
    assert "evidence_excerpt" in prompt


def test_all_section_briefs_and_retries_share_evidence_boundaries() -> None:
    from agent.paper_writer_prompts import ABSTRACT_SOURCE_RETRY, format_prompts_for_topic
    from agent.paper_writer_backstop import build_backstop_prompt

    prompts = format_prompts_for_topic("BNT162b2", "vaccine")
    assert len(prompts) == 8
    for name, prompt in prompts.items():
        assert "Do not invent citations, study designs, search dates" in prompt
        assert "Word targets apply to THIS section" in prompt
        assert "A value elsewhere in the corpus is not support" in prompt
        assert "canonical clinical thresholds with their Author-Year" not in prompt
        backstop = build_backstop_prompt(prompt, name, 20, 250)
        assert "original JSON schema" in backstop
        assert "Make each paragraph 8-12 sentences" not in backstop
    for prompt in (prompts["abstract"], ABSTRACT_SOURCE_RETRY):
        assert "200-280" in prompt and "300" in prompt
        assert "300-400" not in prompt and "250-350" not in prompt
    for name in ("cross_domain_synthesis", "limitations_full"):
        retry = paper_writer.cross_domain_retry_prompt("base", name, ["novel_numeric:'50'"])
        assert "omit ALL numeric quantities" in retry
    assert "NOT actionable treatment advice" in prompts["conclusion"]


def test_abstract_retries_over_ceiling_instead_of_returning_it(monkeypatch) -> None:
    from agent.synthesis_schemas import SynthesisSection

    calls = []
    async def call(**kwargs):
        calls.append(kwargs["user_prompt"])
        return {"words": 330 if len(calls) == 1 else 260}

    def build(parsed, **kwargs):
        return SynthesisSection(name="abstract", body_md="## Abstract\n\n" + "word " * parsed["words"], anchors=())

    async def citation_pass(section, **kwargs):
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", call)
    monkeypatch.setattr(paper_writer, "build_anchored_from_parsed", build)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", citation_pass)
    section = asyncio.run(paper_writer._write_anchored_section(
        name="abstract", heading="## Abstract", system_prompt="brief", user_prompt="evidence",
        accepted=[], chain=[], client=None, ledger=None, seed=None, fallback_body="fallback",
    ))
    assert paper_writer._section_word_count(section) == 260
    assert len(calls) == 2 and "LENGTH RETRY REQUIRED" in calls[1]
    assert "200-300 words" in calls[1]


def test_thin_brief_render_uses_deterministic_results(monkeypatch) -> None:
    receipts = [
        _summary(
            "r-immune", outcome="immune", directness="direct",
            source_title="Direct vascular-age cohort", source_year=2025,
        ),
        _summary(
            "r-longevity", outcome="longevity", directness="protocol",
            source_title="Vascular aging trial protocol", source_year=2026,
        ),
    ]

    async def fake_anchored(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def fake_scoped(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def fail_results(*_args, **_kwargs):
        raise AssertionError("thin_corpus_brief must not call long-form Results writer")

    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_anchored)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_scoped)
    monkeypatch.setattr(paper_writer, "write_results_section", fail_results)
    md, sections = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="vitamin_d",
        submission_id="thin-test", chain=(), review_type="thin_corpus_brief",
    ))
    assert "### Immune and Inflammation Outcomes" in md and "### Longevity Outcomes" in md
    assert "Source examples: Direct vascular-age cohort 2025" in md
    assert "**Design-limit note:**" in md and "Vascular aging trial protocol 2026" in md
    assert "**Direct-source ceiling:**" in md and "Direct vascular-age cohort 2025" in md
    assert "## Introduction" not in md and all(s.name != "inferential_bridge" for s in sections)


def test_thin_brief_renders_explicitly_requested_bridge(monkeypatch) -> None:
    receipts = [_summary("r-direct", directness="direct")]

    async def fake_anchored(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def fake_scoped(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def no_inference_claims(*_args, **_kwargs):
        return ()

    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "Add a dedicated Inferential Bridge section.")
    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_anchored)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_scoped)
    monkeypatch.setattr("agent.inferential_bridge.request_inference_claims", no_inference_claims)

    md, sections = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="vitamin_d",
        submission_id="thin-revise", chain=(), review_type="thin_corpus_brief",
    ))

    assert "## Inferential Bridge" in md
    assert "[inferential bridge status: not established]" in md
    assert any(section.name == "inferential_bridge" for section in sections)


def test_thin_revision_renders_only_requested_long_form_sections(monkeypatch) -> None:
    receipts = [_summary("r-direct", directness="direct")]

    async def fake_anchored(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nIntegrated evidence.\n", anchors=())

    async def fake_scoped(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nCoherent discussion.\n", anchors=())

    monkeypatch.setenv(
        "RESEARKA_REVISION_FEEDBACK",
        "Rewrite the Discussion section; Mark mechanism-level explanations in the Cross-Domain Synthesis as author inference.",
    )
    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_anchored)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_scoped)

    md, sections = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="vitamin_d",
        submission_id="thin-revise", chain=(), review_type="thin_corpus_brief",
    ))

    assert "## Research Question" in md
    assert "findings for muscle function" in md
    assert "among older adults" in md
    assert "population, study-design, and directness boundaries" in md
    assert "## Cross-Domain Synthesis" in md
    assert "**Author-inference boundary:**" in md
    assert "## Discussion" in md
    assert "## Introduction" not in md
    assert {"research_question", "cross_domain_synthesis", "discussion"} <= {s.name for s in sections}
    section_map = {section.name: section.body_md for section in sections}
    assert "**Author-inference boundary:**" in section_map["cross_domain_synthesis"]
    assert "**Author-inference boundary:**" not in section_map["discussion"]

    monkeypatch.setenv(
        "RESEARKA_REVISION_FEEDBACK",
        "Mark mechanistic explanations as author inference.",
    )
    generic_md, _ = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="vitamin_d",
        submission_id="thin-generic-revise", chain=(), review_type="thin_corpus_brief",
    ))
    assert "## Cross-Domain Synthesis" in generic_md
    assert "**Author-inference boundary:**" in generic_md


def test_full_revision_reapplies_author_boundary_after_backstop(monkeypatch) -> None:
    receipts = [_summary("r-direct")]
    fallbacks: dict[str, str] = {}

    async def fake_section(**kwargs):
        fallbacks[kwargs["name"]] = kwargs["fallback_body"]
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nDraft.\n", anchors=())

    async def fake_results(*_args, **_kwargs):
        return SynthesisSection(name="results", body_md="## Results\n\nDraft.\n", anchors=())

    async def replace_cross_domain(sections, **_kwargs):
        updated = dict(sections)
        updated["cross_domain_synthesis"] = SynthesisSection(
            name="cross_domain_synthesis",
            body_md="## Cross-Domain Synthesis\n\nBackstop replacement.\n",
            anchors=(),
        )
        return updated

    monkeypatch.setenv(
        "RESEARKA_REVISION_FEEDBACK",
        "Mark mechanistic explanations in the Cross-Domain Synthesis as author inference.",
    )
    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_section)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_section)
    monkeypatch.setattr(paper_writer, "write_results_section", fake_results)
    monkeypatch.setattr(writer_backstop, "apply_section_backstop", replace_cross_domain)

    md, _ = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="vitamin_d",
        submission_id="full-revise", chain=(), review_type="research_synthesis",
    ))

    assert "Backstop replacement." in md
    assert "**Author-inference boundary:**" in md
    assert "the conclusion synthesizes evidence on vitamin d" in fallbacks["conclusion"].lower()


def test_evidence_map_uses_compact_writer_path(monkeypatch) -> None:
    receipts = [_summary("r-safety", outcome="safety_comorbidity")]

    async def fake_anchored(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def fake_scoped(**kwargs):
        return SynthesisSection(name=kwargs["name"], body_md=f"{kwargs['heading']}\n\nBrief section.\n", anchors=())

    async def fail_results(*_args, **_kwargs):
        raise AssertionError("evidence_map must not call long-form Results writer")

    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_anchored)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_scoped)
    monkeypatch.setattr(paper_writer, "write_results_section", fail_results)
    md, sections = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="creatine",
        submission_id="map-test", chain=(), review_type="evidence_map",
    ))
    assert "### Safety and Comorbidity Outcomes" in md
    assert "## Introduction" not in md and all(s.name != "discussion" for s in sections)


def test_full_render_repairs_abstract_and_discussion_before_assembly(monkeypatch) -> None:
    receipts = [_summary("r-mech", tier="C", directness="mechanistic")]
    order: list[str] = []

    async def fake_anchored(**kwargs):
        name = kwargs["name"]
        if name == "abstract":
            body = (
                "## Abstract\n\nPositive signals support biological plausibility for anti-aging effects. "
                "In a preclinical model, treatment attenuated frailty and modulated cytokines."
            )
        else:
            body = f"{kwargs['heading']}\n\n" + " ".join([f"{name} words"] * 120)
        return SynthesisSection(name=name, body_md=body, anchors=())

    async def fake_scoped(**kwargs):
        name = kwargs["name"]
        order.append(name)
        body = f"{kwargs['heading']}\n\nToo short." if name == "discussion" else f"{kwargs['heading']}\n\n" + " ".join([f"{name} words"] * 120)
        return SynthesisSection(name=name, body_md=body, anchors=())

    async def fake_results(*_args, **_kwargs):
        return SynthesisSection(name="results", body_md="## Results\n\nResults remain bounded.", anchors=())

    async def fake_backstop(sections, **_kwargs):
        order.append("backstop")
        if "discussion" in sections:
            sections["discussion"] = SynthesisSection(
                name="discussion",
                body_md="## Discussion\n\n" + " ".join(["substantive discussion"] * 500),
                anchors=(),
            )
        return sections

    monkeypatch.setattr(paper_writer, "_write_anchored_section", fake_anchored)
    monkeypatch.setattr(paper_writer, "_write_scoped_section", fake_scoped)
    monkeypatch.setattr(paper_writer, "write_results_section", fake_results)
    monkeypatch.setattr(writer_backstop, "apply_section_backstop", fake_backstop)

    md, _sections = asyncio.run(paper_writer.render_full_paper(
        receipts, _matrix(receipts), _thesis(), topic="ace_inhibitors_aging",
        submission_id="writer-loop", chain=(),
    ))

    assert "context-specific signals" in md
    assert "was reported to attenuate" in md
    assert "**Thesis:**" in md
    assert "**Resolution criteria:**" in md
    assert "substantive discussion" in md
    assert order.count("backstop") == 1
    assert order.index("conclusion") < order.index("backstop")


def test_strip_rendered_citation_markers_removes_body_metadata() -> None:
    md = (
        "## Results\n\n"
        "_Cited: `Moel 2025`_\n"
        "Rapamycin evidence remains bounded.\n"
    )
    out = strip_rendered_citation_markers(md)
    assert "_Cited:" not in out
    assert "Rapamycin evidence remains bounded." in out


def test_build_user_prompt_caller_filter_treats_accept_caveated_as_accepted() -> None:
    """Boundary test (reviewer pin): the production caller in
    render_full_paper computes `rejected` as `spar_verdict not in
    ('accept_clean', 'accept_caveated')`. Verify that membership
    expression treats `accept_caveated` as accepted, not rejected.
    Regression risk: a future maintainer might tighten the filter to
    `spar_verdict == 'accept_clean'` and silently quarantine the
    accept_caveated receipts that should still be cited."""
    ACCEPTED_VERDICTS = ("accept_clean", "accept_caveated")
    receipts = [
        _summary("r-clean", spar_verdict="accept_clean"),
        _summary("r-caveated", spar_verdict="accept_caveated"),
        _summary("r-rej", spar_verdict="reject_majority"),
    ]
    accepted = [r for r in receipts if r.spar_verdict in ACCEPTED_VERDICTS]
    rejected = [r for r in receipts if r.spar_verdict not in ACCEPTED_VERDICTS]
    assert {r.receipt_id for r in accepted} == {"r-clean", "r-caveated"}
    assert {r.receipt_id for r in rejected} == {"r-rej"}
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-clean" in prompt
    assert "r-caveated" in prompt
    assert "r-rej" not in prompt


# ============ Fix #27 — prose-compression word floors ===============


def test_section_word_floors_protect_analytical_depth() -> None:
    """Fix #45 (post Fix #27 review): the two intellectual-core
    sections — Discussion and Cross-Domain Synthesis — must have
    floors at or above downstream audit/surface gates so the writer cannot land at 310 / 525 words
    (the grok-smart paper's desk-reject regression). Lean
    Introduction/Background floors stay (Fix #27 was right for
    those — they're not analytical sections)."""
    from agent.paper_writer import SECTION_WORD_FLOORS
    assert SECTION_WORD_FLOORS["abstract"] <= 250
    assert SECTION_WORD_FLOORS["introduction"] <= 1000
    assert SECTION_WORD_FLOORS["background"] <= 800
    assert SECTION_WORD_FLOORS["results"] <= 1700
    # Analytical-core floors RESTORED after Fix #27 over-compression
    assert SECTION_WORD_FLOORS["cross_domain_synthesis"] >= 850
    assert SECTION_WORD_FLOORS["discussion"] >= 900
    assert SECTION_WORD_FLOORS["limitations_full"] <= 500
    assert SECTION_WORD_FLOORS["conclusion"] <= 300


def test_section_prompts_use_explicit_targets() -> None:
    """Mixed contract per Fix #27 + Fix #45:
      - Lean sections (Intro/Background/Results/Limitations/Conclusion)
        use `TARGET RANGE` (Fix #27 prose compression)
      - Analytical sections (Discussion/CrossDomain) use
        `HARD MINIMUM` (Fix #45 depth restoration)
    Either explicit-target language is acceptable; what matters is
    the prompt isn't silent on word count."""
    from agent.paper_writer_prompts import (
        BACKGROUND_SYSTEM_PROMPT, CONCLUSION_SYSTEM_PROMPT,
        CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        DISCUSSION_SYSTEM_PROMPT, INTRODUCTION_SYSTEM_PROMPT,
        LIMITATIONS_FULL_SYSTEM_PROMPT, RESULTS_SYSTEM_PROMPT,
    )
    for name, prompt in (
        ("BACKGROUND", BACKGROUND_SYSTEM_PROMPT),
        ("CONCLUSION", CONCLUSION_SYSTEM_PROMPT),
        ("CROSS_DOMAIN", CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT),
        ("DISCUSSION", DISCUSSION_SYSTEM_PROMPT),
        ("INTRODUCTION", INTRODUCTION_SYSTEM_PROMPT),
        ("LIMITATIONS", LIMITATIONS_FULL_SYSTEM_PROMPT),
        ("RESULTS", RESULTS_SYSTEM_PROMPT),
    ):
        assert (
            "TARGET RANGE" in prompt
            or "HARD MINIMUM" in prompt
            or "Fix #27" in prompt
            or "Fix #45" in prompt
        ), f"{name} prompt missing explicit word-count target"


def test_discussion_and_cross_domain_prompts_demand_900_word_floor() -> None:
    """Fix #45: the analytical-core sections explicitly require ≥900
    words to prevent the grok-smart 310/525 regression."""
    from agent.paper_writer_prompts import (
        CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        DISCUSSION_SYSTEM_PROMPT,
    )
    for name, prompt in (
        ("DISCUSSION", DISCUSSION_SYSTEM_PROMPT),
        ("CROSS_DOMAIN", CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT),
    ):
        assert "900" in prompt, (
            f"{name} prompt no longer carries the 900-word floor "
            "(Fix #45 regression)"
        )
        assert "adjudicate" in prompt.lower(), (
            f"{name} prompt no longer requires per-paragraph "
            "tension adjudication"
        )


def test_conclusion_prompt_demands_clinical_practice_statement() -> None:
    """2026-05-09 peer-review fix (Bug 3): the panel found the conclusion
    correctly hedged "evidence is mixed and incomplete" but did not state
    the actionable clinical-practice implication. The prompt now requires
    an off-label-use statement."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "clinical-practice" in CONCLUSION_SYSTEM_PROMPT.lower(), (
        "Conclusion prompt no longer demands a clinical-practice "
        "statement (peer-review fix 2026-05-09 regression)"
    )
    assert "off-label" in CONCLUSION_SYSTEM_PROMPT.lower(), (
        "Conclusion prompt no longer references off-label-use guidance"
    )
    assert "Pending further trials" in CONCLUSION_SYSTEM_PROMPT, (
        "Conclusion prompt no longer carries the canonical "
        "'Pending further trials' phrase template"
    )


def test_conclusion_prompt_lists_required_content_item_5() -> None:
    """The required-content list must enumerate the new clinical-practice
    requirement as item 5 — older runs had only 4 items."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    # The literal "5." marker for required content is load-bearing —
    # the writer LLM keys off the numbered list.
    assert "5." in CONCLUSION_SYSTEM_PROMPT
    # Sanity: the prior 4 items must still be present.
    for marker in ("1.", "2.", "3.", "4."):
        assert marker in CONCLUSION_SYSTEM_PROMPT


def test_conclusion_prompt_word_target_accommodates_extra_clause() -> None:
    """Adding the clinical-practice clause bumped target from
    250-350 → 280-380 words. The prompt's word target should reflect this."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "280-380" in CONCLUSION_SYSTEM_PROMPT or "280" in CONCLUSION_SYSTEM_PROMPT


def test_conclusion_prompt_retains_overclaim_guard() -> None:
    """Regression: the new clause must not weaken the existing overclaim
    guard (no unhedged 'extends lifespan' or similar)."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "extends lifespan" in CONCLUSION_SYSTEM_PROMPT  # in the do-NOT list
    assert "unhedged clinical claim" in CONCLUSION_SYSTEM_PROMPT.lower()


def test_writer_prompts_frame_intervention_entity_not_topic_phrase() -> None:
    """#7: paper_writer feeds intervention_label(topic) — not the raw slug
    or the multi-token humanized phrase — into the {topic} slot of the
    section prompts, so the LLM names the compound ('resveratrol'), never
    'the candidate compound Resveratrol Metabolism Effects'."""
    from agent.paper_writer_prompts import format_prompts_for_topic
    from agent.topic_display import intervention_label
    entity = intervention_label("resveratrol_metabolism_effects")
    assert entity == "resveratrol"
    blob = " ".join(
        format_prompts_for_topic(topic=entity, drug_class="polyphenol").values()
    )
    assert "resveratrol" in blob.lower()
    assert "resveratrol_metabolism_effects" not in blob
    assert "Resveratrol Metabolism Effects" not in blob
