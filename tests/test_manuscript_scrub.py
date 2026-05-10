"""Tests for agent.manuscript_scrub — universal post-render scrubber.

Stdlib-only, no LLM. All tests are domain-agnostic — the scrubber
works for any topic the platform synthesises, not just biomedical.
"""
from __future__ import annotations

from agent.manuscript_scrub import (  # type: ignore[import-not-found]
    dedupe_included_studies,
    rejected_citation_tokens_from_artifacts,
    scrub_broken_effect_estimates,
    scrub_engine_residue,
    scrub_paper,
    scrub_rejected_evidence_leaks,
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


def test_scrub_residue_removes_h3_section_tags() -> None:
    md = "### H3: Cardiometabolic Outcomes\n\nClean body.\n"
    out, n = scrub_engine_residue(md)
    assert n == 1
    assert "H3:" not in out
    assert "### Cardiometabolic Outcomes" in out


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


def test_dedupe_references_section_collapses_dup_citations() -> None:
    """Wave 25: same paper retrieved under different identifiers
    (PMID vs DOI vs manual ID) produces multiple receipt entries
    that get rendered as multiple References lines. The scrubber
    must collapse to one entry per citation_token."""
    from agent.manuscript_scrub import (  # type: ignore[import-not-found]
        dedupe_references_section,
    )
    md = (
        "## References\n\n"
        "- **Walton 2019.** _Title A._ Aging Cell, 2019. PMID 32385376.\n"
        "- **Walton 2019.** _Title A._ Aging Cell, 2019. PMID 31557380.\n"
        "- **Smith 2020.** _Other paper._ JAMA, 2020. PMID 12345.\n"
    )
    out, n = dedupe_references_section(md)
    assert n == 1
    assert out.count("**Walton 2019.**") == 1
    assert "**Smith 2020.**" in out


def test_dedupe_references_section_no_op_when_unique() -> None:
    from agent.manuscript_scrub import (  # type: ignore[import-not-found]
        dedupe_references_section,
    )
    md = (
        "## References\n\n"
        "- **Smith 2020.** _A._ J, 2020. PMID 1.\n"
        "- **Jones 2021.** _B._ J, 2021. PMID 2.\n"
    )
    out, n = dedupe_references_section(md)
    assert out == md
    assert n == 0


def test_fix_qei_title_count_updates_top_N_to_actual_rows() -> None:
    """Wave 25: when the QEI title says 'Top 40' but only 3 data rows
    follow, the title must be repaired to 'Top 3'. Universal — every
    topic uses the same QEI title format. Markdown italic underscores
    around 'Top N' must not block the match."""
    from agent.manuscript_scrub import (  # type: ignore[import-not-found]
        fix_qei_title_count,
    )
    md = (
        "## Quantitative Evidence Index — testing\n\n"
        "_Top 40 high-confidence numeric claims._\n\n"
        "| Study | Endpoint | Value |\n| --- | --- | --- |\n"
        "| Smith 2020 | A | 0.5 |\n"
        "| Jones 2021 | B | 0.7 |\n"
        "| Patel 2022 | C | 0.9 |\n"
    )
    out, fixed = fix_qei_title_count(md)
    assert fixed
    assert "Top 3" in out
    assert "Top 40" not in out


def test_fix_qei_title_no_op_when_count_matches() -> None:
    from agent.manuscript_scrub import (  # type: ignore[import-not-found]
        fix_qei_title_count,
    )
    md = (
        "## Quantitative Evidence Index — testing\n\n"
        "Top 2 high-confidence numeric claims.\n\n"
        "| Study | Value |\n| --- | --- |\n"
        "| Smith 2020 | 0.5 |\n"
        "| Jones 2021 | 0.7 |\n"
    )
    out, fixed = fix_qei_title_count(md)
    assert not fixed
    assert out == md


def test_rejected_tokens_from_artifacts_maps_spar_rejects() -> None:
    manifest = {
        "receipts": [
            {"receipt_id": "r1", "citation_token": "Smith 2020"},
            {"receipt_id": "r2", "citation_token": "Jones 2021"},
        ]
    }
    spar_cache = {
        "verdicts": {
            "r1": {"verdict": "reject_direction_mismatch"},
            "r2": {"verdict": "accept_clean"},
        }
    }
    assert rejected_citation_tokens_from_artifacts(
        manifest, spar_cache,
    ) == ("Smith 2020",)


def test_scrub_broken_effect_estimate_sentence_removed() -> None:
    md = (
        "## Results\n\n"
        "The trial was heterogeneous. UKPDS 1998 reported an effect "
        "estimate. The next sentence remains supported.\n"
    )
    out, n = scrub_broken_effect_estimates(md)
    assert n == 1
    assert "reported an effect estimate." not in out
    assert "The next sentence remains supported." in out


def test_scrub_rejected_leaks_deletes_main_body_only() -> None:
    md = (
        "## Background\n\n"
        "Smith 2020 reported a rejected effect. Jones 2021 remains.\n\n"
        "## Rejected / Contested Evidence\n\n"
        "| Citation | Verdict |\n| --- | --- |\n"
        "| Smith 2020 | reject_direction_mismatch |\n\n"
        "## References\n\n"
        "- **Smith 2020.** _Rejected paper._ Journal.\n"
    )
    out, rows, sentences = scrub_rejected_evidence_leaks(
        md, ("Smith 2020",),
    )
    assert rows == 0
    assert sentences == 1
    assert "Smith 2020 reported a rejected effect" not in out
    assert "| Smith 2020 | reject_direction_mismatch |" in out
    assert "- **Smith 2020.**" in out


def test_scrub_rejected_qei_row_updates_top_count() -> None:
    md = (
        "## Quantitative Evidence Index\n\n"
        "_Top 3 high-confidence numeric claims._\n\n"
        "| Study | Endpoint | Value |\n| --- | --- | --- |\n"
        "| Smith 2020 | A | 0.5 |\n"
        "| Jones 2021 | B | 0.7 |\n"
        "| Patel 2022 | C | 0.9 |\n"
    )
    out, report = scrub_paper(
        md, rejected_citation_tokens=("Jones 2021",),
    )
    assert report.rejected_evidence_rows_removed == 1
    assert "Jones 2021" not in out
    assert "Top 2" in out
    assert "Top 3" not in out


def test_dedupe_runs_across_multiple_evidence_tables() -> None:
    """Wave 24: dedupe also collapses Risk-of-Bias (Table 4) and
    other ## Table N sections. Universal — every topic uses the same
    `## Table N: ...` schema with citation_token first cell."""
    md = (
        "## Table 1: Included Studies\n\n"
        "| Citation | Tier |\n| --- | --- |\n"
        "| Walton 2019 | A1 |\n"
        "| Walton 2019 | A1 |\n"
        "## Table 4 (supplemental): Per-Domain Risk of Bias\n\n"
        "| Citation | Domain1 | Domain2 |\n| --- | --- | --- |\n"
        "| Konopka 2019 | Some | Concerns |\n"
        "| Konopka 2019 | Some | Concerns |\n"
    )
    out, n = dedupe_included_studies(md)
    assert n == 2
    assert out.count("| Walton 2019") == 1
    assert out.count("| Konopka 2019") == 1


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
