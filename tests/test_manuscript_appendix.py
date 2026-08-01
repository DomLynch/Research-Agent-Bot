"""Researka manuscript appendix tests.

Covers the four publication-ready sections that journals expect:
search provenance, AI-use disclosure (ICMJE-compliant), human
accountability template, data + code availability.

Pure-Python composer; no LLM calls; data-dependent fixtures use
synthetic manifest dicts so tests run fast and on CI."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent import manuscript_appendix as appx  # noqa: E402


def _fake_manifest() -> dict:
    return {
        "n_receipts": 15,
        "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "n_llm_calls": 16,
        "total_cost_usd": 0.022104,
        "extractor_version": "v0.6.0",
        "claim_strength_repairs": 8,
        "retrieval": {
            "sources": [
                {"name": "PubMed", "status": "ok"},
                {"name": "OpenAlex", "status": "rate_limited"},
            ],
            "queries": ["metformin AND aging"],
            "expected_evidence_slots": ["clinical_trial"],
            "counts": {"parsed": 136, "quant_extracted": 120},
        },
        "receipt_funnel": {
            "quant_claim_files": 287,
            "active_paper_ids": 136,
            "classified_receipt_candidates": 40,
            "receipt_candidate_union": 40,
            "counts": {
                "accepted_high_confidence": 40,
                "candidate_no_claims": 49,
                "candidate_partial_only": 26,
                "candidate_partial_and_none_only": 57,
                "candidate_none_only": 6,
                "outside_active_or_classified_scope": 109,
            },
        },
        "receipts": [
            {
                "receipt_id": "Walton_2019",
                "evidence_tier": "A1",
                "directness": "direct",
                "outcome_class": "muscle_function",
            },
            {
                "receipt_id": "Konopka_2019",
                "evidence_tier": "A1",
                "directness": "direct",
                "outcome_class": "cardiometabolic",
            },
            {
                "receipt_id": "Witham_2025",
                "evidence_tier": "A1",
                "directness": "direct",
                "outcome_class": "frailty",
            },
            {
                "receipt_id": "Keys_2025",
                "evidence_tier": "B1",
                "directness": "review",
                "outcome_class": "longevity",
            },
        ],
    }


def _fake_model_stack() -> dict:
    return {
        "writer": "MiMo-VL-7B-RL-2508",
        "reviewer": "Grok-4.3-Reasoning",
        "extractor": "MiMo-VL-7B-RL-2508",
        "thesis": "MiMo-VL-7B-RL-2508",
    }


# =========== Search Provenance ====================================


def test_search_provenance_names_databases_queried() -> None:
    """Only frozen retrieval sources may be disclosed."""
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "PubMed" in md
    assert "OpenAlex" in md
    assert "failed" in md
    assert "rate_limited" not in md
    assert "Europe PMC" not in md
    assert "ClinicalTrials.gov" not in md


def test_search_provenance_has_no_hardcoded_database_inventory() -> None:
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "bioRxiv" not in md
    assert "Web of Science" not in md
    assert "Google Scholar" not in md
    assert "17 sources" not in md


def test_search_provenance_without_inventory_claims_no_source_count() -> None:
    manifest = _fake_manifest()
    manifest.pop("retrieval")
    manifest["receipts"] = []
    md = appx.build_search_provenance_appendix(manifest, topic="metformin")
    assert "source inventory was not frozen" in md
    assert "17 sources" not in md


def test_receipt_sources_do_not_fabricate_retrieval_inventory() -> None:
    manifest = _fake_manifest()
    manifest.pop("retrieval")
    manifest["receipts"] = [{"source": "PubMed"}]
    md = appx.build_search_provenance_appendix(manifest, topic="metformin")
    assert "inventory unavailable" in md
    assert "| PubMed |" not in md


def test_search_provenance_does_not_claim_prisma_compliance() -> None:
    """Critical honesty constraint: must NOT claim PRISMA compliance.
    The reviewer flagged this exact issue."""
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "not a PRISMA" in md or "not PRISMA" in md
    assert "do not claim" in md.lower() or (
        "we do not" in md.lower()
    )


def test_search_provenance_reports_receipt_counts() -> None:
    """Reader must see the exact n_receipts / n_claims / n_tensions
    so they can audit the synthesis pool."""
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "15" in md  # n_receipts
    assert "134" in md  # n_claims
    assert "42" in md  # n_tensions


def test_search_provenance_renders_selection_flow_counts() -> None:
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "Selection flow (PRISMA-style counts)" in md
    assert "| Quant-claim files screened | 287 |" in md
    assert "| Receipt candidate union | 40 |" in md
    assert "| No extractable claims | 49 |" in md
    assert "| Mixed partial-or-none claim-binding candidates | 57 |" in md
    assert "not additive exclusion totals" in md
    assert "| Admitted final receipts | 40 |" in md
    assert "not a PRISMA claim" in md


def test_search_provenance_includes_tier_distribution() -> None:
    """Tier breakdown must be present (3 A1 + 1 B1 in fake data)."""
    md = appx.build_search_provenance_appendix(_fake_manifest(), topic="metformin")
    assert "A1" in md
    assert "B1" in md


# =========== AI-Use Disclosure ====================================


def test_ai_use_disclosure_declares_audit_protocol_complement() -> None:
    """Reviewer wave 9 (2026-05-05): combative 'does not defer to
    ICMJE/Nature/BMJ' framing softened to journal-neutral
    'complement, not replace' framing. The disclosure must
    explicitly position itself as complementary to peer review."""
    md = appx.build_ai_use_disclosure(
        _fake_manifest(), model_stack=_fake_model_stack(),
    )
    assert "complement" in md.lower()
    assert "Researka A2A-AAA Protocol" in md
    assert "ICMJE" not in md  # combative reference removed
    assert "Researka A2A-AAA" in md
    # Naming legacy policies is fine — the manifesto explicitly
    # contrasts with them — but the headline framing is RIS.
    assert "trust spine" in md.lower() or "trust-spine" in md.lower()


def test_ai_use_disclosure_names_every_model() -> None:
    """Every model in model_stack must appear in the disclosure
    table — no hidden AI use."""
    stack = _fake_model_stack()
    md = appx.build_ai_use_disclosure(
        _fake_manifest(), model_stack=stack,
    )
    for model in stack.values():
        assert model in md


def test_ai_use_disclosure_lists_what_ai_did_not_do() -> None:
    """Honest scoping: name the things AI did NOT do."""
    md = appx.build_ai_use_disclosure(
        _fake_manifest(), model_stack=_fake_model_stack(),
    )
    assert "did NOT do" in md or "did not do" in md.lower()
    assert "research question" in md.lower()


def test_ai_use_disclosure_describes_trust_spine() -> None:
    """Must explain what gates AI output — the moat."""
    md = appx.build_ai_use_disclosure(
        _fake_manifest(), model_stack=_fake_model_stack(),
    )
    assert "Citation registry" in md or "citation registry" in md
    assert "Numeric registry" in md or "numeric registry" in md
    assert "Stage-1" in md
    assert "Stage-2" in md
    assert "no-regression" in md.lower() or "No-regression" in md


def test_ai_use_disclosure_reports_run_metadata() -> None:
    """Number of LLM calls + total cost must be disclosed for
    cost-transparency."""
    md = appx.build_ai_use_disclosure(
        _fake_manifest(), model_stack=_fake_model_stack(),
    )
    assert "16" in md  # n_llm_calls
    assert "0.0221" in md  # cost_usd (truncated)


# =========== Human Accountability =================================


def test_submitter_block_is_researka_independent_standard() -> None:
    """RIS replaces ICMJE-deferring 'Human Accountability Statement'.

    Researka does NOT defer to legacy AI-use policies. The audit trail
    is the primary accountability mechanism. The submitter releases
    the artifact + invites public error-reporting; they do not claim
    to have personally re-read every word."""
    md = appx.build_human_accountability_template()
    assert "Researka Submitter Block" in md
    assert "audit trail" in md.lower()
    assert "Researka Independent Standard" in md
    # No legacy ICMJE deference
    assert "ICMJE" not in md


def test_submitter_block_includes_template_placeholders() -> None:
    """Submitter must fill in name + affiliation + ORCID + COI + funding."""
    md = appx.build_human_accountability_template()
    assert "ORCID" in md
    assert "Conflict of interest" in md
    assert "Funding" in md
    # Versioning + re-cert framing
    assert "versioned re-cert" in md.lower() or "Versioning" in md


def test_submitter_block_does_not_certify_trust_spine_artifact() -> None:
    """Non-AAA artifacts get audit wording, not certification wording."""
    md = appx.build_human_accountability_template(verdict="Trust-Spine Pass")
    assert "Trust-Spine Pass audit artifact" in md
    assert "not represented as an A2A-AAA certification" in md
    assert "certification tolerances" not in md
    assert "pending AAA" not in md


def test_submitter_block_uses_certification_wording_only_for_aaa() -> None:
    """AAA artifacts may use certification wording."""
    md = appx.build_human_accountability_template(verdict="AAA")
    assert "Researka-Certified A2A-AAA artifact" in md
    assert "certification tolerances" in md


# =========== Data and Code Availability ===========================


def test_data_code_availability_includes_run_id_and_sha() -> None:
    """A reader must see exactly which run + SHA produced this
    paper to reproduce."""
    md = appx.build_data_code_availability(
        run_id="synthesis-metformin-v06-fix54-verify2-...",
        git_sha="274648e",
    )
    assert "synthesis-metformin-v06-fix54-verify2" in md
    assert "274648e" in md


def test_data_code_availability_includes_clone_recipe() -> None:
    """Reproduction recipe must be a runnable command, not prose."""
    md = appx.build_data_code_availability(
        run_id="r1", git_sha="abc1234",
    )
    assert "git clone" in md
    assert "git checkout" in md
    assert "run_v06_synthesis.py" in md


def test_data_code_availability_invites_error_reports() -> None:
    """Per Researka manifesto: public error surface. Bundle must
    direct readers to the issue tracker for found errors."""
    md = appx.build_data_code_availability(
        run_id="r1", git_sha="abc1234",
    )
    assert "issue" in md.lower() or "github" in md.lower()


def test_data_code_availability_non_aaa_uses_audit_bundle_language() -> None:
    """TSP/blocked outputs are audit bundles, not certification bundles."""
    md = appx.build_data_code_availability(
        run_id="r1", git_sha="abc1234", verdict="Trust-Spine Pass",
    )
    assert "Git SHA at run" in md
    assert "unified verdict and audit record" in md
    assert "A2A-AAA certification" not in md


def test_data_code_availability_aaa_keeps_certification_language() -> None:
    """AAA outputs may expose the certification record."""
    md = appx.build_data_code_availability(
        run_id="r1", git_sha="abc1234", verdict="AAA",
    )
    assert "Git SHA at certification" in md
    assert "A2A-AAA certification record" in md


# =========== Top-level composer ===================================


def test_compose_appendix_assembles_all_four_sections() -> None:
    """compose_appendix returns a single block with all 4 sections
    in the correct order."""
    md = appx.compose_appendix(
        _fake_manifest(),
        model_stack=_fake_model_stack(),
        topic="metformin",
        run_id="r1",
        git_sha="abc1234",
    )
    assert md.startswith("## Publication Appendix")
    sp_pos = md.find("## Search Provenance and Selection")
    ai_pos = md.find("## AI-Use Disclosure")
    sb_pos = md.find("## Researka Submitter Block")
    dc_pos = md.find("## Data and Code Availability")
    assert sp_pos >= 0
    assert ai_pos > sp_pos
    assert sb_pos > ai_pos
    assert dc_pos > sb_pos


def test_compose_disclosures_share_frozen_retrieval_manifest() -> None:
    md = appx.compose_appendix(
        _fake_manifest(),
        model_stack=_fake_model_stack(),
        topic="metformin",
        run_id="r1",
        git_sha="abc1234",
    )
    assert md.count("2 enabled; 1 succeeded; 1 failed") == 2
    assert "`metformin AND aging`" in md
    assert "Papers parsed into the corpus: **136**" in md
    assert "Papers with quant-extracted claims: **120**" in md
    assert "17 sources" not in md


def test_compose_appendix_does_not_emit_stale_spar_adjudication_phrase() -> None:
    """Appendix prose must not reintroduce stale Stage-2 SPAR wording."""
    md = appx.compose_appendix(
        _fake_manifest(),
        model_stack=_fake_model_stack(),
        topic="metformin",
        run_id="r1",
        git_sha="abc1234",
        verdict="Trust-Spine Pass",
    )
    assert "SPAR adjudication" not in md
    assert "pending AAA" not in md
    assert "cert's stated tolerances" not in md


# =========== Splice helper ========================================


def test_splice_inserts_before_references() -> None:
    """Splicing puts the appendix immediately before '## References'."""
    paper = (
        "## Conclusion\n\nFoo.\n\n"
        "## References\n\n[1] Bar.\n"
    )
    appendix = "## Search Provenance and Selection\n\nbody\n"
    out = appx.splice_appendix_before_references(paper, appendix)
    assert "## Publication Appendix" in out
    sp_pos = out.find("## Search Provenance")
    ref_pos = out.find("## References")
    assert sp_pos >= 0 and ref_pos >= 0
    assert sp_pos < ref_pos


def test_splice_is_idempotent() -> None:
    """Bare historical appendix is wrapped once, then stable."""
    paper = (
        "## Conclusion\n\nFoo.\n\n"
        "## Search Provenance and Selection\n\nold body\n\n"
        "## References\n\n[1] Bar.\n"
    )
    appendix = "## Search Provenance and Selection\n\nNEW body\n"
    out = appx.splice_appendix_before_references(paper, appendix)
    assert out.count("## Publication Appendix") == 1
    assert "old body" in out and "NEW body" not in out
    assert appx.splice_appendix_before_references(out, appendix) == out


def test_splice_appends_when_no_references_section() -> None:
    """If there's no '## References', the appendix appends to end."""
    paper = "## Conclusion\n\nFoo.\n"
    appendix = "## Search Provenance and Selection\n\nbody\n"
    out = appx.splice_appendix_before_references(paper, appendix)
    assert "## Publication Appendix" in out
    assert "## Search Provenance" in out
    assert out.startswith("## Conclusion")
