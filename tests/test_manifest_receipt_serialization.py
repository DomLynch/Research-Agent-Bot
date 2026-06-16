"""Regression: manifest receipt serialization must carry p_values.

The 2026-06 publish stall: ReceiptSummary.p_values was populated from
claim_type=="p_value" claims, but the hand-built manifest['receipts']
dict dropped the field. audit_v06_paper._manifest_structural_numerics()
harvests receipts[].p_values into the Q2 numeric pool, so dropping it
made every cited source p-value untraceable -> Q2_numeric_integrity
failed the 100% gate -> nothing published. These tests pin the seam.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import audit_v06_paper as audit  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as v06  # type: ignore[import-not-found]  # noqa: E402
from agent.synthesis_schemas import ReceiptSummary  # noqa: E402


def _receipt(p_values: tuple[str, ...]) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id="Janic_2019_longevity", receipt_path="/tmp/x", topic="t",
        thesis_text="", spar_verdict="accept_clean", n_claims=5,
        n_failed_traces=0, canonical_trial_id=None, evidence_tier="A1",
        directness="direct", outcome_class="metabolic_health",
        effect_direction="positive", p_values=p_values, population_summary="",
    )


def test_manifest_receipt_dict_carries_p_values() -> None:
    r = _receipt(("P = 0.0165", "P = 0.0229"))
    row = v06._manifest_receipt_dict(r, citation_registry={})
    assert row["p_values"] == ["P = 0.0165", "P = 0.0229"]
    # citation_token falls back to the author-year token when no registry entry
    assert row["citation_token"] == "Janic 2019"


def test_serialized_p_values_make_a_body_p_value_trace_in_q2() -> None:
    """End-to-end seam: a body p-value cited from a source traces ONLY
    because the serialized receipt carries it into the Q2 numeric pool."""
    r = _receipt(("P = 0.0165", "P = 0.0229"))
    manifest = {"receipts": [v06._manifest_receipt_dict(r, citation_registry={})]}
    paper = "The Janic 2019 study reported significant effects (P = 0.0165)."
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest=manifest,
    )
    assert ok, msg  # 0.0165 traces via the harvested receipt p_values


def test_leading_zero_p_value_traces_despite_source_format() -> None:
    """A source claim may omit the leading zero ('P = .0038') while the
    body writes it conventionally ('P = 0.0038'). canonical_numeric's
    leading-decimal normalization + the leading-dot-safe harvest regex
    must make them match — else real source p-values fail Q2."""
    r = _receipt(("P = .0038",))
    manifest = {"receipts": [v06._manifest_receipt_dict(r, citation_registry={})]}
    paper = "The trial reported a significant effect (P = 0.0038)."
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest=manifest,
    )
    assert ok, msg


def test_canonical_numeric_normalizes_leading_decimal() -> None:
    assert audit.canonical_numeric(".0038") == audit.canonical_numeric("0.0038")
    assert audit.canonical_numeric(".5") == "0.5"
    assert audit.canonical_numeric("0.5") == "0.5"  # idempotent


def test_q2_still_fails_a_p_value_present_in_no_source_receipt() -> None:
    """Anti-fabrication preserved: a p-value in no receipt's p_values
    (i.e. not in any source claim) is still untraceable and fails."""
    r = _receipt(("P = 0.0165",))
    manifest = {"receipts": [v06._manifest_receipt_dict(r, citation_registry={})]}
    paper = "An unsourced claim with a fabricated p-value (P = 0.00031)."
    ok, msg = audit._check_numeric_integrity(
        paper, corpus_nums=set(), manifest=manifest,
    )
    assert ok is False
    assert "0.00031" in msg or "p_value" in msg, msg
