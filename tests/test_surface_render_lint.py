"""Fix #22 — surface-render lint gate.

Detects the "generated artifact" patterns the Stage-2 audit historically
missed: orphan `_Cited:` blocks, consecutive cite blocks with no prose
between, abstract paragraphs that are nothing but a citation block, and
sentence-end author-year fragments."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import surface_render_lint as srl  # noqa: E402


@pytest.mark.parametrize("label,value", [("Study A", "−0.45"), ("Study B", "1.27")])
def test_fragment_cleanup_preserves_source_table_and_comparator(label, value):
    quote = f"Treatment vs. a control group had an estimate of {value}."
    table = f"| {label} |  Endpoint  | {value} | {quote} |\n"
    assert srl.detect_sentence_fragments(table) == []
    assert srl.strip_sentence_fragments(table) == (table, 0)
    prose = "Valid result. e when paired with exercise. Next finding.\n\n"
    fixed, count = srl.strip_sentence_fragments(prose + table)
    assert count == 1 and "e when paired" not in fixed
    assert fixed.endswith(table)


@pytest.mark.parametrize("abbreviation", ["vs.", "e.g.", "i.e.", "et al."])
def test_fragment_cleanup_respects_abbreviations_in_prose(abbreviation):
    text = f"The comparison used {abbreviation} a control group with an estimate of −0.45."
    assert srl.detect_sentence_fragments(text) == []
    assert srl.strip_sentence_fragments(text) == (text, 0)


def test_fragment_cleanup_does_not_stop_at_decimal_or_cross_into_table():
    text = "Valid result. e when measured at 0.45 units. Next finding."
    fixed, count = srl.strip_sentence_fragments(text)
    assert count == 1 and fixed == "Valid result. Next finding."
    unfinished = "Valid result. e when measured\n| Study | 0.45 |\n"
    assert srl.strip_sentence_fragments(unfinished) == (unfinished, 0)


# ----- detect_orphan_citations -----------------------------------------


def test_orphan_after_section_heading_flagged() -> None:
    """A `_Cited:` block immediately after a `## Heading` line (no
    prose between) is an orphan — the writer dropped the sentence
    that should anchor it."""
    paper = (
        "## Abstract\n\n"
        "  _Cited: `Walton 2019`_\n\n"
        "Real sentence here.\n"
    )
    findings = srl.detect_orphan_citations(paper)
    assert len(findings) == 1
    assert findings[0].kind == "orphan_cite"


def test_consecutive_citation_blocks_flagged() -> None:
    """Two `_Cited:` blocks separated only by blank lines = the
    second one is orphan (its anchor sentence vanished)."""
    paper = (
        "Real sentence A.\n\n"
        "  _Cited: `Walton 2019`_\n\n"
        "  _Cited: `Konopka 2019`_\n\n"
        "Real sentence B.\n"
    )
    findings = srl.detect_orphan_citations(paper)
    kinds = [f.kind for f in findings]
    assert "consecutive_cites" in kinds


def test_clean_paper_has_no_orphans() -> None:
    """Sentence + cite + blank + sentence + cite is the canonical
    well-formed shape — zero findings."""
    paper = (
        "## Abstract\n\n"
        "Real sentence A.\n\n"
        "  _Cited: `Walton 2019`_\n\n"
        "Real sentence B.\n\n"
        "  _Cited: `Konopka 2019`_\n"
    )
    assert srl.detect_orphan_citations(paper) == []


def test_orphan_at_file_start_flagged() -> None:
    """Cite block as the very first line of the paper — no anchor
    possible, must be stripped."""
    paper = "  _Cited: `X 2020`_\n\nReal sentence A.\n"
    findings = srl.detect_orphan_citations(paper)
    assert len(findings) == 1


# ----- detect_abstract_cite_only_paragraphs ----------------------------


def test_abstract_cite_only_paragraph_flagged() -> None:
    """An Abstract paragraph that is JUST a cite block (no prose)
    fails the lint — the reader sees a dangling citation list."""
    paper = (
        "## Abstract\n\n"
        "Real sentence A.\n\n"
        "  _Cited: `Walton 2019`, `Konopka 2019`_\n\n"
        "## Methods\n\n"
        "Real methods text.\n"
    )
    findings = srl.detect_abstract_cite_only_paragraphs(paper)
    assert len(findings) == 1
    assert findings[0].kind == "abstract_cite_only"


def test_abstract_with_normal_paragraphs_clean() -> None:
    """A normal abstract paragraph (sentence followed by cite block
    on the next line is a sentence + cite paragraph, NOT cite-only)."""
    paper = (
        "## Abstract\n\n"
        "Real sentence A. _Cited: `Walton 2019`_\n\n"
        "Real sentence B.\n\n"
        "## Methods\n"
    )
    assert srl.detect_abstract_cite_only_paragraphs(paper) == []


def test_no_abstract_section_returns_empty() -> None:
    """A paper without an Abstract section → no abstract-specific
    lint, no crash."""
    paper = "## Methods\n\nText.\n"
    assert srl.detect_abstract_cite_only_paragraphs(paper) == []


# ----- detect_sentence_end_authoryear ----------------------------------


def test_sentence_end_authoryear_flagged() -> None:
    """`Konopka et al. 2019.` followed by another capitalized sentence
    is a sentence-ending author-year token — awkward."""
    paper = (
        "Some claim was made by Konopka et al. 2019. The study found...\n"
    )
    findings = srl.detect_sentence_end_authoryear(paper)
    assert len(findings) == 1
    assert findings[0].kind == "sentence_end_authoryear"
    assert "Konopka" in findings[0].evidence


def test_inline_authoryear_not_flagged() -> None:
    """`(Konopka et al., 2019)` mid-sentence is the canonical form —
    NOT flagged. We only care about the sentence-end pattern."""
    paper = "Some claim (Konopka et al., 2019) was made.\n"
    assert srl.detect_sentence_end_authoryear(paper) == []


# ----- run_surface_lint -----------------------------------------------


def test_run_surface_lint_combines_all_findings() -> None:
    """Top-level helper aggregates findings across detectors and
    sorts them by line number for reader-friendly output."""
    paper = (
        "## Abstract\n\n"
        "  _Cited: `X 2020`_\n\n"
        "Real sentence here. Konopka et al. 2019. The next sentence.\n\n"
        "  _Cited: `Y 2021`_\n\n"
        "  _Cited: `Z 2022`_\n"
    )
    findings = srl.run_surface_lint(paper)
    kinds = [f.kind for f in findings]
    assert "orphan_cite" in kinds  # the abstract-following cite
    assert "consecutive_cites" in kinds  # the Y / Z back-to-back
    assert "sentence_end_authoryear" in kinds  # the Konopka pattern
    # Verify line ordering
    assert findings == sorted(findings, key=lambda f: f.line_no)


# ----- strip_orphan_citation_blocks ------------------------------------


def test_strip_removes_orphan_after_heading() -> None:
    """The auto-fix strips orphan blocks (post-heading, no anchor)
    AND abstract paragraph cite-onlys (cite block as its own
    abstract paragraph). Both are covered safely — the surrounding
    prose remains intact, and the citation info is non-load-bearing
    in the abstract (Tables + body re-cite the same receipts)."""
    paper = (
        "## Abstract\n\n"
        "  _Cited: `X 2020`_\n\n"
        "Real sentence A.\n\n"
        "  _Cited: `Y 2021`_\n\n"
        "## Methods\n\n"
        "Methods text.\n"
    )
    cleaned, n = srl.strip_orphan_citation_blocks(paper)
    # X is post-heading orphan → stripped.
    # Y is in abstract as its own paragraph (cite-only) → also stripped.
    assert n == 2
    assert "_Cited: `X 2020`_" not in cleaned
    assert "_Cited: `Y 2021`_" not in cleaned
    assert "Real sentence A." in cleaned
    # No 3+ blank-line runs left behind
    assert "\n\n\n" not in cleaned


def test_strip_preserves_well_attached_body_cite_blocks() -> None:
    """Body sections (NOT abstract) keep cite blocks that have a
    valid anchor sentence — only orphans get stripped."""
    paper = (
        "## Methods\n\n"
        "Methods text.\n\n"
        "## Results\n\n"
        "Real sentence A.\n\n"
        "  _Cited: `Y 2021`_\n\n"
        "Real sentence B.\n"
    )
    cleaned, n = srl.strip_orphan_citation_blocks(paper)
    # No orphans, no abstract-cite-only → noop.
    assert n == 0
    assert "_Cited: `Y 2021`_" in cleaned


def test_strip_handles_clean_paper_as_noop() -> None:
    """When there are no orphans, strip is a no-op (idempotent)."""
    paper = (
        "Real sentence A.\n\n"
        "  _Cited: `X 2020`_\n\n"
        "Real sentence B.\n\n"
        "  _Cited: `Y 2021`_\n"
    )
    cleaned, n = srl.strip_orphan_citation_blocks(paper)
    assert n == 0
    assert cleaned == paper


def test_strip_collapses_consecutive_cite_duplicates() -> None:
    """Two cites in a row → strip the second; first survives as the
    anchored one. Reader sees only one cite block per claim."""
    paper = (
        "Real sentence A.\n\n"
        "  _Cited: `X 2020`_\n\n"
        "  _Cited: `Y 2021`_\n\n"
        "Real sentence B.\n"
    )
    cleaned, n = srl.strip_orphan_citation_blocks(paper)
    assert n == 1
    # First cite block is anchored to sentence A → survives
    assert "_Cited: `X 2020`_" in cleaned
    # Second was orphan → stripped
    assert "_Cited: `Y 2021`_" not in cleaned


# ----- Fix #52 — sentence-fragment detection + strip ----------------


def test_detect_single_letter_fragment_after_paren() -> None:
    """Real defect from a2a run line 256: '...extension) e when
    paired with exercise.' — a deterministic-template strip cut
    most of the thesis text and left a single 'e' word fragment."""
    paper = (
        "## Discussion\n\n"
        "Some prose here (a parenthetical list) e when paired with "
        "exercise.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    assert len(findings) == 1
    assert findings[0].kind == "sentence_fragment_single_letter"


def test_detect_lowercase_preposition_fragment() -> None:
    """Real defect from a2a run line 146: '...over the study
    period. on 2019 in a healthier older adult cohort.' — a
    citation-prefix strip ate 'Konopka' or 'Walton' before the
    year, leaving 'on 2019' as a subjectless fragment."""
    paper = (
        "## Discussion\n\n"
        "MET-PREVENT showed no change over the study period. "
        "on 2019 in a healthier older adult cohort. The next "
        "sentence is fine.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    fragment_finds = [
        f for f in findings
        if f.kind == "sentence_fragment_lowercase_start"
    ]
    assert len(fragment_finds) == 1


def test_detect_spliced_word_fragment() -> None:
    paper = (
        "## Results\n\n"
        "Translational relevance to humans remains uncertain.cy between "
        "body weight and intake reductions was duplicated. Next sentence.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    assert any(
        f.kind == "sentence_fragment_spliced_word"
        for f in findings
    )
    fixed, n = srl.strip_sentence_fragments(paper)
    assert n == 1
    assert "uncertain.cy" not in fixed
    assert "Translational relevance to humans remains uncertain." in fixed


def test_spliced_word_fragment_ignores_file_extensions() -> None:
    paper = (
        "## Data Availability\n\n"
        "README.md in the bundle root explains the run artifacts.\n"
    )
    assert srl.detect_sentence_fragments(paper) == []


def test_detect_lowercase_line_start_fragment() -> None:
    paper = (
        "## Methods\n\n"
        "1. deterministic step.\n"
        "ing a randomized paragraph fragment remains after deletion. "
        "Next sentence.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    assert any(
        f.kind == "sentence_fragment_lowercase_line_start"
        for f in findings
    )
    fixed, n = srl.strip_sentence_fragments(paper)
    assert n == 1
    assert "ing a randomized" not in fixed
    assert "Next sentence." in fixed


def test_lowercase_line_start_does_not_flag_wrapped_prose() -> None:
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "Interpreting evidence requires treating each domain as\n"
        "part of a boundary-condition map rather than as a pooled effect.\n"
    )
    assert srl.detect_sentence_fragments(paper) == []


def test_blank_table_rows_are_detected_and_stripped() -> None:
    paper = (
        "| Study | Value |\n"
        "|---|---|\n"
        "| A 2020 | 5% |\n"
        "| \n"
        "| B 2021 | 6% |\n"
    )
    findings = srl.detect_blank_table_rows(paper)
    assert len(findings) == 1
    fixed, n = srl.strip_blank_table_rows(paper)
    assert n == 1
    assert "| \n" not in fixed
    assert "B 2021" in fixed


def test_malformed_table_rows_are_detected_and_stripped() -> None:
    paper = (
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| A 2020 | glucose | drug | p=0.04 | p value | — |\n"
        "| B 2021 | glucose | drug | p=0.05 |\n"
    )
    findings = srl.detect_malformed_table_rows(paper)
    assert len(findings) == 1
    fixed, n = srl.strip_malformed_table_rows(paper)
    assert n == 1
    assert "B 2021" not in fixed
    assert "A 2020" in fixed


def test_empty_qei_rows_are_stripped_after_repair() -> None:
    paper = (
        "## Quantitative Evidence Index — topic\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| A 2020 | glucose | drug | p=0.04 | p value | — |\n"
        "| B 2021 | HbA1c | drug | — | — | — |\n\n"
        "## Methods\n\nText.\n"
    )
    fixed, n = srl.strip_empty_qei_rows(paper)
    assert n == 1
    assert "B 2021" not in fixed
    assert "A 2020" in fixed


def test_spliced_word_after_closing_parenthesis_is_stripped() -> None:
    paper = (
        "## Background\n\n"
        "The original sentence is complete (Smith 2020).ever, this "
        "broken duplicate fragment should be removed. Next sentence.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    assert any(f.kind == "sentence_fragment_spliced_word" for f in findings)
    fixed, n = srl.strip_sentence_fragments(paper)
    assert n == 1
    assert "ever, this broken" not in fixed
    assert "Next sentence." in fixed


def test_unterminated_paragraphs_are_detected_and_stripped() -> None:
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "Interpreting the evidence requires treating each domain as\n"
        "Direct human findings set the clinical perimeter\n\n"
        "A complete paragraph remains.\n"
    )
    findings = srl.detect_unterminated_paragraphs(paper)
    assert len(findings) == 1
    fixed, n = srl.strip_unterminated_paragraphs(paper)
    assert n == 1
    assert "clinical perimeter" not in fixed
    assert "A complete paragraph remains." in fixed


def test_does_not_false_fire_on_legitimate_enumeration() -> None:
    """`(a) a per-receipt evidence-weighting (Table 4: ...)` is a
    legitimate enumerated list — NOT a fragment. Fix #52's pattern
    must NOT trigger on this."""
    paper = (
        "## Discussion\n\n"
        "This synthesis adds (a) a per-receipt evidence-weighting "
        "(Table 4: tier × directness), (b) a deterministic per-paper "
        "numeric index, and (c) an explicit pairwise tension matrix.\n"
    )
    findings = srl.detect_sentence_fragments(paper)
    assert findings == [], (
        f"enumeration pattern false-fired: {[f.evidence for f in findings]}"
    )


def test_strip_sentence_fragments_clears_real_defects() -> None:
    """End-to-end on the actual a2a paper: the two known prose
    defects (line 146 + 256) get stripped; clean paper post-fix."""
    paper_path = (
        Path(__file__).resolve().parent.parent
        / "runs/synthesis-metformin-v06-a2a-"
          "2026-05-04T06-33-54Z/full_paper.md"
    )
    if not paper_path.exists():
        return  # archived run; skip silently
    paper = paper_path.read_text()
    fixed, n = srl.strip_sentence_fragments(paper)
    assert n >= 2, f"expected ≥2 strips, got {n}"
    # No remaining fragments after one pass
    post = srl.detect_sentence_fragments(fixed)
    assert post == []
    # Specific defect strings gone
    assert "on 2019 in a healthier older adult cohort." not in fixed
    assert "extension) e when paired with exercise." not in fixed


def test_strip_idempotent_after_one_pass() -> None:
    """Running strip twice gives same output as running once."""
    paper = (
        "## Heading\n\n"
        "  _Cited: `A 2020`_\n\n"
        "  _Cited: `B 2020`_\n\n"
        "Real sentence.\n\n"
        "  _Cited: `C 2020`_\n"
    )
    once, _ = srl.strip_orphan_citation_blocks(paper)
    twice, n_twice = srl.strip_orphan_citation_blocks(once)
    assert n_twice == 0
    assert twice == once


# ----- end-to-end audit integration ------------------------------------


def test_run_audit_includes_surface_lint_issues() -> None:
    """final_consistency_audit.run_audit must include the C10
    surface-lint check in its result set."""
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts"
    ))
    import final_consistency_audit as fca

    paper = (
        "## Abstract\n\n"
        "  _Cited: `X 2020`_\n\n"
        "Real sentence A.\n"
    )
    issues = fca.run_audit(
        paper, manifest={"receipts": []}, audit={"checks": []},
    )
    surface_issues = [i for i in issues if i.id.startswith("C10-")]
    # The same offending cite block fires BOTH the orphan-cite
    # detector AND the abstract-cite-only detector — both findings
    # are valid (the lint surfaces every angle a reviewer might
    # notice). Both should be auto-fixable.
    types = {i.issue_type for i in surface_issues}
    assert "surface_render_orphan_cite" in types
    assert "surface_render_abstract_cite_only" in types
    for i in surface_issues:
        assert i.auto_fixable is True
