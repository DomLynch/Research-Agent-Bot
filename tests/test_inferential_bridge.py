from __future__ import annotations

from agent.inferential_bridge import (
    InferenceClaim,
    render_inferential_bridge_section,
    validate_inference,
)


def test_valid_d1_bridge_renders_machine_checkable_tags() -> None:
    claim = InferenceClaim(
        claim="Mechanistic direction is plausibly translatable under conserved signaling.",
        mechanism_anchor=("r1",),
        conservation_argument="Conservation is supported by the configured canon.",
        canon_refs=("Canon 2020",),
        existing_human_signal=("r2",),
        confidence="medium",
        testability="Future studies can test the same pathway prospectively.",
    )
    assert not validate_inference(
        claim,
        receipt_ids={"r1", "r2"},
        canon_refs={"Canon 2020"},
    )
    md = render_inferential_bridge_section((claim,)).body_md
    assert "[D1_inferential_bridge | confidence=medium]" in md
    assert "[mechanism anchor: r1]" in md
    assert "[conservation: Canon 2020]" in md
    assert "[testability: explicit]" in md
    assert ".. [testability:" not in md


def test_d1_bridge_rejects_unknown_anchor_and_new_numeric() -> None:
    claim = InferenceClaim(
        claim="The bridge predicts a 12 percent directional effect.",
        mechanism_anchor=("missing",),
        conservation_argument="Canon supports the bridge.",
        canon_refs=("Canon 2020",),
        existing_human_signal=(),
        confidence="low",
        testability="Test prospectively.",
    )
    errors = validate_inference(
        claim,
        receipt_ids={"r1"},
        canon_refs={"Canon 2020"},
    )
    assert any("unknown mechanism_anchor" in e for e in errors)
    assert any("must not introduce new numerics" in e for e in errors)


def test_high_confidence_requires_existing_human_signal() -> None:
    claim = InferenceClaim(
        claim="The mechanism has a direct translational bridge.",
        mechanism_anchor=("r1",),
        conservation_argument="Canon supports the bridge.",
        canon_refs=("Canon 2020",),
        existing_human_signal=(),
        confidence="high",
        testability="Run a prospective validation.",
    )
    errors = validate_inference(
        claim,
        receipt_ids={"r1"},
        canon_refs={"Canon 2020"},
    )
    assert "high confidence requires existing_human_signal" in errors


def test_existing_human_signal_must_resolve_to_receipt() -> None:
    claim = InferenceClaim(
        claim="The bridge remains tentative.",
        mechanism_anchor=("r1",),
        conservation_argument="Canon supports the bridge.",
        canon_refs=("Canon 2020",),
        existing_human_signal=("Unlisted 2024",),
        confidence="medium",
        testability="Run prospective validation.",
    )
    errors = validate_inference(
        claim,
        receipt_ids={"r1"},
        canon_refs={"Canon 2020"},
    )
    assert any("unknown existing_human_signal" in e for e in errors)


def test_benefit_framing_requires_positive_or_mixed_anchor() -> None:
    claim = InferenceClaim(
        claim="The bridge may improve downstream healthspan interpretation.",
        mechanism_anchor=("r1",),
        conservation_argument="Canon supports the bridge.",
        canon_refs=("Canon 2020",),
        existing_human_signal=("none identified",),
        confidence="low",
        testability="Run prospective validation.",
    )
    errors = validate_inference(
        claim,
        receipt_ids={"r1"},
        canon_refs={"Canon 2020"},
        receipt_effects={"r1": "null"},
    )
    assert "benefit framing requires at least one positive/mixed anchor" in errors


def test_directional_verbs_in_all_bridge_fields_require_positive_anchor() -> None:
    claim = InferenceClaim(
        claim="The bridge remains biologically plausible.",
        mechanism_anchor=("r1",),
        conservation_argument="Canon suggests conserved signaling may reduce decline.",
        canon_refs=("Canon 2020",),
        existing_human_signal=("none identified",),
        confidence="low",
        testability="Future validation should test whether it attenuates decline.",
    )
    errors = validate_inference(
        claim,
        receipt_ids={"r1"},
        canon_refs={"Canon 2020"},
        receipt_effects={"r1": "null"},
    )
    assert "benefit framing requires at least one positive/mixed anchor" in errors
