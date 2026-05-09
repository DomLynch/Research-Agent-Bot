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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # noqa: E402
import run_v06_synthesis as orch  # noqa: E402


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
    exist, it returns exit code 4 (corpus-missing) — NOT a
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
    assert rc == 4, f"expected exit 4 (corpus-missing), got {rc}"


def test_main_accepts_topic_cli_arg() -> None:
    """The CLI exposes --topic. main() with --dry-run + a missing
    corpus exits with code 4 (corpus-missing); proves the arg
    parser threaded through to _run."""
    # parse + dispatch — a missing-corpus topic exits 4
    rc = orch.main([
        "--topic", "nonexistent-zzz", "--dry-run",
        "--out-dir", "/tmp/_topic_test_run",
    ])
    orch._set_topic("metformin")  # reset
    assert rc == 4


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
            "title": "Test",
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
            "paper_id": pid, "year": 2024, "title": pid,
        }))
    (tmp_path / "_extract_report.json").write_text(_json.dumps({
        "active_paper_ids": ["active_paper"],
    }))
    monkeypatch.setattr(orch, "QUANT_DIR", qdir)
    monkeypatch.setattr(orch, "PARSED_DIR", pdir)
    receipts = orch.build_receipts_from_quant_claims(topic="test_topic")
    assert [r.receipt_id for r in receipts] == ["active_paper"]


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


def test_population_summary_does_not_render_derived_sample_sum() -> None:
    """Population summaries must not synthesize derived n totals.

    Q2 traces literals in the corpus. If two arms are n=152, rendering
    n=304 creates a true but untraceable derived number in prose.
    """
    summary = orch._build_population_summary(
        {"title": "older adults trial"},
        [152.0, 152.0],
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


def test_title_direction_guard_preserves_positive_when_no_null_cue() -> None:
    title = (
        "Creatine supplementation improves muscle strength in older "
        "adults: a randomized controlled trial"
    )
    assert orch._title_guarded_effect_direction(title, "positive") == "positive"


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


def test_section_backstop_handles_plural_topic_names() -> None:
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

    assert "the evidence base for nad precursors has enough" in backstop
    assert "In conclusion, nad precursors has enough" not in backstop
