"""Fix #2: run-mode contract + deterministic Methods renderer.

Pre-fix the Methods section described pipeline stages that did not run
in the v0.6 adapter (SPAR adjudication, LLM fact extraction, multi-
receipt clusters) — Methods/run-mode contradiction. Fix renders
Methods deterministically from a frozen contract; output is bounded
by an explicit blocked-phrase list."""
from __future__ import annotations

import sys
from pathlib import Path
import re

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_mode_contract as rmc  # noqa: E402


def _v06_contract() -> rmc.RunModeContract:
    """Canonical v0.6 quant-claim adapter contract — what actually runs."""
    return rmc.RunModeContract(
        run_mode="v0.6 quant-claim adapter",
        topic="metformin",
        submission_id="synthesis-metformin-v06-test-2026-05-02T00-00-00Z",
        n_papers_in_corpus=15,
        n_high_confidence_claims_used_by_writer=134,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="docs/quality-reference/metformin/quant_claims/*.json",
    )


def test_v06_contract_renders_without_blocked_phrases() -> None:
    """The whole point of the fix: rendered Methods can never contain
    SPAR/quarantine/cluster/fact-extraction language. validate_rendered
    is the gate; this test proves the renderer respects it."""
    contract = _v06_contract()
    methods = rmc.render_methods(contract)
    assert rmc.validate_rendered(methods) == [], (
        f"Rendered Methods contains blocked phrases: "
        f"{rmc.validate_rendered(methods)}"
    )


def test_methods_excludes_operational_absence_disclosures() -> None:
    """Public Methods must not expose operational absence audit prose."""
    methods = rmc.render_methods(_v06_contract())
    assert "What did NOT run" not in methods
    assert "SPAR" not in methods
    assert "did NOT run" not in methods
    assert "LLM fact extraction" not in methods


def test_public_methods_meets_journal_surface_depth_floor() -> None:
    """Regression for urolithin_a live repro: deterministic Methods must
    clear the public journal-surface depth floor without operational prose."""
    methods = rmc.render_methods(_v06_contract())
    match = re.search(r"^## Methods\n\n(.*)", methods, flags=re.S)
    assert match is not None, "rendered Methods must start with '## Methods'"
    body = match.group(1)
    assert len(re.findall(r"\b\w+\b", body)) >= 300
    assert rmc.validate_rendered(methods) == []


def test_methods_does_not_name_operational_models() -> None:
    """Model stack belongs in appendix/provenance, not public Methods."""
    contract = _v06_contract()
    methods = rmc.render_methods(contract)
    assert contract.writer_model not in methods
    assert contract.in_writing_judge_model not in methods
    assert contract.final_layer_reviewer_model not in methods
    assert contract.final_layer_fallback_model not in methods
    assert contract.submission_id not in methods


def test_contract_validates_self_consistency_spar_requires_fact_extraction() -> None:
    """SPAR adjudicates LLM-extracted facts. spar_ran=True without
    llm_fact_extraction_ran=True is a contradiction — must surface."""
    bad = rmc.RunModeContract(
        run_mode="hybrid (test)",
        topic="metformin",
        submission_id="test",
        n_papers_in_corpus=15,
        n_high_confidence_claims_used_by_writer=100,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="quant_claims_json",
        spar_adjudication_ran=True,  # contradiction
        llm_fact_extraction_ran=False,
    )
    errors = rmc.validate_contract(bad)
    assert errors
    assert any("spar" in e.lower() and "fact_extraction" in e.lower()
               for e in errors)


def test_contract_validates_quarantine_requires_spar() -> None:
    """Quarantine receives SPAR-rejected receipts; can't run without SPAR."""
    bad = rmc.RunModeContract(
        run_mode="hybrid (test)",
        topic="metformin",
        submission_id="test",
        n_papers_in_corpus=15, n_high_confidence_claims_used_by_writer=100,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="quant_claims_json",
        spar_adjudication_ran=False,
        rejected_evidence_quarantine_ran=True,  # contradiction
    )
    errors = rmc.validate_contract(bad)
    assert any("quarantine" in e.lower() for e in errors)


def test_replace_methods_in_paper_handles_existing_methods() -> None:
    """Surgical replacement: existing ## Methods block → new block;
    other sections untouched; idempotent on second call."""
    paper = (
        "# Title\n\n"
        "## Abstract\n\nA brief.\n\n"
        "## Methods\n\n"
        "Old SPAR adjudication boilerplate that should NOT appear.\n"
        "Multi-receipt cluster machinery.\n\n"
        "## Results\n\nFindings here.\n"
    )
    new_methods = "## Methods\n\nClean deterministic Methods.\n"
    out1 = rmc.replace_methods_in_paper(paper, new_methods)
    assert "Clean deterministic Methods." in out1
    assert "SPAR adjudication" not in out1
    assert "## Results" in out1 and "Findings here." in out1
    # Idempotency: a second pass produces the same result
    out2 = rmc.replace_methods_in_paper(out1, new_methods)
    assert out1 == out2


def test_replace_methods_in_paper_inserts_when_missing() -> None:
    """A paper without a Methods section gets one inserted before
    References, or appended at end if no References either."""
    paper_with_refs = (
        "# Title\n\n## Abstract\n\nText.\n\n## References\n\n- Foo 2020.\n"
    )
    new_methods = "## Methods\n\nDeterministic Methods.\n"
    out = rmc.replace_methods_in_paper(paper_with_refs, new_methods)
    assert out.index("## Methods") < out.index("## References")

    paper_no_refs = "# Title\n\n## Abstract\n\nText.\n"
    out2 = rmc.replace_methods_in_paper(paper_no_refs, new_methods)
    assert "## Methods" in out2


def test_validate_rendered_catches_inserted_blocked_phrase() -> None:
    """Sanity: if someone hand-edits the renderer to leak a blocked
    phrase, validate_rendered must catch it. Otherwise the gate is
    a no-op."""
    poisoned = "## Methods\n\nThis used SPAR adjudication.\n"
    found = rmc.validate_rendered(poisoned)
    assert "SPAR adjudication" in found


def test_n_papers_zero_fails_validation() -> None:
    """A run with zero source papers makes no sense; surface the bug."""
    contract = rmc.RunModeContract(
        run_mode="v0.6", topic="metformin", submission_id="x",
        n_papers_in_corpus=0,
        n_high_confidence_claims_used_by_writer=0,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="quant_claims_json",
    )
    errors = rmc.validate_contract(contract)
    assert any("n_papers_in_corpus" in e for e in errors)


def test_contract_is_frozen() -> None:
    """RunModeContract is frozen+slots per project rule. Must not
    accept attribute mutation."""
    c = _v06_contract()
    with pytest.raises(Exception):  # FrozenInstanceError
        c.run_mode = "mutated"


# ----- Reviewer-fix discriminating tests (post-2x review) ---------------


def test_contract_is_kw_only_blocks_positional_swap() -> None:
    """kw_only=True forces all callers to use keyword args. Pre-fix a
    caller could swap n_papers and n_high_confidence_claims_used_by_writer
    silently — both bare ints, both pass int validation."""
    with pytest.raises(TypeError):
        rmc.RunModeContract(  # type: ignore[call-arg]
            "v0.6", "metformin", "test", 15, 100,
            "mimo", "gemma", "grok", "mistral", "src",
        )


def test_replace_methods_handles_methods_in_code_fence() -> None:
    """Pre-fix the regex matched `## Methods` inside fenced code blocks
    and clobbered real prose. Now code fences are masked before
    matching."""
    paper = (
        "## Methods\n\nReal methods text.\n\n"
        "## Discussion\n\n"
        "Example log:\n\n"
        "```\n"
        "## Methods\n"
        "fake methods inside code\n"
        "## Results\n"
        "```\n\n"
        "## Conclusion\n\nReal conclusion.\n"
    )
    new_methods = "## Methods\n\nDETERMINISTIC METHODS.\n"
    out = rmc.replace_methods_in_paper(paper, new_methods)
    assert "DETERMINISTIC METHODS." in out
    # Real Discussion + code fence + Conclusion are preserved
    assert "Example log:" in out
    assert "fake methods inside code" in out
    assert "## Conclusion" in out
    assert "Real conclusion." in out


def test_replace_methods_does_not_match_methods_section_suffix() -> None:
    """`## Methods Section` and `## Methods and Materials` are NOT the
    target — they're real authored headers. Pre-fix `\\b` boundary
    matched them; insert-before-References path produced a duplicate."""
    paper = (
        "## Methods and Materials\n\n"
        "Author-written methods detail.\n\n"
        "## Results\n\nFindings.\n"
    )
    new_methods = "## Methods\n\nDeterministic.\n"
    out = rmc.replace_methods_in_paper(paper, new_methods)
    # Original "Methods and Materials" header is untouched
    assert "## Methods and Materials" in out
    # New ## Methods section was inserted (since none was found)
    assert out.count("## Methods") == 2  # both headers present


def test_repeated_replace_does_not_accumulate_blank_lines() -> None:
    """Idempotency check: running 5 times must produce the same length
    as running once (no triple+newline accumulation)."""
    paper = (
        "## Methods\n\nold\n\n## Results\n\nx\n"
    )
    new_methods = "## Methods\n\nfresh.\n"
    out1 = rmc.replace_methods_in_paper(paper, new_methods)
    out_n = out1
    for _ in range(5):
        out_n = rmc.replace_methods_in_paper(out_n, new_methods)
    assert out_n == out1
    # Sanity: no triple-newlines anywhere
    assert "\n\n\n" not in out_n


def test_validate_rendered_is_case_insensitive() -> None:
    """Pre-fix `\\b` + case-sensitive match missed lowercase variants
    like `spar adjudication` or `Spar Adjudication`. Now case-insensitive."""
    poisoned1 = "## Methods\n\nWe used spar adjudication on the receipts.\n"
    poisoned2 = "## Methods\n\nFact Extractor proposed quotes.\n"
    poisoned3 = "## Methods\n\nManual Review by two reviewers.\n"
    assert rmc.validate_rendered(poisoned1)
    assert rmc.validate_rendered(poisoned2)
    assert rmc.validate_rendered(poisoned3)


def test_what_did_not_run_section_omitted_when_nothing_to_disclose() -> None:
    """When all four 'did NOT run' flags flip to True (a future run
    that genuinely runs SPAR + clusters + fact extraction + quarantine),
    the section is suppressed entirely instead of leaving a dangling
    header. Discrimination test: matches future-state regression."""
    full_run = rmc.RunModeContract(
        run_mode="hybrid (test)",
        topic="metformin",
        submission_id="future",
        n_papers_in_corpus=15,
        n_high_confidence_claims_used_by_writer=100,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="quant_claims_json",
        spar_adjudication_ran=True,
        multi_receipt_clusters_ran=True,
        llm_fact_extraction_ran=True,
        rejected_evidence_quarantine_ran=True,
    )
    methods = rmc.render_methods(full_run)
    assert "What did NOT run" not in methods


def test_public_methods_excludes_root_cause_meta_phrases() -> None:
    methods = rmc.render_methods(_v06_contract())
    lower = methods.lower()
    for phrase in (
        "this synthesis was produced by",
        "submission `synthesis-",
        "final-layer reviewer",
        "patches are auto-applied",
        "grok",
        "llm proposes, code disposes",
        "no llm authorship",
    ):
        assert phrase not in lower


def test_contract_validates_unsubstituted_topic_placeholder() -> None:
    """Pre-fix `claim_source` had a literal `<topic>` placeholder that
    leaked into Methods. Now the validator catches angle-bracket
    placeholders."""
    bad = rmc.RunModeContract(
        run_mode="v0.6", topic="metformin", submission_id="test",
        n_papers_in_corpus=15, n_high_confidence_claims_used_by_writer=100,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="docs/quality-reference/<topic>/quant_claims/*.json",
    )
    errors = rmc.validate_contract(bad)
    assert any("placeholder" in e.lower() for e in errors)


def test_contract_validates_cluster_without_claims() -> None:
    """Cluster-without-prerequisites: clusters need claims. A cluster
    flag with zero claims is structurally inconsistent."""
    bad = rmc.RunModeContract(
        run_mode="hybrid", topic="metformin", submission_id="test",
        n_papers_in_corpus=15,
        n_high_confidence_claims_used_by_writer=0,
        writer_model="mimo-v2.5-pro",
        in_writing_judge_model="google/gemma-4-31b-it",
        final_layer_reviewer_model="google/gemini-3.1-flash-lite:exacto",
        final_layer_fallback_model="mistralai/mistral-small-2603",
        claim_source="quant_claims_json",
        multi_receipt_clusters_ran=True,
    )
    errors = rmc.validate_contract(bad)
    assert any("cluster" in e.lower() for e in errors)


def test_validate_rendered_returns_sorted() -> None:
    """validate_rendered output is sorted for deterministic test
    assertions (frozenset/tuple iteration order otherwise unspecified)."""
    poisoned = (
        "## Methods\n\nWe ran SPAR adjudication AND fact extractor "
        "AND multi-receipt cluster machinery.\n"
    )
    found = rmc.validate_rendered(poisoned)
    assert found == sorted(found)
    assert len(found) >= 3
