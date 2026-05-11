from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import apply_patches as ap  # noqa: E402
import run_v06_synthesis as orch  # noqa: E402
from agent.synthesis_schemas import SynthesisSection  # noqa: E402


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def test_restore_rendered_section_headings_from_typed_sections() -> None:
    paper = (
        "## Limitations\n\n"
        "The corpus remains limited.\n\n"
        "The boundary conditions remain unresolved.\n\n"
        "## References\n\n"
        "Ref.\n"
    )
    sections = (
        SynthesisSection(
            name="limitations_full",
            body_md="## Limitations\n\nThe corpus remains limited.\n",
            anchors=(),
        ),
        SynthesisSection(
            name="conclusion",
            body_md=(
                "## Conclusion\n\n"
                "The boundary conditions remain unresolved.\n"
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Conclusion\n\nThe boundary conditions remain unresolved." in out
    assert out.index("## Conclusion") < out.index("## References")


def test_restore_rendered_section_headings_is_idempotent() -> None:
    paper = (
        "## Conclusion\n\n"
        "The boundary conditions remain unresolved.\n"
    )
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md=paper,
            anchors=(),
        ),
    )
    assert orch._restore_rendered_section_headings(paper, sections) == paper


def test_absent_flagged_patch_resolved_after_final_cleanup() -> None:
    result = ap.PatchResult(
        patch_id="P02",
        patch_type="structure",
        severity="P1",
        decision="flagged",
        reason_for_decision="structure patch flag-only",
        before="8. Results-like prose leaked into Methods.",
        after="",
    )
    clean_paper = "## Methods\n\nDeterministic Methods only.\n"
    resolved = orch._resolve_absent_flagged_patches([result], clean_paper)
    assert resolved[0].decision == "applied"
    assert "FINAL-CLEANUP-RESOLVED" in resolved[0].reason_for_decision


def test_restore_cross_domain_heading_by_structural_boundary() -> None:
    paper = (
        "## Results\n\n"
        "### Immune Outcomes\n\n"
        "Metformin changed inflammatory markers.\n\n"
        " _Cited: `A 2020`_\n\n"
        "A cross-domain tension concerns immune signals that do not "
        "translate into functional improvement.\n\n"
        " _Cited: `A 2020`, `B 2021`_\n\n"
        "## Discussion\n\n"
        "Interpretation follows.\n"
    )
    sections = (
        SynthesisSection(
            name="cross_domain",
            body_md=(
                "## Cross-Domain Synthesis\n\n"
                "The original anchor was revised by review."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Cross-Domain Synthesis\n\nA cross-domain tension" in out
    assert out.index("## Cross-Domain Synthesis") < out.index("## Discussion")


def test_restore_conclusion_heading_after_limitations_citations() -> None:
    paper = (
        "## Limitations\n\n"
        "The corpus remains limited.\n\n"
        " _Cited: `A 2020`_\n\n"
        "The synthesis therefore remains conditional.\n\n"
        "## Structured Evidence Tables\n\n"
        "Table body.\n"
    )
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md=(
                "## Conclusion\n\n"
                "The original anchor was revised by review."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_headings(paper, sections)
    assert "## Conclusion\n\nThe synthesis therefore remains conditional." in out
    assert out.index("## Conclusion") < out.index("## Structured Evidence Tables")


def test_restore_required_section_body_when_post_processing_strips_depth() -> None:
    paper = (
        "## Results\n\n"
        f"{_words(500)}\n\n"
        "## Cross-Domain Synthesis\n\n"
        "Too short.\n\n"
        "## Discussion\n\n"
        f"{_words(800)}\n"
    )
    full_cross_domain = (
        "## Cross-Domain Synthesis\n\n"
        f"{_words(850)}\n"
    )
    sections = (
        SynthesisSection(
            name="cross_domain_synthesis",
            body_md=full_cross_domain,
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    assert "Still short." not in out
    assert orch._word_count(
        orch._rendered_section_match(
            out, "## Cross-Domain Synthesis",
        ).group(1),
    ) >= 850
    assert "compiled from" not in out
    assert "compiler" not in out
    assert "word849" in out


def test_restore_required_section_body_drops_unsafe_short_restore() -> None:
    paper = "## Introduction\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="introduction",
            body_md=(
                "## Introduction\n\n"
                "Unsafe numeric source-context sentence 5 mg."
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    body = orch._rendered_section_match(out, "## Introduction").group(1)
    assert "Unsafe numeric source-context sentence" not in body
    assert body.strip() == "Too short."


def test_restore_required_section_body_uses_safe_short_writer_section() -> None:
    paper = "## Conclusion\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="conclusion",
            body_md="## Conclusion\n\nStill short.\n",
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    match = orch._rendered_section_match(out, "## Conclusion")
    assert match is not None
    assert "Too short." not in out
    assert "compiled from" not in out
    assert "compiler" not in out
    assert "Still short." in match.group(1)


def test_restore_public_surface_floors_does_not_inject_filler() -> None:
    paper = (
        "## Abstract\n\n" + _words(160) + "\n\n"
        "## Introduction\n\nToo short.\n\n"
        "## Background\n\n" + _words(320) + "\n\n"
        "## Methods\n\n" + _words(320) + "\n\n"
        "## Results\n\n" + _words(520) + "\n\n"
        "## Cross-Domain Synthesis\n\n" + _words(870) + "\n\n"
        "## Discussion\n\n" + _words(820) + "\n\n"
        "## Limitations\n\n" + _words(260) + "\n\n"
        "## Conclusion\n\n" + _words(260) + "\n"
    )
    out, log = orch._restore_public_surface_floors(paper)
    assert out == paper
    assert log == []


def test_restore_required_section_body_restores_safe_typed_section() -> None:
    paper = "## Results\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="results",
            body_md="## Results\n\n" + _words(500),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(
        paper, sections, prefer_typed_sections=False,
    )
    body = orch._rendered_section_match(out, "## Results").group(1)
    assert "word499" in body
    assert "Too short." not in body


def test_restore_required_section_body_refuses_public_residue() -> None:
    paper = "## Results\n\nToo short.\n"
    sections = (
        SynthesisSection(
            name="results",
            body_md=(
                "## Results\n\n"
                "When a source passage cannot support its own specificity, "
                "the surviving section therefore fails.\n"
            ),
            anchors=(),
        ),
    )
    out = orch._restore_rendered_section_contract(paper, sections)
    body = orch._rendered_section_match(out, "## Results").group(1)
    assert "source passage cannot support" not in body
    assert body.strip() == "Too short."


def test_restore_contract_collapses_consecutive_qei_headings() -> None:
    paper = (
        "## Quantitative Evidence Index — Urolithin A\n\n"
        "## Quantitative Evidence Index — urolithin_a\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Acevedo 2025 | muscle strength | ua | 57% | % | — |\n"
    )
    out = orch._restore_rendered_section_contract(paper, ())
    assert out.count("## Quantitative Evidence Index") == 1
    assert "## Quantitative Evidence Index — Urolithin A" in out
    assert "57%" in out


def test_split_quantitative_evidence_index_moves_table_out_of_main() -> None:
    paper = (
        "## Abstract\n\nShort abstract.\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "_Top 1 high-confidence numeric claim._\n\n"
        "| Study | Endpoint |\n|---|---|\n| Smith 2020 | BMI |\n\n"
        "## Methods\n\nMethods prose.\n"
    )
    main, qei = orch._split_quantitative_evidence_index(paper)
    assert "## Quantitative Evidence Index" not in main
    assert "## Abstract" in main and "## Methods" in main
    assert qei.startswith("## Quantitative Evidence Index")
    assert "Smith 2020" in qei


def test_split_quantitative_evidence_index_collapses_duplicate_heading() -> None:
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "_Top 40 claims._\n\n"
        "| Study | Endpoint |\n|---|---|\n| Smith 2020 | BMI |\n"
        "| Jones 2021 | weight |\n\n"
        "## Methods\n\nM.\n"
    )
    main, qei = orch._split_quantitative_evidence_index(paper)
    assert "## Quantitative Evidence Index" not in main
    assert qei.count("## Quantitative Evidence Index") == 1
    assert "Top 2 claims" in qei


def test_drop_cross_outcome_paragraphs_removes_wrong_section_citation() -> None:
    paper = (
        "## Results\n\n"
        "### Immune Outcomes\n\n"
        "Meydani 2016 found an immune signal.\n\n"
        "Beavers 2022 reported gait speed.\n\n"
        "### Frailty Outcomes\n\n"
        "Beavers 2022 reported gait speed.\n"
    )
    manifest = {"receipts": [
        {
            "citation_token": "Meydani 2016",
            "outcome_class": "immune",
            "spar_verdict": "accept_clean",
        },
        {
            "citation_token": "Beavers 2022",
            "outcome_class": "frailty",
            "spar_verdict": "accept_clean",
        },
    ]}
    out, n = orch._drop_cross_outcome_paragraphs(paper, manifest)
    immune = out.split("### Immune Outcomes", 1)[1].split(
        "### Frailty Outcomes", 1,
    )[0]
    frailty = out.split("### Frailty Outcomes", 1)[1]
    assert n == 1
    assert "Beavers 2022" not in immune
    assert "Meydani 2016" in immune
    assert "Beavers 2022" in frailty


def test_replace_conclusion_with_bounded_summary_removes_exact_numeric() -> None:
    paper = (
        "## Discussion\n\nInterpretation.\n\n"
        "## Conclusion\n\n"
        "Chakraborty 2023 reported an effect estimate of 10 weeks. "
        "This should not survive.\n\n"
        "## References\n\nRef.\n"
    )
    out, changed = orch._replace_conclusion_with_bounded_summary(
        paper, {"topic": "caloric_restriction"},
    )
    assert changed is True
    conclusion = out.split("## Conclusion", 1)[1].split("## References", 1)[0]
    assert "10 weeks" not in conclusion
    assert "caloric restriction" in conclusion
    assert "## References" in out


def test_neutralize_final_consistency_issue_replaces_sentence_only() -> None:
    paper = (
        "## Background\n\n"
        "The first sentence is safe. However, the translation of these "
        "preclinical findings to human disease prevention is ungrounded. "
        "The last sentence remains useful.\n"
    )
    issues = [SimpleNamespace(
        severity="P1",
        issue_type="source_context_drift",
        evidence=(
            "However, the translation of these preclinical findings to "
            "human disease prevention is ungrounded."
        ),
    )]
    out, n = orch._neutralize_final_consistency_issues(paper, issues)
    assert n == 1
    assert "preclinical findings to human disease prevention" not in out
    assert "The first sentence is safe." in out
    assert "The last sentence remains useful." in out
    assert "interpretive context" in out


def test_shape_abstract_moves_intro_leakage_to_introduction() -> None:
    paper = (
        "## Abstract\n\n"
        "First abstract sentence states the question. "
        "Second sentence gives the corpus and finding. "
        "Third sentence gives the boundary condition. "
        "Fourth sentence keeps the abstract specific. "
        "Fifth sentence closes the abstract claim. "
        "The intervention, defined as a long contextual explanation, "
        "belongs in the Introduction. "
        "The geroscience hypothesis posits another introductory claim "
        "(Lopez-Otin et al.\n\n"
        "## Introduction\n\n"
        "Original introduction.\n\n"
        "## Methods\n\nMethods.\n"
    )
    out, changed = orch._shape_abstract_and_intro(
        paper, {"topic": "caloric_restriction"},
    )
    abstract = out.split("## Abstract", 1)[1].split("## Introduction", 1)[0]
    intro = out.split("## Introduction", 1)[1].split("## Methods", 1)[0]
    assert changed is True
    assert "defined as" not in abstract
    assert "defined as" in intro
    assert "geroscience hypothesis posits" not in intro
    assert "Original introduction" in intro
