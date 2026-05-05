"""Fix #54 — cross-sentence anaphoric misread of change-value numerics.

C13 (Fix #37) catches per-sentence misreads:
  'value of 0.13 m/s, below the 0.8 m/s threshold' → P1

But the reviewer caught a CROSS-SENTENCE variant in fix53-verify
line 156 that slipped through:

  Sentence A: '...placebo group showing no change in walk speed
                (0.13 m/s)...'        [has 'change' → C13 clears]
  Sentence B: 'This walk speed value is below the 0.8 m/s
                threshold...'         [no 0.13 m/s → C13 skips]

The implicit anaphoric reference ('this walk speed value' refers
back to 0.13 m/s) means sentence B effectively treats the change
as absolute. Fix #54 detects + auto-strips this pattern.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import final_consistency_audit as fca  # noqa: E402
import apply_consistency_fixes as fixer  # noqa: E402


def _empty_audit() -> dict:
    return {"score_out_of_10": 10.0, "p1_pass": True}


def _empty_manifest() -> dict:
    return {"receipts": []}


# =========== Fix #54 — detection (C13b) ============================


def test_fix54_catches_walk_speed_anaphor_pattern() -> None:
    """The exact reviewer-flagged pattern from fix53-verify line 156:
    sentence A has 0.13 m/s with 'change'; sentence B says 'this
    walk speed value is below 0.8 m/s threshold'. Fix #54 must
    flag sentence B as P1."""
    paper = (
        "## Frailty\n\n"
        "The MET-PREVENT trial reported the placebo group showing "
        "no change in frailty status or walk speed (0.13 m/s). "
        "This walk speed value is below the 0.8 m/s threshold "
        "associated with impaired mobility and frailty risk.\n"
    )
    issues = fca._check_change_value_anaphor_misread(
        paper, _empty_manifest(),
    )
    c13b = [
        i for i in issues
        if i.id.startswith("C13b-anaphor-misread-")
    ]
    assert len(c13b) >= 1, (
        "Fix #54 must catch the anaphoric misread pattern"
    )
    assert c13b[0].severity == "P1"
    assert c13b[0].auto_fixable is True
    assert "this walk speed value" in c13b[0].evidence.lower()


def test_fix54_catches_actual_fix53_verify_paper() -> None:
    """End-to-end on the real fix53-verify paper that the reviewer
    flagged — must catch the misread that C13 missed."""
    paper_path = (
        Path(__file__).resolve().parent.parent
        / "runs/synthesis-metformin-v06-fix53-verify-"
          "2026-05-04T07-52-04Z/full_paper.md"
    )
    if not paper_path.exists():
        return  # archived; skip silently
    paper = paper_path.read_text()
    issues = fca._check_change_value_anaphor_misread(
        paper, _empty_manifest(),
    )
    c13b = [
        i for i in issues
        if i.id.startswith("C13b-anaphor-misread-")
    ]
    assert len(c13b) >= 1, (
        "Fix #54 must catch the reviewer-flagged misread on "
        "fix53-verify (line 156)"
    )


def test_fix54_silent_when_no_anaphor() -> None:
    """A paragraph with the change-numeric BUT no anaphoric back-
    reference produces no C13b finding."""
    paper = (
        "## Frailty\n\n"
        "The trial reported a 0.13 m/s improvement in walk speed "
        "with metformin treatment.\n"
    )
    issues = fca._check_change_value_anaphor_misread(
        paper, _empty_manifest(),
    )
    c13b = [i for i in issues if i.id.startswith("C13b-")]
    assert c13b == [], (
        "Should not flag a single sentence with change-word and no "
        "anaphor"
    )


def test_fix54_silent_for_legitimate_absolute_speed() -> None:
    """A sentence reporting an ACTUAL absolute walk speed (not the
    0.13 m/s change value) is not a misread. The detector must not
    false-positive on legitimate absolute-value reporting."""
    paper = (
        "## Methods\n\n"
        "Baseline walk speed was 0.78 m/s in the metformin arm and "
        "0.81 m/s in the placebo arm at randomization. "
        "These walk speed values fall below the 1.0 m/s normative "
        "threshold for healthy older adults.\n"
    )
    issues = fca._check_change_value_anaphor_misread(
        paper, _empty_manifest(),
    )
    c13b = [i for i in issues if i.id.startswith("C13b-")]
    assert c13b == [], (
        f"Fix #54 must NOT flag legitimate absolute speeds; got "
        f"{[i.evidence for i in c13b]}"
    )


def test_fix54_silent_when_change_word_repeated_in_anaphor() -> None:
    """A defence: 'This represents a change of X below threshold'
    is OK — the change-word is in the anaphor sentence so the
    interpretation is preserved."""
    paper = (
        "## Frailty\n\n"
        "The trial reported a 0.13 m/s improvement in walk speed. "
        "This change in walk speed remains below the 0.5 m/s "
        "clinically meaningful difference threshold.\n"
    )
    issues = fca._check_change_value_anaphor_misread(
        paper, _empty_manifest(),
    )
    c13b = [i for i in issues if i.id.startswith("C13b-")]
    assert c13b == [], (
        "Should NOT flag when the anaphor sentence repeats the "
        "change-word — interpretation is preserved"
    )


# =========== Fix #54 — auto-strip ===================================


def test_fix54_auto_strip_removes_misread_sentence() -> None:
    """The threshold-comparison sentence (B) is the misread carrier.
    Auto-strip removes it; the change-numeric sentence (A) stays.

    Note: includes 'Studenski 2011' citation so the upstream
    background-lit strip (Fix #18b) doesn't pre-empt Fix #54 — we
    want to test Fix #54 in the realistic case where the writer
    cited the threshold reference."""
    paper = (
        "## Frailty\n\n"
        "The MET-PREVENT trial reported a walk-speed change of "
        "0.13 m/s in the placebo group. "
        "This walk speed value is below the 0.8 m/s threshold "
        "(Studenski 2011) associated with impaired mobility and "
        "frailty risk.\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    anaphor_logs = [
        e for e in log
        if e.get("fix_type") == "change_value_anaphor_strip"
    ]
    assert anaphor_logs, (
        f"Fix #54 auto-strip must fire; log was: "
        f"{[e['fix_type'] for e in log]}"
    )
    assert anaphor_logs[0]["n_changes"] >= 1
    # Misread sentence is gone
    assert "This walk speed value is below" not in fixed
    # Change-numeric sentence stays
    assert "0.13 m/s" in fixed


def test_fix54_auto_strip_clears_audit_p1() -> None:
    """Round-trip: after Fix #54 strips the misread, a re-audit
    finds no remaining C13b issues — the gap is closed."""
    paper = (
        "## Frailty\n\n"
        "The trial showed a 0.13 m/s improvement in walk speed. "
        "This walk speed value is below the 0.8 m/s frailty "
        "threshold (Studenski 2011) associated with mobility "
        "risk.\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, _log = fixer.apply_fixes(paper, [])
    issues = fca._check_change_value_anaphor_misread(
        fixed, _empty_manifest(),
    )
    c13b = [i for i in issues if i.id.startswith("C13b-")]
    assert c13b == [], (
        f"Fix #54 strip did not clear C13b — remaining: "
        f"{[i.evidence for i in c13b]}"
    )


def test_fix54_preserves_paragraph_structure() -> None:
    """Strip must not destroy the rest of the paragraph or other
    sentences. Only the misread sentence disappears."""
    paper = (
        "## Frailty\n\n"
        "The trial reported a 0.13 m/s improvement. "
        "This walk speed value is below the 0.8 m/s threshold "
        "(Studenski 2011). "
        "Other findings included reduced grip strength in the "
        "placebo arm.\n\n"
        "## References\n\n[1] Foo et al.\n"
    )
    fixed, _log = fixer.apply_fixes(paper, [])
    assert "0.13 m/s improvement" in fixed
    assert "This walk speed value is below" not in fixed
    assert "Other findings included reduced grip strength" in fixed
