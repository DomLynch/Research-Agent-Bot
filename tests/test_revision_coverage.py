from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import revision_coverage  # type: ignore[import-not-found]  # noqa: E402
from agent import revision_claim_trace  # noqa: E402
from agent.evidence_lanes import effective_directness  # noqa: E402
from agent.revision_contract import ask_fingerprint, gate_report  # noqa: E402
from agent.sources.pubmed import pmid_rows_fingerprint  # noqa: E402
from agent.revision_identity import (  # noqa: E402
    direction_tally_note,
    outcome_class_tally_note,
    repair_revision_identity,
)
from agent.revision_quality import (  # noqa: E402
    _findings_map_is_exact,
    findings_map_row,
    manifest_row_finding,
    repair_revision_quality,
    revision_quality_proof_is_stated,
)


def _chat(parsed: dict[str, Any]) -> Any:
    async def fake(**_kwargs: Any) -> Any:
        return type("Resp", (), {"parsed": parsed})()
    return fake


def test_findings_map_reclassifies_animal_trial_as_context() -> None:
    row = {
        "citation_token": "Smith 2026",
        "source_title": "Randomized trial in overweight cats with diabetes",
        "evidence_tier": "A1",
        "directness": "direct",
        "outcome_class": "cardiometabolic",
        "effect_direction": "positive",
    }

    projected = findings_map_row(row)

    assert projected[0] == "Animal/Preclinical Context (Cardiometabolic)"
    assert projected[3] == "directness=animal/preclinical context"
    assert projected[5].startswith(
        "outcome=Animal/Preclinical Context (Cardiometabolic);"
    )
    from agent.journal_finalizer import _findings_map_section
    assert _findings_map_is_exact(_findings_map_section([row]), [row])


def test_effective_directness_excludes_animal_trial_from_human_direct_core() -> None:
    animal = {
        "source_title": "Randomized veterinary trial in overweight cats",
        "evidence_tier": "A1",
        "directness": "direct",
    }
    human = {
        "source_title": "Randomized trial in older human participants",
        "population_summary": "older human participants",
        "evidence_tier": "A1",
        "directness": "direct",
    }

    assert effective_directness(animal) == "indirect"
    assert effective_directness(human) == "direct"


def test_latest_reviewer_source_and_disclosure_asks_are_deterministic() -> None:
    asks = [
        "Jorgensen 2026 is a veterinary cat RCT and must not be listed as direct human clinical; "
        "downgrade its directness and move it out of the load-bearing clinical list.",
        "Kitzman 2016 is itself a 2x2 factorial RCT but functions as a review-grade comparison "
        "for this synthesis; make the framing consistent.",
        "For each numeric statistic cited, verify it against the bundle excerpts or mark it unverifiable.",
        "Methods must disclose non-PubMed source_type=corpus abstracts and add publisher venue where possible.",
        "Cross-Domain Synthesis should explicitly state that the proposed long-duration RCT does not currently exist.",
        "Abstract should note source-level direction is conservative coded polarity and may differ from claim-level direction.",
    ]
    rows = [
        {
            "citation_token": "Jorgensen 2026",
            "source_title": "Veterinary randomized trial in overweight cats",
            "source_venue": "Journal of Feline Medicine",
            "evidence_tier": "A1",
            "directness": "indirect",
        },
        {
            "citation_token": "Kitzman 2016",
            "source_title": "Two by two factorial randomized trial",
            "source_pmid": "12345678",
            "source_venue": "Clinical Trials",
            "evidence_tier": "A1",
            "directness": "direct",
        },
    ]
    paper = (
        "## Abstract\n\nThe evidence remains bounded.\n\n"
        "## Methods\n\nSources were retained from the frozen corpus.\n\n"
        "## Results\n\nJorgensen 2026 and Kitzman 2016 were retained. "
        "A reported comparison had p = 0.009.\n\n"
        "## Cross-Domain Synthesis\n\nThe proposed trial would resolve the design gap.\n"
    )
    feedback = "; ".join(asks)

    fixed, details = repair_revision_quality(paper, rows, feedback)

    assert details == [
        "exact_stat_trace",
        "evidence_role_reconciliation",
        "source_indexing_disclosure",
        "unrepresented_trial_boundary",
        "abstract_coded_polarity",
    ]
    assert "directness=indirect" in fixed
    assert "review-grade comparison" in fixed
    assert "venue=Journal of Feline Medicine" in fixed
    assert "future-study requirement, not evidence claimed to exist" in fixed
    assert "may differ from claim-level direction" in fixed
    assert revision_coverage.deterministic_known_asks(asks, evidence_rows=rows) == asks
    assert revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []
    assert repair_revision_quality(fixed, rows, feedback) == (fixed, [])


def test_non_pubmed_disclosure_fails_closed_without_corpus_rows() -> None:
    ask = "Methods must disclose non-PubMed source_type=corpus abstracts and publisher venues."
    rows = [{"citation_token": "Smith 2025", "source_pmid": "12345"}]
    paper = "## Methods\n\nThe retained source is PubMed indexed.\n"

    assert revision_quality_proof_is_stated(paper, ask, rows) is False
    assert repair_revision_quality(paper, rows, ask) == (paper, [])


def _unmet(asks: list[str], parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unmet_asks("MANUSCRIPT BODY", asks, chat=_chat(parsed), settings=object())


def test_unmet_asks_empty_when_all_addressed(monkeypatch) -> None:
    assert _unmet(["a", "b"], {"addressed": [True, True]}, monkeypatch) == []


def test_unmet_asks_flags_unaddressed_in_order(monkeypatch) -> None:
    assert _unmet(["hedge claims", "clarify scope"], {"addressed": [True, False]}, monkeypatch) == ["clarify scope"]


def test_unmet_asks_fail_closed_on_malformed_verdict(monkeypatch) -> None:
    assert _unmet(["a", "b"], {"addressed": [True]}, monkeypatch) == ["a", "b"]
    assert _unmet(["a"], {"addressed": "nope"}, monkeypatch) == ["a"]
    assert _unmet(["a"], {"addressed": ["false"]}, monkeypatch) == ["a"]


def test_exact_stat_trace_does_not_collapse_integer_values() -> None:
    ask = "For every exact statistic, attach the bundle token or use directional language."
    rows = [{"citation_token": "Smith 2025", "thesis_text": "The reported NNT was 10."}]

    assert revision_quality_proof_is_stated("Smith 2025 [bundle:1] reported NNT = 10.", ask, rows) is True
    assert revision_quality_proof_is_stated("Smith 2025 [bundle:1] reported NNT = 1.", ask, rows) is False
    assert revision_quality_proof_is_stated("Smith 2025 reported NNT = 10.", ask, rows) is False


def test_named_source_revisions_are_repaired_from_receipt_truth() -> None:
    feedback = (
        "Reconcile Mandrioli 2023 direction coding: either keep positive or null, but use "
        "consistent wording in Abstract, Findings Map, Cross-Domain Synthesis, and Results; "
        "Clarify or correct the Stanfield 2026 'P < 0.001' statistic if it is not present "
        "in the bundle excerpt; "
        "Justify inclusion of Wick 2025 under the paper topic or flag it as a structural "
        "corpus limitation."
    )
    rows: list[dict[str, Any]] = [
        {
            "citation_token": "Mandrioli 2023",
            "source_title": "Randomized trial of rapamycin",
            "effect_direction": "positive",
            "directness": "direct",
        },
        {
            "citation_token": "Stanfield 2026",
            "source_title": "Exercise and weekly sirolimus",
            "effect_direction": "unclear",
            "directness": "direct",
            "p_values": ["p = 0.089", "p < 0.001"],
            "thesis_text": "The retained source excerpt reports p = 0.089.",
        },
        {
            "citation_token": "Wick 2025",
            "source_title": "Molecularly matched therapies in glioblastoma",
            "effect_direction": "unclear",
            "directness": "indirect",
        },
    ]
    paper = (
        "# Paper\n\n## Abstract\n\nMandrioli 2023 was coded as null.\n\n"
        "## Evidence Landscape\n\n### Findings Map\n\n"
        "| Source | Finding |\n| --- | --- |\n| Mandrioli 2023 | direction=null |\n\n"
        "## Results\n\nMandrioli 2023 (null on the measured endpoint) was retained.\n\n"
        "## Cross-Domain Synthesis\n\nMandrioli 2023 direction=null.\n\n"
        "## Limitations\n\nCorpus limitations.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, feedback)
    asks = revision_coverage.revision_asks(feedback)

    assert details == [
        "named_direction_reconciliation",
        "named_statistic_reconciliation",
        "named_topic_fit_boundary",
    ]
    assert fixed.count("Source-direction reconciliation (Mandrioli 2023):") == 1
    assert fixed.count("Mandrioli 2023") == paper.count("Mandrioli 2023") + 1
    assert "Mandrioli 2023 was coded as positive" in fixed
    assert "Mandrioli 2023 (positive on the measured endpoint)" in fixed
    assert "Mandrioli 2023 direction=positive" in fixed
    assert "Stanfield 2026 [bundle:2] retains p = 0.089 as bundle-traceable" in fixed
    assert "p < 0.001" not in fixed
    assert "Source-scope boundary (Wick 2025):" in fixed
    assert "structural corpus limitation" in fixed
    assert revision_coverage.deterministic_known_asks(asks, evidence_rows=rows) == asks
    assert revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []
    assert repair_revision_quality(fixed, rows, feedback) == (fixed, [])


def test_pending_protocol_and_reviewer_boilerplate_repairs_converge(tmp_path: Path) -> None:
    asks = [
        (
            "Resolve the Smith 2024 internal contradiction: the Results claim that no numerics "
            "are available, while the Evidence Snapshot cites a representative statistic for "
            "Smith 2024 — pick one framing and align the other section."
        ),
        (
            "Delete the boilerplate/word-floor/recommendation-boundary paragraphs that do not "
            "advance evidence synthesis (Abstract closing paragraph; scattered public word floor lines)."
        ),
        (
            "Make Smith 2024 and Smith 2026 evidence pending if no numerics can be cited, "
            "and remove unverified effect direction inferences."
        ),
    ]
    rows: list[dict[str, Any]] = [
        {
            "citation_token": "Smith 2024",
            "source_title": "Protocol for a randomized study to evaluate treatment effects",
            "effect_direction": "null",
            "p_values": [],
            "thesis_text": "Participants will be randomly assigned; a prior cohort reported RR = 0.75.",
        },
        {
            "citation_token": "Smith 2026",
            "effect_direction": "positive",
            "p_values": ["p = 0.089"],
            "thesis_text": "The primary analysis reported p = 0.089.",
        },
    ]
    paper = (
        "# Paper\n\n## Abstract\n\nBounded synthesis.\n\n"
        "This paragraph marks that evidence boundary and adds no result or recommendation "
        "beyond the cited corpus.\n\n"
        "## Evidence Landscape\n\n### Findings Map\n\n"
        "| Source | Direction |\n| --- | --- |\n| Smith 2024 | direction=null |\n"
        "| Smith 2026 | direction=positive |\n\n"
        "## Results\n\nSource-statistic reconciliation (Smith 2024; exact statistic): "
        "Smith 2024 has no bundle-traceable exact statistic; other exact values are excluded, "
        "and no direction is inferred from a statistic alone. "
        "Existing evidence suffix: Smith 2024 [bundle:1] reports RR = 0.75.\n\n"
        "Smith 2024 direction=null. Smith 2026 direction=positive.\n\n"
        "This section-scoped result reports Smith 2026 [bundle:2] at p = 0.089.\n\n"
        "## Cross-Domain Synthesis\n\nA null signal is represented by Smith 2024.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, "; ".join(asks))

    assert details == [
        "named_direction_reconciliation", "named_statistic_reconciliation",
        "fragmentary_prose",
    ]
    assert "Smith 2024 has no bundle-traceable exact statistic and remains evidence-pending" in fixed
    assert fixed.count("Smith 2024 has no bundle-traceable exact statistic and remains evidence-pending") == 1
    assert "Existing evidence suffix: Smith 2024 [bundle:1] reports RR = 0.75." in fixed
    assert "direction=null" not in fixed
    assert "Smith 2026 direction=positive" in fixed
    assert "null signal is represented by Smith 2024" not in fixed
    assert "An unclear signal is represented by Smith 2024" in fixed
    assert "This paragraph marks that evidence boundary" not in fixed
    assert "This section-scoped result reports Smith 2026" in fixed
    assert revision_coverage.deterministic_known_asks(asks, evidence_rows=rows) == asks
    assert revision_coverage.deterministic_unmet_asks(
        fixed, asks, evidence_rows=rows,
    ) == []
    assert repair_revision_quality(fixed, rows, "; ".join(asks)) == (fixed, [])

    (tmp_path / "full_paper.md").write_text(fixed)
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "citation_registry.json").write_text("{}")
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": "; ".join(asks), "required_revisions": asks,
    }))
    (tmp_path / "revision_coverage_gate.json").write_text(json.dumps({
        "passed": False, "ask_count": len(asks), "unmet_asks": asks,
    }))

    assert gate_report(tmp_path, revision_coverage, refreshed_by="test") == {
        "passed": True,
        "ask_count": len(asks),
        "unmet_asks": [],
        "refreshed_by": "test",
    }


def test_boilerplate_cleanup_preserves_neighboring_evidence() -> None:
    ask = "Delete the boilerplate recommendation-boundary paragraph."
    paper = (
        "## Abstract\n\nSmith 2027 [bundle:1] reported RR = 0.75. "
        "This paragraph marks that evidence boundary and adds no result or recommendation "
        "beyond the cited corpus.\n"
    )

    fixed, details = repair_revision_quality(paper, [], ask)

    assert details == ["fragmentary_prose"]
    assert "Smith 2027 [bundle:1] reported RR = 0.75." in fixed
    assert "This paragraph marks that evidence boundary" not in fixed


def test_boilerplate_cleanup_is_decimal_safe_and_idempotent() -> None:
    ask = "Delete public word floor boilerplate."
    paper = (
        "## Results\n\nSmith 2027 [bundle:1] reported RR = 0.75. "
        "The public word floor is preserved. Smith 2028 [bundle:2] reported p = 0.089.\n\n"
        "Because the public word floor is preserved by preprocessing, Smith 2029 remains traceable.\n"
    )

    fixed, details = repair_revision_quality(paper, [], ask)

    assert details == ["fragmentary_prose"]
    assert "RR = 0.75" in fixed and "p = 0.089" in fixed
    assert "0.75.089" not in fixed
    assert "Because the public word floor is preserved by preprocessing" in fixed
    assert repair_revision_quality(fixed, [], ask) == (fixed, [])


def test_boilerplate_cleanup_handles_doubled_whitespace_exact_sentence() -> None:
    ask = "Delete public word floor boilerplate."
    paper = (
        "## Results\n\nSmith 2027 reported RR = 0.75.  "
        "The public  word floor is preserved.  Smith 2028 reported p = 0.089.\n"
    )

    fixed, details = repair_revision_quality(paper, [], ask)

    assert details == ["fragmentary_prose"]
    assert "public  word floor" not in fixed.lower()
    assert "RR = 0.75. Smith 2028" in fixed
    assert repair_revision_quality(fixed, [], ask) == (fixed, [])


def test_evidence_pending_condition_preserves_traceable_non_p_statistic() -> None:
    ask = (
        "Make Smith 2027 evidence pending if no numerics can be cited, "
        "and remove unverified effect direction inferences."
    )
    rows = [{
        "citation_token": "Smith 2027",
        "effect_direction": "positive",
        "thesis_text": "The completed trial reported RR = 0.75.",
    }]
    paper = "## Results\n\nSmith 2027 direction=positive and reported RR = 0.75.\n"

    fixed, _ = repair_revision_quality(paper, rows, ask)

    assert "direction=positive" in fixed
    assert "RR = 0.75" in fixed
    assert "remains evidence-pending" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_named_direction_repair_accepts_coding_alignment_wording() -> None:
    ask = (
        "Reconcile the Opstad 2022 framing: explicitly state whether the 'positive' "
        "coding refers to the within-trial LTL change contrast (p = 0.02) or the "
        "secondary cardiovascular mortality finding, and align the Results, "
        "Cross-Domain Synthesis, and Evidence Snapshot rows accordingly."
    )
    rows = [{
        "citation_token": "Opstad 2022", "effect_direction": "positive",
        "directness": "direct",
    }]
    paper = (
        "## Results\n\nOpstad 2022 was coded as positive.\n\n"
        "## Cross-Domain Synthesis\n\nOpstad 2022 direction=positive.\n\n"
        "## Evidence Snapshot\n\nOpstad 2022 direction=positive.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["named_direction_reconciliation"]
    assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == [ask]
    assert revision_quality_proof_is_stated(fixed, ask, rows) is False


def test_named_direction_proof_accepts_explicit_endpoint_attribution() -> None:
    ask = (
        "Reconcile the Opstad 2022 framing: explicitly state whether the 'positive' "
        "coding refers to the within-trial LTL change contrast (p = 0.02) or the "
        "secondary cardiovascular mortality finding, and align the Results, "
        "Cross-Domain Synthesis, and Evidence Snapshot rows accordingly."
    )
    rows = [{
        "citation_token": "Opstad 2022", "effect_direction": "positive",
        "directness": "direct",
    }]
    paper = (
        "## Results\n\nThe 'positive' direction coding applied to Opstad 2022 refers "
        "specifically to the within-trial LTL change contrast at P = 0.02, not to "
        "the secondary cardiovascular mortality finding, which is a separate endpoint.\n\n"
        "## Cross-Domain Synthesis\n\nOpstad 2022 direction=positive.\n\n"
        "## Evidence Snapshot\n\nOpstad 2022 direction=positive.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_named_direction_proof_rejects_unrelated_attribution() -> None:
    ask = (
        "Reconcile the Opstad 2022 framing: explicitly state whether the 'positive' "
        "coding refers to the within-trial LTL change contrast (p = 0.02) or the "
        "secondary cardiovascular mortality finding, and align the Results, "
        "Cross-Domain Synthesis, and Evidence Snapshot rows accordingly."
    )
    rows = [{"citation_token": "Opstad 2022", "effect_direction": "positive"}]
    paper = (
        "## Results\n\nOpstad 2022 positive coding refers to source-level direction, "
        "not to table formatting.\n\n## Cross-Domain Synthesis\n\n"
        "Opstad 2022 direction=positive.\n\n## Evidence Snapshot\n\n"
        "Opstad 2022 direction=positive.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_named_direction_proof_accepts_rather_than_wording() -> None:
    ask = (
        "Reconcile the Opstad 2022 framing: explicitly state whether the 'positive' "
        "coding refers to the within-trial LTL change contrast or the secondary "
        "cardiovascular mortality finding, and align the Results accordingly."
    )
    rows = [{"citation_token": "Opstad 2022", "effect_direction": "positive"}]
    paper = (
        "## Results\n\nOpstad 2022 positive coding refers to the within-trial LTL "
        "change contrast rather than the secondary cardiovascular mortality finding.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_named_direction_proof_rejects_uncertain_or_opposing_attribution() -> None:
    ask = (
        "Reconcile the Opstad 2022 framing: explicitly state whether the 'positive' "
        "coding refers to the within-trial LTL change contrast or the secondary "
        "cardiovascular mortality finding, and align the Results accordingly."
    )
    rows = [{"citation_token": "Opstad 2022", "effect_direction": "positive"}]
    uncertain = (
        "## Results\n\nWhether Opstad 2022 positive coding refers to the within-trial "
        "LTL change contrast rather than the secondary cardiovascular mortality "
        "finding remains unresolved.\n"
    )
    opposing = (
        "## Results\n\nOpstad 2022 positive coding refers to the within-trial LTL "
        "change contrast rather than the secondary cardiovascular mortality finding.\n\n"
        "## Discussion\n\nOpstad 2022 positive coding refers to the secondary "
        "cardiovascular mortality finding rather than the within-trial LTL change contrast.\n"
    )

    assert revision_quality_proof_is_stated(uncertain, ask, rows) is False
    assert revision_quality_proof_is_stated(opposing, ask, rows) is False


def test_review_role_proof_ignores_other_reference_titles() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{
        "citation_token": "Su 2025", "directness": "review",
        "source_title": "A systematic review and meta-analysis",
    }]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT.\n\n## References\n\n"
        "- **Su 2025.** A systematic review and meta-analysis.\n"
        "- **Opstad 2022.** Sub-study of a randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_proof_rejects_following_pronoun_contradiction() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT. It is a primary randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_review_role_proof_rejects_results_bullet_contradiction() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT.\n\n- Su 2025 is a primary randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_review_role_proof_keeps_pronoun_with_immediate_other_source() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT. Opstad 2022 was evaluated separately. This study is a "
        "randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_proof_rejects_the_study_contradiction() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review). The study is a primary randomized "
        "clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_review_role_proof_accepts_review_containing_trial() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT. It includes a randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_proof_rejects_containment_then_trial_assertion() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review). Su 2025 is a review of multiple "
        "studies but remains a definitive clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_review_role_proof_does_not_adopt_another_named_source() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT. Su 2025 remains review-level, but Opstad 2022 remains a "
        "definitive clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_proof_splits_while_contrast_sources() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT. Su 2025 remains review-level while Opstad 2022 remains a "
        "definitive clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_proof_handles_terse_hyphenated_and_negated_roles() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    base = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review). "
    )

    assert revision_quality_proof_is_stated(
        base + "Su 2025: primary randomized clinical trial.\n", ask, rows,
    ) is False
    assert revision_quality_proof_is_stated(
        base + "Su 2025 is a meta-analysis containing a randomized clinical trial.\n", ask, rows,
    ) is True
    assert revision_quality_proof_is_stated(
        base + "Su 2025 is definitively not a clinical trial.\n", ask, rows,
    ) is True


def test_review_role_proof_ignores_same_source_reference_title() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    paper = (
        "## Results\n\nEvidence-type reconciliation: Su 2025 is retained as "
        "review-level evidence (directness=review) and is not counted as a direct "
        "clinical RCT.\n\n## References\n\n"
        "Su 2025. Systematic review of a randomized clinical trial.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_review_role_repair_changes_results_but_preserves_references() -> None:
    ask = (
        "Clarify Su 2025's role: directness=review and evidence_type=review are correct; "
        "ensure the Results prose does not conflate this meta-analysis of randomized "
        "trials with a primary clinical RCT."
    )
    rows = [{"citation_token": "Su 2025", "directness": "review"}]
    reference = "Su 2025. Systematic review of a randomized clinical trial."
    paper = f"## Results\n\n- Su 2025 is a primary randomized clinical trial.\n\n## References\n\n{reference}\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["evidence_role_reconciliation"]
    assert "- Su 2025 is a primary randomized clinical trial." not in fixed
    assert reference in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_gate_refresh_preserves_prior_verdict_for_unknown_asks(tmp_path: Path) -> None:
    known = (
        "Justify inclusion of Wick 2025 under the paper topic or flag it as a structural "
        "corpus limitation."
    )
    unknown = "Improve the Discussion's clinical interpretation."
    rows: list[dict[str, Any]] = [{
        "citation_token": "Wick 2025", "directness": "indirect",
        "effect_direction": "unclear",
    }]
    paper, _ = repair_revision_quality(
        "## Evidence Landscape\n\nBounded evidence.\n", rows, known,
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    (tmp_path / "researka_revision_request.json").write_text(json.dumps({
        "feedback": f"{known}; {unknown}", "required_revisions": [known, unknown],
    }))
    (tmp_path / "revision_coverage_gate.json").write_text(json.dumps({
        "passed": False, "ask_count": 2, "unmet_asks": [known],
    }))

    refreshed = gate_report(tmp_path, revision_coverage, refreshed_by="test")
    fingerprint = ask_fingerprint([known, unknown])

    assert refreshed == {
        "passed": True, "ask_count": 2, "unmet_asks": [],
        "ask_fingerprint": fingerprint, "refreshed_by": "test",
    }
    (tmp_path / "revision_coverage_gate.json").write_text(json.dumps({
        "passed": False, "ask_count": 2, "unmet_asks": [unknown],
        "ask_fingerprint": fingerprint,
    }))
    assert gate_report(tmp_path, revision_coverage, refreshed_by="test") == {
        "passed": False, "ask_count": 2, "unmet_asks": [unknown],
        "ask_fingerprint": fingerprint, "refreshed_by": "test",
    }


def test_gate_refresh_rejects_stale_unknown_ask_verdict(tmp_path: Path) -> None:
    known = (
        "Justify inclusion of Wick 2025 under the paper topic or flag it as a structural "
        "corpus limitation."
    )
    first_unknown = "Improve the Discussion's clinical interpretation."
    rows = [{"citation_token": "Wick 2025", "directness": "indirect"}]
    paper, _ = repair_revision_quality("## Evidence Landscape\n\nEvidence.\n", rows, known)
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": rows}))
    request = tmp_path / "researka_revision_request.json"
    request.write_text(json.dumps({"required_revisions": [known, first_unknown]}))

    assert gate_report(tmp_path, revision_coverage, refreshed_by="test") is None
    legacy = tmp_path / "revision_coverage_gate.json"
    legacy.write_text(json.dumps({
        "passed": True, "ask_count": 2, "unmet_asks": [],
    }))
    current = gate_report(tmp_path, revision_coverage, refreshed_by="test")
    assert current is not None and current["passed"] is True
    legacy.write_text(json.dumps(current))
    request.write_text(json.dumps({
        "required_revisions": [known, "Explain the Discussion's clinical boundary."],
    }))

    assert gate_report(tmp_path, revision_coverage, refreshed_by="test") is None


def test_named_statistic_repair_covers_findings_map_tables() -> None:
    ask = (
        "Clarify or correct the Stanfield 2026 'P < 0.001' statistic if it is not present "
        "in the bundle excerpt."
    )
    rows = [{
        "citation_token": "Stanfield 2026", "directness": "direct",
        "thesis_text": "The retained excerpt reports p = 0.089.",
    }]
    paper = (
        "## Evidence Landscape\n\n### Findings Map\n\n"
        "| Source | Finding |\n| --- | --- |\n"
        "| Stanfield 2026 | P < 0.001 |\n\n"
        "## Results\n\nBounded result.\n"
    )

    assert revision_quality_proof_is_stated(paper, ask, rows) is False
    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["named_statistic_reconciliation"]
    assert "P < 0.001" not in fixed
    assert "Stanfield 2026 [bundle:1] retains p = 0.089" in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True
    assert repair_revision_quality(fixed, rows, ask) == (fixed, [])


def test_named_statistic_repair_retains_traceable_effect_estimate() -> None:
    ask = (
        "Correct Smith 2025's effect estimate if it is not present in the source trace."
    )
    rows = [{
        "citation_token": "Smith 2025", "directness": "direct",
        "thesis_text": "The retained source excerpt reports HR = 0.72.",
    }]
    paper = "## Results\n\nSmith 2025 reported HR = 9.99.\n"

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["exact_stat_trace", "named_statistic_reconciliation"]
    assert "Smith 2025 [bundle:1] retains HR = 0.72" in fixed
    assert "HR = 9.99" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_topic_fit_repair_does_not_fabricate_boundary_for_direct_source() -> None:
    ask = (
        "Justify inclusion of Smith 2025 under the paper topic or flag it as a structural "
        "corpus limitation."
    )
    rows = [{"citation_token": "Smith 2025", "directness": "direct"}]
    paper = "## Evidence Landscape\n\nSmith 2025 directly studies the paper topic.\n"

    assert repair_revision_quality(paper, rows, ask) == (paper, [])
    assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == []
    assert revision_quality_proof_is_stated(paper, ask, rows) is True


def test_named_revision_matches_exact_citation_suffix() -> None:
    ask = (
        "Reconcile Phillips 2022b direction coding: keep negative and use consistent wording "
        "in Results."
    )
    rows = [
        {"citation_token": "Phillips 2022", "effect_direction": "positive"},
        {"citation_token": "Phillips 2022b", "effect_direction": "negative"},
    ]
    paper = "## Results\n\nPhillips 2022b showed a positive direction.\n"

    fixed, _ = repair_revision_quality(paper, rows, ask)

    assert "Phillips 2022b showed a negative direction" in fixed
    assert "Source-direction reconciliation (Phillips 2022b):" in fixed
    assert "Source-direction reconciliation (Phillips 2022):" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_direction_repair_reconciles_claim_wording_not_just_codes() -> None:
    ask = (
        "Reconcile Mandrioli 2023 direction coding: keep positive and use consistent wording "
        "in Results."
    )
    rows = [{"citation_token": "Mandrioli 2023", "effect_direction": "positive"}]
    paper = (
        "## Results\n\nMandrioli 2023 showed a null direction. "
        "Mandrioli 2023 supports a null effect.\n"
    )

    fixed, _ = repair_revision_quality(paper, rows, ask)

    assert "showed a positive direction" in fixed
    assert "supports a positive effect" in fixed
    assert "null direction" not in fixed and "null effect" not in fixed
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_p_value_and_effect_estimate_repairs_do_not_overwrite_each_other() -> None:
    feedback = (
        "Correct Smith 2025's P < 0.001 if it is not present in the source trace; "
        "Correct Smith 2025's effect estimate if it is not present in the source trace."
    )
    rows = [{
        "citation_token": "Smith 2025", "directness": "direct",
        "thesis_text": "The source excerpt reports p = 0.089 and HR = 0.72.",
    }]
    paper = "## Results\n\nSmith 2025 reported P < 0.001 and HR = 9.99.\n"

    fixed, _ = repair_revision_quality(paper, rows, feedback)
    asks = revision_coverage.revision_asks(feedback)

    assert "Source-statistic reconciliation (Smith 2025; p-value):" in fixed
    assert "Source-statistic reconciliation (Smith 2025; effect estimate):" in fixed
    assert "retains p = 0.089" in fixed and "retains HR = 0.72" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, asks, evidence_rows=rows) == []
    assert repair_revision_quality(fixed, rows, feedback) == (fixed, [])


def test_exact_stat_trace_cannot_borrow_a_different_source_value() -> None:
    ask = "For every exact statistic, attach the bundle token or use directional language."
    rows = [
        {"citation_token": "Smith 2025", "thesis_text": "The reported NNT was 10."},
        {"citation_token": "Jones 2024", "thesis_text": "The reported NNT was 1."},
    ]
    paper = "Smith 2025 [bundle:1] reported NNT = 1. Jones 2024 [bundle:2] provided context."

    assert revision_quality_proof_is_stated(paper, ask, rows) is False


def test_exact_stat_trace_accepts_et_al_citation_in_same_sentence() -> None:
    ask = "For every exact statistic, attach the bundle token or use directional language."
    rows = [{
        "receipt_id": "r1", "citation_token": "Smith et al. 2025",
        "source_year": 2025, "n_claims": 1, "thesis_text": "The reported HR was 0.72.",
    }]

    assert revision_quality_proof_is_stated(
        "Smith et al. 2025 [bundle:1] reported HR = 0.72.", ask, rows,
    ) is True


def test_exact_stat_trace_checks_bulleted_bold_prose() -> None:
    ask = "For every exact statistic, attach the bundle token or use directional language."
    rows = [{
        "receipt_id": "r1", "citation_token": "Smith 2025",
        "source_year": 2025, "n_claims": 1, "thesis_text": "The reported HR was 0.72.",
    }]
    paper = "- **Primary result:** Smith 2025 [bundle:2] reported HR = 999."

    assert revision_quality_proof_is_stated(paper, ask, rows) is False
    fixed, details = repair_revision_quality(paper, rows, ask)

    assert "Smith 2025 [bundle:1]" in fixed
    assert "HR = 999" not in fixed
    assert details == ["exact_stat_trace"]
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_exact_stat_trace_requires_matching_p_value_operator() -> None:
    ask = "For every exact statistic, attach the bundle token or use directional language."
    rows = [{"citation_token": "Smith 2025", "thesis_text": "The result was p < 0.05."}]

    assert revision_quality_proof_is_stated(
        "Smith 2025 [bundle:1] reported p < 0.05.", ask, rows,
    ) is True
    assert revision_quality_proof_is_stated(
        "Smith 2025 [bundle:1] reported p > 0.05.", ask, rows,
    ) is False


def test_exact_p_value_in_array_is_not_traceable_without_source_excerpt() -> None:
    ask = "Provide the exact bundle token supporting any exact p-value or effect estimate."
    rows = [{
        "citation_token": "Smith 2025", "p_values": ["p = 0.01"],
        "thesis_text": "The source excerpt reports a bounded directional finding.",
        "n_claims": 4,
    }]
    paper = "Smith 2025 [bundle:1] reported p = 0.01."

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert "p = 0.01" not in fixed
    assert details == ["exact_stat_trace"]
    assert manifest_row_finding(rows[0]).startswith("4 extracted claim")
    assert revision_quality_proof_is_stated(fixed, ask, rows) is True


def test_generic_representative_statistic_request_removes_unverified_token() -> None:
    ask = (
        "Verify each representative-statistic token in the Findings Map against "
        "the corresponding bundle excerpt; remove tokens that cannot be located "
        "in the supplied abstract."
    )
    rows = [{
        "citation_token": "Han 2020",
        "thesis_text": "The retained excerpt reports fatty liver index p = 0.002.",
    }]
    paper = (
        "### Findings Map\n\n"
        "| Outcome class | Source | Direction | Directness | Tier | Role | Finding |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Cardiometabolic | Han 2020 | direction=positive | directness=direct | "
        "A1 | outcome=Cardiometabolic; direction=positive | "
        "finding=representative statistic p = 0.001; source-level statistic reported |\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == [ask]
    assert "p = 0.001" not in fixed
    assert "exact statistic unavailable in retained source excerpt" in fixed
    assert "a source-reported estimate" not in fixed
    assert details == ["exact_stat_trace"]
    assert revision_coverage.deterministic_unmet_asks(
        fixed, [ask], evidence_rows=rows,
    ) == []


def test_major_claim_trace_revision_adds_requested_source_bound_claims() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "10/20 claims are exactly traceable (required 16)."
    )
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_title": f"Study {i}",
            "source_doi": f"10.1000/study.{i}",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 20 - i,
            "endpoints": [f"Outcome {i}"],
            "thesis_text": (
                f"Study {i} — source excerpts: Outcome {i} decreased by {i}% "
                "after treatment."
            ),
        }
        for i in range(1, 21)
    ]
    paper = (
        "## Results\n\n"
        "The retained evidence remains mixed across outcomes and populations."
        + "\n\n## Major Claim Trace\n\n"
        "- **Manuscript claim 1.** Stale duplicated claim.\n\n"
        "## References\n\n- Study1 2025.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["major_claim_trace"]
    assert "Study1 2025 [bundle:" in fixed
    assert "## Major Claim Trace" not in fixed
    assert fixed.count("[exact source: https://doi.org/") == 16
    assert "https://doi.org/10.1000/study.1" in fixed
    assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == [ask]
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []
    assert repair_revision_quality(fixed, rows, ask) == (fixed, [])


def test_quantified_trace_requires_source_owned_results_not_generic_locators() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "1/2 claims are exactly traceable (required 2)."
    )
    rows = [
        {
            "citation_token": "Study1 2025",
            "source_doi": "10.1000/result.1",
            "endpoints": ["body weight"],
            "thesis_text": "Source excerpts: Body weight decreased by 5% (p = 0.01).",
        },
        {
            "citation_token": "Study2 2025",
            "source_doi": "10.1000/method.2",
            "endpoints": ["body weight"],
            "thesis_text": "Source excerpts: We aimed to evaluate whether body weight changed.",
        },
    ]
    paper = (
        "## Results\n\n"
        "Study1 2025 [bundle:1] reports: Body weight decreased by 5% (p = 0.01) "
        "[exact source: https://doi.org/10.1000/result.1].\n\n"
        "Study2 2025 [bundle:2] reported a bounded manuscript finding "
        "[exact source: https://doi.org/10.1000/method.2]."
    )

    assert revision_claim_trace.major_claim_trace_capacity(ask, rows) == (1, 2)
    assert revision_claim_trace.major_claim_trace_is_stated(paper, ask, rows) is False
    assert revision_claim_trace.repair_major_claim_trace(paper, ask, rows) == (paper, 0)
    overclaim = paper.replace(
        "Body weight decreased by 5% (p = 0.01)",
        "Body weight decreased by 5% (p = 0.01), proving a mortality benefit",
    )
    assert revision_claim_trace.major_claim_trace_is_stated(overclaim, ask, rows) is False
    assert revision_claim_trace.major_claim_trace_capacity(
        "Correct direction coding in 1/2 claims (required 2).", rows,
    ) is None


def test_quantified_trace_dedupes_existing_results_before_repairing() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "1/3 claims are exactly traceable (required 2)."
    )
    findings = (
        (["body weight", "LDL cholesterol"], "LDL cholesterol decreased by 10% (p = 0.02). | Body weight decreased by 5% (p = 0.01)."),
        (["body weight"], "Body weight decreased by 5% (p = 0.01)."),
        (["body weight", "blood pressure"], "Body weight decreased by 5% (p = 0.01). | Blood pressure decreased by 6% (p = 0.03)."),
    )
    rows = [{
        "citation_token": f"Study{i} 2025",
        "source_doi": f"10.1000/dedupe.{i}",
        "endpoints": endpoints,
        "thesis_text": f"Source excerpts: {finding}",
    } for i, (endpoints, finding) in enumerate(findings, 1)]
    paper = (
        "## Results\n\n"
        + "\n\n".join(
            f"Study{i} 2025 [bundle:{i}] reports: Body weight decreased by 5% "
            f"(p = 0.01) [exact source: https://doi.org/10.1000/dedupe.{i}]."
            for i in (1, 2)
        )
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "Blood pressure decreased by 6%" in fixed
    assert "LDL cholesterol decreased by 10%" not in fixed
    assert revision_claim_trace.major_claim_trace_capacity(ask, rows) == (3, 2)
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_adds_only_source_owned_findings_when_prose_is_generic() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "5/20 claims are exactly traceable (required 16)."
    )
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
            "directness": "direct",
            "evidence_tier": "A1",
            "n_claims": 21 - i,
            "endpoints": [f"Outcome {i}"],
            "thesis_text": (
                f"Source excerpts: We aimed to evaluate intervention {i}. | "
                f"Outcome {i} decreased by {i}% after treatment."
            ),
        }
        for i in range(1, 21)
    ]
    paper = (
        "## Results\n\n"
        "The retained evidence remains mixed across outcomes and populations.\n"
    )

    fixed, details = repair_revision_quality(paper, rows, ask)

    assert details == ["major_claim_trace"]
    assert fixed.count("[exact source: https://doi.org/") == 16
    assert "Study1 2025 [bundle:1] reports: Outcome 1 decreased by 1%" in fixed
    assert "Study1 2025 [bundle:1] reports: Outcome 2 decreased" not in fixed
    assert "We aimed to evaluate" not in fixed
    assert revision_coverage.deterministic_unmet_asks(
        fixed, [ask], evidence_rows=rows,
    ) == []
    assert repair_revision_quality(fixed, rows, ask) == (fixed, [])


def test_major_claim_trace_is_idempotent_with_duplicate_citation_tokens() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    rows = [
        {
            "citation_token": "Smith 2025",
            "source_doi": f"10.1000/smith.{i}",
            "endpoints": [f"Outcome {i}"],
            "thesis_text": f"Source excerpts: Outcome {i} decreased by {i}% after treatment.",
        }
        for i in range(1, 3)
    ]
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "Outcome 1 decreased" in fixed
    assert "Outcome 2 decreased" in fixed
    assert fixed.count("[bundle:1]") == 1
    assert fixed.count("[bundle:2]") == 1
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_rejects_unverifiable_or_procedural_spans() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."
    cases: list[tuple[dict[str, object], list[str], str]] = [
        ({}, ["body weight"], "Body weight decreased by 5%."),
        ({"source_doi": "10.1000/method"}, ["body weight"], "Participants were assigned to higher-dose and lower-dose groups to examine the effect of treatment."),
        ({"source_doi": "10.1000/baseline"}, ["body weight"], "Baseline characteristics showed 120 participants with a mean age of 52 years."),
        ({"source_doi": "10.1000/search"}, ["sensitivity"], "The search increased sensitivity or specificity before screening."),
        ({"source_doi": "10.1000/index"}, ["body mass index"], "Index selection procedure increased candidate coverage."),
        ({"source_doi": "10.1000/sample"}, ["body mass index"], "Sample size increased significantly after recruitment."),
        ({"source_doi": "10.1000/frequency"}, ["body mass index"], "Body mass index measurement frequency increased from monthly to weekly."),
        ({"source_doi": "10.1000/clause"}, ["body mass index"], "Body mass index was measured, while visit frequency increased by 50%."),
        ({"source_doi": "10.1000/imbalance"}, ["body mass index"], "At baseline, body mass index differed between groups (p = 0.03)."),
        ({"source_doi": "10.1000/age", "outcome_class": "cardiometabolic"}, ["body weight"], "Mean age differed by 5 years between groups (p = 0.03)."),
        ({"source_doi": "10.1000/unrelated", "outcome_class": "cardiometabolic"}, ["body weight"], "Sleep duration differed by 5% between groups (p = 0.03)."),
        ({"source_doi": "10.1000/status", "outcome_class": "deficiency_prevalence"}, ["vitamin D"], "Employment status improved by 10% (p = 0.03)."),
        ({"source_doi": "10.1000/chronic", "outcome_class": "safety_comorbidity"}, ["kidney function"], "Chronic exercise adherence improved by 12% (p = 0.03)."),
        ({"source_doi": "10.1000/dose"}, ["body weight"], "Participants with higher body weight received a 10% lower dose."),
        ({"source_doi": "10.1000/dose-control"}, ["glycemic control"], "Participants with worse glycemic control received a 10% larger dose."),
        ({"source_doi": "10.1000/titration", "outcome_class": "cardiometabolic"}, ["insulin"], "Insulin dose decreased by 20% during titration."),
        ({"source_doi": "10.1000/doses", "outcome_class": "cardiometabolic"}, ["insulin"], "Insulin doses decreased by 20%."),
        ({"source_doi": "10.1000/dosages", "outcome_class": "cardiometabolic"}, ["insulin"], "Insulin dosages decreased by 20%."),
        ({"source_doi": "10.1000/dosing", "outcome_class": "cardiometabolic"}, ["insulin"], "Insulin dosing decreased by 20%."),
        ({"source_doi": "10.1000/unverified", "spar_verdict": "reject_critical"}, [], "Maximal heart rate was unaffected."),
        ({"source_doi": "10.1000/truncated"}, ["body weight"], "Body weight decreased by 8% in participants…"),
        ({"source_doi": "10.1000/definition"}, ["blood pressure"], "Response was defined as a blood-pressure decrease of at least 10%."),
        ({"source_doi": "10.1000/fragment", "spar_verdict": "accept_clean", "n_failed_traces": 0}, [], "Whereas leukocytes remained elevated."),
        ({"source_doi": "10.1000/secondhand", "spar_verdict": "accept_clean", "n_failed_traces": 0}, [], "Meta-analyses have indicated a significant improvement."),
    ]
    for extra, endpoints, text in cases:
        row = {
            "citation_token": "Smith 2025",
            "endpoints": endpoints,
            "thesis_text": f"Source excerpts: {text}",
            **extra,
        }
        fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, [row])
        assert (fixed, changed) == (paper, 0), text
        assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, [row]) is False


def test_major_claim_trace_rejects_numeric_methods_and_aim_clauses() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."
    clauses = [
        "The quantitative analysis was performed using standardized mean differences (SMD = 0.20) to compare outcomes.",
        "We aimed to evaluate whether body weight decreased by 5% (p = 0.03).",
    ]

    for index, clause in enumerate(clauses, 1):
        row = {
            "citation_token": f"Study{index} 2025",
            "source_doi": f"10.1000/method.{index}",
            "endpoints": ["body weight"],
            "thesis_text": f"Source excerpts: {clause}",
        }
        assert revision_claim_trace.repair_major_claim_trace(paper, ask, [row]) == (paper, 0)


def test_major_claim_trace_dedupes_substantive_findings_and_source_labels() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    duplicate_rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/duplicate.{i}",
            "endpoints": ["body weight"],
            "thesis_text": "Source excerpts: Body weight decreased by 5% after treatment.",
        }
        for i in range(1, 3)
    ]
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."
    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, duplicate_rows)
    assert changed == 1
    assert fixed.count("Body weight decreased by 5%") == 1
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, duplicate_rows) is False

    cited_rows = [
        {
            "citation_token": "Smith 2025",
            "source_doi": "10.1000/smith.duplicate",
            "endpoints": ["body weight"],
            "thesis_text": "Source excerpts: Body weight decreased by 5%.",
        },
        {
            "citation_token": "Smith 2025a",
            "source_doi": "10.1000/jones.duplicate",
            "endpoints": ["body weight"],
            "thesis_text": "Source excerpts: Body weight decreased by 5%.",
        },
    ]
    cited = "## Results\n\nBody weight decreased by 5% (Smith 2025; Smith 2025a)."
    fixed, changed = revision_claim_trace.repair_major_claim_trace(cited, ask, cited_rows)
    assert changed == 1
    assert fixed.count("Body weight decreased by 5%") == 1
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, cited_rows) is False


def test_major_claim_trace_dedupes_source_reporting_wrapper() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    row = {
        "citation_token": "Study1 2025",
        "source_doi": "10.1000/wrapper.1",
        "endpoints": ["body weight"],
        "thesis_text": "Source excerpts: Body weight decreased by 5% (p = 0.01).",
    }
    paper = (
        "## Results\n\nStudy1 2025 [bundle:1] reported that Body weight decreased "
        "by 5% (p = 0.01) [exact source: https://doi.org/10.1000/wrapper.1]."
    )

    fixed, _changed = revision_claim_trace.repair_major_claim_trace(paper, ask, [row])

    assert "### Source-Traced Findings" not in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, [row]) is False


def test_major_claim_trace_skips_wrapped_duplicate_and_adds_distinct_result() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    row = {
        "citation_token": "Study1 2025",
        "source_doi": "10.1000/wrapper.2",
        "endpoints": ["body weight", "LDL cholesterol"],
        "thesis_text": (
            "Source excerpts: Study1 2025 reported that Body weight decreased by 5% (p = 0.01). "
            "LDL cholesterol decreased by 10% (p = 0.02)."
        ),
    }
    paper = (
        "## Results\n\nStudy1 2025 [bundle:1] reported that Body weight decreased "
        "by 5% (p = 0.01) [exact source: https://doi.org/10.1000/wrapper.2]."
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, [row])

    assert changed == 1
    assert fixed.count("Body weight decreased by 5%") == 1
    assert "LDL cholesterol decreased by 10%" in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, [row]) is True


def test_major_claim_trace_accepts_quantified_endpoint_results() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."
    cases = [
        ("body weight", "Body weight decreased by 5%. | The protocol dose increased from 1 mg to 2 mg at weeks 2, 4, and 8.", "Body weight decreased by 5%"),
        ("body weight", "In the randomized trial, body weight decreased by 5%.", "randomized trial, body weight decreased by 5%"),
        ("body mass index", "BMI decreased significantly (p < 0.05).", "BMI decreased significantly (p < 0.05)"),
        ("mortality risk", "Mortality risk decreased (OR 0.72).", "Mortality risk decreased (OR 0.72)"),
        ("mortality risk", "Mortality risk decreased (Odds ratio 0.72).", "Mortality risk decreased (Odds ratio 0.72)"),
        ("low-density lipoprotein cholesterol", "LDL-C decreased by 12%.", "LDL-C decreased by 12%"),
        ("muscle pain", "Muscle pain was significantly better than placebo (p < 0.05).", "significantly better than placebo"),
    ]
    for index, (endpoint, text, expected) in enumerate(cases, 1):
        rows = [{
            "citation_token": f"Study{index} 2025",
            "source_doi": f"10.1000/result.{index}",
            "endpoints": [endpoint],
            "thesis_text": f"Source excerpts: {text}",
        }]
        fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)
        assert changed == 1
        assert expected in fixed
        assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True
        assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_accepts_quantified_outcome_class_alias() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    row = {
        "citation_token": "Study1 2025",
        "source_doi": "10.1000/inflammation.1",
        "outcome_class": "immune",
        "endpoints": ["inflammation"],
        "thesis_text": "Source excerpts: C-reactive protein decreased by 15% (p = 0.01).",
    }
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, [row])

    assert changed == 1
    assert "C-reactive protein decreased by 15%" in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, [row]) is True


def test_major_claim_trace_uses_multiple_grounded_results_after_source_diversity() -> None:
    ask = "Add exact source tokens to major claims; required 4."
    rows = [
        {
            "citation_token": "Study1 2025",
            "source_doi": "10.1000/study.1",
            "endpoints": ["body weight", "LDL cholesterol"],
            "thesis_text": (
                "Source excerpts: Body weight decreased by 5% (p = 0.01). "
                "LDL cholesterol decreased by 10% (p = 0.02)."
            ),
        },
        {
            "citation_token": "Study2 2025",
            "source_doi": "10.1000/study.2",
            "endpoints": ["blood pressure", "fasting glucose"],
            "thesis_text": (
                "Source excerpts: Blood pressure decreased by 6% (p = 0.03). "
                "Fasting glucose decreased by 8% (p = 0.04)."
            ),
        },
    ]
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert fixed.count("[exact source: https://doi.org/") == 4
    assert fixed.index("Blood pressure decreased") < fixed.index("LDL cholesterol decreased")
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_repairs_diverse_source_result_language() -> None:
    ask = "Add exact source tokens to major claims; required 8."
    findings = (
        ("body mass index", "BMI reduction was -1.01 kg/m 2 without lean mass loss."),
        ("body weight", "Body weight decreased from 86.65 kg to 82.94 kg."),
        ("blood glucose", "The intervention achieved better glycemic control compared with metformin."),
        ("body weight", "The diet showed a reduction in body weight (mean difference -1.69 kg)."),
        ("blood pressure", "SBP significantly decreased by -0.31 mmHg."),
        ("body mass index", "Participants showed significant decreases in BMI after 24 weeks."),
        ("insulin sensitivity", "The intervention was associated with improved insulin sensitivity."),
        ("inflammation", "C-reactive protein decreased by 15% (p = 0.01)."),
    )
    rows = [{
        "citation_token": f"Study{i} 2025",
        "source_doi": f"10.1000/diverse.{i}",
        "outcome_class": "immune" if endpoint == "inflammation" else "cardiometabolic",
        "endpoints": [endpoint],
        "directness": "direct" if i % 2 else "review",
        "evidence_tier": "A1" if i % 2 else "B1",
        "thesis_text": f"Source excerpts: {finding}",
    } for i, (endpoint, finding) in enumerate(findings, 1)]
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert fixed.count("[exact source: https://doi.org/") == 8
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_allows_quantified_direct_primary_outcome_fallback() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    row = {
        "citation_token": "Study1 2025",
        "source_doi": "10.1000/direct.1",
        "outcome_class": "cardiometabolic",
        "endpoints": ["body mass index"],
        "directness": "direct",
        "evidence_tier": "A1",
        "thesis_text": "Source excerpts: Liver stiffness significantly decreased (p = 0.01).",
    }
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, [row])

    assert changed == 1
    assert "Liver stiffness significantly decreased" in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, [row]) is True


def test_major_claim_trace_uses_verified_results_when_endpoint_metadata_is_sparse() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "0/3 claims are exactly traceable (required 3)."
    )
    rows = [
        {
            "citation_token": "Study1 2025",
            "source_doi": "10.1000/verified.1",
            "spar_verdict": "accept_clean",
            "n_failed_traces": 0,
            "endpoints": ["inflammation"],
            "thesis_text": (
                "Source excerpts: Acute exercise elevated CRP by 7.7% "
                "[95% CI, 5.5-10.0]."
            ),
        },
        {
            "citation_token": "Study2 2025",
            "source_doi": "10.1000/verified.2",
            "spar_verdict": "accept_clean",
            "n_failed_traces": 0,
            "endpoints": [],
            "thesis_text": "Source excerpts: Maximal heart rate was unaffected.",
        },
        {
            "citation_token": "Study3 2025",
            "source_doi": "10.1000/verified.3",
            "spar_verdict": "accept_caveated",
            "n_failed_traces": 0,
            "endpoints": [],
            "thesis_text": (
                "Source excerpts: The exercise group had a greater learning effect "
                "than control (p = 0.02)."
            ),
        },
    ]
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert revision_claim_trace.major_claim_trace_capacity(ask, rows) == (3, 3)
    assert fixed.count("[exact source: https://doi.org/") == 3
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True


def test_major_claim_trace_rejects_protocol_recommendation_and_incomplete_comparison() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    invalid: tuple[dict[str, object], ...] = (
        {
            "directness": "protocol",
            "evidence_tier": "D1",
            "thesis_text": "Source excerpts: Primary outcomes selected were differences in BMI after 8 weeks.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: A 5-10% weight loss is recommended for blood glucose regulation.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: Hepatic steatosis significantly decreased (29.6% vs.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: Mean age is increased by 20% under the weighting coefficients.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: We examined whether BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: Baseline BMI increased from 24 to 26.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: Baseline body mass index increased from 24 to 26.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: Baseline BMI differed by 20%.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: The objective was to determine whether BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["liver stiffness"],
            "thesis_text": "Source excerpts: Liver enzyme levels decreased by 20%.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: To determine whether BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: The study was designed to determine whether BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: We hypothesized that BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["body mass index"],
            "thesis_text": "Source excerpts: Insulin assay sensitivity increased by 20% during validation.",
        },
        {
            "directness": "review",
            "evidence_tier": "B1",
            "endpoints": [],
            "thesis_text": "Source excerpts: Insulin was associated with improved outcomes.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: The hypothesis was that BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "thesis_text": "Source excerpts: We tested the hypothesis that BMI was associated with treatment assignment.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["body mass index"],
            "thesis_text": "Source excerpts: Insulin calibration accuracy increased by 20%.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["body mass index"],
            "thesis_text": "Source excerpts: Participants with lower BMI were assigned to the 20% calorie-restriction arm.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["body mass index"],
            "thesis_text": "Source excerpts: Lower BMI was used to allocate 20% of participants to intervention.",
        },
        {
            "directness": "direct",
            "evidence_tier": "A1",
            "endpoints": ["body mass index"],
            "thesis_text": "Source excerpts: Lower BMI was used to assign 20% of participants to intervention.",
        },
    )
    paper = "## Results\n\nThe retained evidence remains uncertain and incomplete."

    for i, row in enumerate(invalid, 1):
        row.update({
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/invalid.{i}",
            "outcome_class": "cardiometabolic",
            "endpoints": row.get("endpoints", ["body mass index", "blood glucose", "hepatic steatosis"]),
        })
        assert revision_claim_trace.repair_major_claim_trace(paper, ask, [row]) == (paper, 0)


def test_major_claim_trace_uses_distinct_sources_before_repeats() -> None:
    ask = "Add exact source tokens to major claims; required 3."
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
            "thesis_text": f"Source excerpts: Retained evidence span {i}.",
        }
        for i in range(1, 4)
    ]
    paper = (
        "## Results\n\n"
        "Study1 2025 reported bounded manuscript finding one.\n\n"
        "Study1 2025 reported bounded manuscript finding two.\n\n"
        "Study1 2025 reported bounded manuscript finding three.\n\n"
        "Study2 2025 reported bounded manuscript finding four.\n\n"
        "Study3 2025 reported bounded manuscript finding five.\n"
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "## Major Claim Trace" not in fixed
    assert fixed.count("https://doi.org/10.1000/study.1") == 3
    assert fixed.count("https://doi.org/10.1000/study.2") == 1
    assert fixed.count("https://doi.org/10.1000/study.3") == 1


def test_major_claim_trace_traces_every_named_source_without_inventing_anchors() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "17/30 claims are exactly traceable (required 24)."
    )
    rows = [
        {
            "citation_token": "Study1 2025",
            "source_doi": "10.1000/study.1",
            "outcome_class": "frailty",
            "directness": "direct",
        },
        {
            "citation_token": "Study2 2025",
            "source_doi": "10.1000/study.2",
            "outcome_class": "longevity",
            "directness": "indirect",
        },
    ]
    paper = (
        "## Abstract\n\n"
        "Direct frailty evidence remains bounded and does not establish broad clinical benefit.\n\n"
        "The review workflow retained a complete audit trail for every included record.\n\n"
        "Frailty guidance remains bounded pending stronger trials (Guideline 2024).\n\n"
        "## Results\n\n"
        "Study1 2025 and Study2 2025 produced different outcome signals.\n\n"
        "## Discussion\n\n"
        "The retained evidence supports only a bounded interpretation pending stronger trials. "
        "Broader clinical claims remain unsupported by the current source record.\n\n"
        "## Conclusion\n\n"
        "The practical interpretation remains bounded by the available source record.\n"
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    result_claim = next(line for line in fixed.splitlines() if "different outcome signals" in line)
    assert "Study1 2025 [bundle:1]" in result_claim
    assert "Study2 2025 [bundle:2]" in result_claim
    assert "https://doi.org/10.1000/study.1" in result_claim
    assert "https://doi.org/10.1000/study.2" in result_claim
    assert "(evidence anchor:" not in fixed
    assert "Direct frailty evidence remains bounded" in fixed
    assert "Direct frailty evidence remains bounded" not in result_claim
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_handles_quoted_sentences_and_parenthesized_dois() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    rows = [
        {"citation_token": "Study1 2025", "source_doi": "10.1002/(SICI)123"},
        {"citation_token": "Study2 2025", "source_doi": "10.1000/study.2"},
    ]
    paper = (
        "## Results\n\n"
        '"Study1 2025 reported the first bounded outcome '
        "(evidence anchor: [Study1 2025](https://doi.org/10.1002/(SICI)123) [bundle:1]).\" "
        "**Study2 2025 reported the second bounded outcome.**\n"
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "https://doi.org/10.1002/(SICI)123" in fixed
    assert "https://doi.org/10.1000/study.2" in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)

    prefix_only = (
        "## Results\n\n"
        "Study1 2025 [bundle:1] reported an outcome "
        "[exact source: https://doi.org/10.1002/(SICI)1234].\n"
    )
    assert revision_claim_trace.major_claim_trace_is_stated(prefix_only, ask, rows) is False


def test_major_claim_trace_completes_partially_traced_claims() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
        }
        for i in range(1, 4)
    ]
    paper = (
        "## Results\n\n"
        "Study1 2025 [bundle:1] reported outcome one "
        "[exact source: https://doi.org/10.1000/study.1].\n\n"
        "Study2 2025 [bundle:2] reported outcome two "
        "[exact source: https://doi.org/10.1000/study.2].\n\n"
        "Study3 2025 [bundle:3] reported outcome three.\n"
    )

    assert revision_claim_trace.major_claim_trace_is_stated(paper, ask, rows) is True

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "outcome three [exact source: https://doi.org/10.1000/study.3]" in fixed
    assert revision_claim_trace.repair_major_claim_trace(fixed, ask, rows) == (fixed, 0)


def test_major_claim_trace_does_not_count_source_role_boilerplate() -> None:
    ask = "Add exact source tokens to major claims; required 3."
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
            "directness": "indirect",
            "evidence_tier": "B2",
        }
        for i in range(1, 4)
    ]
    paper = (
        "## Results\n\n"
        "Evidence-type reconciliation: Study1 2025 [bundle:1] is indirect B2 evidence "
        "and is down-weighted for causal inference "
        "[exact source: https://doi.org/10.1000/study.1]. "
        "Study2 2025 [bundle:2] is retained as animal/preclinical contextual evidence "
        "[exact source: https://doi.org/10.1000/study.2]. "
        "Study3 2025 [bundle:3] is retained as review-level evidence "
        "[exact source: https://doi.org/10.1000/study.3].\n\n"
        "Study1 2025 [bundle:1] reported the first bounded outcome.\n\n"
        "Study2 2025 [bundle:2] reported the second bounded outcome.\n\n"
        "Study3 2025 [bundle:3] reported the third bounded outcome.\n"
    )

    assert revision_claim_trace.major_claim_trace_is_stated(paper, ask, rows) is False

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "first bounded outcome [exact source: https://doi.org/10.1000/study.1]" in fixed
    assert "second bounded outcome [exact source: https://doi.org/10.1000/study.2]" in fixed
    assert "third bounded outcome [exact source: https://doi.org/10.1000/study.3]" in fixed
    assert revision_claim_trace.major_claim_trace_is_stated(fixed, ask, rows) is True


def test_major_claim_trace_proof_rejects_unknown_bundle_and_wrong_span() -> None:
    ask = (
        "Add exact source tokens, DOI/PMID links, or evidence spans to major claims; "
        "required 2."
    )
    rows = [
        {
            "citation_token": f"Study{i} 2025",
            "source_doi": f"10.1000/study.{i}",
            "thesis_text": f"Source excerpts: Retained evidence span {i}.",
        }
        for i in range(1, 3)
    ]
    manuscript = (
        "## Results\n\n"
        "Study1 2025 [bundle:1] reported bounded manuscript finding 1.\n\n"
        "Study2 2025 [bundle:2] reported bounded manuscript finding 2.\n\n"
    )
    forged = manuscript + (
        "## Major Claim Trace\n\n"
        "- **Manuscript claim 1.** Study1 2025 [bundle:101] reported bounded manuscript "
        "finding 1. **Supporting source:** Study1 2025 [bundle:101] "
        "https://doi.org/10.1000/study.1 **Evidence span:** Retained evidence span 1.\n"
        "- **Manuscript claim 2.** Study2 2025 [bundle:102] reported bounded manuscript "
        "finding 2. **Supporting source:** Study2 2025 [bundle:102] "
        "https://doi.org/10.1000/study.2 **Evidence span:** Retained evidence span 2.\n"
    )
    mismatched = manuscript + (
        "## Major Claim Trace\n\n"
        "- **Manuscript claim 1.** Study1 2025 [bundle:1] reported bounded manuscript "
        "finding 1. **Supporting source:** Study1 2025 [bundle:1] "
        "https://doi.org/10.1000/study.1 **Evidence span:** Wrong evidence.\n"
        "- **Manuscript claim 2.** Study2 2025 [bundle:2] reported bounded manuscript "
        "finding 2. **Supporting source:** Study2 2025 [bundle:2] "
        "https://doi.org/10.1000/study.2 **Evidence span:** Wrong evidence.\n"
    )

    assert revision_quality_proof_is_stated(forged, ask, rows) is False
    assert revision_quality_proof_is_stated(mismatched, ask, rows) is False

    short, _ = repair_revision_quality(manuscript, rows, ask.replace("required 2", "required 16"))
    assert revision_quality_proof_is_stated(
        short, ask.replace("required 2", "required 16"), rows,
    ) is False


def test_major_claim_trace_proof_rejects_fragments_of_one_claim() -> None:
    ask = "Add exact source tokens to major claims; required 2."
    rows = [{
        "citation_token": "Study1 2025",
        "source_doi": "10.1000/study.1",
        "thesis_text": "Source excerpts: Retained evidence span 1.",
    }]
    manuscript = (
        "## Results\n\nA bounded result from Study1 2025 [bundle:1] "
        "showed improvement on the measured endpoint.\n\n"
    )
    support = (
        "**Supporting source:** Study1 2025 [bundle:1] "
        "https://doi.org/10.1000/study.1 "
        "**Evidence span:** Retained evidence span 1."
    )
    forged = manuscript + (
        "## Major Claim Trace\n\n"
        "- **Manuscript claim 1.** A bounded result from Study1 2025 [bundle:1] "
        f"showed improvement on the measured endpoint. {support}\n"
        "- **Manuscript claim 2.** Study1 2025 [bundle:1] "
        f"showed improvement on the measured endpoint. {support}\n"
    )

    assert revision_quality_proof_is_stated(forged, ask, rows) is False


def test_major_claim_trace_span_drops_only_unmatched_parentheses() -> None:
    row = {
        "thesis_text": (
            "Source excerpts: Balanced (n=20). "
            + "x" * 290
            + " (truncated detail"
        ),
    }

    span = revision_claim_trace._evidence_span(row)

    assert "(n=20)" in span
    assert span.count("(") == span.count(")")
    assert span.endswith("[excerpt truncated].")
    assert len(span) <= 320


def test_major_claim_trace_completes_upstream_truncated_span() -> None:
    span = revision_claim_trace._evidence_span({
        "thesis_text": "Source excerpts: Retained evidence ends mid-sentenc\u2026",
    })

    assert span == "Retained evidence ends mid-sentenc [excerpt truncated]."


def test_major_claim_trace_does_not_split_at_vs_inside_parenthetical() -> None:
    ask = "Add exact source tokens to major claims; required 1."
    rows = [
        {
            "citation_token": "Study1 2025",
            "source_doi": "10.1000/study.1",
            "thesis_text": "Source excerpts: Direct evidence span one.",
        },
        {
            "citation_token": "Study2 2025",
            "source_doi": "10.1000/study.2",
            "thesis_text": "Source excerpts: Direct evidence span two.",
        },
    ]
    paper = (
        "## Results\n\n"
        "The direction differed (Study1 2025 positive vs. Study2 2025 null) "
        "on the prespecified endpoint.\n"
    )

    fixed, changed = revision_claim_trace.repair_major_claim_trace(paper, ask, rows)

    assert changed == 1
    assert "## Major Claim Trace" not in fixed
    assert "positive vs. Study2 2025" in fixed
    assert fixed.count("(") == fixed.count(")")
    assert "[exact source: https://doi.org/10.1000/study.1]" in fixed


def test_fragment_repair_preserves_valid_colon_lead_in() -> None:
    ask = "Complete the fragmentary prose sections with an ending mid-sentence."
    paper = "## Results\n\nThe retained evidence is summarized in the following table:\n\n| Source | Finding |"

    fixed, details = repair_revision_quality(paper, [], ask)

    assert fixed == paper
    assert details == []
    assert revision_quality_proof_is_stated(fixed, ask, []) is True


def test_generic_fragment_request_repairs_unnamed_trailing_fragment() -> None:
    ask = "Complete all prose sections ending mid-sentence."
    paper = "## Results\n\nThis retained evidence paragraph ends without a completed boundary"

    fixed, details = repair_revision_quality(paper, [], ask)

    assert "This subsection remains bounded" in fixed
    assert details == ["fragmentary_prose"]
    assert revision_quality_proof_is_stated(fixed, ask, []) is True


def test_garbled_named_fragment_request_is_deterministically_satisfied() -> None:
    ask = (
        "Repair the two garbled section fragments (the 'He Longevity Outcomes' "
        "and 'The Safety and Comorbidity Outcomes' headers/sentences) so the "
        "Results flow without broken mid-sentence strings."
    )
    paper = (
        "## Results\n\n"
        "### Longevity Outcomes\n\nThe retained evidence is bounded and complete.\n\n"
        "### Safety and Comorbidity Outcomes\n\nThe safety evidence is bounded and complete.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(
        paper.replace("### Longevity Outcomes", "### He Longevity Outcomes"),
        [ask],
    ) == [ask]


def test_generic_fragment_request_preserves_complete_markdown_link() -> None:
    ask = "Complete all prose sections ending mid-sentence."
    paper = (
        "## Results\n\nThe complete retained source record remains available in the "
        "[public registry](https://example.test/source)"
    )

    fixed, details = repair_revision_quality(paper, [], ask)

    assert fixed.endswith("[public registry](https://example.test/source).")
    assert "This subsection remains bounded" not in fixed
    assert details == ["fragmentary_prose"]
    assert revision_quality_proof_is_stated(fixed, ask, []) is True


def test_fragment_repair_removes_quoted_garble_from_heading() -> None:
    ask = 'Remove the garbled section fragment ("Malformed heading tail") from the Results.'
    paper = "## Results Malformed heading tail\n\nComplete result paragraph.\n"

    fixed, changed = revision_coverage.repair_fragment_headings(paper, ask)

    assert fixed.startswith("## Results\n")
    assert changed == 1
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_internal_duplication_repair_converges_and_is_idempotent() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    repeated = (
        "The current corpus is mixed and hypothesis-generating, with evidence distribution statistics "
        "showing indirect and review evidence rather than settled clinical translation."
    )
    paper = f"## Gaps Identified\n\n{repeated}\n\n## Discussion\n\n{repeated}\n"

    fixed, changed = revision_coverage.repair_internal_duplication(paper, ask)

    assert changed == 1
    assert fixed.count(repeated) == 1
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert revision_coverage.repair_internal_duplication(fixed, ask) == (fixed, 0)


def test_detects_reviewer_request_to_replace_unclear_direction_codes() -> None:
    feedback = (
        "Integrate the positive/null MACE signals from the named studies rather "
        "than leaving direction coded 'unclear' without explanation."
    )

    assert revision_coverage.asks_effect_direction_reconciliation(feedback) is True


def test_receipt_contract_fields_are_authorized_only_by_explicit_recode_asks() -> None:
    assert revision_coverage.authorized_receipt_contract_fields(
        "Reconcile outcome-class assignments. Move one source into Mechanism.",
    ) == {"outcome_class"}
    assert revision_coverage.authorized_receipt_contract_fields(
        "Recode Harris 2008 as a primary RCT, not review; correct direct/indirect and proper tier.",
    ) == {"directness", "evidence_tier"}
    assert revision_coverage.authorized_receipt_contract_fields(
        "Improve the discussion and conclusion.",
    ) == set()


def test_receipt_contract_authorization_is_limited_to_named_sources() -> None:
    feedback = (
        "Move Schmid 2021 into the Mechanism outcome class and Dorneles 2020 "
        "into Immune/Inflammation; Recode Harris 2008 as a primary RCT, not "
        "review; correct directness and tier. The Harris 2008 effect direction "
        "is inconsistent with the underlying source."
    )
    rows = {
        "schmid": {"source_title": "MiRNA126 RGS16 CXCL12 cascade"},
        "dorneles": {"source_title": "Immunoregulation after exercise"},
        "harris": {"source_title": "Flow-mediated dilation response"},
        "unrelated": {"source_title": "Unrelated trial"},
    }
    aliases = {
        "schmid": ("Schmid 2021",),
        "dorneles": ("Dorneles 2020",),
        "harris": ("Harris 2008",),
        "unrelated": ("Other 2020",),
    }

    assert revision_coverage.authorized_receipt_contract_fields_by_receipt(
        feedback, rows, aliases,
    ) == {
        "schmid": {"outcome_class"},
        "dorneles": {"outcome_class"},
        "harris": {"directness", "evidence_tier", "effect_direction"},
    }


def test_primary_rct_reclassification_is_verified_from_named_source_row() -> None:
    ask = (
        "Recode or reroute Harris 2008: the source is a primary RCT, not a "
        "review; change the directness and reset the tier to match an RCT code."
    )
    fixed = "- Harris 2008: outcome=immune; directness=direct; tier=A1."
    stale = "- Harris 2008: outcome=immune; directness=review; tier=B1."

    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(stale, [ask]) == [ask]


def test_inferential_bridge_boundary_satisfies_dedicated_section_ask() -> None:
    ask = (
        "Add a dedicated 'Inferential Bridge' section covering the mechanistic-to-clinical gap, "
        "population-to-population transfer, and the biomarker-to-bedside boundary."
    )
    paper = """
## Inferential Bridge

[inferential bridge status: not established]

The mechanistic-to-clinical and biomarker-to-bedside bridges remain untested.
Population-to-population transfer is unsupported.
"""

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []

    tagged = """
## Inferential Bridge

1. [D1_inferential_bridge | confidence=low] Bounded bridge.
   [mechanism anchor: r1] [conservation: Canon]
   Testability: prospective validation. [testability: explicit]
"""
    assert revision_coverage.deterministic_unmet_asks(tagged, [ask]) == []


def test_live_statins_revision_classes_have_deterministic_coverage() -> None:
    asks = [
        "Resolve the numeric discrepancies in reported p-values and add a verification note.",
        "Mark mechanism-level explanations in the Cross-Domain Synthesis as author inference.",
        "Provide a Quantitative Evidence Index or evidence-claim table with consistent p-values.",
        "Tighten the Research Question to a specific and clinically bounded question.",
    ]
    paper = """
## Research Question

Within the retained source corpus for statins, among older adults, do findings for mortality support a decision-grade
conclusion (clinically actionable where applicable), and which population, study-design, and directness
boundaries keep extrapolation to other outcome classes hypothesis-generating?

## Quantitative Evidence Index

**Numeric verification note:** P-values use the implied decimal reporting floor.

| Study | Endpoint | Arm | Value | Type | Statistic |
|---|---|---|---|---|---|
| Smith 2024 | mortality | treatment | P < 0.001 | p-value | — |

## Cross-Domain Synthesis

**Author-inference boundary:** Mechanism-level explanations are synthesis-author inferences and are
not independently established causal findings.
"""

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_numeric_revision_rejects_impossible_rounded_zero_p_value() -> None:
    ask = "Resolve the numeric discrepancies in reported P < 0.000 values and add a verification note."
    for notation in ("P < 0.000", "P = 0", "P=0.", "P = 0."):
        assert revision_coverage._ROUNDED_ZERO_P_RE.search(notation)
        paper = f"**Numeric verification note:** checked. {notation}"
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_qei_revision_requires_data_rows_and_normalized_p_values() -> None:
    ask = "Provide a Quantitative Evidence Index with consistent rounding and notation for p-values."
    header_only = """
## Quantitative Evidence Index
| Study | Endpoint | Arm | Value | Type | Statistic |
|---|---|---|---|---|---|
"""
    invalid = header_only + "| Smith 2024 | mortality | treatment | p=.000 | p-value | — |\n"
    blank = header_only + "| | | | | | |\n"
    assert revision_coverage.deterministic_unmet_asks(header_only, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(invalid, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(blank, [ask]) == [ask]
    numeric_ask = "Resolve the numeric discrepancies in p-values and add a verification note."
    assert revision_coverage.deterministic_unmet_asks(
        "**Numeric verification note:** checked.", [numeric_ask],
    ) == [numeric_ask]


def test_author_inference_boundary_must_be_in_requested_section() -> None:
    ask = "Mark mechanistic explanations in the Discussion as author inference."
    note = "**Author-inference boundary:** These are synthesis-author inferences, not independently established causal findings."
    assert revision_coverage.deterministic_unmet_asks(
        f"## Cross-Domain Synthesis\n\n{note}", [ask],
    ) == [ask]
    assert revision_coverage.deterministic_unmet_asks(
        f"## Discussion\n\n{note}", [ask],
    ) == []

    move_ask = "Move the mechanistic author inference boundary from Discussion to Cross-Domain Synthesis."
    assert revision_coverage.deterministic_unmet_asks(
        f"## Cross-Domain Synthesis\n\n{note}", [move_ask],
    ) == []
    relocate_ask = "Author-inference boundary within Discussion should relocate to Cross-Domain Synthesis."
    assert revision_coverage.deterministic_unmet_asks(
        f"## Discussion\n\n{note}", [relocate_ask],
    ) == [relocate_ask]
    assert revision_coverage.deterministic_unmet_asks(
        f"## Cross-Domain Synthesis\n\n{note}", [relocate_ask],
    ) == []
    contrast_ask = (
        "Relocate the mechanistic author inference boundary to Cross-Domain "
        "Synthesis rather than to Discussion."
    )
    assert revision_coverage._author_inference_sections(contrast_ask) == (
        "Cross-Domain Synthesis",
    )
    assert revision_coverage.deterministic_unmet_asks(
        f"## Cross-Domain Synthesis\n\n{note}", [contrast_ask],
    ) == []
    plain_contrast = (
        "Place the author-inference boundary in Discussion rather than "
        "Cross-Domain Synthesis."
    )
    assert revision_coverage._author_inference_sections(plain_contrast) == (
        "Discussion",
    )
    generic = "Population boundary within Discussion should relocate to Cross-Domain Synthesis."
    assert not revision_coverage._asks_author_inference_boundary(generic)
    repetition = (
        "Remove the repeated Cross-Domain Synthesis template and explain what "
        "population, endpoint, or dose boundary each divergence implies."
    )
    assert not revision_coverage._asks_author_inference_boundary(repetition)
    assert not revision_coverage._asks_author_inference_boundary(
        "Remove the repeated author-inference boundary from the Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "Do not move the mechanistic author-inference boundary from Discussion "
        "into Cross-Domain Synthesis."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "Don't add an author-inference boundary to the Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "There is no need to place the mechanistic author-inference boundary "
        "in the Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "You shouldn't move the author-inference boundary into Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "The author-inference boundary should not be labeled in Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "Keep the author-inference boundary unchanged; add a limitation in Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "You do not need to move the author-inference boundary into Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "You shouldn't automatically move the author-inference boundary into Discussion."
    )
    assert not revision_coverage._asks_author_inference_boundary(
        "The author-inference boundary should not be explicitly labeled in Discussion."
    )
    clause_local = (
        "Move the author-inference boundary from Discussion to Cross-Domain Synthesis. "
        "Add limitations in Discussion."
    )
    assert revision_coverage._author_inference_sections(clause_local) == (
        "Cross-Domain Synthesis",
    )


def test_directness_coding_criteria_require_explicit_methods_definition() -> None:
    ask = (
        "Clarify the 'directness' coding criteria in the Methods section to explicitly define "
        "what constitutes a 'direct' source versus 'indirect' or 'review' sources."
    )
    weak = "## Methods\n\nSources were assigned directness labels.\n"
    defined = """
## Methods

Directness coding criteria were fixed before rendering. A source was coded as
direct only when it tested the topic itself against a clinically proximate
outcome in the relevant population. Adjacent evidence was coded as indirect;
syntheses were coded as review-level evidence.
"""

    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(defined, [ask]) == []


def test_unmet_asks_empty_for_no_asks(monkeypatch) -> None:
    assert _unmet([], {"addressed": []}, monkeypatch) == []


def test_unmet_asks_fail_closed_on_judge_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unmet_asks("M", ["a"], chat=boom, settings=object()) == ["a"]


def test_deterministic_unmet_flags_missing_classification_criteria() -> None:
    ask = "Define the classification criteria used to assign studies to outcome classes and to code directness."

    assert revision_coverage.deterministic_unmet_asks("## Methods\n\nMethods.\n", [ask]) == [ask]


def test_deterministic_unmet_accepts_classification_criteria_and_map() -> None:
    paper = (
        "## Methods\n\n"
        "### Classification criteria\n\n"
        "**Outcome class** records the endpoint family. **Directness** records whether evidence is direct, "
        "indirect, mechanistic, or review. **Evidence tier** records A1, A2, B1, B2, C1, or C2.\n\n"
        "### Source classification map\n\n"
        "- Smith 2024: outcome=cardiometabolic; directness=indirect; tier=B2.\n"
    )
    asks = [
        "Define the classification criteria used to assign studies to outcome classes and to code directness.",
        "Provide a mapping table or list showing which sources were assigned to which outcome class.",
    ]

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_unmet_flags_missing_source_directness_breakdown() -> None:
    ask = (
        "Clarify source directness: explicitly note which of the 28 sources directly "
        "address deep sleep manipulation and aging-relevant hard endpoints versus which "
        "are adjacent (e.g., insomnia drug trials, general sleep architecture descriptions, "
        "preclinical models)."
    )
    paper = "## Evidence Landscape\n\nThe corpus is adjacent and mixed.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_directness_breakdown() -> None:
    ask = (
        "Clarify source directness: explicitly note which of the 28 sources directly "
        "address deep sleep manipulation and aging-relevant hard endpoints versus which "
        "are adjacent (e.g., insomnia drug trials, general sleep architecture descriptions, "
        "preclinical models)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses deep sleep manipulation and aging-relevant hard endpoints; "
        "directness=direct_interventional.\n"
        "- Jones 2025: adjacent insomnia-drug trial evidence; directness=adjacent.\n"
        "- Lee 2026: mechanistic sleep-architecture model; directness=mechanistic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_direct_vs_adjacent_scope_statement() -> None:
    ask = (
        "Clarify the scope statement: explicitly state which included sources are direct "
        "ABT-263 (navitoclax) studies versus other senolytics used as adjacent context, "
        "and justify why each non-ABT-263 source is included in an ABT-263 evidence map."
    )
    paper = "## Evidence Landscape\n\nThe source set is mixed.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_direct_vs_adjacent_scope_statement() -> None:
    ask = (
        "Clarify the scope statement: explicitly state which included sources are direct "
        "ABT-263 (navitoclax) studies versus other senolytics used as adjacent context, "
        "and justify why each non-ABT-263 source is included in an ABT-263 evidence map."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Source directness breakdown: 1/3 retained sources directly address the stated topic "
        "and aging-relevant hard endpoints; 2/3 are adjacent contextual sources.\n\n"
        "### Source Classification Map\n\n"
        "- Smith 2024: outcome=longevity; direction=positive; directness=direct; tier=A1.\n"
        "- Jones 2025: outcome=contextual adjacent evidence; direction=null; directness=adjacent; tier=B2.\n"
        "- Lee 2026: outcome=mechanism; direction=unclear; directness=mechanistic; tier=C1.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_general_vs_direct_source_breakdown() -> None:
    ask = (
        "Clarify which of the 52 sources directly address a composite digital "
        "frailty index versus general digital biomarker research, and bound the "
        "synthesis claims accordingly."
    )
    paper = "## Evidence Landscape\n\nThe source set is heterogeneous.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_general_vs_direct_source_breakdown() -> None:
    ask = (
        "Clarify which of the 52 sources directly address a composite digital "
        "frailty index versus general digital biomarker research, and bound the "
        "synthesis claims accordingly."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses the composite index endpoint; directness=direct.\n"
        "- Jones 2025: broader general digital biomarker research; directness=contextual.\n"
        "- Lee 2026: adjacent frailty assessment evidence; directness=adjacent.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_revision_asks_splits_strengthen_followup() -> None:
    feedback = (
        "Expand the underpopulated outcome-class subsections (Longevity, Muscle Function).; "
        "Strengthen the Tensions and Gaps section by naming specific disagreements."
    )

    assert revision_coverage.revision_asks(feedback) == [
        "Expand the underpopulated outcome-class subsections (Longevity, Muscle Function).",
        "Strengthen the Tensions and Gaps section by naming specific disagreements.",
    ]


def test_revision_asks_splits_rename_followup() -> None:
    feedback = "Clarify the endpoint.; Rename the 'Longevity' outcome class to 'MACE'."

    assert revision_coverage.revision_asks(feedback) == [
        "Clarify the endpoint.",
        "Rename the 'Longevity' outcome class to 'MACE'.",
    ]


def test_deterministic_unmet_accepts_subgroup_lens_narrative() -> None:
    ask = (
        "Add a narrative synthesis section that explicitly maps findings to the five subgroup "
        "lenses (frailty, sarcopenic obesity, CKM stage, diabetes comorbidity, intervention type) "
        "using the admitted sources, rather than only listing source counts."
    )
    paper = (
        "## Results\n\n"
        "Narrative subgroup synthesis maps source findings across the five subgroup lenses. "
        "Frailty is represented by Nguyen 2025 and Garcia 2026, while sarcopenic obesity is "
        "represented by Zhang 2025. CKM stage is represented by Chen 2026 and An 2026. "
        "Diabetes comorbidity is represented by Nielsen 2026, and intervention type separates "
        "exercise, vaccination, pharmacologic, and invasive-procedure records. These source-linked "
        "lenses define boundary conditions rather than simple counts, and the narrative explains "
        "why each source supports only bounded subgroup inference across the admitted evidence set."
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_keeps_subgroup_lens_ask_without_sources() -> None:
    ask = (
        "Add a narrative synthesis section that explicitly maps findings to the five subgroup "
        "lenses (frailty, sarcopenic obesity, CKM stage, diabetes comorbidity, intervention type) "
        "using the admitted sources, rather than only listing source counts."
    )
    paper = (
        "## Results\n\n"
        "Narrative subgroup synthesis maps frailty, sarcopenic obesity, CKM stage, diabetes "
        "comorbidity, and intervention type across the admitted evidence set, but only as "
        "unattributed category labels without source-linked findings."
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_underpopulated_outcome_attribution_and_tensions() -> None:
    asks = [
        (
            "Expand the underpopulated outcome-class subsections (Longevity, Muscle Function, "
            "Immune Inflammation, Safety, Safety and Comorbidity) with at least one or two "
            "attributed findings each, drawn from the source bundle, or remove the headers if no "
            "findings are retained."
        ),
        "Strengthen the Tensions and Gaps section by naming specific disagreements among the retained sources.",
    ]
    paper = (
        "## Results\n\n"
        "Retained sources include You 2026, Delaney 2025, Liu 2026, and Wolfe 2025.\n\n"
            "### Longevity Outcomes\n\nZhao 2025 reports cardiovascular mortality risk in frailty cohorts.\n\n"
        "### Muscle Function Outcomes\n\nChu 2026 reports exercise-related functional contrasts.\n\n"
        "### Immune and Inflammation Outcomes\n\nWard 2026 reports inflammatory-marker associations.\n\n"
        "### Safety Outcomes\n\nLong 2026 reports dose-stratified safety signals.\n\n"
        "### Safety and Comorbidity Outcomes\n\nFu 2026 reports CKM-related diagnostic value.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-Gap Priority: the named disagreements below identify unresolved gaps.\n\n"
        "- Severity 5 disagreement: You 2026 vs Delaney 2025; tension in cardiometabolic direction.\n"
        "- Severity 5 disagreement: Liu 2026 vs Delaney 2025; tension in cardiometabolic direction.\n"
        "- Severity 4 disagreement: Wolfe 2025 vs You 2026; conflict between null and negative findings.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_unmet_keeps_underpopulated_outcome_ask_without_attribution() -> None:
    ask = (
        "Expand the underpopulated outcome-class subsections (Longevity, Muscle Function, "
        "Immune Inflammation) with at least one or two attributed findings each, drawn from "
        "the source bundle, or remove the headers if no findings are retained."
    )
    paper = (
        "## Results\n\n"
        "### Longevity Outcomes\n\nThis subsection has no source attribution.\n\n"
        "### Muscle Function Outcomes\n\nThis subsection has no source attribution.\n\n"
        "### Immune and Inflammation Outcomes\n\nThis subsection has no source attribution.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_topic_fit_rationale_for_umbrella_source_ask() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring, sports workload, "
        "geolocation in psychiatric disorders, and Alzheimer's speech analysis are "
        "included under the 'digital frailty index' umbrella, given that none appear "
        "to operationalize a frailty index."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "digital frailty index directly or provide adjacent/contextual boundary "
        "evidence for the same construct. 0/4 retained sources are classified as "
        "direct; adjacent, contextual, review-level, or mechanistic sources are "
        "reclassified as boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_topic_fit_rationale_in_evidence_snapshot() -> None:
    ask = (
        "Add a note explaining why sources are included under the digital frailty "
        "index umbrella when they do not operationalize a frailty index."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "digital frailty index directly or provide adjacent/contextual boundary "
        "evidence for the same construct. Adjacent sources are reclassified as "
        "boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_off_topic_source_audit_without_breakdown() -> None:
    ask = (
        "Audit the source bundle for sources that are clearly off-topic to hydrogen "
        "water in humans or animals and either remove them or explain their inclusion "
        "as contextual adjacent evidence."
    )
    paper = "## Evidence Landscape\n\nThe included sources are summarized below.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_evidence_type_metadata_inconsistency() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = "## Methods\n\nSources were grouped by topic.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_evidence_type_metadata_resolution() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Methods\n\n"
        "### Source Classification Map\n\n"
        "Evidence type labels were resolved against excerpts: review records with RCT excerpt data "
        "were reclassified under classification criteria that separate review, RCT, and trial evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_evidence_type_metadata_in_evidence_snapshot() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Evidence Snapshot\n\n"
        "### Source Classification Map\n\n"
        "Evidence type metadata note: evidence-type labels are resolved against source excerpts; "
        "review, RCT/trial, and excerpt evidence are reclassified under the source classification map.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_off_topic_source_audit_breakdown() -> None:
    ask = (
        "Audit the source bundle for sources that are clearly off-topic to hydrogen "
        "water in humans or animals and either remove them or explain their inclusion "
        "as contextual adjacent evidence."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses the intervention and hard endpoints; directness=direct.\n"
        "- Jones 2025: contextual adjacent evidence retained for mechanism only; directness=contextual.\n"
        "- Lee 2026: mechanistic animal evidence; directness=mechanistic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_remove_or_justify_off_topic_sources() -> None:
    ask = (
        "Remove or justify clearly off-topic sources from the corpus, and update "
        "the source count and evidence landscape accordingly."
    )
    paper = "## Evidence Landscape\n\nAll sources are summarized.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_umbrella_source_inclusion_without_rationale() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring and geolocation are included "
        "under the digital frailty index umbrella, given that none appear to operationalize a frailty index."
    )
    paper = "## Evidence Landscape\n\nThe included sources are summarized.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_umbrella_source_inclusion_rationale() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring and geolocation are included "
        "under the digital frailty index umbrella, given that none appear to operationalize a frailty index."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Classification Map\n\n"
        "Inclusion rationale: sources that directly addresses frailty-index operationalization are "
        "kept as direct; contextual digital-biomarker sources are reclassified as adjacent and not "
        "used for broad claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_primary_content_reclassification_rationale() -> None:
    ask = (
        "Prune or reclassify cited sources whose primary content is not about "
        "cardiovascular subgroups."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "cardiovascular subgroups directly or provide adjacent/contextual boundary "
        "evidence for the same construct. Adjacent sources are reclassified as "
        "boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_operational_subgroup_definition() -> None:
    ask = (
        "Define 'cardiovascular subgroup' operationally at the start "
        "(which subgrouping axes, which population strata, which outcomes)."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "cardiovascular subgroups directly or provide adjacent/contextual boundary "
        "evidence for the same construct. Adjacent sources are reclassified as "
        "boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_weak_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable research gaps."
    paper = "## Gaps Identified\n\nMore research is needed because the current corpus is limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_actionable_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable future research directions."
    paper = (
        "## Gaps Identified\n\n"
        "The next study should use a powered randomized trial in an older adult priority population, "
        "with a prespecified comparator, 12-month follow-up duration, clinically meaningful endpoint "
        "selection, dose documentation, and safety monitoring. Measurement should separate sleep, "
        "functional, and cardiometabolic endpoints so the evidence gap is testable rather than generic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_gaps_that_repeat_limitations() -> None:
    ask = (
        "Rewrite the 'Gaps Identified' section to provide specific, actionable "
        "research gaps instead of repeating the limitations."
    )
    paper = (
        "## Gaps Identified\n\n"
        "The main gaps are the same as the limitations: the corpus is indirect, "
        "heterogeneous, and lacks definitive evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_gaps_rewritten_as_actionable_next_steps() -> None:
    ask = (
        "Rewrite the 'Gaps Identified' section to provide specific, actionable "
        "research gaps instead of repeating the limitations."
    )
    paper = (
        "## Gaps Identified\n\n"
        "1. Run a powered prospective trial in the priority population with a "
        "prespecified comparator, dose documentation, and clinical endpoint hierarchy.\n"
        "2. Extend follow-up duration to at least 24 months with safety monitoring and "
        "patient-relevant functional measurement.\n"
        "3. Standardize measurement timing across cardiometabolic and functional endpoints "
        "so future analyses can test pooled effects rather than restating heterogeneity.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_live_top_bucket_matrix() -> None:
    asks = [
        (
            "In the Evidence Landscape table, the column 'Strongest signal' states "
            "'no extracted directional signal in 20/20 sources'. Given that some sources "
            "report directional results, reconcile the table coding with the narrative."
        ),
        "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data.",
        (
            "Verify that all 50 bundle sources actually address melatonin and aging; "
            "remove or reclassify sources whose excerpts clearly address unrelated topics."
        ),
        (
            "The manuscript's explicit absence of direct clinical evidence and reliance on "
            "adjacent/mechanistic data requires a revise status to signal that broad "
            "population-level proof is missing."
        ),
        (
            "Rewrite the 'Gaps Identified' section to provide specific, actionable "
            "research gaps instead of repeating the limitations."
        ),
    ]
    missing = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n|---|---|\n"
        "| Contextual Adjacent Evidence | no extracted directional signal in 20/20 sources |\n\n"
        "## Gaps Identified\n\nThe limitations are indirect evidence and heterogeneity.\n\n"
        "## Conclusion\n\nA broad geroscience rationale remains plausible.\n"
    )
    repaired = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class; it is not an "
        "absence-of-support finding. Positive, negative, mixed, unclear, and null are "
        "outcome-specific codes, so signals in other outcome evidence are separately reported.\n\n"
        "Source directness breakdown: 1/3 retained sources directly address the stated topic and "
        "aging-relevant hard endpoints; 2/3 are adjacent, contextual, review-level, or mechanistic "
        "and are used only to bound interpretation.\n\n"
        "### Source Classification Map\n\n"
        "- Smith 2024: outcome=cardiometabolic; directness=direct; tier=A1.\n"
        "- Jones 2025: outcome=contextual adjacent evidence; directness=adjacent; tier=B2.\n\n"
        "Evidence type metadata note: evidence-type labels are resolved against source excerpts; "
        "review, RCT/trial, and excerpt evidence are reclassified under the source classification map.\n\n"
        "## Gaps Identified\n\n"
        "1. Run a powered prospective trial in the priority population with a prespecified "
        "comparator, dose documentation, and clinical endpoint hierarchy.\n"
        "2. Extend follow-up duration to at least 24 months with safety monitoring and "
        "patient-relevant functional measurement.\n"
        "3. Standardize measurement timing across cardiometabolic and functional endpoints "
        "so future analyses can test pooled effects rather than restating heterogeneity.\n\n"
        "## Conclusion\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes adjacent/mechanistic evidence, "
        "this synthesis is hypothesis-generating and not definitive. It does not support "
        "broad causal or policy claims; broad population-level proof is missing.\n"
    )

    assert set(revision_coverage.deterministic_unmet_asks(missing, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_deterministic_unmet_flags_unbounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = "## Conclusion\n\nThis synthesis supports a bounded geroscience rationale for clinical use.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_supportive_null_signal_even_if_hypothesis_generating() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = (
        "## Conclusion\n\n"
        "Because most directional signals are null, this synthesis supports a bounded geroscience "
        "rationale and is hypothesis-generating for clinical translation.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_bounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = (
        "## Conclusion\n\n"
        "Because most directional signals are null or mixed, this synthesis is hypothesis-generating and "
        "does not support a clinical recommendation. The bounded rationale is limited to study design.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_evidence_boundary() -> None:
    ask = (
        "Clarify in the abstract and key findings that the evidence is mixed and does not "
        "support broad causal or policy claims. Explicitly state that the synthesis is "
        "mechanistic and hypothesis-generating rather than definitive."
    )
    paper = "## Abstract\n\nThe evidence supports a plausible anti-aging signal.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_evidence_boundary() -> None:
    ask = (
        "The manuscript is technically sound, but the absence of direct clinical evidence "
        "and reliance on adjacent/mechanistic data requires a revise status to signal that "
        "broad population-level proof is missing."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
        "synthesis is hypothesis-generating and not definitive. It does not support broad "
        "causal or policy claims; broad population-level proof is missing.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_requires_abstract_and_key_findings_boundary() -> None:
    ask = (
        "Clarify in the abstract and key findings that the evidence is mixed and does not "
        "support broad causal or policy claims. Explicitly state that the synthesis is "
        "mechanistic and hypothesis-generating rather than definitive."
    )
    abstract_only = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
        "synthesis is hypothesis-generating and not definitive. It does not support broad "
        "causal or policy claims; broad population-level proof is missing.\n\n"
        "## Key Findings\n\nThe signal is promising.\n"
    )
    both_sections = abstract_only.replace(
        "## Key Findings\n\nThe signal is promising.",
        (
            "## Key Findings\n\n"
            "Evidence-boundary note: Because the retained corpus relies on limited direct "
            "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
            "synthesis is hypothesis-generating and not definitive. It does not support broad "
            "causal or policy claims; broad population-level proof is missing."
        ),
    )

    assert revision_coverage.deterministic_unmet_asks(abstract_only, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(both_sections, [ask]) == []


def test_deterministic_unmet_flags_claims_not_bounded_by_tier_directness() -> None:
    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = (
        "## Key Findings\n\nThe signal is promising.\n\n"
        "## Conclusion\n\nThe intervention is biologically plausible.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_claims_bounded_by_tier_directness() -> None:
    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = (
        "## Key Findings\n\nA B2 indirect evidence tier supports only hypothesis-generating "
        "claims; directness is indirect/review rather than direct.\n\n"
        "## Conclusion\n\nThe conclusion is bounded to A1/B2 evidence tier patterns and "
        "directness ratings that separate direct, indirect, review, and mechanistic sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_directional_signal_explanation() -> None:
    ask = (
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class, "
        "given that some sources report positive or mixed associations elsewhere."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding is counted within each assigned outcome class only. A no extracted directional "
        "signal cell means null or unclear coding for that outcome slice; positive and mixed signals in "
        "other outcome classes remain separately reported and do not change that row.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_weak_directional_signal_explanation() -> None:
    ask = (
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class, "
        "given that some sources report positive or mixed associations elsewhere."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding is counted within the assigned outcome class only. A no extracted directional "
        "signal cell means the retained sources did not yield a coded null or unclear signal for that slice.\n\n"
        "### Source Classification Map\n\n"
        "- Hayashi 2025: outcome=contextual adjacent evidence; direction=positive.\n"
        "- Yiallourou 2025: outcome=contextual adjacent evidence; direction=mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_contextual_claims_without_direction_explanation() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = "## Evidence Landscape\n\nThe table reports no directional signal.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_contextual_claims_without_direction_explanation() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Contextual claims are bibliographic and mechanistic context, not effect-direction findings. "
        "A no extracted directional signal row means the extracted statistic was not directional for "
        "that outcome slice; it is not directional evidence of benefit.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_contextual_claims_explanation_in_evidence_snapshot() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded effect was "
        "extracted for that outcome class. Contextual claims contain bibliographic background, "
        "mechanistic context, methods, or population context rather than effect-direction evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_directional_table_narrative_contradiction() -> None:
    ask = (
        "Resolve the contradiction between the Evidence Landscape table showing no directional signal "
        "and the narrative claiming positive associations in frailty-outcome studies. Either the table "
        "coding or the narrative needs correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Frailty | no directional signal in 20/20 sources |\n\n"
        "## Key Findings\n\n"
        "The corpus shows positive associations in frailty-outcome studies.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_reconciled_directional_table_narrative() -> None:
    ask = (
        "Resolve the contradiction between the Evidence Landscape table showing no directional signal "
        "and the narrative claiming positive associations in frailty-outcome studies. Either the table "
        "coding or the narrative needs correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Frailty | no directional signal in 20/20 sources |\n\n"
        "## Key Findings\n\n"
        "Positive associations are separately reported in other outcome classes; the frailty row's "
        "no directional signal coding does not mean absence of support across the whole corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_null_directional_vs_positive_narrative() -> None:
    ask = (
        "Resolve the inconsistency between the Evidence Landscape table (all null "
        "directional signals) and the rest of the manuscript (references to positive, "
        "mixed, and negative signals in the frailty class)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Direction |\n"
        "|---|---|\n"
        "| Frailty | all null directional signals |\n\n"
        "## Key Findings\n\n"
        "The frailty class shows positive signals in several sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_null_directional_reconciled_narrative() -> None:
    ask = (
        "Resolve the inconsistency between the Evidence Landscape table (all null "
        "directional signals) and the rest of the manuscript (references to positive, "
        "mixed, and negative signals in the frailty class)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Direction |\n"
        "|---|---|\n"
        "| Frailty | all null directional signals |\n\n"
        "## Key Findings\n\n"
        "Positive and mixed signals are separately reported in other outcome classes; "
        "the frailty row's null directional signal does not mean absence of support "
        "outside that specific coded slice.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_internal_duplication() -> None:
    ask = "Remove internal duplication of content across the Evidence Landscape and Key Findings sections."
    repeated = (
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and "
        "shows that the current evidence base remains mixed, hypothesis-generating, and not sufficient "
        "for broad clinical or policy claims."
    )
    paper = f"## Evidence Landscape\n\n{repeated}\n\n## Key Findings\n\n{repeated}\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_duplicate_discussion_sentences() -> None:
    ask = (
        "Resolve the duplicate sentences in the Discussion section and produce "
        "a clean final render of the long-form manuscript."
    )
    sentence = "The retained evidence supports only a bounded interpretation of these effects."
    paper = f"## Discussion\n\n{sentence} Additional context follows. {sentence}\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]

    fixed = (
        "## Discussion\n\nThe retained evidence supports only a bounded interpretation "
        "of these effects. Additional context follows without repetition.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask]) == []


def test_conclusion_scope_rejects_positive_lifestyle_recommendation() -> None:
    ask = (
        "Tighten the Conclusion to match the bounded claim posture and do not "
        "allow soft lifestyle recommendations."
    )
    paper = (
        "## Conclusion\n\n"
        "The conclusion does not support broad causal, clinical, or policy claims. "
        "Fasting is recommended as a general health and lifestyle intervention.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_conclusion_scope_rejects_affirmative_recommendation_variants() -> None:
    ask = (
        "Tighten the Conclusion to match the bounded claim posture and do not "
        "allow soft lifestyle recommendations."
    )
    variants = (
        "The intervention can be used as a general health intervention.",
        "The intervention may be used as a general health intervention.",
        "The intervention is appropriate as a lifestyle intervention.",
        "The intervention is suitable as a lifestyle intervention.",
        "The evidence supports its use as a lifestyle intervention.",
        "The evidence supports adoption as a lifestyle intervention.",
        "The evidence not only supports its use as a lifestyle intervention.",
    )

    for sentence in variants:
        paper = (
            "## Conclusion\n\n"
            "The conclusion does not support broad causal, clinical, or policy claims. "
            f"{sentence}\n"
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]

    bounded = (
        "## Conclusion\n\n"
        "The evidence does not support its use as a lifestyle intervention. "
        "It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(bounded, [ask]) == []
    uncertain = (
        "## Conclusion\n\nThe evidence is insufficient to determine whether the "
        "intervention is appropriate as a lifestyle intervention. It does not "
        "support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(uncertain, [ask]) == []
    contrastive = (
        "## Conclusion\n\nThe intervention does not prevent cancer but is suitable "
        "as a lifestyle intervention. It does not support broad causal, clinical, "
        "or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(contrastive, [ask]) == [ask]
    for sentence in (
        "Although efficacy is unproven, it is suitable as a lifestyle intervention.",
        "Efficacy is unproven and the intervention may be used for general health.",
    ):
        paper = (
            f"## Conclusion\n\n{sentence} It does not support broad causal, "
            "clinical, or policy claims.\n"
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    bounded = (
        "## Conclusion\n\nThe evidence fails to support its use as a lifestyle "
        "intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(bounded, [ask]) == []
    past_bounded = (
        "## Conclusion\n\nThe trial failed to support its use as a lifestyle "
        "intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(past_bounded, [ask]) == []
    cross_clause = (
        "## Conclusion\n\nThe evidence supports further research but does not "
        "support its use as a lifestyle intervention. It does not support broad "
        "causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(cross_clause, [ask]) == []
    because = (
        "## Conclusion\n\nThe evidence supports further research because it does "
        "not support its use as a lifestyle intervention. It does not support broad "
        "causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(because, [ask]) == []
    unlikely = (
        "## Conclusion\n\nThe evidence is unlikely to support its use as a lifestyle "
        "intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(unlikely, [ask]) == []
    coordinated_safe = (
        "## Conclusion\n\nThe evidence does not support or recommend its use as a "
        "lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(coordinated_safe, [ask]) == []
    coordinated_unsafe = (
        "## Conclusion\n\nThe evidence supports adoption and use as a lifestyle "
        "intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(coordinated_unsafe, [ask]) == [ask]
    not_merely = (
        "## Conclusion\n\nThe evidence does not merely support its use as a lifestyle "
        "intervention; it establishes it. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(not_merely, [ask]) == [ask]
    for bounded in (
        "The authors recommend against using it as a lifestyle intervention.",
        "The evidence supports avoiding its use as a lifestyle intervention.",
    ):
        paper = (
            f"## Conclusion\n\n{bounded} It does not support broad causal, "
            "clinical, or policy claims.\n"
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    temporal = (
        "## Conclusion\n\nThe intervention has been recommended since 2020 as a "
        "lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(temporal, [ask]) == [ask]
    for bounded in (
        "The authors recommend that the intervention not be used as a lifestyle intervention.",
        "The evidence neither supports nor recommends its use as a lifestyle intervention.",
    ):
        paper = (
            f"## Conclusion\n\n{bounded} It does not support broad causal, "
            "clinical, or policy claims.\n"
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    temporal_subject = (
        "## Conclusion\n\nThe intervention has been recommended since it was introduced "
        "as a lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(temporal_subject, [ask]) == [ask]
    abbreviation_negation = (
        "## Conclusion\n\nNo evidence from Smith et al. supports its use as a "
        "lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(abbreviation_negation, [ask]) == []
    abbreviation_boundary = (
        "## Conclusion\n\nNo evidence was reported by Smith et al. Participants report "
        "that the intervention is suitable as a lifestyle intervention. It does not "
        "support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(abbreviation_boundary, [ask]) == [ask]
    for bounded in (
        "No evidence from Dr. Smith supports its use as a lifestyle intervention.",
        "No U.S. Food and Drug Administration evidence supports its use as a lifestyle intervention.",
        "No evidence was reported by the U.S. Food and Drug Administration to support its use as a lifestyle intervention.",
        "No evidence was found in the U.S. Food and Drug Administration report to support its use as a lifestyle intervention.",
        "No credible evidence from the U.S. FDA supports its use as a lifestyle intervention.",
        "Not any available evidence from the U.S. FDA supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. FDA currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Food and Drug Administration currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Centers for Disease Control and Prevention currently supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. Preventive Services Task Force supports its use as a lifestyle intervention.",
        "No direct evidence from the U.S. National Academy of Medicine supports its use as a lifestyle intervention.",
        "No evidence from a U.S. FDA report supports its use as a lifestyle intervention.",
        "No evidence from any U.S. FDA source supports its use as a lifestyle intervention.",
        "No evidence from the U.S. FDA-supported trial supports its use as a lifestyle intervention.",
    ):
        paper = f"## Conclusion\n\n{bounded} It does not support broad causal, clinical, or policy claims.\n"
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    for boundary in ("U.S.", "p.o."):
        paper = (
            f"## Conclusion\n\nNo evidence was reported in the {boundary} Participants report "
            "that the intervention is suitable as a lifestyle intervention. It does not "
            "support broad causal, clinical, or policy claims.\n"
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]
    long_subject = (
        "## Conclusion\n\nNo evidence was reported in the U.S. Independent clinical "
        "experts now recommend its use as a lifestyle intervention. It does not "
        "support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(long_subject, [ask]) == [ask]
    from_boundary = (
        "## Conclusion\n\nNo evidence was reported from the U.S. Independent clinical "
        "experts now recommend its use as a lifestyle intervention. It does not "
        "support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(from_boundary, [ask]) == [ask]
    named_boundary = (
        "## Conclusion\n\nNo evidence was reported from the U.S. Food and Drug "
        "Administration recommends its use as a lifestyle intervention. It does not "
        "support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(named_boundary, [ask]) == [ask]
    for action in ("recommends", "endorses", "adopts", "adopted", "used"):
        institutional_boundary = (
            f"## Conclusion\n\nNo evidence from the U.S. FDA {action} its use as a "
            "lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
        )
        assert revision_coverage.deterministic_unmet_asks(institutional_boundary, [ask]) == [ask]
    short_boundary = (
        "## Conclusion\n\nThere was no effect in the U.S. Experts recommend its use "
        "as a lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(short_boundary, [ask]) == [ask]
    adverb_boundary = (
        "## Conclusion\n\nNo evidence from the U.S. Experts currently recommend its "
        "use as a lifestyle intervention. It does not support broad causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(adverb_boundary, [ask]) == [ask]
    titled_boundary = (
        "## Conclusion\n\nNo evidence from the U.S. Public Health Experts currently "
        "recommend its use as a lifestyle intervention. It does not support broad "
        "causal, clinical, or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(titled_boundary, [ask]) == [ask]
    trailing_qualifier = (
        "## Conclusion\n\nThe intervention is suitable as a lifestyle intervention "
        "despite no evidence of efficacy. It does not support broad causal, clinical, "
        "or policy claims.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(trailing_qualifier, [ask]) == [ask]


def test_funnel_reconciliation_requires_reviewer_named_counts() -> None:
    ask = (
        "Reconcile the source-admission funnel counts and explain how the 73 "
        "classified candidates resolve to 66 admitted final sources."
    )
    generic = (
        "Admission-bucket note: The rows are not an additive conservation table "
        "because claim-binding states overlap."
    )
    exact = (
        f"{generic} Stepwise reconciliation: classified source candidates (73) "
        "-> admitted final sources (66)."
    )

    assert revision_coverage.deterministic_unmet_asks(generic, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(exact, [ask]) == []


def test_funnel_reconciliation_does_not_borrow_unrelated_counts() -> None:
    ask = (
        "Reconcile the source-admission funnel counts and explain how the 73 "
        "classified candidates resolve to 66 admitted final sources."
    )
    paper = (
        "## Results\n\nThe cohort included 73 participants and reported 66 outcomes.\n\n"
        "## Methods\n\nAdmission-bucket note: The rows are not an additive "
        "conservation table because claim-binding states overlap.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_funnel_reconciliation_binds_counts_to_labels() -> None:
    asks = (
        "Reconcile how the 73 classified candidates resolve to 66 admitted final sources.",
        "Reconcile classified candidates (73) with admitted final sources (66).",
        "Reconcile Classified Candidates (73) with Admitted Final Sources (66).",
    )
    wrong = (
        "## Methods\n\nAdmission-bucket note: The 73 participants produced 66 outcomes. "
        "The rows are not an additive conservation table because claim-binding states overlap.\n"
    )
    exact = (
        "## Methods\n\nAdmission-bucket note: The rows are not an additive conservation "
        "table because claim-binding states overlap. Stepwise reconciliation: "
        "classified source candidates (73) -> admitted final sources (66).\n"
    )

    for ask in asks:
        assert revision_coverage.deterministic_unmet_asks(wrong, [ask]) == [ask]
        assert revision_coverage.deterministic_unmet_asks(exact, [ask]) == []


def test_funnel_reconciliation_accepts_exact_typed_rows() -> None:
    ask = "Reconcile Classified Candidates (73) with Admitted Final Sources (66)."
    paper = (
        "## Methods\n\n### Source admission funnel\n\n"
        "| Admission bucket | n |\n|---|---:|\n"
        "| Classified source candidates | 73 |\n"
        "| Admitted final sources | 66 |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_near_duplicate_narrative() -> None:
    ask = "Remove repetitive narrative across the Evidence Landscape and Key Findings sections."
    paper = (
        "## Evidence Landscape\n\n"
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and shows "
        "that the current evidence base remains mixed, hypothesis-generating, and insufficient for broad "
        "clinical or policy claims.\n\n"
        "## Key Findings\n\n"
        "The synthesis separates direct intervention evidence from indirect biomarker evidence, showing "
        "that the current evidence base remains mixed and hypothesis-generating rather than sufficient "
        "for broad clinical policy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_duplication_check_scopes_to_named_sections() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    repeated_results = (
        "92 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources."
    )
    paper = (
        "## Results\n\n"
        f"{repeated_results}\n\n"
        "14 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n\n"
        "## Gaps Identified\n\n"
        "Future trials should define endpoints, comparators, follow-up duration, and safety monitoring.\n\n"
        "## Discussion\n\n"
        "The discussion interprets the evidence without repeating the gap list or corpus statistics.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_duplication_check_flags_named_section_overlap() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    repeated = (
        "The current corpus is mixed and hypothesis-generating, with evidence distribution statistics "
        "showing indirect and review evidence rather than settled clinical translation."
    )
    paper = (
        f"## Gaps Identified\n\n{repeated}\n\n"
        f"## Discussion\n\n{repeated}\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_duplication_check_does_not_fallback_when_named_sections_absent() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    paper = (
        "## Results\n\n"
        "92 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n\n"
        "14 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_non_repetitive_sections() -> None:
    ask = "Remove internal duplication and present a single, non-repetitive narrative."
    paper = (
        "## Evidence Landscape\n\n"
        "The evidence landscape separates direct intervention evidence from indirect biomarker evidence "
        "and identifies mixed signals across outcome domains.\n\n"
        "## Key Findings\n\n"
        "The key finding is that clinical translation remains premature because source directness and "
        "endpoint maturity vary across the corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = "## Abstract\n\nThe evidence is mixed.\n\n## Conclusion\n\nClinical translation remains premature.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = (
        "## Abstract\n\n"
        "The evidence is mixed, and long-term safety data in older adults remain insufficient.\n\n"
        "## Conclusion\n\n"
        "Because long-term safety in older adults is not established, clinical translation remains premature.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_reference_without_identifier() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults.\n"
        "- Jones 2025. Cohort evidence. DOI: 10.1000/example.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_reference_identifiers() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n"
        "- Jones 2025. Cohort evidence. PMID: 12345678.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_reference_identifier_caveat() -> None:
    ask = "Make every reference traceable to the source bundle and clarify missing DOI/PMID entries."
    paper = (
        "## References\n\n"
        "- Smith 2024. Registered trial. Trial registration: NCT01234567.\n"
        "- Jones 2025. Registry protocol. Identifier unavailable; no DOI or PMID in source metadata.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_ignores_reference_headings_and_notes() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n\n"
        "### Background References\n\n"
        "*Canonical clinical thresholds cited in prose; entries below remain source-traceable.*\n\n"
        "- Jones 2025. Cohort evidence. PMID: 12345678.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_still_flags_identifierless_reference_entry() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n\n"
        "### Background References\n\n"
        "*Canonical clinical thresholds cited in prose; entries below remain source-traceable.*\n\n"
        "- Jones 2025. Cohort evidence without a public identifier.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_missing_prior_publication_differentiation() -> None:
    ask = (
        "High overlap with publication 5f852f5b. Differentiate angle, "
        "findings, or population to resubmit."
    )
    paper = "## Introduction\n\nThis evidence brief summarizes the current corpus.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_prior_publication_differentiation() -> None:
    ask = (
        "High overlap with publication 5f852f5b. Differentiate angle, "
        "findings, or population to resubmit."
    )
    paper = (
        "## Introduction\n\n"
        "Prior-brief differentiation: This revision makes the angle, findings, "
        "and population boundary explicit. The angle is a source-bounded synthesis; "
        "the findings are limited to cardiometabolic and sleep outcomes; and the "
        "population boundary follows the included corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_source_verification_transparency() -> None:
    ask = (
        "Add a verification transparency statement acknowledging that the reference-only source bundle "
        "limits external verification of detailed quantitative claims, and direct readers to "
        "supplementary artifacts (manifest.json, methods_pack.json) for full traceability."
    )
    paper = "## Limitations\n\nThe corpus is limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_verification_transparency() -> None:
    ask = (
        "Add a verification transparency statement acknowledging that the reference-only source bundle "
        "limits external verification of detailed quantitative claims, and direct readers to "
        "supplementary artifacts (manifest.json, methods_pack.json) for full traceability."
    )
    paper = (
        "## Limitations\n\n"
        "The source bundle is reference-only, so exact statistics may not be independently verified "
        "from the public manuscript alone. Readers should use the supplementary artifacts, including "
        "manifest.json and methods_pack.json, for source-bundle traceability.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_section_source_grounding() -> None:
    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, Limitations, "
        "and Conclusion can be traced to at least one source whose excerpt or title directly "
        "supports that specific claim."
    )
    paper = (
        "## Limitations\n\n"
        "The corpus is heterogeneous, but no source trace is provided.\n\n"
        "## Conclusion\n\n"
        "The conclusion is bounded, but no source trace is provided.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_section_source_grounding() -> None:
    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, Limitations, "
        "and Conclusion can be traced to at least one source whose excerpt or title directly "
        "supports that specific claim."
    )
    paper = (
        "## Key Findings\n\n"
        "Movahedian 2025 supports the cardiometabolic signal, while Casper 2024 supports the "
        "sleep-outcome boundary condition.\n\n"
        "## Limitations\n\n"
        "Bradfield 2025 and Gupta 2025 are adjacent-context sources, so the claim is bounded "
        "to source-traceable context rather than direct aging efficacy.\n\n"
        "## Conclusion\n\n"
        "Mohammadi 2025 supports the review-level synthesis boundary; the conclusion does not "
        "add claims beyond those source-traced observations.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_admission_funnel_equal_opposite_counts() -> None:
    ask = (
        "Resolve the numerical inconsistency in the admission funnel where "
        "'No extractable claims' and 'Admitted final sources' both equal 56."
    )
    paper = (
        "## Source Admission Funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 56 |\n"
        "| Admitted final sources | 56 |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_admission_funnel_distinct_opposite_counts() -> None:
    ask = (
        "Resolve the numerical inconsistency in the admission funnel where "
        "'No extractable claims' and 'Admitted final sources' both equal 56."
    )
    paper = (
        "## Source Admission Funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 24 |\n"
        "| Admitted final sources | 13 |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_coherent_admission_funnel_note() -> None:
    ask = (
        "Reconcile the admission funnel numbers to a single coherent accounting, "
        "and explain how '63 admitted sources' is derived."
    )
    paper = (
        "## Source Admission Funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| Mixed partial-or-none claim-binding candidates | 70 |\n"
        "| Admitted final sources | 63 |\n\n"
        "Admission-bucket note: The funnel rows are audit categories, not an "
        "additive conservation table. No-extractable-claim, mixed partial-or-none, "
        "partial-only, and admitted-final-source counts can be equal or overlap "
        "because they describe different screening and claim-binding states.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_single_source_proportionality() -> None:
    ask = (
        "For single-source outcome classes (frailty, immune/inflammation, muscle function), "
        "explicitly state upfront that these are hypothesis-generating only and reduce "
        "narrative depth accordingly to maintain proportionality."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Frailty and immune outcomes are discussed as major findings.\n\n"
        "## Conclusion\n\n"
        "The paper summarizes these outcome classes as part of the overall synthesis.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_n_equals_one_context_only_statement() -> None:
    ask = (
        "For outcome classes with n=1 sources, either merge them into adjacent "
        "classes or explicitly flag them as context-only and do not present them "
        "as parallel evidence domains."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Single-source outcome classes are treated as hypothesis-generating and "
        "receive proportional narrative depth rather than standalone evidentiary weight.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_single_source_proportionality_statement() -> None:
    ask = (
        "For single-source outcome classes (frailty, immune/inflammation, muscle function), "
        "explicitly state upfront that these are hypothesis-generating only and reduce "
        "narrative depth accordingly to maintain proportionality."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Single-source outcome classes are treated as hypothesis-generating and receive "
        "proportional narrative depth rather than standalone evidentiary weight.\n\n"
        "## Conclusion\n\n"
        "The synthesis keeps one-source findings bounded.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


_PAPER = "## Abstract\n\nEGCG reverses aging in humans.\n\n## Results\n\nMixed, mostly null.\n"


def _claims(parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unsupported_abstract_claims(_PAPER, chat=_chat(parsed), settings=object())


def test_unsupported_abstract_claims_flags_overclaim(monkeypatch) -> None:
    assert _claims({"unsupported": ["EGCG reverses aging in humans."]}, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_ignores_neutral_profile_summaries(monkeypatch) -> None:
    parsed = {
        "unsupported": [
            "The evidence profile contains no sources classified primarily as mechanistic evidence.",
            "Positive study-level signals concentrate in no dominant outcome class.",
            "positive signals concentrated in contextual cardioprotection, negative signals in cardiometabolic domains",
            "EGCG reverses aging in humans.",
        ],
    }
    assert _claims(parsed, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_empty_when_supported(monkeypatch) -> None:
    assert _claims({"unsupported": []}, monkeypatch) == []


def test_unsupported_abstract_claims_no_abstract_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    assert revision_coverage.unsupported_abstract_claims("## Results\n\nx\n", chat=_chat({"unsupported": ["x"]}), settings=object()) == []


def test_unsupported_abstract_claims_failopen_on_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unsupported_abstract_claims(_PAPER, chat=boom, settings=object()) == []


def test_numeric_effect_direction_flags_non_significant_p_value_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "non-significant p-value described as significant: Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08)."
    ]


def test_deterministic_unmet_flags_numeric_effect_revision_still_wrong() -> None:
    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction. Audit all reported "
        "p-values and effect directions."
    )
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_corrected_numeric_effect_revision() -> None:
    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction. Audit all reported "
        "p-values and effect directions."
    )
    paper = (
        "## Methods\n\n"
        "Numeric effect audit: all reported p-values and effect directions were checked against "
        "source excerpt statistics from the source bundle.\n\n"
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_numeric_effect_direction_allows_explicit_non_significant_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_allows_not_significantly_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 did not significantly reduce LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_flags_ci_crossing_null_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "The pooled effect was statistically significant (95% CI 0.84-1.18).\n\n"
        "## Results\n\nThe confidence interval crosses the null.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "CI crossing null described as significant: The pooled effect was statistically significant (95% CI 0.84-1.18)."
    ]


def test_deterministic_unmet_flags_missing_numeric_effect_audit_statement() -> None:
    ask = "Audit all reported p-values and effect directions in the manuscript against source bundle excerpts."
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_numeric_effect_audit_statement() -> None:
    ask = "Audit all reported p-values and effect directions in the manuscript against source bundle excerpts."
    paper = (
        "## Methods\n\n"
        "Numeric effect audit: all reported p-values and effect directions were checked against "
        "source excerpt statistics from the source bundle.\n\n"
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_prisma_all_included_without_rationale() -> None:
    ask = "Clarify why 100% of retrieved records were included given the PRISMA-ScR eligibility criteria."
    paper = "## Methods\n\nThe PRISMA-ScR flow retained all records.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_prisma_all_included_rationale() -> None:
    ask = "Clarify why 100% of retrieved records were included given the PRISMA-ScR eligibility criteria."
    paper = (
        "## Methods\n\n"
        "100% of retrieved records were included because the screening scope used prequalified "
        "eligibility criteria from the topic pack; the rationale is that all retrieved records "
        "already met the source-bound inclusion scope.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_known_grammar_artifact() -> None:
    ask = "Correct the grammatical error in the abstract: 'is insufficient to is consistent with therapeutic efficacy'."
    paper = "## Abstract\n\nThe evidence is insufficient to is consistent with therapeutic efficacy.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_known_grammar_artifact_repair() -> None:
    ask = "Correct the grammatical error in the abstract: 'is insufficient to is consistent with therapeutic efficacy'."
    paper = "## Abstract\n\nThe evidence is insufficient to establish therapeutic efficacy.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_source_statistics_missing_from_landscape() -> None:
    ask = (
        "For cited sources with specific statistics, ensure these appear in the evidence landscape "
        "and are connected to the appropriate outcome class rather than buried in the source bundle."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_missing_source_outcome_class_map() -> None:
    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_outcome_class_map() -> None:
    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Source outcome-class map: Smith 2024 -> outcome=cardiometabolic; "
        "Jones 2025 -> outcome=immune.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_source_statistics_in_landscape() -> None:
    ask = (
        "For cited sources with specific statistics, ensure these appear in the evidence landscape "
        "and are connected to the appropriate outcome class rather than buried in the source bundle."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Weiss 2026 is mapped to outcome class=longevity and reports a 33% lifespan increase; "
        "the statistic is visible in the outcome-class landscape rather than only in the source bundle.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_soft_human_longevity_conclusion() -> None:
    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits are currently "
        "unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = "## Conclusion\n\nThe human longevity evidence remains biologically plausible but incomplete.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_unproven_human_longevity_conclusion() -> None:
    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits are currently "
        "unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = "## Conclusion\n\nLongevity benefits are currently unproven in humans and not established clinically.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_population_proof_calibration_boundary() -> None:
    ask = (
        "The manuscript is technically sound and highly bounded, but per calibration rules, "
        "the explicit absence of direct clinical evidence and the reliance on adjacent/mechanistic "
        "data requires a 'revise' status to signal that broad population-level proof is missing."
    )
    paper = "## Abstract\n\nThis synthesis is bounded but does not state the population proof boundary.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_population_proof_calibration_boundary() -> None:
    ask = (
        "The manuscript is technically sound and highly bounded, but per calibration rules, "
        "the explicit absence of direct clinical evidence and the reliance on adjacent/mechanistic "
        "data requires a 'revise' status to signal that broad population-level proof is missing."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes adjacent/mechanistic evidence, "
        "this synthesis is hypothesis-generating and not definitive. It does not support "
        "broad causal or policy claims; broad population-level proof is missing.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_mixed_indirect_overclaim_boundary() -> None:
    ask = (
        "Add explicit language in the abstract and conclusion highlighting the mixed "
        "and indirect nature of the evidence base to preempt any overclaiming."
    )
    paper = "## Abstract\n\nEvidence is promising.\n\n## Conclusion\n\nTranslation remains limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_mixed_indirect_overclaim_boundary() -> None:
    ask = (
        "Add explicit language in the abstract and conclusion highlighting the mixed "
        "and indirect nature of the evidence base to preempt any overclaiming."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes mixed, indirect, adjacent/mechanistic "
        "evidence, this synthesis is hypothesis-generating and not definitive. It does not "
        "support broad causal or policy claims.\n\n"
        "## Conclusion\n\n"
        "Evidence-boundary note: Because the retained corpus relies on mixed, indirect evidence, "
        "this synthesis is not definitive and does not support broad causal or policy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_no_signal_proportion_note() -> None:
    ask = (
        "Ensure all outcome-class summaries in the 'Evidence Landscape' table explicitly "
        "note the proportion of sources with no extracted directional signal to avoid ambiguity."
    )
    paper = "## Evidence Landscape\n\n| Outcome | Signal |\n|---|---|\n| Immune | no extracted directional signal |\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_no_signal_proportion_note() -> None:
    ask = (
        "Ensure all outcome-class summaries in the 'Evidence Landscape' table explicitly "
        "note the proportion of sources with no extracted directional signal to avoid ambiguity."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class. When an outcome-class "
        "summary uses no extracted directional signal, it states the source proportion, such as X/Y "
        "sources, to avoid ambiguity.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_named_numeric_correction_without_audit_ask() -> None:
    ask = (
        "Correct the factual error in the abstract regarding Waghmare 2024: the source excerpt "
        "reports a non-significant result (p = 0.08), not a significant reduction in LF HRV power."
    )
    paper = "## Abstract\n\nWaghmare 2024 reported a non-significant result in LF HRV power (p = 0.08).\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_disputed_representative_statistic_uses_source_excerpt_values() -> None:
    rows = [
        {
            "citation_token": "Han 2020",
            "source_title": "Ipragliflozin add-on trial",
            "thesis_text": "Unrelated endpoint p=0.001; fatty liver index p=0.002; NAFLD liver fat score p=0.049.",
            "p_values": ["p=0.001", "p=0.002", "p=0.049"],
        },
        {
            "citation_token": "Li 2025",
            "source_title": "Separate cohort",
            "thesis_text": "Separate source-supported result p=0.001.",
            "p_values": ["p=0.001"],
        },
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "Han 2020 reported a representative statistic P = 0.001. "
        "Li 2025 reported P = 0.001 in a separate source. "
        "Han 2020 contextualized another comparison; P = 0.001 in Li 2025 was separately supported.\n\n"
        "## Results\n\nThe trial reported liver outcomes.\n"
    )

    for verb in ("shows", "lists"):
        ask = (
            "Verify or correct the representative statistic 'P = 0.001' for Han 2020 "
            f"[bundle:1]; the bundled excerpt {verb} P=0.002 for fatty liver index and "
            "P=0.049 for NAFLD liver fat score."
        )
        assert revision_coverage.deterministic_unmet_asks(paper, [ask], evidence_rows=rows) == [ask]
        fixed, details = repair_revision_quality(paper, rows, ask)

        assert "Han 2020 reported a representative statistic P = 0.001" not in fixed
        assert "Li 2025 [bundle:2] reported P = 0.001" in fixed
        assert "P = 0.001 in Li 2025 [bundle:2] was separately supported" in fixed
        assert "Han 2020 [bundle:1] retains p=0.002 as bundle-traceable" in fixed
        assert details == ["named_statistic_reconciliation"]
        assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == [ask]
        assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []


def test_indirect_b2_narrative_ask_is_repaired_from_manifest_roles() -> None:
    ask = (
        "When invoking indirect (B2) sources in narrative arguments, explicitly flag "
        "their indirectness status so readers can weight the inference appropriately."
    )
    rows = [
        {"citation_token": "Li 2025", "directness": "indirect", "evidence_tier": "B2"},
        {"citation_token": "Han 2020", "directness": "direct", "evidence_tier": "A1"},
    ]
    paper = (
        "## Abstract\n\nLi 2025 was associated with the outcome.\n\n"
        "## Results\n\nLi 2025 and Han 2020 reported different signals.\n\n"
        "## References\n\nLi 2025. Source title.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask], evidence_rows=rows) == [ask]
    fixed, details = repair_revision_quality(paper, rows, ask)

    flag = "[indirect B2; down-weighted for causal inference]"
    assert fixed.count(flag) == 2
    assert "Li 2025 is indirect B2 evidence and is down-weighted for causal inference." in fixed
    assert "## References\n\nLi 2025. Source title." in fixed
    assert "Han 2020 is indirect B2" not in fixed
    assert details == ["evidence_role_reconciliation"]
    assert revision_coverage.deterministic_known_asks([ask], evidence_rows=rows) == [ask]
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []


def test_indirect_b2_flags_preserve_reference_heading_variants() -> None:
    ask = (
        "When invoking indirect (B2) sources in narrative arguments, explicitly flag "
        "their indirectness status so readers can weight the inference appropriately."
    )
    rows = [{"citation_token": "Li 2025", "directness": "indirect", "evidence_tier": "B2"}]
    for heading in ("## REFERENCES", "## Bibliography", "### References"):
        reference = f"{heading}\n\nLi 2025. Source title.\n"
        paper = f"## Results\n\nLi 2025 reported an association.\n\n{reference}"

        fixed, _details = repair_revision_quality(paper, rows, ask)

        assert reference in fixed
        assert fixed.count("[indirect B2; down-weighted for causal inference]") == 1


def test_indirect_b2_flags_do_not_treat_narrative_reference_heading_as_bibliography() -> None:
    ask = (
        "When invoking indirect (B2) sources in narrative arguments, explicitly flag "
        "their indirectness status so readers can weight the inference appropriately."
    )
    rows = [{"citation_token": "Li 2025", "directness": "indirect", "evidence_tier": "B2"}]
    paper = "## References to Prior Work\n\nLi 2025 reported an association.\n"

    fixed, _details = repair_revision_quality(paper, rows, ask)

    assert "Li 2025 [indirect B2; down-weighted for causal inference] reported" in fixed
    assert revision_coverage.deterministic_unmet_asks(fixed, [ask], evidence_rows=rows) == []


def test_deterministic_unmet_rejects_non_significant_source_still_positive() -> None:
    ask = (
        "Reconcile the Brouwers 2016 frailty coding: if p=0.88 is the headline statistic, "
        "the source should be recoded as null/mixed in the frailty outcome class, or the "
        "'positive signal' label should be removed and the non-significant result stated explicitly."
    )
    weak = (
        "## Abstract\n\n"
        "Numeric correction: Brouwers 2016 reported a non-significant result (p = 0.88); "
        "this synthesis treats that finding as non-significant. Positive study-level signals "
        "are summarized in the frailty outcome class.\n\n"
        "## Evidence Landscape\n\n"
        "### Frailty\n\n"
        "positive signal in 1/1 sources.\n"
        "- Brouwers 2016: outcome=Frailty; direction=positive; directness=indirect; "
        "tier=B2; finding=representative statistic p = 0.88.\n"
    )
    repaired = weak.replace("Positive study-level signals", "Non-significant or mixed study-level signals").replace(
        "positive signal in 1/1 sources", "non-significant or mixed signal in 1/1 sources",
    ).replace("direction=positive", "direction=null").replace("Numeric correction:", "Numeric verification note:")

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_named_numeric_correction_ignores_unrelated_positive_sources() -> None:
    ask = (
        "Resolve the Brouwers 2016 direction coding inconsistency: either confirm the "
        "positive frailty coding with the supporting statistic, or correct to unclear/null "
        "to match the p=0.88 numeric correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Numeric verification note: Brouwers 2016 reported a non-significant mapped "
        "comparison (p = 0.88); this synthesis treats that mapped comparison, not every "
        "within-source contrast, as non-significant.\n\n"
        "| Outcome | Summary |\n"
        "|---|---|\n"
        "| Treatment response | positive signal in 1/1 sources from Liu 2026 |\n"
        "| Frailty | non-significant or mixed signal in 1/1 sources from Brouwers 2016 |\n\n"
        "- Brouwers 2016: outcome=Frailty; direction=null; finding=representative statistic p=0.88.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_substantive_conclusion_ask_requires_source_pattern_conclusion() -> None:
    ask = (
        "Clarify in the Conclusion what the evidence actually shows about telomere cancer effects, "
        "not just what kind of evidence it is. A conclusion that only describes its own epistemic "
        "status is not informative."
    )
    weak = "## Conclusion\n\nThe conclusion is bounded and hypothesis-generating.\n"
    repaired = (
        "## Conclusion\n\n"
        "Substantive conclusion for Telomere Cancer Effects: the retained source set shows "
        "prognostic and survival-marker evidence n=3, causal-risk and Mendelian-randomization "
        "evidence n=2, and treatment/intervention-response evidence n=1; receipt-level "
        "directions positive=2, null=1, unclear=3. These source patterns support bounded "
        "risk-marker, causal, mechanistic, or treatment-response hypotheses and do not "
        "establish standalone clinical actionability.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_unmet_requires_full_corpus_sources_in_result_sections() -> None:
    ask = (
        "Add the missing bundle sources to the Results outcome slices (Andreikos 2024, "
        "Chen 2023, Wan 2023) so the evidence map covers the full admitted corpus."
    )
    weak = (
        "## Evidence Landscape\n\n"
        "### Findings Map\n\n"
        "- Andreikos 2024: outcome=Frailty; direction=null; directness=indirect; tier=B2.\n"
        "- Chen 2023: outcome=Cancer Risk; direction=mixed; directness=review; tier=B1.\n"
        "- Wan 2023: outcome=Mechanism; direction=unclear; directness=mechanistic; tier=C1.\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis:\n\n"
        "- Andreikos 2024: outcome=Frailty; direction=null; directness=indirect; tier=B2.\n"
    )
    repaired = weak + (
        "- Chen 2023: outcome=Cancer Risk; direction=mixed; directness=review; tier=B1.\n"
        "- Wan 2023: outcome=Mechanism; direction=unclear; directness=mechanistic; tier=C1.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_unmet_flags_unclear_table_vs_positive_negative_narrative() -> None:
    ask = (
        "Reconcile the Evidence Landscape table signals (predominantly 'unclear') with the "
        "narrative claims of positive/negative signals in each outcome section."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Signal |\n|---|---|\n| HRV | predominantly unclear |\n\n"
        "## Results\n\nPositive/negative signals are emphasized in the outcome sections.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_unclear_table_reconciled_with_narrative() -> None:
    ask = (
        "Reconcile the Evidence Landscape table signals (predominantly 'unclear') with the "
        "narrative claims of positive/negative signals in each outcome section."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Signal |\n|---|---|\n| HRV | predominantly unclear |\n\n"
        "## Results\n\nPositive/negative signals are separately reported in other outcome classes; "
        "directional coding for the HRV row is reconciled and does not mean absence of support.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_null_coded_directional_reconciliation() -> None:
    ask = (
        "Resolve the disconnect between the '47/48 null-coded' framing and the clearly directional "
        "findings visible in the source bundle excerpts."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class. Positive and mixed "
        "signals in other outcome classes are separately reported.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_removed_unbundled_citations() -> None:
    ask = (
        "Remove or add to the source bundle the citations Ioannidis 2005, Studenski 2011, "
        "and Perera 2006, which appear in the prose but are not in the source_bundle list."
    )
    paper = "## References\n\n- **Huang 2025.** Registry-backed source.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_replaced_structured_table_stubs() -> None:
    ask = (
        "Replace the 'See the structured evidence table' stubs with one or two short prose "
        "paragraphs per outcome class that name the specific sources driving the dominant signal."
    )
    paper = (
        "## Results\n\n"
        "The frailty slice is driven by Sanz 2021, with no second same-outcome source to "
        "create a direct disagreement. The muscle-function slice is driven by Correa 2022 "
        "and Oliveira 2026, while the broader clinical bridge remains uncertain.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_requires_consistent_source_count_bundle_reconciliation() -> None:
    ask = (
        "Reconcile the in-text source count (52) with the actual source bundle and either "
        "restore missing bundle entries or correct the count; for every named author-year "
        "citation in the prose, verify a plausible bundle counterpart exists."
    )
    reconciled = (
        "## Methods\n\n"
        "Of 172 records in the receipt-candidate union, 52 were classified as source "
        "candidates and 52 were admitted as traceable synthesis sources. The source bundle "
        "therefore contains 52 references with DOI/PMID traceability where available; "
        "author-year citations in the prose are matched to the reference list.\n"
    )
    inconsistent = reconciled + "\n## Results\n\nThis paper synthesizes 49 included sources.\n"

    assert revision_coverage.deterministic_unmet_asks(reconciled, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(inconsistent, [ask]) == [ask]


def test_deterministic_unmet_accepts_citation_traceability_map_note() -> None:
    ask = (
        "Provide a complete, auditable in-text citation list mapping every author-year "
        "prose reference to a specific source bundle entry; add a methods_pack.json-style "
        "table or appendix in the manuscript itself so the reader can verify grounding "
        "without external artifacts."
    )
    missing = "## Evidence Snapshot\n\n### Source Classification Map\n\n- Smith 2024: outcome=frailty.\n"
    repaired = (
        "## Evidence Snapshot\n\n"
        "Citation traceability map: author-year prose citations are reconciled to specific "
        "source-bundle entries in the in-manuscript Source Classification Map and References "
        "section; `manifest.json`, `citation_registry.json`, and `methods_pack.json` provide "
        "the complete machine-readable mapping.\n\n"
        "### Source Classification Map\n\n- Smith 2024: outcome=frailty.\n\n"
        "## References\n\n- **Smith 2024.** Example source.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(missing, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_unmet_accepts_concrete_tensions_and_gap_priority() -> None:
    ask = (
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions "
        "(e.g. source A vs source B) and tie each to specific sources."
    )
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "### Load-Bearing Tensions\n\n"
        "- Severity 5 disagreement: Paradoxical 2026 vs Nong 2025; the sources report opposing longevity directions.\n"
        "- Severity 5 disagreement: Pei 2023 vs Gan 2026; the sources disagree on safety comorbidity direction.\n"
        "- Severity 5 disagreement: Zhuang 2025 vs Zeng 2025; the sources conflict on deficiency prevalence.\n\n"
        "### Evidence-Gap Priority\n\n"
        "| Priority | Gap | Rationale |\n|---|---|---|\n| P1 | longevity conflict-resolution gap | opposing source directions |\n\n"
        "## References\n\nParadoxical 2026. Nong 2025. Pei 2023. Gan 2026. Zhuang 2025. Zeng 2025.\n"
    )
    weak = (
        "## Cross-Domain Synthesis\n\n"
        "There are several tensions. Future research should resolve the gaps.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]


def test_deterministic_unmet_accepts_specific_cross_source_disagreements() -> None:
    ask = (
        "Expand the Tensions and Gaps section to enumerate at least three specific "
        "cross-source disagreements with named sources on each side."
    )
    paper = (
        "## Evidence Landscape\n\nGrazuleviciene 2026, Durstenfeld 2026, Salerno 2026, "
        "Riquelme-Hernandez 2026, Liu 2025, and Garcia 2026 are retained.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: cross-source disagreement counts are manifest-derived.\n"
        "- Grazuleviciene 2026 vs Durstenfeld 2026: surfaced tension/disagreement in Cardiometabolic because directions are null versus unclear.\n"
        "- Salerno 2026 vs Riquelme-Hernandez 2026: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are unclear versus null.\n"
        "- Liu 2025 vs Garcia 2026: surfaced tension/disagreement in Frailty because directions are unclear versus null.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_tension_count_does_not_treat_three_year_followup_as_three_pairs() -> None:
    ask = "Use three-year follow-up and describe a concrete cross-source tension."
    paper = (
        "## Evidence Landscape\n\nSmith 2024 and Jones 2025 are retained.\n\n"
        "## Tensions and Gaps\n\nEvidence-gap priority: direct replication.\n"
        "- Smith 2024 vs Jones 2025: surfaced tension/disagreement in function.\n"
    )
    assert revision_coverage._concrete_tensions_gaps_are_stated(paper, ask)

    three_pair_ask = "Enumerate at least three specific, named cross-source disagreements."
    assert not revision_coverage._concrete_tensions_gaps_are_stated(paper, three_pair_ask)

    long_ask = (
        "Enumerate three specific, named, semantically comparable, within-outcome "
        "source pairs."
    )
    assert not revision_coverage._concrete_tensions_gaps_are_stated(paper, long_ask)

    duplicates = paper + paper + paper
    assert not revision_coverage._concrete_tensions_gaps_are_stated(duplicates, three_pair_ask)


def test_tension_count_rejects_self_pairs_and_untraced_citations() -> None:
    ask = "Enumerate at least three named source pairs."
    paper = (
        "## Evidence Landscape\n\nSmith 2024 and Jones 2025 are retained.\n\n"
        "## Tensions and Gaps\n\nEvidence-gap priority: direct replication.\n"
        "- Smith 2024 vs Smith 2024: surfaced tension/disagreement in function.\n"
        "- Fake 2023 vs Invented 2022: surfaced tension/disagreement in function.\n"
        "- Jones 2025 vs Imaginary 2021: surfaced tension/disagreement in function.\n"
    )
    assert not revision_coverage._concrete_tensions_gaps_are_stated(paper, ask)


def test_negated_disagreement_feedback_is_not_a_tension_request() -> None:
    for ask in (
        "The studies do not disagree.",
        "There is no disagreement among retained sources.",
        "No source disagreement was found.",
        "No cross-study tension exists.",
        "Source disagreement is not present and should not be invented.",
        "Studies agree rather than disagree.",
        "Source disagreement should not be fabricated.",
        "Do not fabricate source disagreement.",
    ):
        assert not revision_coverage._asks_concrete_tensions_gaps(ask.lower())


def test_tension_pairs_accept_particle_apostrophe_and_year_suffix_labels() -> None:
    ask = "Enumerate at least three named cross-source disagreements."
    labels = {"O'Connor 2024", "van der Meer 2025", "Smith 2024a", "Lee 2023"}
    paper = (
        "## Evidence Landscape\n\n" + ", ".join(sorted(labels)) + ".\n\n"
        "## Tensions and Gaps\n\nEvidence-gap priority: direct replication.\n"
        "- O'Connor 2024 vs van der Meer 2025: endpoint disagreement.\n"
        "- Smith 2024a vs Lee 2023: endpoint disagreement.\n"
        "- O'Connor 2024 vs Smith 2024a: endpoint disagreement.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(
        paper, [ask], retained_citations=labels,
    ) == []


def test_tension_pairs_accept_title_and_pmcid_labels() -> None:
    ask = "Enumerate at least three named cross-source disagreements."
    labels = {
        "Impact of Fasting 2025", "Response to Intervention 2024",
        "PMC1234567 2023", "Smith 2024",
    }
    paper = (
        "## Evidence Landscape\n\n" + ", ".join(sorted(labels)) + ".\n\n"
        "## Tensions and Gaps\n\nEvidence-gap priority: direct replication.\n"
        "- Impact of Fasting 2025 vs Response to Intervention 2024: endpoint disagreement.\n"
        "- PMC1234567 2023 vs Smith 2024: endpoint disagreement.\n"
        "- Impact of Fasting 2025 vs PMC1234567 2023: endpoint disagreement.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(
        paper, [ask], retained_citations=labels,
    ) == []


def test_retained_citation_labels_include_title_and_pmcid_fields() -> None:
    manifest = {"receipts": [{
        "source_title": "Impact of Fasting 2025",
        "source_pmcid": "PMC1234567 2023",
    }]}
    assert revision_coverage.retained_citation_labels(manifest) == {
        "impact of fasting 2025", "pmc1234567 2023",
    }


def test_tension_coverage_rejects_labels_absent_from_retained_receipts() -> None:
    ask = "Enumerate at least three named cross-source disagreements."
    paper = (
        "## Evidence Landscape\n\nFake 2024, Invented 2023, Jones 2025, Smith 2024 are discussed.\n\n"
        "## Tensions and Gaps\n\nEvidence-gap priority: direct replication.\n"
        "- Fake 2024 vs Invented 2023: surfaced tension/disagreement in function.\n"
        "- Jones 2025 vs Smith 2024: surfaced tension/disagreement in function.\n"
        "- Fake 2024 vs Jones 2025: surfaced tension/disagreement in function.\n"
    )
    assert revision_coverage.deterministic_unmet_asks(
        paper, [ask], retained_citations={"Jones 2025", "Smith 2024"},
    ) == [ask]
    for wording in (
        "Enumerate at least three named source-pair disagreements.",
        "List three concrete conflicting source pairs.",
        "Identify study pairs that disagree, at least three.",
        "Provide conflicting study pairs, at least three.",
        "Provide three author-year contrasts showing disagreement.",
        "Name three pairs of retained sources that disagree.",
        "Show three conflicting source pairs.",
        "Give three study pairs that disagree.",
        "Describe three pairs among retained sources.",
        "Provide three contrasts between retained sources.",
    ):
        assert revision_coverage.deterministic_unmet_asks(
            paper, [wording], retained_citations=set(),
        ) == [wording]


def test_deterministic_unmet_requires_replaced_surface_tensions() -> None:
    ask = (
        "Replace the three Curran 2025-based 'surfaced tensions' with genuinely "
        "comparable within-outcome tensions. A cross-species, cross-population, "
        "cross-endpoint disagreement is not a meaningful tension to surface."
    )
    stale = (
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: unresolved.\n"
        "- Zhao 2024 vs Curran 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus positive.\n"
        "- Pei 2024 vs Curran 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus positive.\n"
        "- Zhao 2024 vs Ministrini 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are negative versus null.\n"
    )
    repaired = (
        "## Evidence Landscape\n\nKatayoshi 2023, Martens 2018, Yi 2022, Simic 2020, "
        "Gao 2025, and Simon 2024 are retained.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: within-outcome contrasts remain.\n"
        "- Katayoshi 2023 vs Martens 2018: surfaced tension/disagreement in Cardiometabolic because directions are null versus unclear.\n"
        "- Yi 2022 vs Simic 2020: surfaced tension/disagreement in Dosing Pharmacokinetics because directions are unclear versus null.\n"
        "- Gao 2025 vs Simon 2024: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are null versus unclear.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(stale, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_known_accepts_auditable_tension_and_source_verdict_asks() -> None:
    asks = [
        "Define and operationalize the '727 non-orthogonal tensions' figure: show the calculation, restrict to verifiable within-class disagreement pairs, or remove the claim if it cannot be auditable.",
        "Expand the Tensions and Gaps section to enumerate the cross-study contradictions actually discussed in the body rather than restating a generic call for future trials.",
        "Provide a one-line directness/direction verdict per cited source in the Findings Map rather than collapsing to 'no extracted directional signal in X/N sources,' so readers can trace each mapped claim to its coded outcome.",
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "Source directness breakdown: 1/3 retained sources directly address the stated topic and hard endpoints; "
        "2/3 are adjacent, contextual, review-level, or mechanistic.\n\n"
        "### Findings Map\n\n"
        "- Smith 2024: outcome=cardiometabolic; direction=positive; directness=direct; tier=A1; finding=representative statistic p = 0.04.\n"
        "- Jones 2025: outcome=cardiometabolic; direction=null; directness=review; tier=B1; finding=12 extracted claim(s).\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: cross-study disagreement counts are manifest-derived claim-level counts.\n"
        "- Smith 2024 vs Jones 2025: surfaced tension/disagreement in Cardiometabolic because directions are positive versus null.\n"
        "- Patel 2023 vs Chen 2022: surfaced tension/disagreement in Immune because directions are mixed versus negative.\n"
        "- Lee 2021 vs Rao 2020: surfaced tension/disagreement in Safety because directions are unclear versus null.\n"
    )

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_coverage_accepts_vascular_source_level_revision_bundle() -> None:
    feedback = (
        "Recode directional findings to match source abstracts; remove/qualify 11/13 null framing as receipt-level not source-level; "
        "Include all 13 admitted sources in Evidence Landscape tables; remove repetitive boilerplate and replace with findings; "
        "Enumerate the 12 cross-study disagreements or replace the count with a qualitative description of where the disagreements lie; "
        "Expand Key Findings with concrete bounded findings per outcome class from source abstracts; "
        "Strengthen Gaps with at least 3 concrete actionable studies."
    )
    asks = revision_coverage.revision_asks(feedback)
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class. Positive and mixed "
        "signals in other outcome classes are separately reported.\n\n"
        "Substantive evidence synthesis: The manifest includes 13 retained sources, 1 direct-source "
        "row, and receipt-level directional coding across null=8, positive=1, unclear=4. "
        "Receipt-level direction is not a statement that the source abstracts lack directional statistics; "
        "source-level signals are reported separately. No extracted directional signal is a receipt-level "
        "code proportion (8/13), not absence of source-level support. Retained sources also include "
        "Rodilla 2026, Luo 2025, Lu 2026, and Vicente-Gabriel 2024.\n\n"
        "### Findings Map\n\n"
        "- Sheng 2025: outcome=Contextual Adjacent Evidence; direction=null; directness=indirect; "
        "tier=B2; finding=representative statistic p < 0.001; source-level statistic reported.\n"
        "- Wang 2024: outcome=Cardiometabolic; direction=positive; directness=direct; "
        "tier=A1; finding=representative statistic p < 0.05; source-level statistic reported.\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis: First, the strongest source-level signals are bounded "
        "rather than broad clinical proof (Wang 2024: outcome=Cardiometabolic; direction=positive; "
        "directness=direct; tier=A1; finding=representative statistic p < 0.05; source-level statistic reported). "
        "Source-level findings by outcome class: Cardiometabolic: Wang 2024 "
        "(representative statistic p < 0.05; direction=positive; directness=direct; tier=A1). "
        "Second, null and unclear receipt-level rows are given equal interpretive weight. "
        "Synthesis interpretation: source-level findings connect risk-marker, mechanistic, and intervention-adjacent "
        "signals into follow-up hypotheses. "
        "The bounded conclusion follows from the balance of source direction, outcome class, "
        "evidence tier, and directness rather than from source count alone.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: cross-study disagreement counts are manifest-derived claim-level counts.\n"
        "- Wang 2024 vs Rodilla 2026: surfaced tension/disagreement in Cardiometabolic because directions are positive versus null.\n"
        "- Luo 2025 vs Lu 2026: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are null versus unclear.\n"
        "- Sheng 2025 vs Vicente-Gabriel 2024: surfaced tension/disagreement in Contextual Adjacent Evidence because directions are null versus unclear.\n\n"
        "## Gaps Identified\n\n"
        "1. Run adequately powered prospective trials in the priority population with prespecified clinical endpoints and at least 2-year follow-up.\n"
        "2. Standardize exposure, comparator, dose, measurement timing, and endpoint definitions before attempting pooled effects.\n"
        "3. Add safety endpoints in direct human studies with patient-relevant function measures.\n"
    )

    assert asks == [
        "Recode directional findings to match source abstracts; remove/qualify 11/13 null framing as receipt-level not source-level.",
        "Include all 13 admitted sources in Evidence Landscape tables; remove repetitive boilerplate and replace with findings.",
        "Enumerate the 12 cross-study disagreements or replace the count with a qualitative description of where the disagreements lie.",
        "Expand Key Findings with concrete bounded findings per outcome class from source abstracts.",
        "Strengthen Gaps with at least 3 concrete actionable studies.",
    ]
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_coverage_accepts_surface_every_admitted_source_feedback() -> None:
    ask = "Surface every admitted source; redesign outcome taxonomy; recode direction values."
    paper = (
        "## Evidence Landscape\n\n"
        "### Findings Map\n\n"
        "- Smith 2026: outcome=Immune and Inflammation; direction=null; directness=adjacent; tier=B2.\n"
        "- Jones 2025: outcome=Mechanistic Signaling; direction=mixed; directness=mechanistic; tier=C1.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_coverage_accepts_human_intervention_reclassification_feedback() -> None:
    ask = "Human intervention studies were misclassified as indirect/review evidence."
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Classification Map\n\n"
        "- Trialists 2026: outcome=Clinical Intervention; direction=mixed; directness=direct; tier=A1.\n"
        "- Reviewers 2025: outcome=Contextual Adjacent Evidence; direction=unclear; directness=review; tier=B2.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_coverage_accepts_ramadan_revision_bundle() -> None:
    asks = [
        "Reconcile directional-coding counts within each Findings Map subsection so n/direction/directness totals are internally consistent.",
        "For each outcome class, explicitly list every admitted source (by cited_as) with direction/directness, not just representatives.",
        "Reclassify Mabrouk 2025 as a deficiency prevalence/context source rather than a hypothesis test; Tone down Metabolic-Functional Tradeoff/falsifying-test framing to an explicitly bounded interpretive note.",
        "Remove/replace Ioannidis 2005 citation with a bundle-resident source because it is not present in the source bundle.",
        "Verify/flag future-dated sources (Demirli 2026, Tasdemir 2026, Lamti 2026).",
        "Ensure cited numbers in Findings Map descriptions appear in each cited source abstract rather than only receipt level.",
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "Findings Map accounting note: Each Findings Map subsection uses internally consistent "
        "n/direction/directness totals; cited numbers below are sourced to source abstracts "
        "rather than receipt-level-only counts.\n\n"
        "### Findings Map\n\n"
        "| Evidence domain | Source | Direction | Directness | Tier | Evidence role | Finding |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| Deficiency Prevalence | Mabrouk 2025 | direction=unclear | directness=indirect | B2 | outcome=Deficiency Prevalence | finding=representative statistic p = 0.017; source-level statistic reported. |\n"
        "| Ramadan Safety | Demirli 2026 | direction=mixed | directness=adjacent | B2 | outcome=Safety | finding=representative statistic p = 0.041; source-level statistic reported. |\n"
        "| Metabolic Context | Tasdemir 2026 | direction=null | directness=adjacent | B2 | outcome=Metabolic Context | finding=representative statistic p = 0.62; source-level statistic reported. |\n\n"
        "Where reviewers might invoke an interpretive note such as a metabolic-functional trade-off "
        "or falsifying-test, the bundle supplies no direct evidence supporting either as a "
        "paper-level organizing claim; any such framing is bounded to context pending corroboration.\n\n"
        "## Limitations\n\n"
        "Publication-year note: citation years follow the manifest metadata; when DOI/PubMed dates "
        "differ, the source should be treated as bibliographic/in-press metadata and not used for "
        "year-specific claims.\n"
    )

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_coverage_accepts_vascular_latest_reviewer_asks() -> None:
    asks = [
        "Write an actual Key Findings section that names 3-5 specific, source-anchored findings and then interpret them as hypotheses worth follow-up.",
        "Add a synthesis paragraph that connects across outcome classes.",
        "Reconcile or flag the 2026 publication-year citations with their 2025 DOI/PubMed dates, or move them to in press status with a note.",
        "Specify what kinds of cross-study disagreement the 12 disagreements represent.",
        "Tighten the conclusion to distinguish contextual evidence from a viable geroscience intervention target.",
    ]
    paper = (
        "## Evidence Landscape\n\n"
        "Substantive evidence synthesis: The manifest includes 13 retained sources. "
        "Receipt-level direction is not a statement that the source abstracts lack directional statistics.\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis:\n\n"
        "Source-level findings by outcome class:\n\n"
        "- Contextual Adjacent Evidence: Sheng 2025 (estimated pulse wave velocity and coronary artery disease; "
        "finding=representative statistic p < 0.001; direction=null; directness=indirect; tier=B2).\n"
        "- Cardiometabolic: Wang 2024 (Tai Chi RCT; finding=representative statistic p < 0.05; "
        "direction=unclear; directness=direct; tier=A1).\n\n"
        "- Sheng 2025: estimated pulse wave velocity and coronary artery disease; "
        "finding=representative statistic p < 0.001; outcome=Contextual Adjacent Evidence; "
        "direction=null; directness=indirect; tier=B2.\n"
        "- Luo 2025: L-citrulline supplementation and arterial stiffness; "
        "finding=representative statistic p = 0.0007; outcome=Contextual Adjacent Evidence; "
        "direction=null; directness=review; tier=B2.\n\n"
        "Synthesis interpretation: source-level findings connect risk-marker, mechanistic, and "
        "intervention-adjacent signals into follow-up hypotheses. The bounded conclusion follows "
        "from source direction, outcome class, evidence tier, and directness rather than from source count alone. "
        "Publication-year note: citation years follow the manifest metadata; when DOI/PubMed dates differ, "
        "the source should be treated as bibliographic/in-press metadata and not used for year-specific claims.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: cross-study disagreement counts are manifest-derived claim-level counts.\n"
        "- Sheng 2025 vs Luo 2025: surfaced tension/disagreement in Contextual Adjacent Evidence because "
        "directions are null versus unclear; this reflects endpoint, population, directness, or study-design heterogeneity.\n"
        "- Wang 2024 vs Azizzadeh 2026: surfaced tension/disagreement in Cardiometabolic because "
        "directions are null versus null; this reflects endpoint, population, directness, or study-design heterogeneity.\n"
        "- Nguyen 2026 vs Alanis 2025: surfaced tension/disagreement in Mechanism because "
        "directions are null versus null; this reflects endpoint, population, directness, or study-design heterogeneity.\n\n"
        "## Conclusion\n\n"
        "The current corpus is non-supportive for clinical efficacy claims. It is not proof of a viable "
        "geroscience intervention target; it supports only hypothesis generation and structured follow-up.\n"
    )

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_revision_asks_splits_latest_vascular_feedback_starts() -> None:
    feedback = (
        "Populate Key Findings and each per-outcome-class subsection with concrete prose "
        "that names individual cited sources.; Reconcile the outcome-class directional "
        "coding with the actual source bundle.; Rewrite the Search Summary to describe "
        "the actual selection logic.; In Limitations, add a specific statement about "
        "forward-dated citations.; Tighten the Conclusion so that the tiered reading is "
        "grounded in named source-level findings."
    )

    asks = revision_coverage.revision_asks(feedback)

    assert [ask.split(" ", 1)[0] for ask in asks] == [
        "Populate", "Reconcile", "Rewrite", "In", "Tighten",
    ]
    assert revision_coverage.deterministic_known_asks(asks[:3]) == asks[:3]


def test_forward_dated_ai_disclosure_ask_accepts_methods_relocation() -> None:
    ask = (
        "In Limitations, add a specific statement about forward-dated (2026) "
        "citations and the implications for reproducibility, and remove or "
        "relocate the AI-use disclosure so it does not crowd the substantive sections."
    )
    paper = (
        "## Methods\n\n"
        "### AI-use disclosure\n\n"
        "Source retrieval and prose drafting were assisted by large language models "
        "under a deterministic audit-trail protocol.\n\n"
        "## Results\n\n"
        "The evidence map is summarized.\n\n"
        "## Limitations\n\n"
        "Forward-dated 2026 citations are retained only as bibliographic/in-press "
        "metadata; their reproducibility implications are bounded by the dated "
        "source records and they are not used for year-specific claims.\n\n"
        "## Conclusion\n\n"
        "The synthesis remains hypothesis-generating.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_forward_dated_ai_disclosure_ask_flags_crowded_limitations() -> None:
    ask = (
        "In Limitations, add a specific statement about forward-dated (2026) "
        "citations and the implications for reproducibility, and remove or "
        "relocate the AI-use disclosure so it does not crowd the substantive sections."
    )
    paper = (
        "## Limitations\n\n"
        "Forward-dated 2026 citations are retained only as bibliographic/in-press "
        "metadata; their reproducibility implications are bounded by the source records.\n\n"
        "### AI-use disclosure\n\n"
        "Source retrieval and prose drafting were assisted by large language models.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_specific_findings_by_source_map() -> None:
    ask = (
        "For each outcome class, extract at least 2-3 specific findings from "
        "individual cited sources (study design, population, effect direction, "
        "effect size where available) and present them in prose, not just in the "
        "coding tally."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Findings Map\n\n"
        "- Smith 2024: outcome=Cardiometabolic; direction=mixed; directness=indirect; "
        "tier=B2; finding=12 extracted claim(s); receipt-level direction is the coded finding.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_key_findings_source_verdict_ask_accepts_structured_source_synthesis() -> None:
    ask = (
        "Replace the Key Findings section with distinct, evidence-tied findings: "
        "for each outcome class, state what the retained sources show (with at "
        "least one effect size or directional statement per source), rather than "
        "restating the conclusion."
    )
    paper = (
        "## Key Findings\n\n"
        "Key findings from source synthesis: First, the strongest source-level "
        "signals are bounded rather than broad clinical proof "
        "(Sun 2026: outcome=Cardiometabolic; direction=unclear; directness=review; "
        "tier=B1; claims=249; Shen 2026: outcome=Contextual Adjacent Evidence; "
        "direction=mixed; directness=review; tier=B1; claims=234). Second, negative "
        "and null rows are given equal interpretive weight.\n\n"
        "## Conclusion\n\n"
        "The conclusion stays bounded.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_revision_asks_splits_soften_and_mark_actions() -> None:
    feedback = (
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions; "
        "Soften or qualify the positive signal coding for single-source slices; "
        "Mark external non-corpus references as illustrative rather than bundle sources."
    )

    assert revision_coverage.revision_asks(feedback) == [
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions.",
        "Soften or qualify the positive signal coding for single-source slices.",
        "Mark external non-corpus references as illustrative rather than bundle sources.",
    ]


def test_revision_asks_splits_resolve_action_after_example_semicolon() -> None:
    feedback = (
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the claim; "
        "Resolve the source coding by stating the exact sample sizes."
    )

    assert revision_coverage.revision_asks(feedback) == [
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the claim.",
        "Resolve the source coding by stating the exact sample sizes.",
    ]


def test_revision_asks_splits_either_and_accepts_findings_map_revise_shape() -> None:
    feedback = (
        "Reconstruct the Findings Map so that each retained source has an explicit "
        "per-source direction on its primary outcome, with the specific effect "
        "estimate or qualitative finding attached.; "
        "Reconcile the abstract's '2 direct / 12 adjacent / 1 mechanistic' framing "
        "with the Findings Map's 'direct / indirect / mechanistic' framing, or "
        "define 'adjacent' and 'indirect' consistently across all sections.; "
        "Expand the Tensions and Gaps section to enumerate the specific 26 "
        "cross-study disagreements by pairing source A vs source B.; "
        "Either remove sources whose design is review/perspective/bioinformatics "
        "from the admitted direct-evidence counting, or relabel them and report "
        "RoB judgments for the admitted RCT and cohort sources."
    )
    paper = (
        "## Abstract\n\n"
        "The evidence profile contains 2 direct clinical sources, 12 adjacent "
        "clinical sources, and 1 mechanistic source.\n\n"
        "## Evidence Snapshot\n\n"
        "Source directness breakdown: 2/15 retained sources directly address the "
        "stated topic and aging-relevant hard endpoints; 13/15 are adjacent, "
        "contextual, review-level, or mechanistic and are used only to bound "
        "interpretation. Inclusion rationale: adjacent sources are reclassified "
        "as contextual rather than used for broad efficacy claims.\n\n"
        "### Findings Map\n\n"
        "- Smith 2024: outcome=Longevity; direction=positive; directness=direct; "
        "tier=A1; finding=representative statistic p = 0.04.\n"
        "- Jones 2025: outcome=Longevity; direction=null; directness=indirect; "
        "tier=B2; finding=12 extracted claim(s).\n\n"
        "Risk-of-bias appraisal summary: The public appraisal artifact reports "
        "2 source-level rating rows; overall ratings are low=1, some concerns=1.\n\n"
        "## Tensions and Gaps\n\n"
        "Evidence-gap priority: cross-study disagreement counts are manifest-derived.\n"
        "- Smith 2024 vs Jones 2025: surfaced tension/disagreement in Longevity because directions are positive versus null.\n"
        "- Patel 2023 vs Chen 2022: surfaced tension/disagreement in Immune because directions are mixed versus negative.\n"
        "- Lee 2021 vs Rao 2020: surfaced tension/disagreement in Safety because directions are unclear versus null.\n"
    )

    asks = revision_coverage.revision_asks(feedback)

    assert len(asks) == 4
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_unmet_requires_species_study_design_summary_table() -> None:
    ask = (
        "Differentiate the 17-source bundle by species and study design in one summary table "
        "(e.g., preclinical rodent n=, human n=) so readers can audit the claim."
    )
    prose_only = (
        "## Evidence Landscape\n\n"
        "The bundle includes preclinical rodent studies and human cohort evidence, "
        "so species and study design are mixed.\n"
    )
    tabled = (
        "## Evidence Landscape\n\n"
        "### Species and Study-Design Summary\n\n"
        "| Evidence group | Study-design signal | n | Example sources | Interpretation boundary |\n"
        "|---|---|---:|---|---|\n"
        "| Preclinical rodent n=12 | animal/preclinical experiment | 12 | Smith 2024 | Mechanistic only. |\n"
        "| Human n=2 | observational/donor or cohort evidence | 2 | Parker 2020 | Association only. |\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(prose_only, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(tabled, [ask]) == []


def test_deterministic_unmet_accepts_single_source_map_caveats() -> None:
    ask = (
        "Soften or qualify the 'positive signal' coding for single-source slices "
        "(Dosing/PK, Frailty, Skeletal/Bone) and add explicit hypothesis-generating caveats in the map."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome | Evidence |\n|---|---|\n"
        "| Dosing and Pharmacokinetics | n=1; positive signal; single-source slice; hypothesis-generating |\n"
        "| Frailty | n=1; positive signal; single-source slice; hypothesis-generating |\n"
        "| Skeletal, Fracture, and Bone | n=1; null signal; single-source slice; hypothesis-generating |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_claim_count_audit_note() -> None:
    ask = (
        "Audit the claim count for the Dosing and Pharmacokinetics slice "
        "(79 claims attributed to one mouse PK study) against the claim registry "
        "and report the corrected number, or explain the claim-derivation protocol if 79 is accurate."
    )
    weak = "## Evidence Landscape\n\nDosing and Pharmacokinetics contains 79 claims.\n"
    repaired = (
        "## Evidence Landscape\n\n"
        "Claim-count audit note: The Dosing and Pharmacokinetics slice count is derived "
        "from the claim registry. The claim-derivation protocol counts extracted claim "
        "records, not independent studies: 1 retained source contributes 79 extracted "
        "claim(s) in this slice. A high count from one source is therefore interpreted "
        "as source-bounded density, not independent studies or pooled effect certainty.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_unmet_accepts_source_identifier_gap_note() -> None:
    ask = (
        "Add an explicit verification-gap note for sources without DOIs, distinguishing "
        "them from peer-reviewed sources in the source-context map."
    )
    weak = "## Evidence Landscape\n\nThe source-context map lists all retained rows.\n"
    repaired = (
        "## Evidence Landscape\n\n"
        "Source-context verification gap: 2 source-bundle records have no DOI, PMID, "
        "PMCID, or trial identifier in the available metadata. They remain traceable "
        "source-bundle records, but are distinguished from externally identifier-verified "
        "peer-reviewed sources in the source-context map and do not independently upgrade "
        "evidence certainty.\n"
    )

    assert revision_coverage.deterministic_known_asks([ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(repaired, [ask]) == []


def test_deterministic_unmet_accepts_combination_product_positive_signal_boundary() -> None:
    ask = (
        "Reclassify or re-label the 'immune and inflammation positive signal' as a "
        "combination-product signal, not a spermidine-monotherapy signal; add a single "
        "sentence in the Findings Map table and Results Summary flagging that the 2/3 "
        "positive sources include one combination-product RCT and one preclinical GWI "
        "mouse model."
    )
    paper = (
        "## Results Summary\n\n"
        "The Felix 2024 RCT used a combination product containing spermidine and "
        "hesperidin, so its positive immune/inflammation findings cannot be attributed "
        "to spermidine monotherapy. Trivedi 2026 is a Gulf War Illness mouse model and "
        "is therefore not a human clinical confirmation.\n"
    )
    weak = (
        "## Results Summary\n\n"
        "The immune and inflammation outcome class contains positive spermidine signals.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]


def test_deterministic_unmet_accepts_external_references_marked_illustrative() -> None:
    ask = (
        "Mark external non-corpus references (e.g. Ioannidis 2005) as illustrative "
        "rather than bundle sources, or remove them."
    )
    paper = (
        "## Discussion\n\n"
        "The surrogate-endpoint caution that Ioannidis 2005 frames as a general "
        "methodological problem is used here only as an illustrative benchmark, "
        "not as a source-bundle claim.\n"
    )
    unmarked = "## Discussion\n\nIoannidis 2005 shows the central result.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(unmarked, [ask]) == [ask]


def test_deterministic_unmet_accepts_thin_brief_revision_surface_notes() -> None:
    asks = [
        "Add substantive narrative under each outcome subsection (Contextual Adjacent Evidence, Cardiometabolic, Deficiency Prevalence, Longevity, Mechanism, Safety and Comorbidity) that links at least one specific quantitative or qualitative finding to its source, or explicitly state null/mechanistic-only status; In the Conclusion, tie the tiered interpretation to the specific bundle: name which 1 direct source carries the most interpretive weight and explain why the remaining 12 sources do not change that weight.",
        "Expand the Limitations to specifically note that several admitted sources are protocols or cross-sectional observational designs that cannot support causal claims even individually.",
    ]
    weak = (
        "## Results\n\n"
        "| Evidence domain | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Vascular age / Cardiometabolic | n=1 | null | 1 direct | thin |\n\n"
        "### Source Classification Map\n\n"
        "- Wang 2024: outcome=cardiometabolic; directness=direct; tier=A1; direction=null.\n\n"
        "## Limitations\n\nThin corpus.\n\n"
        "## Conclusion\n\nThe conclusion is bounded.\n"
    )
    repaired = weak.replace(
        "## Results\n\n",
        "## Results\n\n"
        "Source examples: Cardiometabolic: Wang 2024 (tier=A1; directness=direct; direction=null).\n\n",
    ).replace(
        "## Limitations\n\nThin corpus.\n",
        "## Limitations\n\n"
        "**Design-limit note:** Protocol, mechanistic, observational, or cross-sectional sources "
        "are retained for context but cannot support causal claims individually.\n\n"
        "Thin corpus.\n",
    ).replace(
        "## Conclusion\n\nThe conclusion is bounded.\n",
        "## Conclusion\n\n"
        "**Direct-source ceiling:** The direct clinical source set is Wang 2024. "
        "The remaining accepted sources are indirect, review, protocol, mechanistic, "
        "or contextual evidence and do not outweigh the direct-source interpretation.\n\n"
        "The conclusion is bounded.\n",
    )

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(weak, asks) == asks
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_latest_telomere_post_submit_feedback_splits_into_material_asks() -> None:
    feedback = (
        "Populate the Key Findings section with a concrete bullet list tied to the explicit "
        "outcome-class slices, naming which sources support each bullet; Restate the research "
        "question to match the two-part claim in the abstract (prognostic value of shorter LTL "
        "for survival; causal-risk direction of genetically predicted longer LTL) and explicitly "
        "answer both halves in the body; Reconcile the corpus-size claims (e.g., 'n=7 causal-risk/MR', "
        "'25 sources', 'n=17 contextual') with the actual supplied bundle and the funnel counts; "
        "correct any overcounts or label them as 'classified' vs 'admitted' consistently; Move "
        "direction-coding 'unclear' status to a more visible position in the narrative so readers "
        "know that the bulk of significant statistics in this corpus are polarity-unsigned at extraction; "
        "Reduce redundant repetition of the evidence-honesty note across Abstract, Research Question, "
        "and Conclusion."
    )

    asks = revision_coverage.revision_asks(feedback)

    assert len(asks) == 5
    assert [ask.split(" ", 1)[0] for ask in asks] == ["Populate", "Restate", "Reconcile", "Move", "Reduce"]
    assert revision_coverage.deterministic_known_asks(asks) == asks


def test_latest_telomere_post_submit_feedback_requires_strict_markers() -> None:
    asks = revision_coverage.revision_asks(
        "Populate the Key Findings section with a concrete bullet list tied to the explicit "
        "outcome-class slices, naming which sources support each bullet; Restate the research "
        "question to match the two-part claim in the abstract (prognostic value of shorter LTL "
        "for survival; causal-risk direction of genetically predicted longer LTL) and explicitly "
        "answer both halves in the body; Reconcile the corpus-size claims with the actual supplied "
        "bundle and the funnel counts; Move direction-coding 'unclear' status to a more visible "
        "position in the narrative; Reduce redundant repetition of the evidence-honesty note."
    )
    weak = (
        "## Research Question\n\n"
        "For Telomere Cancer Effects, what does retained evidence show about prognostic or "
        "risk-marker associations across outcome classes?\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis: Sasmita 2025: outcome=Contextual Adjacent Evidence; "
        "direction=unclear; directness=review.\n\n"
        "## Conclusion\n\n"
        "Substantive conclusion: the retained source set shows causal-risk and Mendelian-randomization "
        "evidence n=7. Evidence-honesty note: bounded.\n\n"
        "## Abstract\n\nEvidence-honesty note: bounded.\n"
    )
    repaired = (
        "## Abstract\n\nEvidence-honesty note: bounded.\n\n"
        "## Research Question\n\n"
        "Two-part research question: (1) Does the retained evidence address prognostic value of shorter "
        "LTL for survival? (2) Does the retained evidence address genetically predicted longer LTL and "
        "cancer risk? The synthesis answers both halves using admitted source counts, manifest "
        "outcome-class slices, direction coding, tier, and directness limits.\n\n"
        "## Key Findings\n\n"
        "Direction-coding visibility note: 17/25 admitted sources are coded unclear at receipt level.\n\n"
        "Corpus-count reconciliation: count-bearing slices use manifest outcome classes from admitted "
        "sources; classified source candidates and admitted source counts are not interchangeable.\n\n"
        "Outcome-class key findings:\n\n"
        "- Contextual Adjacent Evidence: admitted n=17; direction coding unclear=15/null=2; "
        "directness review=5/indirect=12; supported by Sasmita 2025 and Markozannes 2022.\n\n"
        "## Conclusion\n\n"
        "Substantive conclusion: the retained source set shows 25 sources across Contextual Adjacent "
        "Evidence admitted n=17 and Mortality Survival admitted n=3; receipt-level directions "
        "unclear=17, null=5, positive=2, negative=1.\n"
    )

    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_scope_framing_and_direction_tally_audit_are_structural_asks() -> None:
    feedback = (
        "Resolve the scope framing. Either retitle and reframe the evidence map as "
        "'Clinical applications across heterogeneous indications' and drop the anti-aging "
        "framing, or restrict the map to aging-relevant evidence; Make the directional "
        "tallies auditable. Provide, in the supplement or inline, the per-source "
        "direction/directness/tier table so counts in the prose can be verified against "
        "the retained sources."
    )
    asks = revision_coverage.revision_asks(feedback)
    weak = "## Research Question\n\nWhat does this evidence map show?\n\n## Key Findings\n\n"
    repaired = (
        "## Research Question\n\n"
        "Scope-framing note: This evidence map frames the target intervention as clinical "
        "applications across heterogeneous indications rather than as standalone proof of broad "
        "longevity benefit. Aging-relevant interpretation is restricted to source rows whose "
        "metadata directly support it.\n\n"
        "## Key Findings\n\n"
        "Per-source direction/directness/tier audit table:\n\n"
        "| Source | Outcome class | Direction | Directness | Tier |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Boada 2020 | Contextual Adjacent Evidence | direction=mixed | directness=direct | tier=A1 |\n"
    )

    assert [ask.split(" ", 1)[0] for ask in asks] == ["Resolve", "Make"]
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_latest_telomere_second_revise_feedback_splits_and_requires_markers() -> None:
    feedback = (
        "Restructure outcome-class taxonomy to separate: (a) telomere length as cancer "
        "prognostic biomarker, (b) telomere length as incident cancer risk factor/MR/causal, "
        "(c) telomere biology mechanisms in tumor cells ALT/TERT, (d) treatment-induced "
        "telomere change, (e) telomere-targeted or supplement interventions. Current "
        "seven-class taxonomy mixes these.; Reconcile directional map with coded extraction: "
        "either re-extract/code directions for all sources, or remove per-class directional "
        "summary and state corpus is predominantly unclear-coded and does not support "
        "directional map.; Remove Jaeger 2024 from cancer-effects bundle or move to clearly "
        "labeled non-cancer evidence annex; healthy-volunteer supplement RCT not appropriate "
        "as direct contextual evidence for telomere-cancer effects.; Recode Ha 2023 in "
        "Mortality and Survival: EFS P=.903 no significant difference; classify null, not "
        "\"significant source statistic in 3/3 sources\", or define significant as \"source "
        "reports p-value.\"; Clarify admission funnel arithmetic: whether 41/8/48/20/3 buckets "
        "are mutually exclusive/overlapping/sequential; reconcile strict high-confidence=3 vs "
        "admitted final=25; explain why 25 not 3 source base.; Tighten conclusion so it does "
        "not present bounded risk-marker, causal, mechanistic, or treatment-response hypotheses "
        "as equally supported when corpus is skewed toward prognostic biomarker studies, MR risk "
        "and mechanistic ALT minority slices."
    )
    asks = revision_coverage.revision_asks(feedback)
    weak = (
        "## Evidence Landscape\n\nThe corpus is heterogeneous.\n\n"
        "## Key Findings\n\nThe directional map is broad.\n\n"
        "## Conclusion\n\nThe evidence supports bounded risk-marker, causal, mechanistic, "
        "and treatment-response hypotheses equally.\n"
    )
    repaired = (
        "## Evidence Landscape\n\n"
        "Outcome-taxonomy separation note: this separates prognostic and survival-marker evidence, "
        "causal-risk and Mendelian-randomization evidence, biology-mechanism and molecular-context "
        "evidence, and treatment or intervention-response supplement evidence.\n\n"
        "Directional-map boundary: Because 17/25 retained sources are predominantly unclear-coded "
        "at receipt level, the corpus does not support a standalone directional map.\n\n"
        "Source-scope annex note: Jaeger 2024 is retained only as non-topic/contextual annex evidence "
        "and is not pooled as direct evidence for the target outcome.\n\n"
        "Numeric verification note: Ha 2023 reported a non-significant mapped comparison "
        "(p = .903); this synthesis treats that mapped comparison as non-significant.\n\n"
        "Admission-bucket note: the source-selection buckets are not an additive conservation "
        "table and are claim-binding states. Strict high-confidence subset note: 3 strict "
        "high-confidence receipts are a quality subset, not the synthesis denominator; the "
        "admitted source base remains 25.\n\n"
        "## Key Findings\n\nKey findings remain source-linked.\n\n"
        "## Conclusion\n\n"
        "Dominant source pattern: prognostic and survival-marker evidence represents 17/25 "
        "retained sources. Minority slices are causal-risk and Mendelian-randomization evidence "
        "n=4, biology-mechanism and molecular-context evidence n=3, treatment or intervention-response "
        "evidence n=1. These source-role strata are not weighed equally and the paper does not "
        "establish standalone clinical actionability.\n"
    )

    assert [ask.split(" ", 1)[0] for ask in asks] == [
        "Restructure",
        "Reconcile",
        "Remove",
        "Recode",
        "Clarify",
        "Tighten",
    ]
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_latest_telomere_third_revise_feedback_splits_and_requires_markers() -> None:
    feedback = (
        "Add a clearly scoped Key Findings section that names the 2-3 most-supported "
        "outcome-specific signals with their source citations, rather than only a "
        "methodological header.; Reconcile the five-domain vs. seven-slice source "
        "stratification: either consolidate to five outcome domains matching the abstract, "
        "or correct the abstract to state seven slices with their n counts.; Recompute "
        "and report the actual MR/ causal-risk source count from the bundle (Wan 2023, "
        "Song 2022, Chen 2023, Markozannes 2022, plus any others) rather than asserting "
        "an unsupported 7/25 figure.; Reclassify Jaeger 2024 as direct interventional "
        "evidence (RCT with TL endpoint) and adjust the direct-evidence count and the "
        "'0/25 direct sources' statement in Gaps Identified accordingly.; Surface the "
        "direction-coded findings for at least the top-cited sources in each outcome "
        "class so that significant source statistic rows are interpretable."
    )
    asks = revision_coverage.revision_asks(feedback)
    weak = "## Key Findings\n\nKey findings from source synthesis.\n\n## Conclusion\n\nBounded.\n"
    repaired = (
        "## Evidence Landscape\n\n"
        "MR/causal-risk source count: 4/25 retained sources (Wan 2023, Song 2022, "
        "Chen 2023, Markozannes 2022).\n\n"
        "Direct-interventional endpoint correction: Jaeger 2024 is counted as direct "
        "interventional endpoint evidence. Direct evidence count is 1/25; RCT endpoint "
        "evidence is separated from hard clinical-outcome proof.\n\n"
        "## Key Findings\n\n"
        "Most-supported outcome-specific signals:\n\n"
        "- Sarkar 2026 (representative statistic p = 0.0005; direction=unclear; source-level statistic reported).\n\n"
        "Stratification reconciliation note: The five-domain source-role summary "
        "(causal-risk and Mendelian-randomization evidence n=4) is separate from "
        "the seven-slice outcome-class table (Mortality and Survival n=3); both "
        "reconcile to the same retained source denominator.\n\n"
        "Direction-coded source highlights:\n\n"
        "- Chen 2023 (representative statistic p = 0.04; direction=null; source-level statistic reported).\n"
    )

    assert [ask.split(" ", 1)[0] for ask in asks] == ["Add", "Reconcile", "Recompute", "Reclassify", "Surface"]
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_latest_telomere_fourth_revise_feedback_splits_and_requires_markers() -> None:
    feedback = (
        "Reconcile each cited source's effect_direction with the actual reported finding "
        "in excerpt; remove or correct contradicted directionality (Brouwers 2016, "
        "Alhareeri 2020, Sasmita 2025, Ha 2023).; Verify/reconcile admission counts "
        "and receipt-level direction tallies (n=24, negative=1, null=5, positive=2, "
        "unclear=16) against source bundle.; Reframe research question and conclusion "
        "so Telomere Cancer Effects is bounded to retained set: adjacent biomarkers, "
        "prognostic associations, MR causal signals; not direct interventional/clinical "
        "efficacy.; Separate MR cancer-risk sources (Li 2026, Chen 2023, Wan 2023, "
        "Song 2022) from mechanistic/ALT sources (Brown 2026, Genetta 2026, Aierken "
        "2026, Xu 2024, Afolabi 2026) when describing disagreements; don't pool.; "
        "Add explicit statement no direct interventional hard-endpoint sources admitted; "
        "conclusion bounded to association/mechanism/hypothesis-generation; remove "
        "clinical actionability/anti-aging framing.; Verify 2026-dated sources for "
        "actual publication status and preprint vs peer-reviewed distinction; flag preprints."
    )
    asks = revision_coverage.revision_asks(feedback)
    weak = (
        "## Key Findings\n\n"
        "Telomere evidence is mixed and clinically actionable.\n\n"
        "## Conclusion\n\n"
        "This supports an anti-aging framing.\n"
    )
    repaired = (
        "## Research Question\n\n"
        "Scope-bounded research question note: This paper asks what the admitted source "
        "set shows across adjacent biomarkers, prognostic associations, MR causal signals, "
        "and mechanism; it is not direct interventional or clinical efficacy evidence.\n\n"
        "## Key Findings\n\n"
        "Effect-direction reconciliation note:\n\n"
        "- Brouwers 2016: direction=null; actual reported finding=manifest-coded source finding.\n"
        "- Alhareeri 2020: direction=positive; actual reported finding=manifest-coded source finding.\n"
        "- Sasmita 2025: direction=unclear; actual reported finding=manifest-coded source finding.\n"
        "- Ha 2023: direction=null; actual reported finding=manifest-coded source finding.\n\n"
        "Admission and direction-tally reconciliation: n=24; negative=1; null=5; "
        "positive=2; unclear=16. These counts use admitted manifest receipts.\n\n"
        "MR/mechanism disagreement separation note: MR/Mendelian rows (Li 2026, Chen 2023, "
        "Wan 2023, Song 2022) are interpreted separately from mechanistic/ALT rows "
        "(Brown 2026, Genetta 2026, Aierken 2026, Xu 2024, Afolabi 2026) and are not pooled.\n\n"
        "No direct interventional hard-endpoint sources were admitted: manifest hard-endpoint "
        "rows=0 (none). The conclusion is bounded to association, mechanism, and "
        "hypothesis-generation rather than clinical actionability.\n\n"
        "Publication-status/preprint note: 2026-dated manifest sources are Li 2026, "
        "Brown 2026, Genetta 2026; preprint candidates flagged by manifest metadata: none.\n\n"
        "## Conclusion\n\n"
        "Scope-bounded research question note: not direct interventional or clinical efficacy.\n"
    )

    assert [ask.split(" ", 1)[0] for ask in asks] == [
        "Reconcile",
        "Verify/reconcile",
        "Reframe",
        "Separate",
        "Add",
        "Verify",
    ]
    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == [asks[1]]


def test_influenza_count_and_pmid_revision_asks_are_deterministic() -> None:
    feedback = (
        "Reconcile the internal count discrepancies in the Conclusion and report a single "
        "authoritative outcome-class tally with explicit numerator definitions.; Resolve PMID "
        "accuracy for every bundle entry; flag any PMID that cannot be verified and either correct it or remove the source."
    )
    asks = revision_coverage.revision_asks(feedback)
    rows = [
        {"source_pmid": "1", "source_title": "Trial A", "effect_direction": "positive", "outcome_class": "cardiometabolic"},
        {"source_pmid": "2", "source_title": "Trial B", "effect_direction": "null", "outcome_class": "contextual_other"},
    ]
    paper = (
        "## Methods\n\nPMID verification audit: retained bundle entries=2; declared PMIDs=2; "
        "verified=2/2; unverifiable=0; entries without PMID=0. Each declared PMID was matched "
        "to its NCBI PubMed title and every supplied DOI or PMCID.\n\n"
        f"## Conclusion\n\n{outcome_class_tally_note(rows)}\n"
    )
    audit = {"provider": "ncbi_pubmed", "entries": 2, "declared": 2, "verified": 2,
             "without_pmid": 0, "issues": [], "status": "verified", "passed": True,
             "input_fingerprint": pmid_rows_fingerprint(rows)}

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert revision_coverage.deterministic_unmet_asks(paper, asks) == asks
    assert revision_coverage.deterministic_unmet_asks(
        paper, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == []
    weak_pmid = paper.replace("verified=2/2", "verified=1/2")
    assert revision_coverage.deterministic_unmet_asks(
        weak_pmid, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[1]]
    forged_pmid = paper.replace("declared PMIDs=2; verified=2/2", "declared PMIDs=1; verified=1/1")
    assert revision_coverage.deterministic_unmet_asks(
        forged_pmid, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[1]]
    missing_outcome_tally = paper.replace("Authoritative outcome-class tally:", "Unlabelled tally:")
    assert revision_coverage.deterministic_unmet_asks(
        missing_outcome_tally, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[0]]
    bad_outcome_total = paper.replace("contextual other=1", "contextual other=2")
    assert revision_coverage.deterministic_unmet_asks(
        bad_outcome_total, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[0]]
    contradictory_tally = paper.replace(
        "These counts use the admitted manifest row set",
        "Authoritative outcome-class tally: n=99; wrong=99. "
        "These counts use the admitted manifest row set",
    )
    assert revision_coverage.deterministic_unmet_asks(
        contradictory_tally, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[0]]
    contradictory_pmid = paper.replace(
        "## Conclusion",
        "PMID verification audit: declared PMIDs=2; verified=1/2; unverifiable=0.\n\n## Conclusion",
    )
    assert revision_coverage.deterministic_unmet_asks(
        contradictory_pmid, asks, evidence_rows=rows, source_identifier_audit=audit,
    ) == [asks[1]]


def test_mixed_outcome_and_direction_tally_feedback_repairs_both() -> None:
    feedback = (
        "Reconcile the internal count discrepancies and report an authoritative outcome-class tally.; "
        "Verify admitted sources against the actual receipt-level direction tally."
    )
    rows = [
        {"effect_direction": "positive", "outcome_class": "cardiometabolic"},
        {"effect_direction": "null", "outcome_class": "contextual_other"},
    ]

    fixed, details, _audit = repair_revision_identity(
        "## Conclusion\n\nBounded conclusion.\n", rows, feedback,
    )
    asks = revision_coverage.revision_asks(feedback)

    assert "Authoritative outcome-class tally: n=2" in fixed
    assert "cardiometabolic=1; contextual other=1" in fixed
    assert "Admission and direction-tally reconciliation: n=2" in fixed
    assert "null=1; positive=1" in fixed
    assert details == ["authoritative_outcome_tally", "authoritative_direction_tally"]
    assert revision_coverage.deterministic_unmet_asks(fixed, asks, evidence_rows=rows) == []


def test_single_ask_requesting_both_tallies_requires_both() -> None:
    feedback = (
        "Reconcile the internal count discrepancies with an authoritative outcome-class tally and "
        "verify admitted sources against the actual receipt-level direction tally."
    )
    rows = [
        {"effect_direction": "positive", "outcome_class": "cardiometabolic"},
        {"effect_direction": "null", "outcome_class": "contextual_other"},
    ]
    fixed, _details, _audit = repair_revision_identity(
        "## Conclusion\n\nBounded conclusion.\n", rows, feedback,
    )
    asks = revision_coverage.revision_asks(feedback)

    assert len(asks) == 1
    assert revision_coverage.deterministic_unmet_asks(fixed, asks, evidence_rows=rows) == []
    direction_missing = fixed.replace(direction_tally_note(rows), "")
    assert revision_coverage.deterministic_unmet_asks(
        direction_missing, asks, evidence_rows=rows,
    ) == asks


def test_influenza_revision_surface_repairs_are_verified_deterministically() -> None:
    feedback = (
        "Fix the typographical artifact in the Abstract ('remains is consistent with before clinical use').; "
        "Reconcile manifest-level direction codes with bundle excerpts where discrepancies exist "
        "(e.g., Bukhbinder 2026 AD risk finding, Wen 2025 seroprotection rates, Wei 2026 pooled ORs) "
        "and flag any retained mismatch explicitly.; "
        "Surface the named internal cross-source tensions (Alotaibi 2026 vs Incalzi 2024/Luo 2026; "
        "Wang 2024 vs Szilagyi 2025/Wang 2025b) directly in the Conclusion or Discussion, not only in the Evidence Snapshot.; "
        "Resolve the contradiction between 'no mechanistic sources' and retained mechanistic content, pick one taxonomy, and define the mechanistic category operationally."
    )
    asks = revision_coverage.revision_asks(feedback)
    weak = (
        "## Abstract\n\nThe result remains is consistent with before clinical use.\n\n"
        "## Evidence Snapshot\n\nThe tension is Alotaibi 2026 versus Incalzi 2024 and Luo 2026; "
        "Wang 2024 conflicts with Szilagyi 2025 and Wang 2025b.\n\n"
        "## Discussion\n\nBounded interpretation.\n\n"
        "## Limitations\n\nNo sources classified primarily as mechanistic.\n"
    )
    repaired = (
        "## Abstract\n\nThe result is bounded before clinical use.\n\n"
        "## Key Findings\n\nEffect-direction reconciliation note:\n\n"
        "- Bukhbinder 2026: direction=positive; actual reported finding=lower AD risk.\n"
        "- Wen 2025: direction=positive; actual reported finding=higher seroprotection.\n"
        "- Wei 2026: direction=mixed; actual reported finding=pooled ORs differ by endpoint.\n\n"
        "## Discussion\n\nThe named tension is Alotaibi 2026 versus Incalzi 2024 and Luo 2026; "
        "Wang 2024 conflicts with Szilagyi 2025 and Wang 2025b.\n\n"
        "## Limitations\n\nNo retained source is classified primarily as mechanistic under the schema; "
        "however, mechanistic or biomarker content can occur within sources classified by their primary role, "
        "so this is not evidence that mechanistic content is absent.\n"
    )

    assert revision_coverage.deterministic_known_asks(asks) == asks
    assert set(revision_coverage.deterministic_unmet_asks(weak, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []
    assert revision_coverage.deterministic_unmet_asks(
        repaired,
        asks,
        retained_citations={
            "Alotaibi 2026", "Incalzi 2024", "Luo 2026", "Wang 2024",
            "Szilagyi 2025", "Wang 2025b",
        },
    ) == []


def test_structured_required_revisions_preserve_every_reviewer_item() -> None:
    required = [
        "Reconcile the Findings Map counts.",
        "For every exact statistic, attach its source token.",
        "Expand Tensions and Gaps to three cross-source tensions.",
        "Complete all fragmentary prose sections.",
        "Either discuss every source or state a representative-subset rationale.",
        "Reconcile a claimed clinical RCT with review-level metadata.",
        "Ensure evidence-honesty limits are reflected throughout.",
    ]
    feedback = "; ".join(required)

    assert revision_coverage.revision_asks(feedback, required) == required
    assert revision_coverage.revision_asks(feedback) == required
