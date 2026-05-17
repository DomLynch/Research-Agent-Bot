"""Fix #39 — smart final-reviewer gate for claim/numeric patches.

Pure-deletion / strict-simplification patches auto-apply; semantic
substitutions and content additions stay flagged. Per the reviewer's
tightening: AFTER must be shorter-or-equal, AFTER's words must be a
strict subset of BEFORE's words, AND post-apply Q2 + Stage-2 audits
must not regress."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches as ap  # noqa: E402


def _manifest() -> dict:
    return {"writer_path": "agent.paper_writer.render_full_paper"}


# ============ _is_safe_simplification helper unit tests ===============


def test_pure_deletion_passes_simplification_gate() -> None:
    """The reviewer's actual 0.13 m/s fix: deletes the word 'improvement'."""
    ok, msg = ap._is_safe_simplification(
        "walk speed (0.13 m/s improvement), while...",
        "walk speed (0.13 m/s), while...",
    )
    assert ok is True
    assert "safe simplification" in msg


def test_sentence_deletion_passes_simplification_gate() -> None:
    """The reviewer's actual 'consistent with 5%' fix: deletes the false
    consistency claim entirely, leaving just a period."""
    ok, msg = ap._is_safe_simplification(
        ", consistent with the approximately 5% typical extension "
        "noted in metformin animal studies (Anisimov 2008).",
        " .",
    )
    assert ok is True


def test_semantic_substitution_blocked_by_subset_rule() -> None:
    """`extended lifespan` → `reduced mortality` has same word
    count, no new numerics — but introduces 'reduced' and
    'mortality' as new content words."""
    ok, msg = ap._is_safe_simplification(
        "metformin extended lifespan",
        "metformin reduced mortality",
    )
    assert ok is False
    assert "semantic substitution" in msg


def test_new_numeric_blocked() -> None:
    """`by 14%` → `by 32%` introduces 32 as a new numeric."""
    ok, msg = ap._is_safe_simplification("by 14%", "by 32%")
    assert ok is False
    assert "new numeric" in msg


def test_new_citation_blocked() -> None:
    """AFTER introducing 'Smith 2020' (not in BEFORE) is
    hallucination. The new-numeric check fires first ('2020' is a
    new digit token), but either rejection is correct — both are
    safety failures."""
    ok, msg = ap._is_safe_simplification(
        "Walton 2019 reported negative results.",
        "Walton 2019 and Smith 2020 reported negative results.",
    )
    assert ok is False
    # Either failure mode catches the hallucinated citation
    assert "new numeric" in msg or "new citation" in msg


def test_new_capitalized_identifier_blocked() -> None:
    """Introducing a new drug or trial name not in BEFORE."""
    ok, msg = ap._is_safe_simplification(
        "metformin reduced mortality",
        "metformin and Sirolimus reduced mortality",
    )
    assert ok is False
    assert "new identifier" in msg


def test_word_count_growth_blocked_strict() -> None:
    """Reviewer-tightened: AFTER must be shorter-or-equal. Even
    1-word growth is rejected (no tolerance)."""
    ok, msg = ap._is_safe_simplification(
        "metformin reduced",
        "metformin reduced significantly",
    )
    assert ok is False
    assert "longer than BEFORE" in msg or "shorter-or-equal" in msg


def test_word_reorder_within_existing_set_passes() -> None:
    """Pure reordering of the SAME word set passes."""
    ok, msg = ap._is_safe_simplification(
        "in mice metformin extended lifespan",
        "metformin extended lifespan in mice",
    )
    assert ok is True


# ============ End-to-end gate behaviour with real paper text ==========


def test_reviewer_real_walk_speed_deletion_auto_applies() -> None:
    """End-to-end: The reviewer's actual P1 patch on the public-repro paper
    auto-applies under Fix #39 (pure deletion of 'improvement')."""
    p = {
        "id": "P-real-1", "patch_type": "numeric", "severity": "P1",
        "location": "Results",
        "before": (
            "or walk speed (0.13 m/s improvement), while the "
            "metformin group's functional trajectory was less "
            "favorable."
        ),
        "after": (
            "or walk speed (0.13 m/s), while the metformin group's "
            "functional trajectory was less favorable."
        ),
        "reason": "Walk speed remained at 0.13 m/s with no improvement",
    }
    paper = (
        "## Results\n\n"
        "MET-PREVENT showed no change for placebo or walk speed "
        "(0.13 m/s improvement), while the metformin group's "
        "functional trajectory was less favorable.\n"
    )
    new_md, results = ap.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied", (
        f"The reviewer's pure-deletion patch should auto-apply under Fix "
        f"#39. Got: {results[0].decision} — "
        f"{results[0].reason_for_decision}"
    )
    assert "0.13 m/s improvement" not in new_md
    assert "0.13 m/s)" in new_md


def test_final_reviewer_prompt_documents_smart_gate_contract() -> None:
    """Fix #40: the final-layer reviewer system prompt explicitly tells the
    model to prefer deletion-style patches because the smart-gate
    only auto-applies them. Without this guidance the model proposes
    word-growth rewordings that the gate then refuses, making AAA
    non-reproducible."""
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts"
    ))
    import final_reviewer as gr
    system, _user = gr._build_reviewer_prompt(
        paper_md="## Test\n\nbody.\n",
        manifest={"receipts": []},
        audit={"checks": [], "p1_pass": True, "score_out_of_10": 10},
    )
    # Smart-gate contract is documented in the prompt
    assert "smart-gate" in system or "smart gate" in system
    assert "DELETION" in system
    assert "shorter-or-equal" in system
    # Concrete examples of GOOD vs BAD patches present
    assert "GOOD" in system and "BAD" in system


def test_reviewer_real_consistency_claim_deletion_auto_applies() -> None:
    """End-to-end: The reviewer's deletion of the false 'consistent with 5%'
    claim auto-applies under Fix #39."""
    p = {
        "id": "P-real-2", "patch_type": "claim", "severity": "P1",
        "location": "Results",
        "before": (
            ", consistent with the approximately 5% typical "
            "extension noted in metformin animal studies "
            "(Anisimov 2008)."
        ),
        "after": " .",
        "reason": "Consistency claim is factually false",
    }
    paper = (
        "## Results\n\n"
        "Metformin extended lifespan by 14%, consistent with the "
        "approximately 5% typical extension noted in metformin "
        "animal studies (Anisimov 2008).\n"
    )
    new_md, results = ap.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied", (
        f"The reviewer's deletion patch should auto-apply. Got: "
        f"{results[0].decision}"
    )
    assert "consistent with the approximately 5%" not in new_md
    assert "Anisimov 2008" not in new_md
