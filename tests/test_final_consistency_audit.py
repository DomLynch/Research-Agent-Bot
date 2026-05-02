"""Tests for scripts/final_consistency_audit.py — Layer 1 deterministic
final-consistency checks. One discriminating test per check class."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import final_consistency_audit as audit  # noqa: E402


def _empty_audit() -> dict:
    return {
        "score_out_of_10": 9.0, "p1_pass": True,
        "n_total": 10, "n_pass": 10,
    }


def _empty_manifest() -> dict:
    return {
        "n_receipts": 7,
        "writer_path": "agent.paper_writer.render_full_paper (production)",
        "receipts": [
            {"receipt_id": "Witham_2025_MET_PREVENT_metformin_trial"},
            {"receipt_id": "Walton_2019_MASTERS"},
        ],
    }


def test_accepted_paper_called_rejected_is_p1() -> None:
    """If manifest lists Witham as accepted but body says
    'Witham was rejected by SPAR', flag P1."""
    paper = "## Discussion\n\nWitham 2025 was rejected by SPAR despite the trial design.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    p1 = [i for i in issues if i.severity == "P1" and i.issue_type == "accepted_paper_called_rejected"]
    assert len(p1) == 1


def test_stale_spar_phrases_flagged_when_no_spar_ran() -> None:
    """v0.6 adapter doesn't run SPAR; Methods must not mention it."""
    paper = (
        "## Methods\n\n"
        "This synthesis used SPAR adjudication on receipt clusters; "
        "rejected by SPAR were quarantined.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    stale = [i for i in issues if i.issue_type == "stale_method_boilerplate"]
    assert len(stale) >= 1


def test_duplicate_references_section_is_p1() -> None:
    """## References appearing twice = duplicate section bug."""
    paper = (
        "## Conclusion\n\nDone.\n\n"
        "## References\n\nFoo.\n\n"
        "## References\n\nBar.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    dup = [i for i in issues if i.issue_type == "duplicate_section"]
    assert len(dup) == 1


def test_malformed_double_hash_header_flagged() -> None:
    """### ### Foo is malformed."""
    paper = "## Results\n\n### ### Muscle Function\n\nText.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    bad = [i for i in issues if i.issue_type == "malformed_header"]
    assert len(bad) == 1


def test_potentially_repair_artifact_flagged() -> None:
    """Inline (potentially) is a Phase-2 repair leftover."""
    paper = "## Discussion\n\nMetformin extends lifespan (potentially) in mice.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    art = [i for i in issues if i.issue_type == "repair_artifact"]
    assert len(art) == 1


def test_audit_verdict_overclaim_flagged() -> None:
    """Audit said 9/10 but only 9 of 10 checks passed → cannot be 'AAA'."""
    paper = "## Abstract\n\nText.\n"
    audit_with_partial_fail = {
        "score_out_of_10": 9.0, "p1_pass": True,
        "n_total": 10, "n_pass": 9,
    }
    issues = audit.run_audit(paper, _empty_manifest(), audit_with_partial_fail)
    over = [i for i in issues if i.issue_type == "audit_verdict_overclaim"]
    assert len(over) == 1


def test_clean_paper_returns_empty_list() -> None:
    """A clean paper should produce zero issues."""
    paper = (
        "## Abstract\n\nClean.\n\n"
        "## Methods\n\nWe used the v0.6 quant_claim adapter.\n\n"
        "## References\n\n- Walton 2019.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    assert issues == []


def test_paper_id_truncation_in_body_flagged() -> None:
    """Truncated paper_id 'Walton_2019_MASTERS_' leaking into body."""
    paper = (
        "## Discussion\n\n"
        "MASTERS (Walton_2019_MASTERS_metformin_) reported significant effects.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    leaks = [i for i in issues if i.issue_type == "paper_id_in_body"]
    assert len(leaks) == 1


def test_paper_id_in_references_section_allowed() -> None:
    """References section may contain paper_id forms; only body leaks count."""
    paper = (
        "## Discussion\n\nClean discussion.\n\n"
        "## References\n\n- Walton_2019_MASTERS_metformin_blunts_resistance_hypertrophy.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    leaks = [i for i in issues if i.issue_type == "paper_id_in_body"]
    assert leaks == []


# Reviewer-fix HIGH 2/3 regression: compound sentence false-positive
def test_compound_sentence_does_not_falsely_flag_other_arm() -> None:
    """'While Walton was rejected, Witham 2025 demonstrated...' must
    NOT flag Witham as the rejected one (clause boundary at the comma)."""
    paper = (
        "## Discussion\n\n"
        "While Walton was rejected by SPAR, Witham 2025 demonstrated "
        "no improvement in walk speed.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    flagged = [i for i in issues if i.issue_type == "accepted_paper_called_rejected"]
    flagged_for_witham = [i for i in flagged if "Witham" in i.suggested_fix]
    assert flagged_for_witham == [], (
        f"Witham wrongly flagged as rejected in compound sentence: {flagged_for_witham}"
    )


# Reviewer-fix MEDIUM 1: Methods-as-last-section regression
def test_methods_as_last_section_scopes_correctly() -> None:
    """A paper ending on Methods (no trailing ## section) must still
    scope the stale-method check to Methods only."""
    paper = (
        "## Discussion\n\n"
        "Discussion text mentions claim receipts in passing.\n\n"
        "## Methods\n\n"
        "We used the v0.6 quant-claim adapter. Clean methods.\n"
    )
    # Discussion mentions "claim receipts" but it's not Methods → no flag.
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    stale = [i for i in issues if i.issue_type == "stale_method_boilerplate"]
    assert stale == [], (
        f"non-Methods 'claim receipts' wrongly flagged: {stale}"
    )


# Reviewer-fix HIGH 1: mutable-default in fixer regression
def test_apply_fixes_idempotent_across_invocations() -> None:
    """Calling apply_fixes twice in one process must not silently lose
    the disclaimer replacement on the second call (mutable-default
    closure bug)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Methods\n\nWe used SPAR adjudication on the receipts.\n"
    )
    # First call: should replace SPAR sentence with disclaimer.
    out1, log1 = fixer.apply_fixes(paper, [])
    assert "v0.6 quant-claim adapter" in out1
    # Second call on a fresh paper: must again replace.
    out2, log2 = fixer.apply_fixes(paper, [])
    assert "v0.6 quant-claim adapter" in out2, (
        f"mutable-default closure regressed; second call output:\n{out2}"
    )


# Reviewer-fix LOW: fix_audit_verdict idempotency
def test_fix_audit_verdict_is_idempotent() -> None:
    """Running fix_audit_verdict twice on the already-renamed text
    must be a no-op (no new changes logged)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    audit_md = "## Verdict: AAA\n\n≥9.0 score. ❌ failed.\n"
    out1, log1 = fixer.fix_audit_verdict(audit_md)
    out2, log2 = fixer.fix_audit_verdict(out1)
    assert log2 == [], f"second pass not idempotent: {log2}"
    assert out2 == out1
