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
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _reload_quant_endpoints() -> Any:
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


def test_unset_domain_uses_cardiometabolic_shared_base_with_warning() -> None:
    """When TOPIC_DOMAIN is unset, the vocab loader falls back to the
    cardiometabolic shared base (vocab/metformin.py — used as endpoint
    inheritance only) AND emits a stderr warning. This is test-time
    backward compat; production callers always set TOPIC_DOMAIN via
    run_v06_synthesis._set_topic before any work runs.

    The fallback exposes the SHARED endpoint vocab (HbA1c, VO2max, thigh
    muscle mass — all cross-cut cardiometabolic / aging drugs). It does
    NOT mean 'pretend the topic is metformin'; production code never
    reaches this path.
    """
    qe = _reload_quant_endpoints()
    canonical_names = {name for name, _pat in qe.ENDPOINT_VOCAB}
    # Shared cardiometabolic endpoint vocab (cross-cuts all drug topics)
    assert "VO2max" in canonical_names
    assert "HbA1c" in canonical_names
    assert "thigh muscle mass" in canonical_names


def test_rapamycin_domain_auto_synth_from_topic_pack() -> None:
    """Refactor 2026-05-04: scripts/vocab/rapamycin.py was retired
    (DEPRECATED). The rapamycin vocab now auto-synthesizes from
    topic_packs/rapamycin.toml. Inherits metformin's endpoint
    regex patterns (cardiometabolic + frailty endpoints overlap)
    but builds ARM_VOCAB from rapamycin's active_arm_synonyms list.
    """
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    canonical_names = {name for name, _pat in qe.ENDPOINT_VOCAB}
    # Inherits metformin's endpoint vocab (HbA1c is shared across
    # cardiometabolic-aging drugs)
    assert "HbA1c" in canonical_names
    # ARM_VOCAB built from rapamycin pack synonyms
    arm_canonical_names = {
        name.lower() for name, _pat in qe.ARM_VOCAB
    }
    assert "rapamycin" in arm_canonical_names
    assert "sirolimus" in arm_canonical_names


def test_rapamycin_pack_binds_real_sentence() -> None:
    """A rapamycin RCT sentence should bind to a rapamycin
    active-arm synonym. Uses inherited metformin endpoint vocab
    (mTOR signaling endpoint covers mTOR-related claims)."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    sentence = "Rapamycin reduced mTOR signaling (p = 0.02)."
    arm = qe.match_arm(sentence)
    assert arm.lower() in {
        "rapamycin", "sirolimus", "rapamune", "rap", "rad001",
    }


def test_metformin_polarity_unchanged() -> None:
    """Metformin polarity table still works post-refactor (backward
    compat — metformin still has its own per-Python-vocab pack)."""
    os.environ.pop("TOPIC_DOMAIN", None)
    qe_met = _reload_quant_endpoints()
    assert qe_met.ENDPOINT_POLARITY["mTOR signaling"] == -1
    assert qe_met.ENDPOINT_POLARITY["HbA1c"] == -1
    assert qe_met.ENDPOINT_POLARITY["VO2max"] == +1


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


def test_generated_topic_pack_auto_synthesizes_vocab() -> None:
    """Fact-backed topic_packs_db records should not fall back to metformin."""
    os.environ["TOPIC_DOMAIN"] = "telomere_biomarker_effects"
    qe = _reload_quant_endpoints()

    assert qe.match_arm("The telomere group showed shorter attrition.") == "telomere"


def test_topic_pack_endpoint_polarity_extends_auto_vocab() -> None:
    """Topic-pack [endpoint_polarity] keys are load-bearing endpoint
    vocab. New topics should not need scripts/vocab/<topic>.py just to
    bind LDL-C, MACE, triglycerides, or cognition claims."""
    os.environ["TOPIC_DOMAIN"] = "statins"
    qe = _reload_quant_endpoints()
    assert qe.match_endpoint(
        "Rosuvastatin-treated patients had lower LDL-C.",
    ) == "ldl cholesterol"
    assert qe.match_endpoint(
        "The trial reduced major adverse cardiovascular events.",
    ) == "incident cv event"
    assert qe.ENDPOINT_POLARITY["ldl cholesterol"] == -1
    assert qe.ENDPOINT_TO_OUTCOME_CLASS["ldl cholesterol"] == "cardiometabolic"

    os.environ["TOPIC_DOMAIN"] = "omega3"
    qe = _reload_quant_endpoints()
    assert qe.match_endpoint("Fish oil lowered triglycerides.") == "triglycerides"
    assert qe.match_endpoint("Older adults had improved cognition.") == "cognition"
    assert qe.ENDPOINT_POLARITY["cognition"] == +1


# Reviewer-fix MEDIUM 2 regression: ARM_VOCAB is per-domain.
def test_rapamycin_arm_binds_to_active_drug_synonym() -> None:
    """Pre-fix the rapamycin pack inherited 'metformin'/'placebo' as
    bare-keyword fallbacks — a sentence about 'sirolimus 1 mg/day'
    couldn't bind arm and never reached high binding_confidence.

    Refactor 2026-05-04: rapamycin pack auto-synthesized from
    topic_packs/rapamycin.toml. The matcher returns the EXACT
    synonym matched (sirolimus → 'sirolimus', rapamycin →
    'rapamycin'). Downstream _claim_topic_effect() reads
    pack.active_arm_synonyms and treats any match as +1 active-arm,
    so both 'sirolimus' and 'rapamycin' produce the same effect
    sign — what matters is the synonym is in active_arm_synonyms,
    not which canonical name it collapses to."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    # Both 'sirolimus' and 'rapamycin' are valid active-arm matches
    sir = qe.match_arm("Sirolimus 1 mg/day reduced p70S6K phosphorylation.")
    rap = qe.match_arm("The rapamycin group experienced more mucositis.")
    valid_synonyms = {
        "rapamycin", "sirolimus", "rapamune", "rap", "rad001",
    }
    assert sir.lower() in valid_synonyms, (
        f"Sirolimus sentence should bind to a rapamycin synonym; "
        f"got {sir!r}"
    )
    assert rap.lower() in valid_synonyms, (
        f"Rapamycin sentence should bind to a rapamycin synonym; "
        f"got {rap!r}"
    )
    # Placebo still binds correctly.
    assert qe.match_arm(
        "The placebo group showed no change.",
    ) == "placebo"


def test_rapamycin_arm_binds_alias_and_retrieval_terms_to_active_canon() -> None:
    """Aliases/retrieval terms such as RAD001 and mTOR inhibitor must
    bind as active intervention terms without a hand-written vocab file."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    active = {
        "rapamycin", "sirolimus", "rapamune", "rap",
    }
    assert qe.match_arm("RAD001 enhanced vaccine response by 20%.").lower() in active
    assert qe.match_arm(
        "mTOR inhibitor treatment enhanced vaccine response by 20%.",
    ).lower() in active
    assert qe.match_arm(
        "RAPA significantly reduced mTOR expression.",
    ).lower() in active
    assert qe.match_arm("Old mice were fed eRapa chow.").lower() in active
    assert qe.match_endpoint(
        "RAD001 enhanced the response to the influenza vaccine by about 20%.",
    ) == "vaccine response"


def test_rapamycin_endpoint_binds_p_value_to_preceding_parenthetical_endpoint() -> None:
    """When a p-value is inside an endpoint's parenthetical, a later endpoint
    in the same sentence must not steal the binding merely by being closer."""
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    sentence = (
        "Lean tissue mass (eta p 2 = 0.202, p = 0.013) and "
        "self-reported pain (eta p 2 = 0.168, p = 0.015) improved "
        "for women using 10 mg rapamycin."
    )
    assert qe.match_endpoint(
        sentence, anchor_offset=sentence.find("p = 0.013"),
    ) == "lean tissue mass"
    assert qe.match_endpoint(
        sentence, anchor_offset=sentence.find("p = 0.015"),
    ) == "self-reported pain"


def test_rapamycin_vocab_covers_rescue_endpoint_terms() -> None:
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    qe = _reload_quant_endpoints()
    assert qe.match_endpoint(
        "Proteome half-lives significantly increased after rapamycin.",
    ) == "proteome turnover"
    assert qe.match_endpoint(
        "Rapamycin reduced kidney enlargement by 65%.",
    ) == "renal function"
    assert qe.match_endpoint(
        "Bacteroides increased after rapamycin treatment.",
    ) == "microbiome composition"
    assert qe.match_endpoint(
        "RAPA significantly reduced CD4 T cell PD-1 expression.",
    ) == "T-cell function"
    assert qe.match_endpoint(
        "Rapamycin treatment significantly increased post infection survival rate.",
    ) == "pathogen survival"


def test_runner_uses_active_rapamycin_vocab_for_outcome_and_polarity() -> None:
    os.environ["TOPIC_DOMAIN"] = "rapamycin"
    import run_v06_synthesis as runner  # type: ignore[import-not-found]

    runner._set_topic("rapamycin")
    assert runner._outcome_class_for_endpoint("autophagy") == "longevity"
    assert runner._outcome_class_for_endpoint("lean tissue mass") == "muscle_function"
    assert runner._outcome_class_for_endpoint("emotional well-being") == "healthspan_qol"
    assert runner._polarity_for_endpoint("respiratory infection rate") == -1
    assert runner._polarity_for_endpoint("pathogen survival") == 1
    assert runner._polarity_for_endpoint("influenza vaccine response") == 1
    assert runner._claim_topic_effect({
        "claim_type": "percentage",
        "numeric_values": [12.0],
        "endpoint": "lifespan",
        "arm": "RAPA",
        "direction": "increase",
        "binding_confidence": "high",
    }) == 1


def test_metformin_arm_unchanged_after_per_domain_refactor() -> None:
    """Default (metformin) ARM_VOCAB must keep working — backward
    compat after the per-domain split."""
    os.environ.pop("TOPIC_DOMAIN", None)
    qe = _reload_quant_endpoints()
    assert qe.match_arm(
        "The metformin group lost more weight than placebo.",
    ) == "metformin"
