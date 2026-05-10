"""Tests for agent.manuscript_scrub — universal post-render scrubber.

Stdlib-only, no LLM. All tests are domain-agnostic — the scrubber
works for any topic the platform synthesises, not just biomedical.
"""
from __future__ import annotations

from agent.manuscript_scrub import (  # type: ignore[import-not-found]
    dedupe_included_studies,
    scrub_engine_residue,
    scrub_paper,
    truncate_abstract,
)


# ---- residue scrub ------------------------------------------------------


def test_scrub_residue_removes_tournament_selector() -> None:
    md = (
        "## Thesis\n\n**Picked thesis (Tournament selector):** the corpus"
        " supports a positive effect.\n"
    )
    out, n = scrub_engine_residue(md)
    assert "Tournament selector" not in out
    assert n >= 1


def test_scrub_residue_removes_no_matched_source_phrase() -> None:
    md = (
        "## Engagement\n\n- Framework X: aligned. no matched source in "
        "the accepted evidence registry.\n"
    )
    out, n = scrub_engine_residue(md)
    assert "no matched source in the accepted evidence" not in out
    assert n >= 1


def test_scrub_residue_idempotent_on_clean_md() -> None:
    md = "## Methods\n\nThis is clean prose with no engine residue.\n"
    out, n = scrub_engine_residue(md)
    assert out == md
    assert n == 0


# ---- abstract truncation ------------------------------------------------


def test_truncate_abstract_caps_at_500_words() -> None:
    long_para = " ".join(
        f"Sentence {i} has several words to fill space."
        for i in range(120)
    )  # ~960 words
    md = f"## Abstract\n\n{long_para}\n## Introduction\n\nIntro.\n"
    out, before, after = truncate_abstract(md, cap=500)
    assert before > 500
    assert after <= 500
    assert "## Introduction" in out


def test_truncate_abstract_no_op_when_under_cap() -> None:
    short = " ".join(["word"] * 200)
    md = f"## Abstract\n\n{short}\n## Introduction\n\nIntro.\n"
    out, before, after = truncate_abstract(md, cap=500)
    assert out == md
    assert before == after == 200


def test_truncate_abstract_no_op_when_no_abstract() -> None:
    md = "## Methods\n\nDirectly to methods.\n"
    out, before, after = truncate_abstract(md, cap=500)
    assert out == md
    assert before == 0


def test_truncate_abstract_at_sentence_boundary() -> None:
    """Truncation should land between sentences, not mid-sentence."""
    sents = [f"This is sentence number {i} in the abstract." for i in range(80)]
    abs_text = " ".join(sents)  # ~720 words (each sentence ~9 words)
    md = f"## Abstract\n\n{abs_text}\n## Introduction\n\nIntro.\n"
    out, before, after = truncate_abstract(md, cap=500)
    # The truncated abstract must end with a sentence terminator.
    abs_match = out.split("## Introduction")[0].rstrip()
    last_char = abs_match[-1] if abs_match else ""
    assert last_char in ".!?"


# ---- dedupe Included Studies --------------------------------------------


def test_dedupe_included_studies_collapses_byte_identical_rows() -> None:
    md = (
        "## Included Studies\n\n"
        "| Citation | Design | Tier |\n| --- | --- | --- |\n"
        "| Walton 2019 | RCT | A1 |\n"
        "| Walton 2019 | RCT | A1 |\n"
        "| Smith 2020 | Cohort | B2 |\n"
    )
    out, n = dedupe_included_studies(md)
    assert n == 1
    assert out.count("| Walton 2019") == 1
    assert "| Smith 2020" in out  # untouched


def test_dedupe_included_studies_keeps_higher_tier() -> None:
    md = (
        "## Included Studies\n\n"
        "| Citation | Design | Tier |\n| --- | --- | --- |\n"
        "| Konopka 2019 | Observational | B2 |\n"
        "| Konopka 2019 | RCT | A1 |\n"
    )
    out, n = dedupe_included_studies(md)
    assert n == 1
    # A1 row should win over B2 row.
    assert "| A1 |" in out
    assert "| B2 |" not in out


def test_dedupe_included_studies_no_op_when_unique() -> None:
    md = (
        "## Included Studies\n\n"
        "| Citation | Design | Tier |\n| --- | --- | --- |\n"
        "| Smith 2020 | Cohort | B2 |\n"
        "| Jones 2021 | RCT | A1 |\n"
    )
    out, n = dedupe_included_studies(md)
    assert out == md
    assert n == 0


def test_dedupe_skips_when_no_included_studies_table() -> None:
    md = "## Methods\n\nNo table here.\n"
    out, n = dedupe_included_studies(md)
    assert out == md
    assert n == 0


# ---- end-to-end scrub_paper ---------------------------------------------


def test_scrub_paper_applies_all_three_rules() -> None:
    long_para = " ".join(
        f"Sentence {i} has several words to fill space."
        for i in range(120)
    )
    md = (
        f"## Abstract\n\n{long_para}\n"
        "## Background\n\nThe (Tournament selector) ranked these papers.\n"
        "## Included Studies\n\n"
        "| Citation | Design | Tier |\n| --- | --- | --- |\n"
        "| Walton 2019 | RCT | A1 |\n"
        "| Walton 2019 | RCT | A1 |\n"
    )
    out, report = scrub_paper(md, abstract_cap=500)
    assert report.abstract_words_after <= 500
    assert report.residue_phrases_scrubbed >= 1
    assert report.duplicate_rows_removed == 1
    assert "Tournament selector" not in out
    assert out.count("| Walton 2019") == 1


def test_scrub_paper_idempotent_on_clean_md() -> None:
    md = (
        "## Abstract\n\nShort clean abstract under 500 words.\n"
        "## Methods\n\nClean methods.\n"
    )
    out, report = scrub_paper(md)
    assert out == md
    assert report.residue_phrases_scrubbed == 0
    assert report.duplicate_rows_removed == 0
