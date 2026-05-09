"""Tests for deterministic Phase 3 paper sections."""
from __future__ import annotations

from agent.framework_engagement_section import (
    build_framework_engagement_section,
    build_novel_framework_section,
)
from agent.synthesis_schemas import ReceiptSummary, Tension, TensionMatrix


def _receipt(
    rid: str,
    *,
    outcome: str = "immune",
    direction: str = "positive",
    tier: str = "A1",
    directness: str = "direct",
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid,
        receipt_path=f"runs/{rid}",
        topic="rapamycin",
        thesis_text=f"claim for {rid}",
        spar_verdict="accept_clean",
        n_claims=2,
        n_failed_traces=0,
        canonical_trial_id=rid,
        evidence_tier=tier,
        directness=directness,
        outcome_class=outcome,  # type: ignore[arg-type]
        effect_direction=direction,  # type: ignore[arg-type]
        p_values=(),
        population_summary="older adults",
    )


def _matrix(receipts: tuple[ReceiptSummary, ...]) -> TensionMatrix:
    return TensionMatrix(
        receipts=receipts,
        pairs=(
            Tension(
                receipt_a_id=receipts[0].receipt_id,
                receipt_b_id=receipts[1].receipt_id,
                kind="mechanism_vs_clinical",
                outcome_class="immune",
                summary="mechanistic receipt differs from clinical endpoint",
                severity=4,
            ),
        ),
    )


def test_novel_framework_section_is_deterministic_and_non_numeric() -> None:
    receipts = (
        _receipt("Mannick 2014", directness="direct"),
        _receipt("Lamming 2012", outcome="mechanism", directness="mechanistic"),
    )
    section = build_novel_framework_section(receipts, _matrix(receipts))
    assert section.name == "novel_framework"
    assert "## Novel Synthesis Framework" in section.body_md
    assert "Endpoint-Sensitivity framework" in section.body_md
    assert "falsifying test" in section.body_md
    assert not any(ch.isdigit() for ch in section.body_md)
    assert section.anchors == ()


def test_framework_engagement_uses_receipts_not_background_to_support() -> None:
    section = build_framework_engagement_section(
        [_receipt("Mannick 2014")],
        background_refs=[{"citation_token": "Lamming 2012"}],
    )
    md = section.body_md
    assert section.name == "framework_engagement"
    assert "**Mannick: support.**" in md
    assert "receipt-level evidence matches Mannick 2014" in md
    assert "**Lamming: insufficient.**" in md
    assert "background context matches Lamming 2012" in md
    assert "background-only matches" in md
    assert section.anchors == ()


def test_framework_engagement_fails_closed_without_source_support() -> None:
    section = build_framework_engagement_section([_receipt("Unrelated 2024")])
    md = section.body_md
    assert "**Kennedy: insufficient.**" in md
    assert "no matched source in the accepted evidence registry" in md
