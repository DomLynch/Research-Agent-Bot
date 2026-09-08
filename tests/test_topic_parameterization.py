"""Workstream A — topic-parameterized pipeline.

Verifies the pipeline can be invoked for any topic with a corpus dir
at docs/quality-reference/<topic>/, not just metformin. Key contract:

  - DEFAULT_TOPIC stays 'metformin' for backward-compat
  - --topic CLI arg is accepted by main()
  - _set_topic() updates QUANT_DIR + PARSED_DIR consistently across
    orchestrator + audit modules
  - build_receipts_from_quant_claims(topic=...) sets the receipt
    .topic field correctly
  - _run() with topic=X but no corpus → exits cleanly with error code
    (not an obscure FileNotFound traceback)"""
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as orch  # type: ignore[import-not-found]  # noqa: E402


def test_manifest_receipt_preserves_full_revision_contract() -> None:
    receipt = SimpleNamespace(
        receipt_id="r1", topic="statins", spar_verdict="accept_clean",
        n_failed_traces=0, outcome_class="cardiometabolic",
        effect_direction="positive", evidence_tier="A1", directness="direct",
        thesis_text="Bound claim.", population_summary="adults", n_claims=2,
        p_values=("P < 0.05",), canonical_trial_id=None, source_title="Trial",
        source_year=2024, source_venue="Journal", source_doi="10.1/example",
        source_pmid="123",
    )

    row = orch._manifest_receipt_dict(receipt, {})

    assert row["topic"] == "statins"
    assert row["spar_verdict"] == "accept_clean"
    assert row["n_failed_traces"] == 0


def test_module_paths_set_via_set_topic_no_metformin_default() -> None:
    """Universal-fix rule (2026-05-04): orchestrator's module-level
    QUANT_DIR/PARSED_DIR are sentinel paths (non-existent on disk)
    until _set_topic() is called explicitly. No silent metformin
    fallback. There is no DEFAULT_TOPIC constant.

    Test suite uses conftest.py to pre-call _set_topic('metformin')
    for backward-compat; production callers go through main() which
    requires --topic.
    """
    # No DEFAULT_TOPIC constant exists anymore.
    assert not hasattr(orch, "DEFAULT_TOPIC")
    # _set_topic propagates to both orchestrator + audit modules.
    orch._set_topic("metformin")
    assert "metformin" in str(orch.QUANT_DIR)
    assert "metformin" in str(audit.QUANT_DIR)
    assert orch._ACTIVE_TOPIC == "metformin"


def test_set_topic_updates_orchestrator_and_audit_in_lockstep() -> None:
    """_set_topic() must update BOTH the orchestrator AND the audit
    module — without lockstep, Q2 trace would read from the wrong
    corpus when synthesising a non-default topic."""
    orch._set_topic("rapamycin")
    assert "rapamycin" in str(orch.QUANT_DIR)
    assert "rapamycin" in str(orch.PARSED_DIR)
    assert "rapamycin" in str(audit.QUANT_DIR)
    assert "rapamycin" in str(audit.PARSED_DIR)
    # Reset so other tests don't see rapamycin paths
    orch._set_topic("metformin")


def test_set_topic_returns_to_metformin_cleanly() -> None:
    """Round-trip: rapamycin → metformin returns to default state."""
    orch._set_topic("rapamycin")
    orch._set_topic("metformin")
    assert "metformin" in str(orch.QUANT_DIR)
    assert "rapamycin" not in str(orch.QUANT_DIR)


def test_run_aborts_cleanly_on_missing_corpus(tmp_path) -> None:
    """When _run is called with a topic whose corpus dir doesn't
    exist, it returns exit code 9 (required input missing) — NOT a
    FileNotFoundError traceback."""
    # Use a topic that definitely doesn't have a corpus
    out_dir = tmp_path / "test-run"

    async def _go():
        return await orch._run(
            out_dir, dry_run=True, topic="nonexistent-topic-xyz",
        )

    rc = asyncio.run(_go())
    # Reset to metformin so other tests don't see the bad path
    orch._set_topic("metformin")
    assert rc == 9, f"expected exit 9 (required input missing), got {rc}"


def test_run_fails_closed_on_corrupt_required_revision_snapshot(
    tmp_path: Path, monkeypatch,
) -> None:
    import json as _json

    source = tmp_path / "source-run"
    snapshot = source / "revision_evidence_snapshot"
    snapshot.mkdir(parents=True)
    (source / "manifest.json").write_text(_json.dumps({
        "receipts": [{"receipt_id": "r1"}],
        "revision_evidence_snapshot": {
            "required": True,
            "manifest": "revision_evidence_snapshot/manifest.json",
        },
    }))
    (snapshot / "manifest.json").write_text(_json.dumps({
        "receipts": [],
        "citation_sha256": "invalid",
    }))
    monkeypatch.setenv("RESEARCH_AGENT_REVISION_SOURCE_RUN", str(source))
    out_dir = tmp_path / "revised-run"

    rc = asyncio.run(orch._run(out_dir, dry_run=True, topic="metformin"))
    continuity = _json.loads((out_dir / "revision_evidence_continuity.json").read_text())

    orch._set_topic("metformin")
    assert rc == 9
    assert "snapshot_receipt_set_mismatch" in continuity["errors"]


def test_main_accepts_topic_cli_arg() -> None:
    """The CLI exposes --topic. main() with --dry-run + a missing
    corpus exits with code 9 (required input missing); proves the arg
    parser threaded through to _run."""
    # parse + dispatch — a missing-corpus topic exits 9
    rc = orch.main([
        "--topic", "nonexistent-zzz", "--dry-run",
        "--out-dir", "/tmp/_topic_test_run",
    ])
    orch._set_topic("metformin")  # reset
    assert rc == 9


def test_default_out_dir_includes_topic() -> None:
    """When --out-dir is omitted the default name encodes the topic
    so multi-topic runs don't collide."""
    # We can't actually run main() without a corpus; just inspect
    # the path-construction logic by importing it inline.
    import datetime as _dt
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    expected_metformin = (
        f"runs/synthesis-metformin-v06-{ts[:4]}"  # year prefix only
    )
    expected_rapamycin = (
        f"runs/synthesis-rapamycin-v06-{ts[:4]}"
    )
    assert "metformin" in expected_metformin
    assert "rapamycin" in expected_rapamycin
    # The actual default-naming code in main() uses
    # `f"synthesis-{args.topic}-v06-{ts}"`; pin that prefix shape
    src = (Path(__file__).resolve().parent.parent
           / "scripts/run_v06_synthesis.py").read_text()
    assert 'f"synthesis-{args.topic}-v06-{ts}"' in src


def test_build_receipts_from_quant_claims_uses_topic_arg(
    monkeypatch, tmp_path,
) -> None:
    """build_receipts_from_quant_claims(topic=X) sets each
    ReceiptSummary's .topic field to X."""
    import json as _json
    qdir = tmp_path / "qc"
    qdir.mkdir()
    pdir = tmp_path / "parsed"
    pdir.mkdir()
    (qdir / "Walton_2019_test.quant_claims.json").write_text(
        _json.dumps({
            "paper_id": "Walton_2019_test",
            "claims": [{
                "binding_confidence": "high",
                "claim_type": "p_value",
                "raw_text": "p < 0.001",
                "endpoint": "muscle_function",
                "arm": "metformin",
                "direction": "negative",
            }],
        }),
    )
    (pdir / "Walton_2019_test.paper_sections.json").write_text(
        _json.dumps({
            "paper_id": "Walton_2019_test",
            "year": 2019,
            "title": "Rapamycin Test",
        }),
    )
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)
    receipts = orch.build_receipts_from_quant_claims(topic="rapamycin")
    assert len(receipts) == 1
    assert receipts[0].topic == "rapamycin", (
        f"receipt.topic should be 'rapamycin', got "
        f"{receipts[0].topic!r}"
    )


def test_build_receipts_filters_to_active_extract_report(
    monkeypatch, tmp_path,
) -> None:
    """When seed_topic_corpus writes active_paper_ids, synthesis must
    ignore stale quant_claims left in the topic directory."""
    import json as _json
    qdir = tmp_path / "quant_claims"
    qdir.mkdir()
    pdir = tmp_path / "parsed"
    pdir.mkdir()
    for pid in ("active_paper", "stale_paper"):
        (qdir / f"{pid}.quant_claims.json").write_text(_json.dumps({
            "paper_id": pid,
            "claims": [{
                "binding_confidence": "high",
                "claim_type": "p_value",
                "raw_text": "p < 0.001",
                "endpoint": "muscle_function",
                "arm": "topic",
                "direction": "positive",
            }],
        }))
        (pdir / f"{pid}.paper_sections.json").write_text(_json.dumps({
            "paper_id": pid, "year": 2024, "title": f"Test topic {pid}",
        }))
    (tmp_path / "_extract_report.json").write_text(_json.dumps({
        "active_paper_ids": ["active_paper"],
    }))
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)
    receipts = orch.build_receipts_from_quant_claims(topic="test_topic")
    assert [r.receipt_id for r in receipts] == ["active_paper"]

    monkeypatch.setattr(orch, "_classify_paper_tier", lambda *_a, **_k: ("A1", "direct"))
    monkeypatch.setattr(orch, "is_source_topic_specific", lambda *_a, **_k: False)
    locked = orch.build_receipts_from_quant_claims(
        topic="test_topic", receipt_ids=frozenset({"stale_paper"}),
    )
    assert [r.receipt_id for r in locked] == ["stale_paper"]


def test_locked_receipt_contract_preserves_original_claim_membership(
    monkeypatch, tmp_path,
) -> None:
    qdir = tmp_path / "quant_claims"
    pdir = tmp_path / "parsed"
    qdir.mkdir()
    pdir.mkdir()
    (qdir / "mixed.quant_claims.json").write_text(json.dumps({
        "paper_id": "mixed",
        "claims": [
            {
                "binding_confidence": "high", "claim_type": "p_value",
                "raw_text": "64.8%", "endpoint": "mortality",
                "arm": "test topic", "direction": "positive",
                "sentence": "Events occurred in 64.8% vs.",
                "context_window": "Other outcome was 10% vs. 20%). Events occurred in 64.8% vs. 36.5%).",
            },
            {
                "binding_confidence": "partial", "claim_type": "effect_size",
                "raw_text": "HR 0.9", "endpoint": "mortality",
                "arm": "test topic", "direction": "positive",
            },
        ],
    }))
    (pdir / "mixed.paper_sections.json").write_text(json.dumps({
        "paper_id": "mixed", "year": 2024, "title": "Test topic trial",
    }))
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)
    monkeypatch.setattr(orch, "is_source_topic_specific", lambda *_a, **_k: True)
    monkeypatch.setattr(orch, "_receipt_mentions_active_topic", lambda *_a, **_k: True)
    monkeypatch.setattr(orch, "_load_paper_class_map", lambda: {})

    original = orch.build_receipts_from_quant_claims(topic="test_topic")
    locked = orch.build_receipts_from_quant_claims(
        topic="test_topic",
        receipt_ids=frozenset({"mixed"}),
        receipt_contracts={"mixed": {"n_claims": original[0].n_claims}},
    )

    assert original[0].n_claims == 1
    assert locked[0].n_claims == original[0].n_claims
    assert locked[0].thesis_text == original[0].thesis_text

    allowed: dict[str, set[str]] = {}
    completed = orch.build_receipts_from_quant_claims(
        topic="test_topic", receipt_ids=frozenset({"mixed"}),
        receipt_contracts={"mixed": {"n_claims": 1, "thesis_text": "Test topic trial — source excerpts: Events occurred in 64.8% vs."}},
        authorized_contract_fields=allowed,
    )[0]
    assert "64.8% vs. 36.5%)" in completed.thesis_text
    assert allowed == {"mixed": {"thesis_text"}}
    assert not orch._completes_locked_comparison(
        "Test topic trial — source excerpts: Events occurred in 64.8% vs. unsupported interpretation)",
        "Test topic trial — source excerpts: Events occurred in 64.8% vs.",
    )

    contract = {
        "outcome_class": "mechanism",
        "effect_direction": "negative",
        "directness": "mechanistic",
        "evidence_tier": "C1",
    }
    preserved = orch.build_receipts_from_quant_claims(
        topic="test_topic",
        receipt_ids=frozenset({"mixed"}),
        receipt_contracts={"mixed": contract},
        authorized_contract_fields={"mixed": {"outcome_class", "effect_direction"}},
    )[0]
    assert preserved.outcome_class == original[0].outcome_class
    assert preserved.effect_direction == original[0].effect_direction
    assert (preserved.directness, preserved.evidence_tier) == ("mechanistic", "C1")


@pytest.mark.parametrize("title,abstract,endpoint,expected", [
    (
        "Long-term effects of resveratrol on cognition and cardio-metabolic markers",
        "We evaluated within individual differences between each treatment period in measures "
        "of cognition (primary outcome), cerebrovascular function and cardio-metabolic markers "
        "as secondary outcomes. Compared to placebo, resveratrol supplementation resulted a "
        "significant 33% improvement in overall cognitive performance (Cohen's d = 0.170, P = 0.005).",
        "insulin sensitivity", "cognitive",
    ),
    (
        "Effects of resveratrol on memory performance in older adults",
        "Baseline and follow-up assessments included the California Verbal Learning Task "
        "(CVLT, main outcome), the ModBent task, and anthropometry. This interventional study "
        "failed to show significant improvements in verbal memory after 6 months of resveratrol "
        "in healthy elderly with a wide BMI range.",
        "body mass index", "cognitive",
    ),
    (
        "Effects of Resveratrol on Cognitive Performance, Mood and Cerebrovascular Function",
        "Significant improvements were observed in the performance of cognitive tasks in the "
        "domain of verbal memory (p = 0.041) and in overall cognitive performance (p = 0.020).",
        "", "cognitive",
    ),
    (
        "Cognitive performance and metabolic effects of resveratrol",
        "The primary outcome was HbA1c, while cognition was a secondary outcome. "
        "Resveratrol significantly improved cognition (p = 0.02).",
        "cognition", "cardiometabolic",
    ),
    (
        "Cognitive performance and metabolic effects of resveratrol",
        "Cognition was a secondary outcome; the primary outcome was HbA1c. "
        "Resveratrol significantly improved cognition (p = 0.02).",
        "cognition", "cardiometabolic",
    ),
])
def test_source_primary_outcome_beats_numeric_frequency(
    title, abstract, endpoint, expected, monkeypatch, tmp_path,
) -> None:
    qdir, pdir = tmp_path / "quant_claims", tmp_path / "parsed"
    qdir.mkdir()
    pdir.mkdir()
    claims = [{
        "claim_id": str(i), "binding_confidence": "high", "claim_type": "p_value",
        "claim_role": "effect", "raw_text": "p = 0.02", "endpoint": endpoint,
        "arm": "resveratrol", "direction": "increase", "sentence": abstract,
    } for i in range(3)]
    (qdir / "trial.quant_claims.json").write_text(json.dumps({"paper_id": "trial", "claims": claims}))
    (pdir / "trial.paper_sections.json").write_text(json.dumps({
        "paper_id": "trial", "title": title, "sections": {"abstract": abstract},
    }))
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)
    monkeypatch.setattr(orch, "_load_paper_class_map", lambda: {})
    contract = {"outcome_class": "contextual_other", "effect_direction": "unclear",
                "endpoints": ["stale endpoint"], "endpoint_directions": {"stale endpoint": "null"},
                "n_claims": 3, "thesis_text": "Trial - source excerpts: Frozen source summary.", "p_values": ["p = 0.02"]}
    args: dict[str, Any] = {"topic": "resveratrol", "receipt_ids": frozenset({"trial"}),
                            "receipt_contracts": {"trial": contract}}
    locked = orch.build_receipts_from_quant_claims(**args)[0]
    assert locked.outcome_class == "contextual_other"
    assert locked.endpoints == contract["endpoints"]
    assert locked.endpoint_directions == contract["endpoint_directions"]
    allowed = {"trial": {"outcome_class"}}
    revised = orch.build_receipts_from_quant_claims(
        **args, authorized_contract_fields=allowed,
    )[0]
    assert allowed == {"trial": {"outcome_class", "endpoints", "endpoint_directions"}}
    assert revised.endpoints == ((endpoint,) if endpoint else ())
    assert "stale endpoint" not in dict(revised.endpoint_directions)
    assert revised.outcome_class == expected
    assert revised.receipt_id == locked.receipt_id == "trial"
    assert revised.n_claims == locked.n_claims == 3
    assert (revised.thesis_text, revised.p_values, revised.effect_direction) == (
        locked.thesis_text, locked.p_values, locked.effect_direction,
    )


def test_background_cognitive_null_does_not_determine_endpoint_direction() -> None:
    own = "Resveratrol significantly improved cognition (p = 0.02)."
    background = "As previously mentioned, Kennedy et al. and Wightman et al. [17, 18] " \
                 "found no improvements in cognition with single doses in young cohorts (~20 years)."
    claims = [
        {"claim_type": "p_value", "raw_text": "p = 0.02", "claim_role": "effect",
         "endpoint": "", "direction": "increase", "arm": "resveratrol", "sentence": own},
        {"claim_type": "unit_value", "raw_text": "20 years", "claim_role": "effect",
         "endpoint": "cognition", "direction": "no_change", "sentence": background},
    ]
    result = orch._aggregate_paper(claims, paper_meta={
        "title": "Effects of Resveratrol on Cognitive Performance",
        "sections": {"abstract": own, "discussion": background},
    })
    assert result["outcome_class"] == "cognitive"
    assert result["endpoint_directions"] == ()
    assert result["n_claims"] == 2
    assert claims[1]["direction"] == "no_change"


def test_restore_revision_citations_is_exact_and_fail_closed(tmp_path: Path) -> None:
    import dataclasses as _dataclasses
    import json as _json
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    registry = {
        "r1": orch._citations.CitationEntry(
            receipt_id="r1", body_citation="Changed 2026", reference_id="R99",
        ),
        "r2": orch._citations.CitationEntry(
            receipt_id="r2", body_citation="Changed 2026", reference_id="R98",
        ),
        "r3": orch._citations.CitationEntry(
            receipt_id="r3", body_citation="Changed 2026", reference_id="R97",
        ),
    }
    valid = _dataclasses.asdict(registry["r1"])
    valid.update(body_citation="Original 2024", reference_id="R01", source_year=2024)
    source_run.joinpath("citation_registry.json").write_text(
        _json.dumps({"r1": valid, "r3": {}}), encoding="utf-8",
    )

    restored, missing = orch._restore_revision_citations(
        registry, source_run / "citation_registry.json",
        frozenset({"r1", "r2", "r3"}),
    )

    assert restored == 1
    assert missing == ["r2", "r3"]
    assert registry["r1"].body_citation == "Original 2024"
    assert registry["r1"].reference_id == "R01"


def test_build_receipts_prunes_off_topic_high_claim_sources(
    monkeypatch, tmp_path,
) -> None:
    import json as _json
    qdir = tmp_path / "quant_claims"
    qdir.mkdir()
    pdir = tmp_path / "parsed"
    pdir.mkdir()
    rows = {
        "semaglutide_cardiometabolic_trial": "Semaglutide effects on insulin sensitivity",
        "oral_magnesium_supplementation_trial": "Oral magnesium supplementation in older adults",
    }
    for pid, title in rows.items():
        (qdir / f"{pid}.quant_claims.json").write_text(_json.dumps({
            "paper_id": pid,
            "claims": [{
                "binding_confidence": "high",
                "claim_type": "p_value",
                "raw_text": "p < 0.05",
                "endpoint": "cardiometabolic",
                "arm": "intervention",
                "direction": "positive",
                "sentence": f"{title} reported a cardiometabolic endpoint.",
            }],
        }))
        (pdir / f"{pid}.paper_sections.json").write_text(_json.dumps({
            "paper_id": pid, "year": 2026, "title": title,
        }))
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)

    receipts = orch.build_receipts_from_quant_claims(topic="magnesium_longevity")

    assert [r.receipt_id for r in receipts] == ["oral_magnesium_supplementation_trial"]


def test_receipt_funnel_reports_drop_reasons(monkeypatch, tmp_path) -> None:
    import json as _json
    qdir = tmp_path / "quant_claims"
    qdir.mkdir()

    def write_claims(pid: str, confidences: list[str]) -> None:
        (qdir / f"{pid}.quant_claims.json").write_text(_json.dumps({
            "paper_id": pid,
            "claims": [
                {
                    "binding_confidence": conf,
                    "claim_type": "p_value",
                    "raw_text": "p < 0.05",
                    "endpoint": "muscle_function",
                    "arm": "topic",
                    "direction": "positive",
                }
                for conf in confidences
            ],
        }))

    write_claims("active_high", ["high"])
    write_claims("active_partial", ["partial"])
    write_claims("active_mixed_low", ["partial", "none"])
    write_claims("outside_high", ["high"])
    write_claims("active_none", ["none"])
    write_claims("active_empty", [])
    (tmp_path / "_extract_report.json").write_text(_json.dumps({
        "active_paper_ids": [
            "active_high", "active_partial", "active_mixed_low",
            "active_none", "active_empty",
        ],
    }))
    (tmp_path / "corpus_classification.json").write_text("[]")

    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    report = orch.build_receipt_funnel_report(topic="test_topic")
    assert report["counts"] == {
        "accepted_high_confidence": 1,
        "candidate_no_claims": 1,
        "candidate_none_only": 1,
        "candidate_partial_and_none_only": 1,
        "candidate_partial_only": 1,
        "outside_active_or_classified_scope": 1,
    }
    assert report["claim_binding_confidence_totals"] == {
        "high": 2,
        "none": 2,
        "partial": 2,
    }
    md = orch.render_receipt_funnel_markdown(report)
    assert "`candidate_partial_only`" in md
    assert "`outside_high`" in md


def test_reconciled_receipt_funnel_renames_strict_high_confidence_count() -> None:
    report = {
        "counts": {"accepted_high_confidence": 2, "candidate_partial_only": 6},
        "examples": {"accepted_high_confidence": ["paper_a"]},
    }
    receipts = [
        SimpleNamespace(evidence_tier="A1", directness="direct"),
        SimpleNamespace(evidence_tier="B2", directness="review"),
        SimpleNamespace(evidence_tier="B2", directness="review"),
        SimpleNamespace(evidence_tier="B2", directness="review"),
        SimpleNamespace(evidence_tier="B2", directness="review"),
    ]
    reconciled = orch.reconcile_receipt_funnel_report(report, cast(Any, receipts))
    assert "accepted_high_confidence" not in reconciled["counts"]
    assert "accepted_high_confidence" not in reconciled["examples"]
    assert reconciled["counts"]["admitted_receipts"] == 5
    assert reconciled["counts"]["direct_receipts"] == 1
    assert reconciled["counts"]["original_strict_high_confidence_receipts"] == 2
    assert reconciled["examples"]["original_strict_high_confidence_receipts"] == ["paper_a"]
    assert orch._manifest_source_fit_counts(reconciled) == {
        "n_primary_tier": 1,
        "n_direct_receipts": 1,
    }


def test_manifest_source_fit_counts_rejects_missing_counts() -> None:
    with pytest.raises(ValueError, match="missing source-fit counts"):
        orch._manifest_source_fit_counts({})
    with pytest.raises(ValueError, match="missing source-fit counts"):
        orch._manifest_source_fit_counts({
            "counts": {"primary_tier_receipts": True, "direct_receipts": 4},
        })


def test_receipt_thesis_uses_source_sentence_not_arm_paraphrase() -> None:
    claim = {
        "binding_confidence": "high",
        "raw_text": "77.1%",
        "sentence": (
            "More participants in the semaglutide group than in the "
            "placebo group achieved weight loss at week 104."
        ),
        # Simulate a noisy extractor arm label. Receipt prose must not
        # turn this into a false cross-topic claim.
        "arm": "metformin",
        "direction": "increase",
        "endpoint": "body weight",
    }
    thesis = orch._build_receipt_thesis_text(
        paper_id="paper",
        paper_title="STEP trial",
        claims=[claim],
    )
    assert "semaglutide group" in thesis
    assert "metformin increase" not in thesis


def test_receipt_excerpt_does_not_invent_species_by_splitting_words() -> None:
    from agent.evidence_lanes import is_animal_context

    sentence = (
        "Patients with type 2 diabetes (HbA1c >= 6.5%, use of antidiabetic drugs, "
        "and/or disease codes of type 2 diabetes) and preserved kidney function "
        "(estimated glomerular filtration rate >= 60) were included."
    )
    excerpt = orch._shorten_claim_sentence(sentence, sentence.index("rate") + 4)
    assert not excerpt.endswith("rat…")
    assert excerpt.endswith("rate…")
    row = {"evidence_tier": "A2", "directness": "indirect", "thesis_text": excerpt}
    assert not is_animal_context(row)
    assert is_animal_context({**row, "thesis_text": "Kidney function was measured in rats."})
    animal = "Kidney function was measured in rats with diabetes."
    excerpt = orch._shorten_claim_sentence(animal, animal.index("rats") + 4)
    assert excerpt.endswith("rats…")
    assert is_animal_context({**row, "thesis_text": excerpt})


def test_receipt_thesis_preserves_late_source_statistics() -> None:
    claims = [
        {
            "sentence": "The intervention group had more adverse events (81 of 125 [64.8%] vs.",
            "context_window": "Other outcome was 10% vs. 20%). adverse events (81 of 125 [64.8%] vs. 46 of 126 [36.5%]) and fewer",
        },
    ]

    thesis = orch._build_receipt_thesis_text("paper", "Safety trial", claims)

    assert "81 of 125 [64.8%] vs. 46 of 126 [36.5%]" in thesis
    sentence = (
        "Among participants assigned to the intervention or comparator, the prespecified "
        "analysis of the primary endpoint at the end of the randomized treatment period "
        "found no significant between-group difference (P = 0.64)."
    )
    assert len(sentence) > 180
    complete = orch._build_receipt_thesis_text("paper", "Safety trial", [{"sentence": sentence}])
    assert sentence in complete and "P = 0.64" in complete


def test_locked_receipt_thesis_allows_only_comparison_completion() -> None:
    locked = "Safety trial — source excerpts: Events occurred in 64.8% vs. | Conclusion."
    completed = "Safety trial — source excerpts: Events occurred in 64.8% vs. 36.5%) | Conclusion."

    assert orch._completes_locked_comparison(completed, locked)
    assert not orch._completes_locked_comparison("Safety trial — source excerpts: Different result.", locked)
    assert not orch._completes_locked_comparison(completed.replace("Conclusion.", "Changed."), locked)
    assert not orch._completes_locked_comparison(completed + " | New unrelated excerpt.", locked)


def test_receipt_thesis_rejects_repeated_comparison_anchor() -> None:
    thesis = orch._build_receipt_thesis_text("paper", "Safety trial", [{
        "sentence": "Target result was 64.8% vs.",
        "context_window": "Target result was 64.8% vs. 20%). Target result was 64.8% vs. 36.5%).",
    }])

    assert "vs. 20%)" not in thesis
    assert "vs. 36.5%)" not in thesis


def test_receipt_thesis_prefers_results_over_methods() -> None:
    thesis = orch._build_receipt_thesis_text(
        paper_id="paper",
        paper_title="Statin trial",
        claims=[
            {"sentence": "The statin methods specified a 40 mg dose.", "source_section": "methods", "claim_role": "effect", "direction": "increase", "binding_confidence": "high"},
            {"sentence": "Statin exposure reduced mortality in the cohort.", "source_section": "results", "claim_role": "effect", "direction": "decrease", "binding_confidence": "partial"},
        ],
    )

    assert "Statin exposure reduced mortality" in thesis
    assert thesis.index("Statin exposure") < thesis.index("40 mg dose")


def test_receipt_packet_prioritizes_own_findings_within_writer_budget() -> None:
    own = [{"sentence": f"Outcome {i} improved in the intervention arm compared with control.",
            "source_section": "results", "claim_role": "unknown"} for i in range(20)]
    background = {"sentence": "Another study reported lower mortality.", "source_section": "discussion",
                  "claim_role": "effect", "direction": "decrease", "binding_confidence": "high"}
    thesis = orch._build_receipt_thesis_text("paper", "Trial", [background, *own])
    spans = thesis.split("source excerpts: ")[1].split(" | ")
    assert len(spans) > 3 and len(thesis) <= orch.MAX_EVIDENCE_CHARS_PER_RECEIPT
    assert spans[0] == own[0]["sentence"] and background["sentence"] not in spans
    assert all(span in {claim["sentence"] for claim in own} for span in spans)


def test_population_summary_does_not_render_derived_sample_sum() -> None:
    """Population summaries must not synthesize derived n totals.

    Q2 traces literals in the corpus. If two arms are n=152, rendering
    n=304 creates a true but untraceable derived number in prose.
    """
    summary = orch._build_population_summary(
        {"title": "older adults trial"},
    )
    assert summary == "older adults"


def test_ratio_below_one_on_adverse_endpoint_is_beneficial() -> None:
    """Universal polarity guard: for adverse endpoints such as
    mortality, a ratio below 1 is a beneficial active-treatment signal
    even if the extractor records the comparator arm."""
    claim = {
        "claim_type": "risk_ratio",
        "endpoint": "mortality",
        "arm": "placebo",
        "numeric_values": [0.90],
    }
    assert orch._claim_topic_effect(claim) == 1


def test_no_benefit_title_guards_positive_effect_direction() -> None:
    title = (
        "Creatine Loading Does Not Preserve Muscle Mass or Strength "
        "During Leg Immobilization in Healthy, Young Males: "
        "A Randomized Controlled Trial"
    )
    assert orch._title_guarded_effect_direction(title, "positive") == "null"
    assert orch._title_guarded_effect_direction(title, "negative") == "negative"


def test_negated_evidence_does_not_become_positive() -> None:
    for evidence in (
        "No improvement in muscle strength was observed.",
        "No improvements in muscle strength were observed.",
        "No statistically significant improvement in muscle strength was observed.",
        "Without improvement in muscle strength, the intervention remained unsupported.",
    ):
        assert orch._title_guarded_effect_direction("Muscle trial", "null", evidence) == "null"
        assert orch._title_guarded_effect_direction("Muscle trial", "negative", evidence) == "negative"

    assert orch._title_guarded_effect_direction(
        "Trial without placebo control improves muscle strength", "positive",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Without adverse events, the intervention improves function", "positive",
    ) == "positive"


def test_title_direction_guard_preserves_positive_when_no_null_cue() -> None:
    title = (
        "Creatine supplementation improves muscle strength in older "
        "adults: a randomized controlled trial"
    )
    assert orch._title_guarded_effect_direction(title, "positive") == "positive"


def test_explicit_directional_title_does_not_override_null_extraction_signal() -> None:
    title = "Ergothioneine promotes longevity and healthy aging in male mice"

    assert orch._title_guarded_effect_direction(title, "null") == "null"


def test_harm_reduction_title_rescues_unclear_extraction_signal() -> None:
    title = "Ergothioneine ameliorates alcoholic fatty liver disease and inflammation"

    assert orch._title_guarded_effect_direction(title, "unclear") == "positive"


def test_review_title_without_directional_signal_stays_null() -> None:
    title = "Systematic review and meta-analysis of ergothioneine biomarkers"

    assert orch._title_guarded_effect_direction(title, "null") == "null"


def test_adverse_directional_title_does_not_override_null_extraction_signal() -> None:
    title = "Exposure increases mortality risk and accelerates biological aging"

    assert orch._title_guarded_effect_direction(title, "null") == "null"


def test_explicit_evidence_text_repairs_unambiguous_direction_miscoding() -> None:
    assert orch._title_guarded_effect_direction(
        "Urolithin A effects in human skeletal muscle cells",
        "unclear",
        "Urolithin A augments glucose uptake in human skeletal muscle cells.",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Healthy lifestyle and all-cause mortality among older adults",
        "negative",
        "A favorable lifestyle was associated with a lower risk of all-cause mortality.",
    ) == "negative"


def test_secondary_positive_prose_cannot_override_a_structured_null_primary() -> None:
    evidence = (
        "The primary endpoint was null. A secondary subgroup improved muscle strength."
    )
    assert orch._title_guarded_effect_direction(
        "Primary endpoint trial", "null", evidence,
    ) == "null"


def test_planned_protocol_cannot_claim_an_observed_effect_direction() -> None:
    evidence = (
        "Participants will be randomly assigned to intervention or placebo. "
        "Background literature reports a 1% annual decline."
    )

    assert orch._title_guarded_effect_direction(
        "A randomized study to evaluate treatment effects", "null", evidence,
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Completed trial results under the study protocol", "null",
        "Participants were randomly assigned and the primary endpoint was null.",
    ) == "null"
    assert orch._title_guarded_effect_direction(
        "Protocol for a trial with prospective follow-up", "positive",
        "Participants will be enrolled for follow-up. The primary analysis showed improved function.",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Completed cohort outcomes with extended follow-up", "null",
        "The cohort observed stable function; participants will be enrolled for follow-up.",
    ) == "null"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "null",
        "Background results showed prior benefit. Participants will be randomly assigned.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "null",
        "Participants will be randomly assigned. The primary endpoint was prespecified.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "null",
        "Participants will be randomly assigned. Prior results showed lower event rates.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior trial results showed lower event rates.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Previously published results showed lower event rates.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Previously published results showed that the primary endpoint was null.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior results showed no benefit, but this trial found improved function.",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior results showed no benefit, and this trial found improved function.",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior results showed, however, that the primary endpoint was null.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior results showed no benefit, but in this trial we found improvement.",
    ) == "positive"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be randomized. Prior results showed\nthat the primary endpoint was null.",
    ) == "unclear"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "null",
        "Participants will be randomly assigned. The primary endpoint was null.",
    ) == "null"
    assert orch._title_guarded_effect_direction(
        "Protocol for a randomized trial", "positive",
        "Participants will be enrolled later. Results showed improved function.",
    ) == "positive"


def test_topic_pack_endpoint_polarity_drives_effect_sign() -> None:
    """Topic-pack endpoint polarity must drive non-metformin topics
    without adding scripts/vocab/<topic>.py or Python topic tables."""
    orch._set_topic("statins")
    statin_claim = {
        "claim_type": "effect_size",
        "endpoint": "ldl cholesterol",
        "arm": "atorvastatin",
        "direction": "decrease",
    }
    assert orch._outcome_class_for_endpoint("ldl cholesterol") == "cardiometabolic"
    assert orch._claim_topic_effect(statin_claim) == 1

    orch._set_topic("omega3")
    omega_claim = {
        "claim_type": "effect_size",
        "endpoint": "cognition",
        "arm": "fish oil",
        "direction": "increase",
    }
    assert orch._outcome_class_for_endpoint("cognition") == "cognitive"
    assert orch._claim_topic_effect(omega_claim) == 1
    orch._set_topic("metformin")


def test_hazard_ratio_below_one_on_lifespan_endpoint_is_beneficial() -> None:
    """A survival hazard ratio below 1 means lower event hazard and can
    be a beneficial lifespan signal even when the endpoint is not
    named mortality."""
    claim = {
        "claim_type": "hazard_ratio",
        "endpoint": "lifespan",
        "arm": "rapamycin",
        "numeric_values": [0.42],
    }
    assert orch._claim_topic_effect(claim) == 1


def test_p_value_does_not_carry_effect_direction() -> None:
    """P-values establish significance for an endpoint; they should
    not independently flip direction labels in receipt aggregation."""
    claim = {
        "claim_type": "p_value",
        "endpoint": "mortality",
        "arm": "placebo",
        "direction": "decrease",
        "numeric_values": [0.004],
    }
    assert orch._claim_topic_effect(claim) == 0


def test_thesis_template_handles_plural_topic_names() -> None:
    receipts = [
        type("R", (), {
            "receipt_id": "r1",
            "outcome_class": "longevity",
            "effect_direction": "positive",
        })(),
        type("R", (), {
            "receipt_id": "r2",
            "outcome_class": "muscle_function",
            "effect_direction": "null",
        })(),
    ]
    thesis = orch.build_thesis(
        receipts, orch.TensionMatrix(receipts=tuple(), pairs=()), "statins",
    )
    assert "the evidence base for" in thesis.text
    assert "curated reference papers, statins shows" not in thesis.text


def test_section_backstop_refuses_conclusion_for_plural_topic_names() -> None:
    old_manifest = orch._ACTIVE_MANIFEST
    old_topic = orch._ACTIVE_TOPIC
    try:
        orch._ACTIVE_TOPIC = "nad_precursors"
        orch._ACTIVE_MANIFEST = {
            "n_receipts": 15,
            "n_high_confidence_claims_total": 85,
            "n_non_orthogonal_tensions": 49,
            "thesis": "The evidence profile is mixed.",
            "receipts": [{
                "directness": "direct",
                "effect_direction": "positive",
                "outcome_class": "cardiometabolic",
                "citation_token": "Example 2025",
            }],
        }
        backstop = orch._compile_public_section_backstop("Conclusion", 250)
    finally:
        orch._ACTIVE_MANIFEST = old_manifest
        orch._ACTIVE_TOPIC = old_topic

    assert backstop == ""


def test_section_backstop_refuses_lifestyle_conclusion_padding() -> None:
    old_manifest = orch._ACTIVE_MANIFEST
    old_topic = orch._ACTIVE_TOPIC
    try:
        orch._ACTIVE_TOPIC = "aerobic_exercise"
        orch._ACTIVE_MANIFEST = {
            "intervention_class": "exercise_intervention",
            "n_receipts": 15,
            "n_high_confidence_claims_total": 85,
            "n_non_orthogonal_tensions": 49,
            "thesis": "The evidence profile is mixed.",
            "receipts": [{
                "directness": "direct",
                "effect_direction": "positive",
                "outcome_class": "cardiometabolic",
                "citation_token": "Example 2025",
            }],
        }
        backstop = orch._compile_public_section_backstop("Conclusion", 250)
    finally:
        orch._ACTIVE_MANIFEST = old_manifest
        orch._ACTIVE_TOPIC = old_topic

    assert backstop == ""
