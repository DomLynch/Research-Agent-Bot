"""Fix #22 — surface-render lint gate.

Detects the "generated artifact" patterns the Stage-2 audit historically
missed: orphan `_Cited:` blocks, consecutive cite blocks with no prose
between, abstract paragraphs that are nothing but a citation block, and
sentence-end author-year fragments."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import surface_render_lint as srl  # noqa: E402


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
