"""Tests for scripts/apply_patches.py — patch-applicator gates."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_patches  # noqa: E402


def _manifest() -> dict:
    return {
        "receipts": [
            {"receipt_id": "Walton_2019_MASTERS"},
            {"receipt_id": "Konopka_2019_metformin"},
        ],
    }


def _formatting_patch() -> dict:
    return {
        "id": "P01", "patch_type": "formatting", "severity": "P3",
        "location": "Abstract",
        "before": "metformin  is", "after": "metformin is",
        "reason": "double space",
    }


def test_formatting_patch_auto_applies() -> None:
    paper = "## Abstract\n\nThe metformin  is widely studied.\n"
    new_md, results = apply_patches.apply_patches(
        paper, [_formatting_patch()], _manifest(),
    )
    assert "metformin is" in new_md
    assert "metformin  is" not in new_md
    assert results[0].decision == "applied"


def test_claim_patch_auto_applies_with_diagnostic() -> None:
    """Architectural shift: there are NO HUMANS in the pipeline. Grok
    4.3 is the final-layer reviewer; flag-for-human is a dead-letter
    state. Claim patches now auto-apply, with a diagnostic line in
    `reason_for_decision` so retroactive review can identify any
    auto-applied patch the deterministic verifier would have rejected."""
    p = {
        "id": "P02", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "metformin extended lifespan",
        "after": "metformin reduced mortality",
        "reason": "polarity correction",
    }
    paper = "## Discussion\n\nIn mice, metformin extended lifespan by 14%.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "metformin reduced mortality" in new_md  # applied
    assert "metformin extended lifespan" not in new_md
    assert results[0].decision == "applied"
    assert "trust Grok" in results[0].reason_for_decision


def test_structure_patch_auto_applies_with_diagnostic() -> None:
    p = {
        "id": "P03", "patch_type": "structure", "severity": "P2",
        "location": "Results",
        "before": "## Results", "after": "## Findings",
        "reason": "rename section",
    }
    paper = "## Results\n\nText.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "## Findings" in new_md
    assert results[0].decision == "applied"


def test_numeric_patch_auto_applies_with_verifier_diagnostic() -> None:
    """Numeric patches now auto-apply (Grok-final-layer trust). The
    deterministic global-corpus verifier still runs and its pass/fail
    is recorded in the diagnostic line for retroactive audit, but it
    no longer blocks apply. The Phase 6.4 'same-claim binding' check
    remains the right long-term hardening."""
    p = {
        "id": "P04", "patch_type": "numeric", "severity": "P2",
        "location": "Results",
        "before": "by 14%", "after": "by 32%",
        "reason": "wrong percentage",
    }
    paper = "## Results\n\nIncreased by 14% in mice.\n"
    with mock_patch.object(
        apply_patches, "_load_corpus_numerics",
        return_value={"32", "32.0", "14", "14.0"},
    ):
        new_md, results = apply_patches.apply_patches(
            paper, [p], _manifest(),
        )
    assert "by 32%" in new_md
    assert results[0].decision == "applied"
    # Verifier diagnostic should be in the reason
    assert "numeric verifier: pass" in results[0].reason_for_decision.lower()


def test_numeric_patch_with_untraceable_value_still_applies_with_FAIL_diagnostic() -> None:
    """Even when the global-corpus verifier reports FAIL, the patch
    auto-applies. Grok is the final say. The FAIL is recorded in the
    diagnostic so a retroactive reviewer can inspect."""
    p = {
        "id": "P05", "patch_type": "numeric", "severity": "P2",
        "location": "Abstract",
        "before": "by 14%", "after": "by 99.9%",
        "reason": "spurious",
    }
    paper = "## Abstract\n\nLifespan increased by 14% in mice.\n"
    with mock_patch.object(
        apply_patches, "_load_corpus_numerics",
        return_value={"14", "14.0"},  # 99.9 not in corpus
    ):
        new_md, results = apply_patches.apply_patches(
            paper, [p], _manifest(),
        )
    assert "by 99.9%" in new_md  # auto-applied
    assert results[0].decision == "applied"
    # Verifier should have reported FAIL in the diagnostic
    assert "fail" in results[0].reason_for_decision.lower()


def test_citation_patch_with_known_receipt_applies() -> None:
    """Replace a citation with another known receipt = auto-apply."""
    p = {
        "id": "P06", "patch_type": "citation", "severity": "P2",
        "location": "Discussion",
        "before": "(Walton 2019)", "after": "(Konopka 2019)",
        "reason": "wrong attribution",
    }
    paper = "## Discussion\n\nResults are interesting (Walton 2019).\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "(Konopka 2019)" in new_md
    assert results[0].decision == "applied"


def test_citation_patch_with_unknown_receipt_still_applies_with_FAIL_diagnostic() -> None:
    """Even when the citation doesn't trace to manifest receipts, the
    patch auto-applies (Grok-final-layer trust). The FAIL is recorded
    in the diagnostic so a retroactive reviewer can inspect."""
    p = {
        "id": "P07", "patch_type": "citation", "severity": "P2",
        "location": "Discussion",
        "before": "(Walton 2019)", "after": "(Smith 2020)",
        "reason": "alternate cite",
    }
    paper = "## Discussion\n\nResults are interesting (Walton 2019).\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "(Smith 2020)" in new_md
    assert results[0].decision == "applied"
    assert "fail" in results[0].reason_for_decision.lower()


def test_patch_with_missing_before_text_rejected() -> None:
    p = {
        "id": "P08", "patch_type": "formatting", "severity": "P3",
        "location": "Abstract",
        "before": "this exact text is not in paper",
        "after": "irrelevant",
        "reason": "test",
    }
    paper = "## Abstract\n\nDifferent text.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "not found" in results[0].reason_for_decision


def test_patch_with_ambiguous_before_text_rejected() -> None:
    """If 'before' appears 2+ times, mechanical safety REJECTS the
    patch — there's no way to know which occurrence Grok meant. This
    is the only remaining safety gate after the trust-Grok shift."""
    p = {
        "id": "P09", "patch_type": "formatting", "severity": "P3",
        "location": "(any)",
        "before": "metformin", "after": "Metformin",
        "reason": "case fix",
    }
    paper = "## Abstract\n\nmetformin study. metformin trial.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "ambiguous" in results[0].reason_for_decision
    # Paper unchanged
    assert paper == new_md


def test_log_includes_per_patch_decision_with_reason() -> None:
    """Log structure must capture the per-patch decision and reason
    for downstream audit replay (per the converged 'audit replay'
    requirement)."""
    p = _formatting_patch()
    paper = "## Abstract\n\nThe metformin  is widely studied.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    r = results[0]
    assert r.patch_id == "P01"
    assert r.patch_type == "formatting"
    assert r.severity == "P3"
    assert r.decision in ("applied", "flagged", "rejected")
    assert r.reason_for_decision  # non-empty
    assert r.before
    assert r.after


# Reviewer-fix HIGH 1 regression: citation regex must NOT false-fire
# on Title Case proper nouns.
def test_citation_regex_does_not_falsefire_on_proper_nouns() -> None:
    """A citation patch where `after` introduces 'Section 2' or
    'Discussion' (capitalized non-citation prose) must NOT be flagged
    as a 'novel un-traced citation'. Pre-fix the regex matched any
    [A-Z][a-zA-Z]+ word."""
    p = {
        "id": "PX1", "patch_type": "citation", "severity": "P2",
        "location": "Discussion",
        "before": "(Walton 2019)",
        "after": "(Walton 2019), as discussed in Section 2",
        "reason": "add cross-reference",
    }
    paper = "## Discussion\n\nThe results (Walton 2019) are interesting.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    # Should APPLY (no novel citations; "Section" is just proper-noun prose)
    assert results[0].decision == "applied", (
        f"Title Case word wrongly treated as novel citation: "
        f"{results[0].reason_for_decision}"
    )


# Reviewer-fix HIGH 2 regression: numeric token with unit suffix
# (no space) like "32%" exercises the bare-prefix fallback path. Patch
# auto-applies (Grok-final-layer trust); verifier diagnostic stays in
# the reason for retroactive audit.
def test_numeric_token_with_glued_unit_suffix_verifier_reports_pass() -> None:
    """Verifier must trace '32%' to corpus value '32'. Patch auto-
    applies; verifier's PASS/FAIL goes into the diagnostic line."""
    p = {
        "id": "PX2", "patch_type": "numeric", "severity": "P2",
        "location": "Results",
        "before": "by 14% in mice",
        "after": "by 32% in mice",
        "reason": "wrong percentage",
    }
    paper = "## Results\n\nThe value rose by 14% in mice.\n"
    with mock_patch.object(
        apply_patches, "_load_corpus_numerics",
        return_value={"32", "32.0", "14", "14.0"},
    ):
        _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    reason = results[0].reason_for_decision.lower()
    assert "numeric verifier: pass" in reason, (
        f"glued unit-suffix verifier should report PASS: "
        f"{results[0].reason_for_decision}"
    )
