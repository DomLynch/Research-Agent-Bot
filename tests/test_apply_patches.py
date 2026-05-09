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
            {
                "receipt_id": "PMC6400206_importance_of_physical_evaluation",
                "citation_token": "Fukuoka 2019",
            },
            {"receipt_id": "PMID25540326_mannick", "citation_token": "Mannick 2014"},
            {"receipt_id": "Lamming_2012_mtor", "citation_token": "Lamming 2012"},
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


def test_claim_patch_with_semantic_substitution_is_flagged() -> None:
    """Fix #39: claim patches go through the smart-gate. Pure
    semantic substitutions (same word count, no new numerics, but
    entirely different content words) ARE flagged by the
    strict-subset rule. 'extended lifespan' → 'reduced mortality'
    is exactly this case — Grok would be inventing a new claim, not
    deleting wrong content."""
    p = {
        "id": "P02", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "metformin extended lifespan",
        "after": "metformin reduced mortality",
        "reason": "polarity correction",
    }
    paper = "## Discussion\n\nIn mice, metformin extended lifespan by 14%.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    # Paper UNCHANGED — patch flagged by strict-subset rule
    assert "metformin extended lifespan" in new_md
    assert "metformin reduced mortality" not in new_md
    assert results[0].decision == "flagged"
    # Reason names the strict-subset failure
    assert "semantic substitution" in results[0].reason_for_decision
    # Grok's rationale preserved in the log
    assert "polarity correction" in results[0].reason_for_decision


def test_claim_patch_pure_deletion_auto_applies() -> None:
    """Fix #39: a CLAIM patch that is a pure deletion (AFTER words
    are a strict subset of BEFORE words, no new content) auto-
    applies. This is exactly Grok's 0.13 m/s 'remove improvement'
    fix that was getting blocked under the old flag-everything
    contract."""
    p = {
        "id": "P-DEL", "patch_type": "claim", "severity": "P1",
        "location": "Results",
        "before": "walk speed (0.13 m/s improvement)",
        "after": "walk speed (0.13 m/s)",
        "reason": "remove false 'improvement' qualifier",
    }
    paper = (
        "## Results\n\n"
        "MET-PREVENT showed walk speed (0.13 m/s improvement) "
        "in this analysis.\n"
    )
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    # Patch APPLIED — paper updated
    assert results[0].decision == "applied"
    assert "walk speed (0.13 m/s improvement)" not in new_md
    assert "walk speed (0.13 m/s)" in new_md


def test_structure_patch_is_flagged_only_with_grok_rationale() -> None:
    p = {
        "id": "P03", "patch_type": "structure", "severity": "P2",
        "location": "Results",
        "before": "## Results", "after": "## Findings",
        "reason": "rename section",
    }
    paper = "## Results\n\nText.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "## Results" in new_md  # unchanged
    assert results[0].decision == "flagged"
    assert "rename section" in results[0].reason_for_decision


def test_numeric_patch_with_value_substitution_is_flagged() -> None:
    """Fix #39: numeric patches go through the smart-gate. A value
    substitution like `14%` → `32%` introduces a NEW numeric (32)
    not present in BEFORE — flagged by the no-new-numerics rule.
    The strict-subset rule + the simplification gate together
    prevent Grok from silently flipping percentages even when the
    new value happens to exist somewhere in the global corpus."""
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
    # Paper unchanged — gated by Fix #39 smart-gate
    assert "by 14%" in new_md and "by 32%" not in new_md
    assert results[0].decision == "flagged"
    # Reason names the new-numeric failure
    reason = results[0].reason_for_decision.lower()
    assert "new numeric" in reason or "32" in reason


def test_claim_patch_allows_neutral_evidence_rephrase() -> None:
    p = {
        "id": "P04", "patch_type": "claim", "severity": "P1",
        "location": "Abstract",
        "before": (
            "Bitto 2016 demonstrated that transient rapamycin treatment "
            "can increase lifespan, though effects were variable."
        ),
        "after": (
            "Bitto 2016 examined transient rapamycin treatment, though "
            "effects were variable."
        ),
        "reason": "downgrade unsupported positive framing",
    }
    paper = "## Abstract\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "examined transient rapamycin treatment" in new_md


def test_claim_patch_allows_traced_citation_attribution() -> None:
    p = {
        "id": "P-cite-claim", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "This suggests a potential benefit for immune resilience.",
        "after": "Mannick 2014 suggests a potential benefit for immune resilience.",
        "reason": "attribute immune claim",
    }
    paper = "## Discussion\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "Mannick 2014 suggests" in new_md
    assert "citation attribution" in results[0].reason_for_decision


def test_claim_patch_rejects_untraced_citation_attribution() -> None:
    p = {
        "id": "P-cite-claim", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "This suggests a potential benefit for immune resilience.",
        "after": "Smith 2020 suggests a potential benefit for immune resilience.",
        "reason": "attribute immune claim",
    }
    paper = "## Discussion\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "Smith 2020" not in new_md


def test_claim_patch_allows_background_literature_attribution() -> None:
    p = {
        "id": "P-bg-cite", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "This threshold marks impaired mobility.",
        "after": "Studenski 2011 threshold marks impaired mobility.",
        "reason": "attribute background threshold",
    }
    paper = "## Discussion\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "Studenski 2011 threshold" in new_md
    assert "citation attribution" in results[0].reason_for_decision


def test_truncated_long_patch_is_rejected() -> None:
    before = "No trial measured patient-reported outcomes."
    after = "No trial measured patient-reported outcomes. " + ("word " * 115) + "funct"
    assert len(after) >= 590
    p = {
        "id": "P-trunc", "patch_type": "formatting", "severity": "P3",
        "location": "Limitations",
        "before": before,
        "after": after,
        "reason": "merge duplicated limitations",
    }
    paper = "## Limitations\n\n" + before + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "funct" not in new_md
    assert "truncated patch contract" in results[0].reason_for_decision
    assert "can increase lifespan" not in new_md


def test_patch_rejects_before_span_ending_inside_word() -> None:
    before = "This mechanistic explanation concerns metabol"
    p = {
        "id": "P-midword", "patch_type": "claim", "severity": "P2",
        "location": "Discussion",
        "before": before,
        "after": "",
        "reason": "delete unsupported mechanistic explanation",
    }
    paper = (
        "## Discussion\n\n"
        "This mechanistic explanation concerns metabolic homeostasis.\n"
    )
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "inside a token" in results[0].reason_for_decision
    assert "metabolic homeostasis" in new_md
    assert ". ic homeostasis" not in new_md


def test_formatting_patch_cannot_remove_bridge_contract_tags() -> None:
    p = {
        "id": "P05", "patch_type": "formatting", "severity": "P2",
        "location": "Inferential Bridge",
        "before": (
            "1. [D1_inferential_bridge | confidence=medium] Claim. "
            "[mechanism_anchor: A 2020] [conservation: B 2021]"
        ),
        "after": "1. Claim.",
        "reason": "remove internal tags",
    }
    paper = "## Inferential Bridge\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "[D1_inferential_bridge" in new_md
    assert "contract-preserving rejection" in results[0].reason_for_decision


def test_formatting_patch_cannot_remove_public_bridge_contract_tags() -> None:
    p = {
        "id": "P05", "patch_type": "formatting", "severity": "P2",
        "location": "Inferential Bridge",
        "before": (
            "1. [D1_inferential_bridge | confidence=medium] Claim. "
            "[mechanism anchor: A 2020] [conservation: B 2021]"
        ),
        "after": "1. Claim.",
        "reason": "remove internal tags",
    }
    paper = "## Inferential Bridge\n\n" + p["before"] + "\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "[mechanism anchor:" in new_md
    assert "contract-preserving rejection" in results[0].reason_for_decision


def test_table_fragment_deletion_removes_full_markdown_row() -> None:
    paper = (
        "| Citation | Section | Type | Value | Units |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Liu 2021 | abstract | mean ± SD | 11.6 ±147.5 | — |\n"
        "| Smith 2022 | results | p-value | P = 0.01 | — |\n"
    )
    fixed = apply_patches._apply_text_patch(
        paper,
        "Liu 2021 | abstract | mean ± SD | 11.6 ±147.5 | —",
        "",
    )
    assert "Liu 2021" not in fixed
    assert "|  |" not in fixed
    assert "Smith 2022" in fixed


def test_numeric_patch_with_untraceable_value_is_flagged_with_fail_diagnostic() -> None:
    """Numeric patches are flag-only regardless of verifier outcome.
    When the global verifier ALSO fails, both reasons are logged."""
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
    assert "by 14%" in new_md  # original kept
    assert "by 99.9%" not in new_md
    assert results[0].decision == "flagged"
    assert "fail" in results[0].reason_for_decision.lower()


def test_citation_patch_with_known_receipt_applies() -> None:
    """Citation patches DO auto-apply when the new citation traces to
    the manifest receipts — that's a fully deterministic check."""
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


def test_repeated_safe_citation_simplification_replaces_all() -> None:
    p = {
        "id": "P-cite-repeat", "patch_type": "citation", "severity": "P1",
        "location": "Results",
        "before": "(Walton 2019 2019)", "after": "(Walton 2019)",
        "reason": "duplicate citation year",
    }
    paper = (
        "## Results\n\n"
        "First result (Walton 2019 2019). "
        "Second result (Walton 2019 2019).\n"
    )
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "(Walton 2019 2019)" not in new_md
    assert new_md.count("(Walton 2019)") == 2
    assert results[0].decision == "applied"
    assert "replace-all" in results[0].reason_for_decision


def test_citation_patch_with_unknown_receipt_is_flagged() -> None:
    """When the new citation doesn't trace to manifest receipts, the
    citation verifier fails → flag-only. Grok's proposer rationale is
    logged for human review."""
    p = {
        "id": "P07", "patch_type": "citation", "severity": "P2",
        "location": "Discussion",
        "before": "(Walton 2019)", "after": "(Smith 2020)",
        "reason": "alternate cite",
    }
    paper = "## Discussion\n\nResults are interesting (Walton 2019).\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert "(Walton 2019)" in new_md  # unchanged
    assert "(Smith 2020)" not in new_md
    assert results[0].decision == "flagged"
    assert "fail" in results[0].reason_for_decision.lower()
    assert "alternate cite" in results[0].reason_for_decision


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


def test_patch_with_ambiguous_before_text_flagged() -> None:
    """If 'before' appears 2+ times, mechanical safety flags (not
    rejects) — there's no way to know which occurrence Grok meant.
    Flagged so a downstream reviewer can pick the right span; rejected
    is reserved for unrecoverable cases (text not found, empty before)."""
    p = {
        "id": "P09", "patch_type": "formatting", "severity": "P3",
        "location": "(any)",
        "before": "metformin", "after": "Metformin",
        "reason": "case fix",
    }
    paper = "## Abstract\n\nmetformin study. metformin trial.\n"
    new_md, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "ambiguous" in results[0].reason_for_decision
    # Paper unchanged
    assert paper == new_md


def test_repeated_safe_claim_simplification_replaces_all_occurrences() -> None:
    p = {
        "id": "P-CLAIM", "patch_type": "claim", "severity": "P1",
        "location": "Abstract",
        "before": "Negative signals appear in: cardiometabolic, longevity.",
        "after": "Negative signals appear in: cardiometabolic.",
        "reason": "delete unsupported longevity direction",
    }
    paper = (
        "## Abstract\n\n"
        "Negative signals appear in: cardiometabolic, longevity.\n\n"
        "## Conclusion\n\n"
        "Negative signals appear in: cardiometabolic, longevity.\n"
    )
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "longevity" not in out
    assert out.count("Negative signals appear in: cardiometabolic.") == 2


def test_known_cited_artifact_delete_replaces_all_occurrences() -> None:
    """Generated `_Cited:` metadata is a known render artifact. If
    Grok proposes deleting it as formatting, replace every identical
    occurrence instead of blocking on the usual ambiguous-before rule."""
    p = {
        "id": "P-CITED", "patch_type": "formatting", "severity": "P1",
        "location": "Results",
        "before": "_Cited: `Moel 2025`_", "after": "",
        "reason": "remove rendered citation marker",
    }
    paper = (
        "## Results\n\n"
        "_Cited: `Moel 2025`_\nParagraph one.\n"
        "_Cited: `Moel 2025`_\nParagraph two.\n"
    )
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "replace-all cleanup" in results[0].reason_for_decision
    assert "_Cited:" not in out
    assert "Paragraph one" in out and "Paragraph two" in out


def test_known_role_repair_artifact_delete_replaces_all_occurrences() -> None:
    p = {
        "id": "P-ROLE", "patch_type": "formatting", "severity": "P1",
        "location": "Discussion",
        "before": (
            "Kell 2026 reported a dose of 4; this manuscript treats "
            "the value according to that source role."
        ),
        "after": "",
        "reason": "remove numeric role repair artifact",
    }
    paper = (
        "## Discussion\n\n"
        "Kell 2026 reported a dose of 4; this manuscript treats "
        "the value according to that source role.\n\n"
        "Other text.\n\n"
        "Kell 2026 reported a dose of 4; this manuscript treats "
        "the value according to that source role.\n"
    )
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "replace-all cleanup" in results[0].reason_for_decision
    assert "reported a dose of 4" not in out
    assert "Other text." in out


def test_numeric_patch_cannot_break_qei_table_shape() -> None:
    p = {
        "id": "P-QEI",
        "patch_type": "numeric",
        "severity": "P1",
        "location": "Quantitative Evidence Index — rapamycin",
        "before": "Kell 2026 | mTOR signaling | placebo | p < 0.0001 | p value | p<0.001",
        "after": "Kell 2026 | mTOR signaling | placebo | p<0.001",
        "reason": "simplify mismatched p-value pair",
    }
    paper = (
        "## Quantitative Evidence Index — rapamycin\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Kell 2026 | mTOR signaling | placebo | p < 0.0001 | p value | p<0.001 |\n"
    )
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "table-shape FAIL" in results[0].reason_for_decision
    assert out == paper


def test_numeric_qei_row_deletion_removes_full_row() -> None:
    p = {
        "id": "P-QEI-DEL",
        "patch_type": "numeric",
        "severity": "P2",
        "location": "Quantitative Evidence Index — metformin",
        "before": "Anisimov 2008 | lifespan | metformin | 37.8% | % | —",
        "after": "",
        "reason": "delete disputed row",
    }
    paper = (
        "## Quantitative Evidence Index — metformin\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Anisimov 2008 | lifespan | metformin | 37.8% | % | — |\n"
        "| UKPDS 1998 | diabetes | metformin | P = 0.03 | p-value | — |\n"
    )
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "Anisimov 2008" not in out
    assert "UKPDS 1998" in out


def test_consecutive_duplicate_qei_headings_are_collapsed() -> None:
    paper = (
        "## Quantitative Evidence Index — Urolithin A\n\n"
        "## Quantitative Evidence Index — urolithin_a\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Acevedo 2025 | muscle strength | ua | 57% | % | — |\n\n"
        "## Methods\n\nText.\n"
    )
    out, results = apply_patches.apply_patches(paper, [], _manifest())
    assert out.count("## Quantitative Evidence Index") == 1
    assert "## Quantitative Evidence Index — Urolithin A" in out
    assert "## Quantitative Evidence Index — urolithin_a" not in out
    assert "57%" in out
    assert any(
        r.patch_id == "SECTION-CONTRACT-Quantitative-Evidence-Index-Dedup"
        for r in results
    )


def test_single_qei_heading_is_not_rewritten() -> None:
    paper = (
        "## Quantitative Evidence Index — topic\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| A 2020 | glucose | drug | p=0.04 | p value | — |\n"
    )
    out, results = apply_patches.apply_patches(paper, [], _manifest())
    assert out == paper
    assert not any("Dedup" in r.patch_id for r in results)


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
# is flag-only (Fix #7 reverts to strict gates); verifier still runs
# and its output appears in the reason line for retroactive audit.
def test_numeric_token_with_glued_unit_suffix_verifier_reports_pass() -> None:
    """Verifier must trace '32%' to corpus value '32'. Patch is
    flag-only per Fix #7; verifier's PASS/FAIL is logged in the
    reason for retroactive review."""
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
    assert results[0].decision == "flagged"
    reason = results[0].reason_for_decision.lower()
    assert "pass" in reason, (
        f"glued unit-suffix verifier should report PASS: "
        f"{results[0].reason_for_decision}"
    )


# ----- Reviewer-fix discriminating tests (post-2x review on Fix #7) ----


def test_unknown_patch_type_is_rejected_not_flagged() -> None:
    """Reviewer P1: malformed contract (unknown patch_type) → REJECTED.
    Pre-fix this got flagged, polluting the requires-review queue and
    hiding upstream Grok contract violations."""
    p = {
        "id": "PX3", "patch_type": "rogue_type", "severity": "P2",
        "location": "Results",
        "before": "x", "after": "y",
        "reason": "Grok shipped a typo'd patch_type",
    }
    paper = "## Results\n\nx\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "malformed patch contract" in results[0].reason_for_decision
    assert "rogue_type" in results[0].reason_for_decision


def test_empty_before_text_is_rejected() -> None:
    """Empty before-text → rejected (not flagged) — Grok shipped
    something fundamentally unactionable."""
    p = {
        "id": "PX4", "patch_type": "formatting", "severity": "P3",
        "location": "Abstract",
        "before": "", "after": "anything",
        "reason": "test empty before",
    }
    paper = "## Abstract\n\nText.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "rejected"
    assert "empty 'before'" in results[0].reason_for_decision


def test_applied_patch_preserves_grok_rationale_in_reason() -> None:
    """Applied patches must also carry Grok's rationale in the log.
    Pre-fix only flagged patches had rationale logged; applied patches
    discarded it."""
    p = {
        "id": "PX5", "patch_type": "formatting", "severity": "P3",
        "location": "Abstract",
        "before": "metformin  is", "after": "metformin is",
        "reason": "double space typo per Grok scan",
    }
    paper = "## Abstract\n\nThe metformin  is widely studied.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "double space typo per Grok scan" in results[0].reason_for_decision


def test_proposer_reason_is_clamped_to_500_chars() -> None:
    """Reviewer P1: a 50KB Grok hallucination must not bloat the JSON
    log. Clamp at 500 chars + ellipsis."""
    huge_reason = "X" * 5000  # 5KB
    p = {
        "id": "PX6", "patch_type": "claim", "severity": "P1",
        "location": "Discussion",
        "before": "metformin extended lifespan",
        "after": "metformin reduced mortality",
        "reason": huge_reason,
    }
    paper = "## Discussion\n\nIn mice, metformin extended lifespan by 14%.\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    # Total reason_for_decision length is bounded; specifically the
    # proposer rationale portion is clamped + ellipsis-marked.
    assert "[truncated]" in results[0].reason_for_decision
    # Total reason should be reasonable length (gate text + clamped reason
    # + repr quoting + format strings); empirically well under 1000 chars.
    assert len(results[0].reason_for_decision) < 1000


def test_citation_patch_introducing_long_pmc_handle_is_flagged() -> None:
    """Fix #11: pre-fix Grok could ship a citation patch whose `after`
    was `PMC12978362_molecular_mechanisms_of_metformin` and the
    verifier passed it as 'no novel citations' (no Author-Year regex
    match). The patch then auto-applied → 96 PMCID body leaks. Now
    the verifier explicitly rejects internal-handle shapes."""
    p = {
        "id": "PX8", "patch_type": "citation", "severity": "P2",
        "location": "Abstract",
        "before": "_Cited: `Walton 2019`_",
        "after": (
            "_Cited: `PMC12978362_molecular_mechanisms_of_metformin`_"
        ),
        "reason": "Grok wrongly enforcing receipt-key consistency",
    }
    paper = "## Abstract\n\n_Cited: `Walton 2019`_\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "internal-handle" in results[0].reason_for_decision


def test_citation_patch_introducing_author_year_trail_is_flagged() -> None:
    """Same protection for Author_YYYY_TRAIL_KEYWORDS shapes."""
    p = {
        "id": "PX9", "patch_type": "citation", "severity": "P2",
        "location": "Abstract",
        "before": "_Cited: `Walton 2019`_",
        "after": "_Cited: `Walton_2019_MASTERS_metformin_blunts_resistance`_",
        "reason": "Grok wants long-form receipt id",
    }
    paper = "## Abstract\n\n_Cited: `Walton 2019`_\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "internal-handle" in results[0].reason_for_decision


def test_citation_patch_with_clean_author_year_still_applies() -> None:
    """Sanity: clean Author-Year-to-Author-Year patches still apply."""
    p = {
        "id": "PX10", "patch_type": "citation", "severity": "P2",
        "location": "Discussion",
        "before": "(Walton 2019)", "after": "(Konopka 2019)",
        "reason": "wrong attribution",
    }
    paper = "## Discussion\n\nResults are interesting (Walton 2019).\n"
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"


def test_citation_patch_allows_manifest_citation_token() -> None:
    """PMC receipts use registry body citations, not receipt_id-derived tokens."""
    p = {
        "id": "PX-token", "patch_type": "citation", "severity": "P1",
        "location": "Results",
        "before": "Fukuoka 2020 associates",
        "after": "Fukuoka 2019 associates",
        "reason": "correct body-citation year",
    }
    paper = "## Results\n\nFukuoka 2020 associates metformin use.\n"
    out, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "applied"
    assert "Fukuoka 2019 associates" in out


def test_citation_patch_preserving_existing_handles_does_not_double_block() -> None:
    """If both before AND after contain the same internal handle
    (legitimate edit elsewhere), the verifier shouldn't flag the
    handle as 'novel' — only NOVEL handles in after are blocked."""
    # Construct a pathological case where existing prose already has
    # a handle and the patch leaves it in place but edits other text.
    p = {
        "id": "PX11", "patch_type": "citation", "severity": "P2",
        "location": "Abstract",
        "before": "_Cited: `PMC12978362_molecular_mechanisms_of_metformin` and Walton 2019_",
        "after":  "_Cited: `PMC12978362_molecular_mechanisms_of_metformin` and Konopka 2019_",
        "reason": "fix attribution; legacy handle stays for now",
    }
    paper = (
        "## Abstract\n\n"
        "_Cited: `PMC12978362_molecular_mechanisms_of_metformin` and "
        "Walton 2019_\n"
    )
    _, results = apply_patches.apply_patches(paper, [p], _manifest())
    # Patch should APPLY (handle was already there, not introduced)
    assert results[0].decision == "applied", (
        f"Existing handle in both before/after must not block apply: "
        f"{results[0].reason_for_decision}"
    )


def test_numeric_patch_with_empty_proposer_reason_logs_only_gate_reason() -> None:
    """Empty proposer_reason → reason_for_decision contains ONLY the
    gate explanation (no trailing 'Grok rationale: ' fragment)."""
    p = {
        "id": "PX7", "patch_type": "numeric", "severity": "P2",
        "location": "Results",
        "before": "by 14%", "after": "by 32%",
        # No reason field
    }
    paper = "## Results\n\nIncreased by 14% in mice.\n"
    with mock_patch.object(
        apply_patches, "_load_corpus_numerics",
        return_value={"32", "14"},
    ):
        _, results = apply_patches.apply_patches(paper, [p], _manifest())
    assert results[0].decision == "flagged"
    assert "Grok rationale" not in results[0].reason_for_decision


def test_section_contract_restores_heading_after_review_patch() -> None:
    """Reviewer patches may delete local prose but cannot remove renderer-owned headings."""
    paper = (
        "## Limitations\n\n"
        "The corpus is limited.\n\n"
        "## Conclusion\n\n"
        "The boundary conditions remain unresolved.\n\n"
        "## References\n\n"
        "Walton 2019.\n"
    )
    # Simulate a bad formatting patch that swallowed the heading but
    # left the original Conclusion paragraph in place.
    patch = {
        "id": "P-heading",
        "patch_type": "formatting",
        "severity": "P1",
        "location": "Conclusion",
        "before": "## Conclusion\n\nThe boundary conditions remain unresolved.",
        "after": "The boundary conditions remain unresolved.",
        "reason": "bad heading trim",
    }
    out, results = apply_patches.apply_patches(paper, [patch], _manifest())
    assert "## Conclusion\n\nThe boundary conditions remain unresolved." in out
    assert any(
        r.patch_id == "SECTION-CONTRACT-Conclusion"
        and r.decision == "applied"
        for r in results
    )
