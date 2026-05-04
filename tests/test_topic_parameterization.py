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


def test_default_topic_is_metformin() -> None:
    """Backward-compat: importing the module without setting a topic
    yields the metformin corpus paths."""
    assert orch.DEFAULT_TOPIC == "metformin"
    # Re-set in case prior tests changed it
    orch._set_topic("metformin")
    assert "metformin" in str(orch.QUANT_DIR)
    assert "metformin" in str(audit.QUANT_DIR)


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
