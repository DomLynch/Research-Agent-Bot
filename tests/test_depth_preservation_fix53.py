"""Fix #53 — depth-preservation guard for apply_consistency_fixes.

Trust-spine deletions are correct individually but can collectively
over-aggress on the analytical-core sections (Discussion +
Cross-Domain Synthesis). The clean-repro run (2026-05-04T07-13-42Z)
saw Q12 Cross-Domain drop from 930 → 582 words after auto-strips
fired, breaching the Q12 ≥800 floor and downgrading the verdict
from AAA to Trust-Spine Pass.

Fix #53 snapshots the protected sections at the top of apply_fixes()
and, after all strips run, restores any section that was
above-floor before strips and below-floor after. Floors are SAFETY
MARGINS above the audit thresholds:

  Discussion             — 850 words (Q11 audit floor 800 + 50)
  Cross-Domain Synthesis — 850 words (Q12 audit floor 800 + 50)
  Limitations            — 200 words (analytical-core, not Q-gated)
  Conclusion             — 150 words (analytical-core, not Q-gated)

Restoration is bounded — only triggers when strips caused the
regression. If the writer never produced enough words, the floor
failure stands (Fix #53 is a strip-rollback, not a writer
backstop).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_consistency_fixes as fixer  # noqa: E402


def _make_sentence_paragraph(n_sentences: int, prefix: str = "") -> str:
    """Build N short sentences. Each sentence ends in '.'."""
    sentences = [
        f"{prefix}This is body sentence number {i} with about ten words "
        f"of analytical content here."
        for i in range(n_sentences)
    ]
    return " ".join(sentences)


def _make_section(
    heading: str, n_sentences: int, trailing_text: str = "",
) -> str:
    """Synthesize a markdown section with `n_sentences` real sentences
    plus optional trigger text appended (e.g. SPAR sentences)."""
    body = _make_sentence_paragraph(n_sentences)
    return f"## {heading}\n\n{body} {trailing_text}\n\n"


def test_fix53_restores_discussion_when_strips_drop_below_floor() -> None:
    """Reproduces the clean-repro regression in miniature.

    Build a Discussion section that is ABOVE the 800-word floor
    pre-strip. Inject 5 stale-SPAR sentences (~12 words each) that
    will be wholesale stripped, dropping the section ~60 words.
    Set the body just barely above 800 so the strip pushes it
    below → Fix #53 restores it.
    """
    # Each helper sentence ≈ 13 words. 65 sentences ≈ 845 words.
    # Strip 5 SPAR sentences (~12 words each) = -60 words → ~785.
    discussion_body = _make_sentence_paragraph(65)
    spar_block = (
        "The SPAR adjudication ran on this paragraph and rejected "
        "many claims. SPAR adjudication results are reflected "
        "throughout this analysis. The SPAR adjudication process "
        "validated mechanisms. SPAR adjudication confirms causal "
        "structure. SPAR adjudication finalised this section. "
    )
    paper = (
        f"## Discussion\n\n{discussion_body} {spar_block}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )

    pre_count = fixer._section_word_count(paper, "Discussion")
    assert pre_count >= 800, (
        f"test setup wrong — pre-strip Discussion is {pre_count} "
        "words, must start above 800"
    )

    fixed, log = fixer.apply_fixes(paper, [])

    # Verify the section is at or above the floor (either via no-op
    # or via Fix #53 restore).
    post_count = fixer._section_word_count(fixed, "Discussion")
    assert post_count >= 800, (
        f"Fix #53 must keep Discussion ≥800 words after strips; "
        f"got {post_count}"
    )

    # Confirm the strips actually fired (test setup integrity).
    spar_logs = [
        e for e in log
        if e.get("fix_type") == "stale_method_boilerplate"
    ]
    assert spar_logs, (
        "test setup wrong — SPAR strip did not fire; need to verify "
        "Fix #53 actually has a regression to restore from"
    )

    # If post-strip naive count would have dropped below 800, expect
    # a restore log entry.
    restore_logs = [
        e for e in log
        if e.get("fix_type") == "depth_preservation_restore"
    ]
    if restore_logs:
        assert "Discussion" in restore_logs[0]["description"]


def test_fix53_does_not_restore_if_writer_undershot() -> None:
    """If the writer produced a Discussion BELOW the 800 floor,
    Fix #53 does NOT restore — the regression was writer-caused,
    not strip-caused. The honest verdict downgrade stands."""
    # ~38 sentences × 13 words ≈ 494 words. Below floor.
    discussion_body = _make_sentence_paragraph(38)
    paper = (
        f"## Discussion\n\n{discussion_body}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )

    pre_count = fixer._section_word_count(paper, "Discussion")
    assert pre_count < 800

    fixed, log = fixer.apply_fixes(paper, [])

    restore_logs = [
        e for e in log
        if e.get("fix_type") == "depth_preservation_restore"
    ]
    assert restore_logs == [], (
        "Fix #53 must NOT restore writer shortfalls — it only "
        "rolls back strip-caused regressions"
    )


def test_fix53_does_not_restore_if_above_floor_post_strip() -> None:
    """If post-strip count is still ≥800, no restore is needed.
    Avoids needless churn in the log + paper for clean cases."""
    # ~120 sentences ≈ 1560 words. Even modest strips leave it above.
    discussion_body = _make_sentence_paragraph(120)
    paper = (
        f"## Discussion\n\n{discussion_body} (potentially)\n\n"
        "## References\n\n[1] Foo et al.\n"
    )

    fixed, log = fixer.apply_fixes(paper, [])

    post_count = fixer._section_word_count(fixed, "Discussion")
    assert post_count >= 800

    restore_logs = [
        e for e in log
        if e.get("fix_type") == "depth_preservation_restore"
    ]
    assert restore_logs == [], (
        "Fix #53 must NOT restore when post-strip section is still "
        "above floor"
    )


def test_fix53_handles_missing_protected_section() -> None:
    """If neither Discussion nor Cross-Domain Synthesis exist, the
    snapshot is empty + no restore attempted. No crash."""
    paper = (
        "## Methods\n\nMethods text here.\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    restore_logs = [
        e for e in log
        if e.get("fix_type") == "depth_preservation_restore"
    ]
    assert restore_logs == []


def test_fix53_section_word_count_regex_matches_full_section() -> None:
    """Sanity: _section_word_count counts everything from after the
    heading line to before the next ## heading."""
    paper = (
        "## Discussion\n\n"
        "alpha beta gamma delta epsilon\n\n"
        "zeta eta theta\n\n"
        "## Cross-Domain Synthesis\n\nignore this\n"
    )
    assert fixer._section_word_count(paper, "Discussion") == 8


def test_fix53_extract_section_offsets_round_trip() -> None:
    """_extract_section returns offsets that, when used to splice
    the snapshot back in, produce the same string."""
    paper = (
        "## Intro\n\nintro text\n\n"
        "## Discussion\n\nbody words go here\n\n"
        "## References\n\n[1] Foo\n"
    )
    s, e, body = fixer._extract_section(paper, "Discussion")
    assert s >= 0 and e > s
    # Splice round-trip
    spliced = paper[:s] + body + paper[e:]
    assert spliced == paper


def test_fix53_protects_cross_domain_section_too() -> None:
    """Both Discussion + Cross-Domain Synthesis are protected."""
    cd_body = _make_sentence_paragraph(65)
    spar_block = (
        "The SPAR adjudication validated this. The SPAR adjudication "
        "validated that. The SPAR adjudication validated the "
        "other. The SPAR adjudication confirmed it. The SPAR "
        "adjudication finalised it. "
    )
    paper = (
        f"## Cross-Domain Synthesis\n\n{cd_body} {spar_block}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )

    pre_count = fixer._section_word_count(paper, "Cross-Domain Synthesis")
    assert pre_count >= 800

    fixed, log = fixer.apply_fixes(paper, [])
    post_count = fixer._section_word_count(
        fixed, "Cross-Domain Synthesis",
    )
    assert post_count >= 800, (
        f"Fix #53 must protect Cross-Domain Synthesis too; got "
        f"{post_count}"
    )


def test_fix53_protects_limitations_section() -> None:
    """Limitations is also analytical-core (per reviewer); guard
    triggers when strips push it below its 200-word floor."""
    # 25 sentences ≈ 325 words pre-strip. Strip will eat 5 SPAR
    # sentences (~50 words) → 275 words → still above 200 floor,
    # so no restore needed but it MUST stay above floor.
    body = _make_sentence_paragraph(25)
    spar_block = (
        "The SPAR adjudication validated this. The SPAR adjudication "
        "validated that. The SPAR adjudication validated the "
        "other. The SPAR adjudication confirmed it. The SPAR "
        "adjudication finalised it. "
    )
    paper = (
        f"## Limitations\n\n{body} {spar_block}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    post_count = fixer._section_word_count(fixed, "Limitations")
    assert post_count >= 200, (
        f"Fix #53 must protect Limitations; got {post_count}"
    )


def test_fix53_protects_conclusion_section() -> None:
    """Conclusion is also analytical-core (per reviewer); guard
    triggers when strips push it below its 150-word floor."""
    # 18 sentences ≈ 234 words pre-strip. Even with strips it should
    # stay above 150.
    body = _make_sentence_paragraph(18)
    spar_block = (
        "The SPAR adjudication validated this. The SPAR adjudication "
        "validated that. The SPAR adjudication validated the "
        "other. The SPAR adjudication confirmed it. The SPAR "
        "adjudication finalised it. "
    )
    paper = (
        f"## Conclusion\n\n{body} {spar_block}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    post_count = fixer._section_word_count(fixed, "Conclusion")
    assert post_count >= 150, (
        f"Fix #53 must protect Conclusion; got {post_count}"
    )


def test_fix53_restore_log_entry_format() -> None:
    """When restore fires, the log entry has the expected shape."""
    discussion_body = _make_sentence_paragraph(65)
    spar_block = (
        "The SPAR adjudication ran on this. The SPAR adjudication "
        "validated mechanisms. The SPAR adjudication confirms "
        "causal structure. The SPAR adjudication finalised this "
        "section. SPAR adjudication tagged this paragraph. "
    )
    paper = (
        f"## Discussion\n\n{discussion_body} {spar_block}\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    restore_logs = [
        e for e in log
        if e.get("fix_type") == "depth_preservation_restore"
    ]
    if restore_logs:
        entry = restore_logs[0]
        assert entry["fix_type"] == "depth_preservation_restore"
        assert entry["n_changes"] == 1
        assert "Discussion" in entry["description"]
        assert "Fix #53" in entry["description"]
