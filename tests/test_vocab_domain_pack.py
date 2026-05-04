"""Tests for the Phase 7 domain-pack vocab refactor.

Verifies that:
1. Default load (no env var) gives metformin pack — backward compat.
2. TOPIC_DOMAIN=rapamycin loads the rapamycin pack and binds
   rapamycin-specific endpoints (mTOR inhibition, autophagy).
3. Polarity table differs correctly between drugs (mTOR inhibition
   is +1 for rapamycin but -1 for metformin since the contexts
   differ).
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _reload_quant_endpoints() -> object:
    """Re-import quant_endpoints with the current TOPIC_DOMAIN env."""
    if "quant_endpoints" in sys.modules:
        del sys.modules["quant_endpoints"]
    if "vocab" in sys.modules:
        del sys.modules["vocab"]
    if "vocab.metformin" in sys.modules:
        del sys.modules["vocab.metformin"]
    if "vocab.rapamycin" in sys.modules:
        del sys.modules["vocab.rapamycin"]
    return importlib.import_module("quant_endpoints")


@pytest.fixture(autouse=True)
def _reset_topic_domain():
    """Clean TOPIC_DOMAIN before each test to avoid bleed."""
    saved = os.environ.pop("TOPIC_DOMAIN", None)
    yield
    if saved is not None:
        os.environ["TOPIC_DOMAIN"] = saved
    else:
        os.environ.pop("TOPIC_DOMAIN", None)


def test_default_domain_loads_metformin() -> None:
    """No TOPIC_DOMAIN → metformin pack (backward compat)."""
    qe = _reload_quant_endpoints()
    canonical_names = {name for name, _pat in qe.ENDPOINT_VOCAB}
    # Metformin-specific endpoints
    assert "VO2max" in canonical_names
    assert "HbA1c" in canonical_names
    assert "thigh muscle mass" in canonical_names


def test_rapamycin_domain_loads_rapamycin_pack() -> None:
    """TOPIC_DOMAIN=rapamycin loads the rapamycin pack."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    canonical_names = {name for name, _pat in qe.ENDPOINT_VOCAB}
    # Rapamycin-specific endpoints
    assert "mTOR inhibition" in canonical_names
    assert "autophagy" in canonical_names
    assert "influenza vaccine response" in canonical_names
    # Metformin-specific should NOT be present
    assert "HbA1c" not in canonical_names


def test_rapamycin_pack_binds_real_sentence() -> None:
    """A canonical rapamycin RCT sentence should bind correctly."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    sentence = (
        "Rapamycin treatment significantly increased autophagic flux "
        "in skeletal muscle (p = 0.02)."
    )
    binding = qe.bind_claim(
        sentence=sentence,
        source_offset_in_section=sentence.find("autophag"),
        sentence_offset_in_section=0,
        claim_role="effect",
    )
    assert binding.endpoint == "autophagy"
    assert binding.direction == "increase"


def test_rapamycin_polarity_inverted_vs_metformin_for_mTOR() -> None:
    """In the metformin pack mTOR signaling polarity is -1 (lower is
    better in aging context). In the rapamycin pack, S6K1
    phosphorylation polarity is -1 (mTOR target suppression =
    drug-effective). Different schemas, both correct for their
    domain."""
    os.environ.pop("TOPIC_DOMAIN", None)
    qe_met = _reload_quant_endpoints()
    assert qe_met.ENDPOINT_POLARITY["mTOR signaling"] == -1

    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe_rap = _reload_quant_endpoints()
    # mTOR INHIBITION is the goal of rapamycin therapy → +1
    assert qe_rap.ENDPOINT_POLARITY["mTOR inhibition"] == +1
    # S6K1 phosphorylation = mTOR-active → drug suppression desired
    assert qe_rap.ENDPOINT_POLARITY["S6K1 phosphorylation"] == -1


def test_unknown_domain_falls_back_via_topic_pack() -> None:
    """Refactor 2026-05-04: removed _KNOWN_DOMAINS allow-list.
    When no vocab/<topic>.py exists AND no topic_packs/<topic>.toml
    exists, load_domain falls back to metformin's vocab module
    (was: raise ValueError). This enables generic multi-topic —
    new topics work via TOML alone, no Python file needed.

    'panaceaol' is a deliberately-fake topic with no .py and no
    .toml → graceful fallback to metformin vocab."""
    os.environ["TOPIC_DOMAIN"] = "panaceaol"
    qe = _reload_quant_endpoints()
    # Should fall back gracefully — metformin vocab loaded
    assert qe.match_arm(
        "The metformin group showed reduction.",
    ) == "metformin"


def test_topic_pack_only_topic_auto_synthesizes_vocab() -> None:
    """Refactor 2026-05-04 part 2: when topic_packs/<topic>.toml
    EXISTS but no vocab/<topic>.py, vocab loader auto-synthesizes
    ARM_VOCAB from the pack's active_arm_synonyms. This is the
    generic-multi-topic acceptance test.

    'statins' has a TOML pack but no vocab/statins.py."""
    os.environ["TOPIC_DOMAIN"] = "statins"
    qe = _reload_quant_endpoints()
    # ARM_VOCAB should bind statin-specific terms from the TOML
    # without requiring a hand-written vocab/statins.py.
    assert qe.match_arm(
        "The atorvastatin group showed reduction.",
    ) == "atorvastatin"
    assert qe.match_arm(
        "Rosuvastatin-treated patients had lower LDL.",
    ) == "rosuvastatin"


# Reviewer-fix MEDIUM 2 regression: ARM_VOCAB is per-domain.
def test_rapamycin_arm_binds_to_rapamycin_not_falls_back() -> None:
    """Pre-fix the rapamycin pack inherited 'metformin'/'placebo' as
    bare-keyword fallbacks — a sentence about 'sirolimus 1 mg/day'
    couldn't bind arm and never reached high binding_confidence.
    Now the rapamycin pack provides its own ARM_VOCAB with
    rapamycin/sirolimus/RTB101 keywords."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    assert qe.match_arm(
        "Sirolimus 1 mg/day reduced p70S6K phosphorylation.",
    ) == "rapamycin"
    assert qe.match_arm(
        "The rapamycin group experienced more mucositis.",
    ) == "rapamycin"
    # Placebo still binds correctly.
    assert qe.match_arm(
        "The placebo group showed no change.",
    ) == "placebo"


def test_metformin_arm_unchanged_after_per_domain_refactor() -> None:
    """Default (metformin) ARM_VOCAB must keep working — backward
    compat after the per-domain split."""
    os.environ.pop("TOPIC_DOMAIN", None)
    qe = _reload_quant_endpoints()
    assert qe.match_arm(
        "The metformin group lost more weight than placebo.",
    ) == "metformin"
