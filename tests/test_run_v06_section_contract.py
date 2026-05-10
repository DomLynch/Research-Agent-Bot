from __future__ import annotations

import sys
from pathlib import Path

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


def test_restore_required_section_body_can_refuse_dirty_typed_restore() -> None:
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
    assert "word499" not in body
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
