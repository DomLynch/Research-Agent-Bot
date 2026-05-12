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


def test_methods_not_run_disclosure_is_not_stale_boilerplate() -> None:
    """Run-mode Methods may explicitly say SPAR did NOT run; that
    negative disclosure is the contract, not stale boilerplate."""
    paper = (
        "## Methods\n\n"
        "This synthesis used the v0.6 quant-claim adapter.\n\n"
        "### What did NOT run\n\n"
        "- SPAR (multi-judge panel adjudication) did NOT run on this corpus.\n"
        "- Multi-receipt cluster aggregation did NOT run.\n\n"
        "### Claim source\n\n"
        "`docs/quality-reference/topic/quant_claims/*.json`.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    stale = [i for i in issues if i.issue_type == "stale_method_boilerplate"]
    assert stale == []


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
    """Truncated paper_id 'Walton_2019_MASTERS_' leaking into body.
    P2 reviewer fix renamed the issue_type to 'truncated_author_year_id'
    to make room for the new 'pmcid_in_body' detector."""
    paper = (
        "## Discussion\n\n"
        "MASTERS (Walton_2019_MASTERS_metformin_) reported significant effects.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    leaks = [i for i in issues if i.issue_type == "truncated_author_year_id"]
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


def test_apply_fixes_strips_role_repair_artifact_sentence() -> None:
    """Role-drift repair may emit an explanatory placeholder sentence
    when no safe canonical rewrite exists. Public prose should strip
    that artifact deterministically instead of waiting for Grok."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "Stable opening sentence remains. "
        "Liao 2025 reported an effect value of 0.42; this manuscript "
        "treats the value according to that source role. "
        "Ham 2022 reported an effect value; this manuscript treats "
        "the value according to that source role.\n\n"
        "Other bounded interpretation remains.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "reported an effect value" not in out
    assert "Stable opening sentence remains." in out
    assert "Other bounded interpretation remains." in out
    assert any(
        item["fix_type"] == "role_repair_artifact_strip"
        for item in log
    )


def test_apply_fixes_strips_public_pipeline_meta_comment() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Methods\n\n"
        "Explicit-absence audit-trail block — earlier drafts inherited "
        "Methods boilerplate describing pipeline stages that were not "
        "actually executed.\n\n"
        "The deterministic Methods section remains.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Explicit-absence audit-trail block" not in out
    assert "The deterministic Methods section remains." in out
    assert any(
        item["fix_type"] == "public_pipeline_meta_strip"
        for item in log
    )


def test_apply_fixes_normalizes_public_p_value_display() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Results\n\n"
        "| Study | Value |\n"
        "| --- | --- |\n"
        "| A | P >0.05 |\n"
        "| B | p<.001 |\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "P > 0.05" in out
    assert "P < 0.001" in out
    assert "P >0.05" not in out
    assert "p<.001" not in out
    assert any(
        item["fix_type"] == "public_p_value_normalization"
        for item in log
    )


def test_apply_fixes_strips_public_placeholder_paragraph() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Introduction\n\n"
        "Real thesis-bearing introduction remains visible.\n\n"
        "This synthesis aims to contribute to the field by systematically "
        "evaluating accepted receipts across outcome domains.\n\n"
        "Another real paragraph remains.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "This synthesis aims to contribute" not in out
    assert "Real thesis-bearing introduction remains" in out
    assert "Another real paragraph remains" in out
    assert any(
        item["fix_type"] == "public_placeholder_paragraph_strip"
        for item in log
    )


def test_apply_fixes_strips_effect_estimate_artifact_sentence() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Results\n\n"
        "The longevity evidence remains indirect. Ryan 2024 reported an "
        "effect estimate of 30 kg/m. The surrounding interpretation remains.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "reported an effect estimate" not in out
    assert "The longevity evidence remains indirect" in out
    assert "The surrounding interpretation remains" in out
    assert any(
        item["fix_type"] == "effect_estimate_artifact_sentence_strip"
        for item in log
    )


def test_apply_fixes_normalizes_public_meta_phrases() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Methods\n\n"
        "The load-bearing principle is **LLM proposes, code disposes** — "
        "no claim, citation, evidence tier, or thesis is author-LLM-invented.\n\n"
        "## Quantitative Evidence Index\n\n"
        "_Every row traces to a corpus-bound claim — no LLM authorship._\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "LLM proposes" not in out
    assert "no LLM authorship" not in out
    assert "run registry" in out
    assert "registered citation" in out
    assert any(
        item["fix_type"] == "public_meta_phrase_normalization"
        for item in log
    )


def test_apply_fixes_renormalizes_meta_phrases_after_depth_restore() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    safe_words = " ".join(["source-bound"] * 45)
    stripped_words = " ".join(["placeholder"] * 125)
    paper = (
        "## Conclusion\n\n"
        "The audited corpus remains interpretable. The public interpretation "
        "is tied to the audited evidence structure rather than to any "
        f"stripped sentence. {safe_words}\n\n"
        f"Deterministic evidence summary {stripped_words}.\n"
    )

    out, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    lower = out.lower()
    assert "audited corpus" not in lower
    assert "audited evidence structure" not in lower
    assert "stripped sentence" not in lower
    assert "accepted corpus" in lower
    assert any(
        item["fix_type"] == "public_meta_phrase_normalization_post_depth"
        for item in log
    )


def test_apply_fixes_strips_fuzzy_duplicate_body_paragraph() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    first = (
        "The clinical evidence should be interpreted through population, "
        "endpoint, duration, and comparator boundaries because the accepted "
        "receipt set contains heterogeneous designs and outcome definitions. "
        "This paragraph states a specific interpretive boundary for the paper."
    )
    second = (
        "The clinical evidence should be interpreted through population, "
        "endpoint, duration, and comparator boundaries because the accepted "
        "receipt set includes heterogeneous designs and outcome definitions. "
        "This paragraph states a specific interpretive boundary for the paper."
    )
    paper = (
        f"## Background\n\n{first}\n\n"
        f"## Limitations\n\n{second}\n\n"
        "A separate limitations paragraph remains visible.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert first in out
    assert second not in out
    assert "A separate limitations paragraph remains visible" in out
    assert any(
        item["fix_type"] == "fuzzy_duplicate_paragraph"
        for item in log
    )


def test_apply_fixes_strips_unreferenced_et_al_parenthetical() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Introduction\n\n"
        "The hallmarks framework is often invoked "
        "(López-Otín et al. 2013), but this paper does not cite it.\n\n"
        "## References\n\n"
        "- **Smith 2024.** _Clean source._ Journal, 2024.\n"
    )
    out, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    assert "López-Otín et al. 2013" not in out
    assert "The hallmarks framework is often invoked" in out
    assert any(
        item["fix_type"] == "unreferenced_parenthetical_citation_strip"
        for item in log
    )


def test_apply_fixes_keeps_manifest_referenced_et_al_parenthetical() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    manifest = {
        **_empty_manifest(),
        "receipts": [{"citation_token": "López-Otín 2013"}],
    }
    paper = (
        "## Introduction\n\n"
        "The hallmarks framework is cited (López-Otín et al. 2013).\n"
    )
    out, log = fixer.apply_fixes(paper, [], manifest=manifest)
    assert "López-Otín et al. 2013" in out
    assert not any(
        item["fix_type"] == "unreferenced_parenthetical_citation_strip"
        for item in log
    )


def test_apply_fixes_backfills_low_discussion_hedge_density() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "The direct and mechanistic evidence diverges across domains. "
        "The result should be interpreted through evidence tier and "
        "outcome proximity rather than as a pooled effect.\n"
    )
    out, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    assert "### Confidence calibration" in out
    assert "context-dependent" in out
    assert any(
        item["fix_type"] == "discussion_hedge_density_backfill"
        for item in log
    )


def test_apply_fixes_strips_orphan_inference_fragments() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Background\n\n"
        "Stable background prose.\n\n"
        "1. [D1_inferential_bridge | confidence=low] Orphan bridge claim. "
        "[mechanism_anchor: A 2020] [conservation: B 2021]\n"
        "Existing human signal: none. [testability: explicit]\n\n"
        "## Results\n\nStable results.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "[D1_inferential_bridge" not in out
    assert "Existing human signal" not in out
    assert "Stable background prose." in out
    assert any(
        item["fix_type"] == "orphan_inference_fragment_strip"
        for item in log
    )


def test_apply_fixes_preserves_real_bridge_but_strips_leaked_bridge_fragment() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Background\n\n"
        "Stable background prose.\n\n"
        "Testability: Trial note. [testability: explicit]\n\n"
        "## Inferential Bridge\n\n"
        "1. [D1_inferential_bridge | confidence=low] Valid bridge claim. "
        "[mechanism_anchor: A 2020] [conservation: B 2021]\n"
        "Existing human signal: none. [testability: explicit]\n\n"
        "## Results\n\nStable results.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Stable background prose." in out
    assert "Testability: Trial note" not in out
    assert "[D1_inferential_bridge" in out
    assert "Valid bridge claim" in out
    assert any(
        item["fix_type"] == "orphan_inference_fragment_strip"
        for item in log
    )


def test_apply_fixes_strips_invalid_bridge_claims_after_review_patch() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Inferential Bridge\n\n"
        "2. [D1_inferential_bridge | confidence=medium] Broken claim. "
        "[mechanism_anchor: A 2020] [conservation: B 2021]\n"
        "Existing human signal: A 2020.\n\n"
        "3. [D1_inferential_bridge | confidence=low] Valid claim. "
        "[mechanism_anchor: C 2022] [conservation: D 2023]\n"
        "Existing human signal: none.\n"
        "Testability: Future validation. [testability: explicit]\n\n"
        "## Results\n\nStable results.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Broken claim" not in out
    assert "1. [D1_inferential_bridge" in out
    assert "Valid claim" in out
    assert "[testability: explicit]" in out
    assert any(
        item["fix_type"] == "invalid_inferential_bridge_claim_strip"
        for item in log
    )


def test_apply_fixes_preserves_deterministic_methods_steps() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    methods = (
        "## Methods\n\n"
        "### Pipeline stages (deterministic, in order)\n\n"
        "1. quant-claim extraction.\n"
        "2. receipt summarization.\n"
        "3. tension matrix construction.\n"
        "4. thesis selection.\n"
        "5. claim-strength repair.\n"
        "6. paper_id -> Author Year substitution.\n"
        "7. References block append.\n"
        "8. Stage-1 audit.\n"
        "9. final-layer LLM review.\n"
        "10. final audit.\n\n"
        "### Claim source\n\n"
        "`docs/quality-reference/topic/quant_claims/*.json`.\n"
    )
    out, log = fixer.apply_fixes(methods, [])
    assert "8. Stage-1 audit." in out
    assert "10. final audit." in out
    assert not any(
        item["fix_type"] == "methods_extra_step_strip"
        for item in log
    )


def test_apply_fixes_strips_leaked_results_from_deterministic_methods() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    methods = (
        "## Methods\n\n"
        "### Pipeline stages (deterministic, in order)\n\n"
        "1. quant-claim extraction.\n"
        "2. receipt summarization.\n"
        "3. tension matrix construction.\n"
        "4. thesis selection.\n"
        "5. claim-strength repair.\n"
        "6. paper_id -> Author Year substitution.\n"
        "7. References block append.\n"
        "8. Participants across dosing groups were not significantly "
        "different at baseline on the majority of measures.\n"
        "8. Stage-1 audit.\n"
        "9. final-layer LLM review.\n"
        "10. final audit.\n\n"
        "### Claim source\n\n"
        "`docs/quality-reference/topic/quant_claims/*.json`.\n"
    )
    out, log = fixer.apply_fixes(methods, [])
    assert "Participants across dosing groups" not in out
    assert "8. Stage-1 audit." in out
    assert "10. final audit." in out
    assert any(
        item["fix_type"] == "methods_extra_step_strip"
        for item in log
    )


def test_apply_fixes_strips_duplicate_long_sentences() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    sentence = (
        "This small human trial base means that the headline conclusions "
        "rest on a narrow evidentiary foundation."
    )
    paper = (
        "## Discussion\n\n"
        f"{sentence} Other valid discussion remains.\n\n"
        "## Limitations\n\n"
        f"{sentence} Additional limitations remain visible.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.count(sentence) == 1
    assert "Other valid discussion remains" in out
    assert "Additional limitations remain visible" in out
    assert any(item["fix_type"] == "duplicate_sentence" for item in log)


def test_apply_fixes_backfills_results_after_numeric_strips() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = "## Results\n\n" + " ".join(f"word{i}" for i in range(380))
    out, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    assert "### Result-interpretation guardrail" in out
    assert fixer._section_word_count(out, "Results") >= 500
    assert any(
        item["fix_type"] == "analytical_depth_backfill"
        and "'Results'" in item["description"]
        for item in log
    )


# P1 reviewer fix: trial acronyms extracted as short forms
def test_trial_acronym_met_prevent_flagged_when_called_rejected() -> None:
    """'MET-PREVENT was rejected by SPAR' must flag — pre-fix, only
    'Witham' / 'Witham 2025' were short forms; the acronym slipped
    through entirely."""
    paper = (
        "## Discussion\n\n"
        "MET-PREVENT was rejected by SPAR despite the protocol design.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    flagged = [i for i in issues if i.issue_type == "accepted_paper_called_rejected"]
    assert len(flagged) == 1, (
        f"trial acronym MET-PREVENT not recognized as short form: {flagged}"
    )


# P1 reviewer fix: sentence-scope catches earlier-in-sentence references
def test_long_sentence_with_earlier_reference_still_flagged() -> None:
    """Pre-fix, a Witham mention >80 chars before 'was rejected'
    slipped past the window. Sentence-scope must catch it."""
    paper = (
        "## Discussion\n\n"
        "Witham 2025 conducted the MET-PREVENT trial with extensive "
        "frailty endpoints across multiple sites and a long follow-up; "
        "later analyses showed it was rejected by SPAR.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    flagged = [i for i in issues if i.issue_type == "accepted_paper_called_rejected"]
    assert len(flagged) >= 1, (
        f"long-sentence reference to Witham not flagged: {flagged}"
    )


# P2 reviewer fix: PMCID handles in body
def test_pmcid_handle_in_body_flagged() -> None:
    """'PMC12978362 2026' is an internal corpus identifier, not a
    citation — it must not appear in body prose."""
    paper = (
        "## Discussion\n\n"
        "Recent work by PMC12978362 2026 extended the mechanism.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    pmcid_leaks = [i for i in issues if i.issue_type == "pmcid_in_body"]
    assert len(pmcid_leaks) == 1, (
        f"PMCID handle not detected: {pmcid_leaks}"
    )


def test_pmcid_handle_in_references_section_allowed() -> None:
    """PMCIDs are valid in the References block — only body leaks count."""
    paper = (
        "## Discussion\n\nClean discussion with no PMCIDs.\n\n"
        "## References\n\n- PMC12978362 2026 — molecular mechanisms paper.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    pmcid_leaks = [i for i in issues if i.issue_type == "pmcid_in_body"]
    assert pmcid_leaks == []


def test_pmcid_in_cited_block_allowed() -> None:
    """The writer emits per-section `_Cited:_` italic blocks. PMCID
    handles inside those blocks ARE the proper citation form for
    PMC-only papers (no Author Year exists). Only PMCIDs in actual
    body prose are leaks."""
    paper = (
        "## Results\n\n"
        "Treatment improved walk speed.\n\n"
        "  _Cited: `Witham 2025`, `PMC13055625 2026`, `PMC13032177 2026`_\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    pmcid_leaks = [i for i in issues if i.issue_type == "pmcid_in_body"]
    assert pmcid_leaks == [], (
        f"PMCIDs inside _Cited:_ blocks must not be flagged: {pmcid_leaks}"
    )


# ----- Fix #13: surface-polish validator (C08) -------------------------


def test_polish_catches_broken_citation_order() -> None:
    """C08: 'Konopka 2019 et al.' is wrong order; should be 'Konopka et
    al. 2019'. Auto-fixable suggestion provided."""
    paper = "## Discussion\n\nAs Konopka 2019 et al. demonstrated, ...\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    polish = [i for i in issues if i.issue_type == "broken_citation_order"]
    assert len(polish) == 1
    assert polish[0].auto_fixable is True
    assert "et al." in polish[0].suggested_fix


def test_polish_catches_empty_cited_block() -> None:
    """C08: `_Cited:_` with nothing between the colon and underscore
    is a writer artifact — the section had no receipts attached."""
    paper = "## Results\n\nFinding.\n\n  _Cited:_\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    empty = [i for i in issues if i.issue_type == "empty_cited_block"]
    assert len(empty) == 1


def test_polish_catches_double_space_in_prose() -> None:
    """C08: double-or-more spaces inside prose break PhD polish."""
    paper = "## Discussion\n\nThe trial was  conducted in older adults.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    spaces = [i for i in issues if i.issue_type == "double_space"]
    assert len(spaces) >= 1


def test_polish_catches_duplicated_word() -> None:
    """C08: 'in in', 'is is', 'were were' — common LLM-generation
    artifact. Whitelist for legitimate 'had had', 'that that'."""
    paper = "## Discussion\n\nThe trial was was conducted in mice.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    dups = [i for i in issues if i.issue_type == "duplicated_phrase"]
    assert len(dups) == 1


def test_polish_whitelists_had_had() -> None:
    """C08: 'had had' is grammatically valid past-perfect; not flagged."""
    paper = "## Discussion\n\nParticipants had had prior exposure.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    dups = [i for i in issues if i.issue_type == "duplicated_phrase"]
    assert dups == []


def test_polish_suppresses_triple_letter_in_identifier_context() -> None:
    """Fix #15: 'aaa' inside a hyphen-bounded identifier (submission_id,
    URL slug) is NOT a typo — suppress."""
    paper = (
        "## Methods\n\n"
        "Submission: synthesis-metformin-v06-aaa-push-2026-05-03.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    polish = [i for i in issues if i.issue_type == "malformed_word"]
    assert polish == [], (
        f"`aaa` inside identifier should not flag: {polish}"
    )


def test_polish_suppresses_uppercase_aaa_cert_label() -> None:
    paper = "## Methods\n\nThe run is labeled as AAA, not preliminary.\n"
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    polish = [i for i in issues if i.issue_type == "malformed_word"]
    assert polish == []


def test_polish_suppresses_dup_word_followed_by_hyphen() -> None:
    """Fix #15: 'over over-claimed' is grammatical (preposition +
    hyphenated adjective); not a duplication artifact."""
    paper = (
        "## Methods\n\n"
        "claim-strength repair (regex over over-claimed prose).\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    dups = [i for i in issues if i.issue_type == "duplicated_phrase"]
    assert dups == [], (
        f"'word word-' should not flag as duplication: {dups}"
    )


def test_polish_skips_code_block_contents() -> None:
    """C08: triple-letter runs (`aaa`) inside fenced code blocks are
    not real prose; should not false-fire on code samples."""
    paper = (
        "## Methods\n\nClean prose.\n\n"
        "```\nlet aaaa = 'code';\n```\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    polish = [i for i in issues if i.issue_type == "malformed_word"]
    assert polish == []


def test_polish_skips_indented_code_block_spacing() -> None:
    paper = (
        "## Methods\n\n"
        "Run the reproducibility command:\n\n"
        "    python scripts/run.py  --topic metformin\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    spaces = [i for i in issues if i.issue_type == "double_space"]
    assert spaces == []


def test_polish_clean_paper_returns_no_polish_issues() -> None:
    """Sanity: a clean paper has zero polish issues."""
    paper = (
        "## Discussion\n\n"
        "The trial demonstrated improvement in older adults.\n\n"
        "  _Cited: `Witham 2025`_\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    polish = [i for i in issues if i.id.startswith("C08-")]
    assert polish == []


# ----- Fix #16: Stage-2 background-literature gate ---------------------


def test_background_lit_unsourced_is_p1_in_stage2() -> None:
    """Fix #16: unsourced background-lit numeric in body prose is a
    P1 Stage-2 issue — the trust-spine extension contract requires
    citation in same sentence."""
    paper = (
        "## Discussion\n\n"
        "Walk-speed declines below 0.8 m/s indicate frailty risk.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    bg_issues = [i for i in issues if i.issue_type == "background_lit_unsourced"]
    assert len(bg_issues) == 1
    assert bg_issues[0].severity == "P1"
    assert "0.8 m/s" in bg_issues[0].suggested_fix
    assert "Studenski 2011" in bg_issues[0].suggested_fix


def test_background_lit_sourced_passes_stage2() -> None:
    """When the canonical citation appears in the same sentence, the
    background-lit numeric passes — this is the admit lane."""
    paper = (
        "## Discussion\n\n"
        "Walk-speed declines below 0.8 m/s (Studenski 2011) indicate "
        "frailty risk.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    bg_issues = [i for i in issues if i.issue_type == "background_lit_unsourced"]
    assert bg_issues == []


# ----- Fix #18b: auto-fix strips unsourced background sentences --------


def test_apply_fixes_strips_unsourced_background_sentence() -> None:
    """Stage-2 P1 issue → auto-fix removes the offending sentence so
    the paper is shippable. The surrounding paragraph remains."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "Mortality reduction is observed across cohorts. "
        "Walk-speed declines below 0.8 m/s indicate frailty risk. "
        "These findings support the hypothesis.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    # Offending sentence (no Studenski 2011) is removed
    assert "0.8 m/s" not in out
    # Surrounding sentences preserved
    assert "Mortality reduction is observed" in out
    assert "support the hypothesis" in out
    # Log records the fix
    bg_log = [e for e in log
              if e["fix_type"] == "background_lit_unsourced_strip"]
    assert len(bg_log) == 1


def test_apply_fixes_preserves_sourced_background_sentence() -> None:
    """When the citation IS present, the sentence stays."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "Walk-speed declines below 0.8 m/s (Studenski 2011) "
        "indicate frailty risk.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "0.8 m/s" in out
    assert "Studenski 2011" in out
    bg_log = [e for e in log
              if e["fix_type"] == "background_lit_unsourced_strip"]
    assert bg_log == []


# ----- Fix #18c: citation-order auto-fix -------------------------------


def test_apply_fixes_rewrites_broken_citation_order() -> None:
    """`Konopka 2019 et al.` → `Konopka et al. 2019` (canonical order)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "As Konopka 2019 et al. demonstrated, the effect was robust. "
        "Walton 2019 et al. confirmed similar findings.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Konopka et al. 2019" in out
    assert "Walton et al. 2019" in out
    assert "Konopka 2019 et al." not in out
    cite_log = [e for e in log if e["fix_type"] == "broken_citation_order"]
    assert len(cite_log) == 1
    assert cite_log[0]["n_changes"] == 2


def test_apply_fixes_idempotent_for_citation_order() -> None:
    """Already-correct order is unchanged."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "As Konopka et al. 2019 demonstrated, the effect was robust.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.strip() == paper.strip()
    cite_log = [e for e in log if e["fix_type"] == "broken_citation_order"]
    assert cite_log == []


def test_apply_fixes_preserves_valid_author_year_token() -> None:
    """Plain `Author YYYY` body citations are already valid tokens."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "Konopka 2019 reported a mechanistic endpoint, and Walton 2019 "
        "reported a clinical endpoint.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.strip() == paper.strip()
    assert not [e for e in log if e["fix_type"] == "broken_citation_order"]


def test_polish_catches_duplicate_citation_year() -> None:
    """C08: `Author et al. YYYY (YYYY)` is a duplicate year artifact."""
    paper = (
        "## Discussion\n\n"
        "Witham et al. 2025 (2025) reported trial outcomes.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    dups = [i for i in issues if i.issue_type == "duplicate_citation_year"]
    assert len(dups) == 1
    assert dups[0].auto_fixable


def test_apply_fixes_rewrites_duplicate_citation_year() -> None:
    """`Witham et al. 2025 (2025)` → `Witham et al. 2025`."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "Witham et al. 2025 (2025) reported trial outcomes. "
        "Konopka 2019 (2019) reported a mechanistic endpoint.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Witham et al. 2025 (2025)" not in out
    assert "Konopka 2019 (2019)" not in out
    assert "Witham et al. 2025 reported" in out
    assert "Konopka 2019 reported" in out
    cite_log = [e for e in log if e["fix_type"] == "duplicate_citation_year"]
    assert len(cite_log) == 1
    assert cite_log[0]["n_changes"] == 2


def test_apply_fixes_adds_preclinical_translation_hedge() -> None:
    """Q6 backstop: preclinical transfer gets a neutral human hedge."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "The animal models showed improved lifespan. "
        "The next sentence discusses trial design.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "Translational relevance to humans remains uncertain." in out
    hedge_log = [
        e for e in log if e["fix_type"] == "preclinical_translation_hedge"
    ]
    assert len(hedge_log) == 1


def test_apply_fixes_does_not_insert_hedge_inside_p_value() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "The animal models showed a preclinical signal (p < 0.01, "
        "p < 0.001).\n"
    )
    out, _log = fixer.apply_fixes(paper, [])
    assert "p < 0. Translational" not in out
    assert "(P < 0.01, P < 0.001)." in out


def test_apply_fixes_removes_consecutive_duplicate_paragraphs() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    para = (
        "Claims that survive into the public manuscript must remain "
        "inside the accepted evidence boundary and stay conditional."
    )
    paper = f"## Background\n\n{para}\n\n{para}\n\nUnique close.\n"
    out, log = fixer.apply_fixes(paper, [])
    assert out.count(para) == 1
    assert any(e["fix_type"] == "duplicate_paragraph" for e in log)


def test_apply_fixes_removes_urolithin_shape_cross_section_duplicates(monkeypatch) -> None:
    """Live urolithin_a repro: exact Cross-Domain paragraphs repeated
    later in the public body should be removed without topic hardcoding."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    # Simulate duplicates introduced after the early cleanup passes by
    # disabling those earlier strippers; the final post-depth pass must catch.
    monkeypatch.setattr(
        fixer, "_strip_consecutive_duplicate_paragraphs",
        lambda md: (md, 0),
    )
    monkeypatch.setattr(
        fixer, "_strip_fuzzy_duplicate_paragraphs",
        lambda md: (md, 0),
    )
    monkeypatch.setattr(
        fixer, "_strip_duplicate_long_sentences",
        lambda md: (md, 0),
    )
    para_a = (
        "A second major tension exists between direct clinical evidence "
        "for muscle function and preclinical cardiometabolic evidence, "
        "highlighting the risk of extrapolating across outcome domains. "
        "The evidence that would resolve this is a human trial with "
        "cardiometabolic endpoints and neurocognitive outcomes."
    )
    para_b = (
        "The immune-modulatory evidence presents a tension between "
        "consistent mechanistic signaling and unclear net effects in "
        "complex in-vivo systems. The boundary condition likely involves "
        "dose, timing, tissue specificity, and measurement context."
    )
    paper = (
        f"## Cross-Domain Synthesis\n\n{para_a}\n\n{para_b}\n\n"
        f"## Discussion\n\n{para_a}\n\n{para_b}\n\nUnique discussion.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.count(para_a) == 1
    assert out.count(para_b) == 1
    assert "Unique discussion." in out
    assert any(
        e["fix_type"] == "exact_public_duplicate_paragraph_post_depth"
        for e in log
    )


def test_apply_fixes_preserves_duplicate_appendix_paragraphs() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    para = " ".join(f"appendixword{i}" for i in range(35))
    paper = (
        "## Discussion\n\n"
        "The public interpretation remains source bounded and unique.\n\n"
        "## Publication Appendix\n\n"
        f"{para}\n\n{para}\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.count(para) == 2
    assert not any("duplicate" in e["fix_type"] for e in log)


def test_apply_fixes_keeps_repeated_legitimate_methods_phrasing() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    phrase = "Source documents were screened for quantitative outcomes. "
    paper = (
        "## Methods\n\n"
        + phrase * 4
        + "\n\n## Results\n\n"
        + phrase * 3
        + "The retained findings addressed different endpoints.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out.count(phrase.strip()) == 7
    assert not any("duplicate" in e["fix_type"] for e in log)


def test_apply_fixes_removes_duplicate_backstop_subsection() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    block = (
        "### Evidence Context\n\n"
        "The evidence context separates direct clinical evidence from "
        "mechanistic evidence so later sections can interpret the accepted "
        "corpus conservatively."
    )
    paper = f"## Background\n\n{block}\n\n{block}\n\n## Results\n\nUnique result.\n"
    out, log = fixer.apply_fixes(paper, [])
    assert out.count("### Evidence Context") == 1
    assert out.count("The evidence context separates") == 1
    assert any(e["fix_type"] == "duplicate_subsection" for e in log)


def test_apply_fixes_strips_extra_methods_step() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Methods\n\n"
        "1. quant extraction.\n"
        "7. References block append.\n"
        "8. Results prose does not belong in Methods.\n\n"
        "## Results\n\n"
        "Real result.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert "8. Results prose" not in out
    assert "7. References block append." in out
    assert any(e["fix_type"] == "methods_extra_step_strip" for e in log)


def test_apply_fixes_does_not_rehedge_already_hedged_preclinical_sentence() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    paper = (
        "## Discussion\n\n"
        "The animal models showed improved lifespan, but translation "
        "to humans remains uncertain.\n"
    )
    out, log = fixer.apply_fixes(paper, [])
    assert out == paper
    assert not [
        e for e in log if e["fix_type"] == "preclinical_translation_hedge"
    ]


def test_apply_fixes_fuzzy_strips_numeric_role_drift_snippet(monkeypatch) -> None:
    """If exact sentence replacement misses, strip paragraph by evidence prefix."""
    import sys as _sys
    from dataclasses import dataclass
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    @dataclass
    class FakeIssue:
        sentence: str
        severity: str = "P1"

    def fake_scan(*_args, **_kwargs):
        return [FakeIssue(
            "Majeed 2021 found metformin reduced HbA1c to 6.52 ± 0.19% "
            "with a significant decrease."
        )]

    def fake_strip(md, _issues):
        return md, 0

    fake_module = type("FakeNRG", (), {
        "scan_paper": staticmethod(fake_scan),
        "auto_strip_offending_sentences": staticmethod(fake_strip),
    })
    monkeypatch.setitem(_sys.modules, "numeric_role_guard", fake_module)
    paper = (
        "## Discussion\n\n"
        "Context before.\n\n"
        "Majeed 2021 found metformin reduced HbA1c to 6.52 ± 0.19% "
        "with a significant decrease and extra trailing words.\n\n"
        "Context after.\n"
    )
    out, log = fixer.apply_fixes(paper, [], manifest={"topic": "metformin"})
    assert "6.52 ± 0.19%" not in out
    assert "Context before" in out
    assert "Context after" in out
    assert [e for e in log if e["fix_type"] == "numeric_role_guard_strip"]


def test_apply_fixes_writes_numeric_claim_quarantine(monkeypatch, tmp_path) -> None:
    import json
    import sys as _sys
    from dataclasses import dataclass
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    @dataclass
    class FakeIssue:
        sentence: str
        issue_type: str = "numeric_claim_contract"
        severity: str = "P1"
        detail: str = "missing inline exact registry value"
        suggested_fix: str = "strip"

    bad = (
        "Smith 2020 reported approximately one-third of participants "
        "responded."
    )

    def fake_scan(*_args, **_kwargs):
        return [FakeIssue(bad)]

    def fake_strip(md, issues):
        out = md
        n = 0
        for issue in issues:
            out = out.replace(issue.sentence, "")
            n += 1
        return out, n

    fake_module = type("FakeNRG", (), {
        "scan_paper": staticmethod(fake_scan),
        "auto_strip_offending_sentences": staticmethod(fake_strip),
    })
    monkeypatch.setitem(_sys.modules, "numeric_role_guard", fake_module)
    qpath = tmp_path / "numeric_claim_quarantine.json"
    out, log = fixer.apply_fixes(
        f"## Results\n\n{bad}\n",
        [],
        manifest={"topic": "demo"},
        numeric_quarantine_path=qpath,
    )
    rows = json.loads(qpath.read_text())
    assert bad not in out
    assert rows[0]["issue_type"] == "numeric_claim_contract"
    assert rows[0]["sentence"] == bad
    assert [
        e for e in log
        if e["fix_type"] == "numeric_claim_contract_quarantine"
    ]


def test_apply_fixes_normalizes_public_topic_slug_from_manifest() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Background\n\n"
        "The urolithin_a evidence base remains early.\n\n"
        "## Publication Appendix\n\n"
        "Bundle path: docs/quality-reference/urolithin_a/quant_claims/.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "urolithin_a"})
    public_body = fixed.split("## Publication Appendix", 1)[0]
    appendix = fixed.split("## Publication Appendix", 1)[1]
    assert "urolithin_a" not in public_body
    assert "Urolithin A evidence base" in public_body
    assert "urolithin_a/quant_claims" in appendix
    assert [e for e in log if e["fix_type"] == "public_topic_slug_normalization"]


def test_apply_fixes_depth_backfill_reaches_floor_after_large_strip() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Cross-Domain Synthesis\n\n"
        + "Cross-domain safe sentence. " * 80
        + "\n\n## Discussion\n\n"
        + "Discussion safe sentence. " * 70
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    assert fixer._section_word_count(fixed, "Cross-Domain Synthesis") >= 850
    assert fixer._section_word_count(fixed, "Discussion") >= 800
    depth = [e for e in log if e["fix_type"] == "analytical_depth_backfill"]
    assert len(depth) == 2
    assert all(e["n_changes"] >= 2 for e in depth)


def test_apply_fixes_backfills_public_bookend_sections() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Introduction\n\n" + "Intro safe sentence. " * 60
        + "\n\n## Background\n\n" + "Background safe sentence. " * 80
        + "\n\n## Limitations\n\n" + "Limit safe sentence. " * 50
        + "\n\n## Conclusion\n\n" + "Conclusion safe sentence. " * 50
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    assert fixer._section_word_count(fixed, "Introduction") >= 400
    assert fixer._section_word_count(fixed, "Background") >= 300
    assert fixer._section_word_count(fixed, "Limitations") >= 250
    assert fixer._section_word_count(fixed, "Conclusion") >= 250
    assert "The synthesis supports a bounded conclusion" not in fixed
    assert "### Closing interpretation" not in fixed
    assert [
        e for e in log
        if e["fix_type"] == "analytical_depth_backfill"
    ]


def test_apply_fixes_removes_conclusion_paragraph_repeated_earlier() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    duplicate = (
        "The synthesis therefore uses a tiered reading of the evidence. "
        "Direct clinical evidence carries the highest interpretive "
        "weight; indirect clinical receipts help define adjacent human "
        "signals; mechanistic receipts explain plausibility and "
        "candidate pathways."
    )
    paper = (
        "## Introduction\n\n"
        + duplicate
        + "\n\n"
        + "Intro safe sentence. " * 80
        + "\n\n## Conclusion\n\n"
        + "Conclusion-specific safe sentence. " * 40
        + "\n\n"
        + duplicate
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    conclusion = fixed.split("## Conclusion", 1)[1]
    assert duplicate not in conclusion
    assert duplicate in fixed.split("## Conclusion", 1)[0]
    assert fixer._section_word_count(fixed, "Conclusion") >= 250
    assert [
        e for e in log
        if e["fix_type"] == "conclusion_cross_section_duplicate"
    ]


def test_apply_fixes_depth_backfill_is_document_global_idempotent() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Introduction\n\n"
        + fixer._BACKGROUND_BACKFILL
        + "\n\n## Background\n\n"
        + "short background. " * 20
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    assert fixed.count("### Evidence Context") == 1
    assert not [
        e for e in log
        if e["fix_type"] == "analytical_depth_backfill"
        and "'Background'" in e["description"]
    ]


def test_apply_fixes_removes_immune_citation_from_muscle_claim() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Introduction\n\n"
        "Older adults may experience lean mass loss even with protein "
        "supplementation (Kazeminasab 2025; Lin 2025).\n\n"
        "## Results\n\n"
        "Lin 2025 compared time-restricted eating and observed that lean "
        "mass decreased in the CR group only.\n"
    )
    manifest = {
        "receipts": [
            {"citation_token": "Kazeminasab 2025", "outcome_class": "muscle_function"},
            {"citation_token": "Lin 2025", "outcome_class": "immune"},
        ],
    }
    fixed, log = fixer.apply_fixes(paper, [], manifest=manifest)
    assert "(Kazeminasab 2025)" in fixed
    assert "Lin 2025 compared time-restricted" not in fixed
    assert any(
        e["fix_type"] == "cross_outcome_muscle_sentence_cleanup"
        for e in log
    )


def test_apply_fixes_strips_parenthesized_author_outcome_mismatch() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Results\n\n"
        "Murphy (2020), studying anabolic resistance during CR, reported "
        "IGF-1 response changes across timepoints.\n"
    )
    manifest = {
        "receipts": [
            {"citation_token": "Murphy 2020", "outcome_class": "immune"},
        ],
    }
    fixed, log = fixer.apply_fixes(paper, [], manifest=manifest)
    assert "Murphy (2020)" not in fixed
    assert any(
        e["fix_type"] == "cross_outcome_muscle_sentence_cleanup"
        for e in log
    )


def test_apply_fixes_strips_healthspan_claim_from_non_healthspan_receipt() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Discussion\n\n"
        "Dorling 2025 observed that physical activity energy expenditure "
        "was associated with markers of healthspan during prolonged CR.\n"
    )
    manifest = {
        "receipts": [
            {"citation_token": "Dorling 2025", "outcome_class": "cardiometabolic"},
        ],
    }
    fixed, log = fixer.apply_fixes(paper, [], manifest=manifest)
    assert "markers of healthspan" not in fixed
    assert any(
        e["fix_type"] == "cross_outcome_muscle_sentence_cleanup"
        for e in log
    )


def test_apply_fixes_normalizes_paragraph_ordinal_gap() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    paper = (
        "## Introduction\n\n"
        "First, one boundary matters. Fourth, another boundary matters.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    assert "First, one boundary matters. Second, another boundary matters." in fixed
    assert any(e["fix_type"] == "ordinal_gap_normalization" for e in log)


def test_apply_fixes_strips_decimal_effect_estimate_artifact_cleanly() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\nHouston 2025 reported an effect estimate of 4.0%.\n",
        [],
    )
    assert "effect estimate" not in fixed
    assert "0%." not in fixed
    assert any(e["fix_type"] == "effect_estimate_artifact_sentence_strip" for e in log)


def test_apply_fixes_strips_orphan_threshold_sentence() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "This improvement, while statistically detectable, fell below the "
        "commonly cited clinically meaningful change threshold of 0.1 m/s "
        "for gait speed in older-adult research (Perera 2006).\n",
        [],
    )
    assert "This improvement" not in fixed
    assert any(e["fix_type"] == "orphan_threshold_sentence_strip" for e in log)


def test_apply_fixes_strips_orphan_demonstrated_clause() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Abstract\n\n"
        "Kazeminasab 2025 found increased handgrip strength, yet "
        "demonstrated that just two days of CR blunted IGF-1 response "
        "(P < 0.05), and Weaver 2026 reported null bone effects.\n",
        [],
    )
    assert "yet demonstrated that" not in fixed
    assert "Kazeminasab 2025 found increased handgrip strength" in fixed
    assert "Weaver 2026 reported null bone effects" in fixed
    assert any(e["fix_type"] == "orphan_demonstrated_clause_strip" for e in log)


def test_apply_fixes_strips_orphan_demonstrated_tail() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Abstract\n\n"
        "Weaver 2026 reported no protein effect on bone outcomes, and "
        "demonstrated that CR induces anabolic resistance.\n",
        [],
    )
    assert "demonstrated that CR induces anabolic resistance" not in fixed
    assert "Weaver 2026 reported no protein effect on bone outcomes." in fixed
    assert any(e["fix_type"] == "orphan_demonstrated_clause_strip" for e in log)


def test_apply_fixes_strips_empty_attribution_sentence() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "Roth 2022 provides real-world training context. The study may "
        "mitigate the anabolic resistance described by . Next sentence remains.\n",
        [],
    )
    assert "described by ." not in fixed
    assert "Roth 2022 provides real-world training context." in fixed
    assert "Next sentence remains." in fixed
    assert any(e["fix_type"] == "empty_attribution_sentence_strip" for e in log)


def test_apply_fixes_normalizes_h3_residue_and_taken_together() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "### H3: Cardiometabolic Outcomes\n\n"
        "Taken together, these findings remain bounded.\n",
        [],
    )
    assert "### H3:" not in fixed
    assert "### Cardiometabolic Outcomes" in fixed
    assert "Taken together," not in fixed
    assert "Across the corpus, these findings remain bounded." in fixed
    assert any(e["fix_type"] == "h3_residue_heading_normalization" for e in log)
    assert any(e["fix_type"] == "public_meta_phrase_normalization" for e in log)


def test_apply_fixes_normalizes_h3_tag_residue() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n### <H3>Cardiometabolic Outcomes</H3>\n\nText.\n",
        [],
    )
    assert "<H3>" not in fixed
    assert "</H3>" not in fixed
    assert "### Cardiometabolic Outcomes" in fixed
    assert any(e["fix_type"] == "h3_residue_heading_normalization" for e in log)


def test_apply_fixes_normalizes_tension_count_and_limited_evidence_phrase() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "The evidence base is limited to preclinical studies. "
        "The synthesis surfaces 366 non-orthogonal tensions.\n",
        [],
    )
    assert "evidence base is limited to" not in fixed
    assert "366 non-orthogonal tensions" not in fixed
    assert "The available evidence is concentrated in preclinical studies" in fixed
    assert "cross-study tensions" in fixed
    assert any(e["fix_type"] == "public_meta_phrase_normalization" for e in log)


def test_apply_fixes_normalizes_outcome_limited_evidence_phrase() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "The frailty evidence base is limited to a single observational analysis.\n",
        [],
    )
    assert "evidence base is limited" not in fixed
    assert "The frailty evidence base contains a single observational analysis" in fixed
    assert any(e["fix_type"] == "public_meta_phrase_normalization" for e in log)


def test_apply_fixes_journalizes_specific_tension_matrix_language() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## What This Synthesis Adds\n\n"
        "The tension matrix reveals substantial heterogeneity. "
        "The final interpretation is deliberately tiered.\n",
        [],
    )
    assert "tension matrix reveals" not in fixed
    assert "cross-study comparisons show" in fixed
    assert "final interpretation" not in fixed.lower()
    assert any(e["fix_type"] == "public_meta_phrase_normalization" for e in log)


def test_apply_fixes_strips_toxin_mobilization_aside() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Conclusion\n\n"
        "Clinical caution remains. Potential mobilization of lipophilic "
        "toxins during fat-mass loss may offset benefit. Final sentence.\n",
        [],
    )
    assert "lipophilic toxins" not in fixed
    assert "Clinical caution remains." in fixed
    assert "Final sentence." in fixed
    assert any(e["fix_type"] == "toxin_mobilization_sentence_strip" for e in log)


def test_apply_fixes_removes_public_reference_dumps_and_final_interpretation() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## What This Synthesis Adds\n\n"
        "This synthesis maps the evidence.\n\n"
        "PMID: 12345. DOI: 10.1000/a. PMID: 67890.\n\n"
        "### Background References\n\n"
        "DOI: 10.1000/b. PMID: 999.\n\n"
        "## Conclusion\n\n"
        "- **renovar 2023.** _Effectiveness._ Nutrients, 2023.\n\n"
        "Clean close.\n\n"
        "### Final interpretation\n\n"
        "Direct clinical receipts carry the most immediate weight.\n",
        [],
    )
    assert "PMID:" not in fixed
    assert "DOI:" not in fixed
    assert "Background References" not in fixed
    assert "renovar 2023" not in fixed
    assert "Final interpretation" not in fixed
    assert "Clean close." in fixed
    assert any(e["fix_type"] == "public_reference_dump_strip" for e in log)
    assert any(e["fix_type"] == "final_interpretation_block_strip" for e in log)


def test_apply_fixes_removes_frailty_sentence_from_immune_and_opener() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Results\n\n"
        "### Immune Outcomes\n\n"
        "CR lowered inflammatory markers in one trial. Beavers 2022 "
        "reported a 0.021 m/s gait speed change in frailty follow-up.\n\n"
        "## Discussion\n\n"
        "However, cardiometabolic benefit remains conditional.\n",
        [],
    )
    assert "gait speed" not in fixed
    assert "CR lowered inflammatory markers" in fixed
    assert "## Discussion\n\ncardiometabolic benefit" in fixed
    assert any(e["fix_type"] == "immune_section_nonimmune_sentence_strip" for e in log)
    assert any(e["fix_type"] == "discussion_opener_normalization" for e in log)


def test_apply_fixes_backfills_clinical_practice_statement() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    fixed, log = fixer.apply_fixes(
        "## Conclusion\n\n"
        "The conclusion remains bounded by current evidence.\n",
        [],
    )
    assert "should not be used off-label" in fixed
    assert any(e["fix_type"] == "clinical_practice_statement_backfill" for e in log)


def test_apply_fixes_repairs_role_drift_before_strip(tmp_path) -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    qc_dir = tmp_path / "quant_claims"
    qc_dir.mkdir()
    (qc_dir / "PMC_witham.quant_claims.json").write_text(
        '{"paper_id":"PMC_witham","claims":[{'
        '"claim_type":"unit_value","numeric_values":[0.13],'
        '"binding_confidence":"high","claim_role":"change_score"}]}'
    )
    manifest = {"receipts": [{
        "paper_id": "PMC_witham",
        "citation_token": "Witham 2025",
    }]}
    paper = (
        "## Results\n\n"
        "Baseline gait speed in this cohort was 0.13 m/s "
        "(Witham 2025), suggesting severely impaired mobility.\n"
    )
    fixed, log = fixer.apply_fixes(
        paper, [], manifest=manifest, quant_claims_dir=qc_dir,
    )
    assert "Baseline gait speed" not in fixed
    assert "change of 0.13 m/s" in fixed
    assert "Witham 2025" in fixed
    assert "according to that source role" not in fixed
    assert [e for e in log if e["fix_type"] == "numeric_role_guard_repair"]
    assert not [e for e in log if e["fix_type"] == "numeric_role_guard_strip"]


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


# ============ Fix #21 follow-up: auto-fixer skips markdown tables ====


def test_auto_fixer_does_not_strip_table_paragraphs() -> None:
    """Critical regression test: Table 5 surfaces corpus numerics
    (some matching background_literature entries like '7%' or
    '0.8 m/s') without their citation tokens — those are corpus-
    authorised, NOT background-context. The auto-fixer's
    background-strip pass MUST skip markdown tables, otherwise it
    eats the entire structured-evidence payload (and tanks Q9
    density)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Discussion\n\n"
        "Real prose paragraph. No background numerics here.\n\n"
        "## Table 5: Per-Paper Numeric Index\n\n"
        "| Citation | Section | Type | Value | Units |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Walton 2019 | abstract | percentage | 7% | % |\n"
        "| Konopka 2019 | abstract | unit_value | 0.8 m/s | m/s |\n"
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    # Table rows MUST survive — they're structured evidence
    assert "| Walton 2019 |" in fixed
    assert "7%" in fixed
    assert "0.8 m/s" in fixed
    # Strip log should NOT report a background-lit strip on table content
    bglit_strips = [
        e for e in log
        if e.get("fix_type") == "background_lit_unsourced_strip"
    ]
    assert not bglit_strips or bglit_strips[0]["n_changes"] == 0


def test_auto_fixer_still_strips_unsourced_prose_sentences() -> None:
    """Regression check: skipping tables MUST NOT skip real prose.
    A naked '7%' in a Discussion sentence (no ADA 2024 citation in
    same sentence) IS still stripped."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Discussion\n\n"
        "Diabetes guidelines target HbA1c below 7% in older adults. "
        "This is a different sentence with no background numeric.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    # The sentence with unsourced "7%" should be stripped
    assert "7%" not in fixed
    # The clean sentence survives
    assert "different sentence" in fixed


# ============ Fix #21 follow-up #2: double-space auto-fix ============


def test_auto_fixer_collapses_mid_line_double_spaces() -> None:
    """Stage-2 C08 flags `  ` (double-space mid-line) as P2
    auto_fixable=True. Pre-fix the auto-fixer had no implementation,
    so the issues survived to final consistency.json and tripped the
    no-regression gate (consistency_count regression)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Discussion\n\n"
        "First sentence  with double space. "
        "Another sentence here.\n"
    )
    fixed, log = fixer.apply_fixes(paper, [])
    # Double space collapsed
    assert "  " not in fixed.replace("\n\n", "")  # ignore paragraph breaks
    # Log records the fix
    ds_logs = [
        e for e in log if e.get("fix_type") == "double_space_collapse"
    ]
    assert ds_logs, f"expected double_space_collapse in log: {log}"
    assert ds_logs[0]["n_changes"] >= 1


def test_auto_fixer_does_not_collapse_indentation() -> None:
    """Line-start indentation (markdown bullets, cite blocks) is
    legitimate — must NOT be collapsed."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Conclusion\n\n"
        "Real sentence.\n\n"
        "  _Cited: `Walton 2019`_\n"  # 2-space indent intentional
    )
    fixed, log = fixer.apply_fixes(paper, [])
    # Indentation preserved
    assert "  _Cited:" in fixed
    # No double-space collapse logged for this paper (no mid-line dups)
    ds_logs = [
        e for e in log if e.get("fix_type") == "double_space_collapse"
    ]
    assert not ds_logs, f"unexpected double_space_collapse: {ds_logs}"


def test_auto_fixer_collapses_adjacent_duplicate_words() -> None:
    """Stage-2 C08 duplicated-word issues should not survive when
    the deterministic fixer can safely collapse the adjacent token."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = "## Discussion\n\nAspirin does not not associate cleanly.\n"
    fixed, log = fixer.apply_fixes(paper, [])

    assert "not not" not in fixed
    assert "does not associate" in fixed
    assert any(
        e.get("fix_type") == "duplicate_word_collapse" for e in log
    )


def test_auto_fixer_preserves_valid_duplicate_words() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = "## Discussion\n\nParticipants had had prior exposure.\n"
    fixed, log = fixer.apply_fixes(paper, [])

    assert "had had" in fixed
    assert not any(
        e.get("fix_type") == "duplicate_word_collapse" for e in log
    )


def test_apply_fixes_backfills_public_thesis_marker() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer
    import audit_v06_paper as audit

    paper = "## Abstract\n\nThis synthesis examined accepted receipts.\n"
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "aspirin"})

    ok, msg = audit._check_thesis_present(fixed)
    assert ok, msg
    assert "**Thesis:**" in fixed
    assert "evidence profile for" in fixed
    assert any(
        e.get("fix_type") == "public_thesis_marker_backfill" for e in log
    )


# ============ Fix #29 — stale SPAR language outside Methods ===========


def test_stale_spar_in_limitations_flagged_as_p1() -> None:
    """Fix #29: 'SPAR quarantine process' in Limitations (or any
    non-Methods section) trips C11 P1 when the manifest writer_path
    is the v0.6 quant-claim adapter (no SPAR ran)."""
    paper = (
        "## Methods\n\n"
        "v0.6 quant-claim adapter; no multi-receipt pipeline.\n\n"
        "## Limitations\n\n"
        "The SPAR quarantine process excluded several papers. "
        "Other limitations apply.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    c11 = [i for i in issues if i.id.startswith("C11-")]
    assert len(c11) >= 1
    assert all(i.severity == "P1" for i in c11)
    assert all(i.issue_type == "stale_spar_in_prose" for i in c11)


def test_stale_spar_in_methods_NOT_double_flagged_as_c11() -> None:
    """Fix #29: C11 (in-prose) check skips Methods because
    _check_stale_methods (C02) already flags it. Avoid double-count."""
    paper = (
        "## Methods\n\n"
        "The SPAR quarantine process applied to ranking.\n\n"
        "## Discussion\n\n"
        "Discussion has no stale SPAR phrases.\n"
    )
    issues = audit.run_audit(paper, _empty_manifest(), _empty_audit())
    c11 = [i for i in issues if i.id.startswith("C11-")]
    assert c11 == [], (
        f"C11 must skip Methods (covered by C02): {c11}"
    )


def test_stale_spar_check_silent_when_spar_actually_ran() -> None:
    """Defensive: if writer_path mentions spar, the check is a no-op
    (SPAR-language is legitimate when SPAR actually ran)."""
    spar_manifest = {
        "n_receipts": 3,
        "writer_path": "agent.spar_synthesis.render_full_paper",
        "receipts": [],
    }
    paper = (
        "## Limitations\n\nThe SPAR quarantine process excluded.\n"
    )
    issues = audit.run_audit(paper, spar_manifest, _empty_audit())
    c11 = [i for i in issues if i.id.startswith("C11-")]
    assert c11 == []


def test_apply_fixes_strips_spar_quarantine_in_limitations() -> None:
    """End-to-end: the auto-fixer's Stage-3 stale-SPAR-sentence strip
    now catches 'spar quarantine' (Fix #29 phrase additions)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Limitations\n\n"
        "The SPAR quarantine process excluded the TAME trial. "
        "Other limitations remain valid.\n"
    )
    fixed, _log = fixer.apply_fixes(paper, [])
    assert "SPAR quarantine" not in fixed
    # Surrounding good sentence survives (or replaced by disclaimer)
    assert "Other limitations" in fixed


def test_apply_fixes_preserves_methods_after_qei_not_run_block() -> None:
    """Regression for the large-corpus metformin paper: stale-SPAR
    cleanup must not eat `## Methods` or merge Methods into QEI."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer

    paper = (
        "## Quantitative Evidence Index — topic\n\n"
        "_Top 40 high-confidence numeric claims. Every row traces._\n\n"
        "## Methods\n\n"
        "This synthesis used the v0.6 quant-claim adapter.\n\n"
        "### LLM roles\n\n"
        "- **Writer:** model.\n\n"
        "### What did NOT run\n\n"
        "- SPAR (multi-judge panel adjudication) did NOT run on this corpus.\n"
        "- Multi-receipt cluster aggregation did NOT run.\n\n"
        "### Claim source\n\n"
        "`docs/quality-reference/topic/quant_claims/*.json`.\n\n"
        "## Results\n\nFindings.\n"
    )
    fixed, _log = fixer.apply_fixes(paper, [])
    assert "## Methods\n\n" in fixed
    assert "_Top 40 high-confidence numeric claims. Every row traces._" in fixed
    assert fixed.index("## Quantitative Evidence Index") < fixed.index("## Methods")
    assert fixed.index("## Methods") < fixed.index("### LLM roles")
    assert fixed.index("### LLM roles") < fixed.index("## Results")


def test_apply_fixes_backfills_cross_domain_after_review_trim() -> None:
    """Grok can shorten Cross-Domain after writer backstop runs; the
    deterministic fixer restores the Q12 floor without new numerics."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(
        _Path(__file__).resolve().parent.parent / "scripts"
    ))
    import apply_consistency_fixes as fixer
    import audit_v06_paper as audit_v06

    paper = (
        "## Cross-Domain Synthesis\n\n"
        + ("word " * 758)
        + "\n\n## Discussion\n\n"
        + ("word " * 900)
        + "\n\n## References\n\n- entry\n"
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest=_empty_manifest())
    ok, msg = audit_v06._check_cross_domain_depth(fixed)
    assert ok is True, msg
    assert "analytical_depth_backfill" in {x["fix_type"] for x in log}


def test_apply_fixes_restores_depth_after_final_public_dedupe(monkeypatch) -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer
    monkeypatch.setattr(
        fixer, "_strip_consecutive_duplicate_paragraphs",
        lambda md: (md, 0),
    )
    monkeypatch.setattr(
        fixer, "_strip_fuzzy_duplicate_paragraphs",
        lambda md: (md, 0),
    )
    monkeypatch.setattr(
        fixer, "_strip_duplicate_long_sentences",
        lambda md: (md, 0),
    )
    para = (
        "A boundary-condition paragraph explains why direct human evidence "
        "and indirect mechanistic evidence should not be interpreted as "
        "interchangeable when endpoints, populations, comparators, and "
        "follow-up windows differ across the retained corpus."
    )
    paper = (
        "## Cross-Domain Synthesis\n\n"
        + (para + "\n\n") * 2
        + "## Discussion\n\n"
        + "Discussion safe sentence. " * 280
    )
    fixed, log = fixer.apply_fixes(paper, [], manifest={"topic": "demo"})
    assert fixed.count(para) == 1
    assert fixer._section_word_count(fixed, "Cross-Domain Synthesis") >= 850
    assert "exact_public_duplicate_paragraph_post_depth" in {
        x["fix_type"] for x in log
    }


def test_lightweight_public_polish_strips_duplicate_paragraphs_pre_final_audit() -> None:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import apply_consistency_fixes as fixer

    para = (
        "This paragraph states a specific interpretive boundary for the "
        "paper across clinical receipts, mechanistic receipts, and indirect "
        "evidence classes while preserving the scientific claim, the "
        "population context, comparator context, endpoint context, and "
        "follow-up context."
    )
    near_dup = para.replace("scientific claim", "scientific conclusion")
    paper = (
        "## Abstract\n\n"
        f"{para}\n\n"
        "## Discussion\n\n"
        f"{near_dup}\n\n"
        "A distinct discussion paragraph remains available for readers.\n"
    )

    fixed, log = fixer.apply_lightweight_public_polish(
        paper,
        manifest={"topic": "demo"},
    )

    assert fixed.count("specific interpretive boundary") == 1
    assert "distinct discussion paragraph" in fixed
    assert any(item["fix_type"] == "fuzzy_duplicate_paragraph" for item in log)
