"""Planted-failure regression suite — Day 1 portion (topic_pack layer).

The 5 hand-crafted broken submissions live as JSON fixtures in
`tests/planted_failures/metformin/`. As each Proof 001 layer comes online,
its corresponding test asserts the relevant case is caught at the right
gate with the right error code.

Day 1 covers what the `topic_pack.py` loader can prove on its own:
- Case 1 (protocol-as-results): registry override pins TAME to
  `registered_pending`, AND the verb 'demonstrated' is in the
  forbidden_verbs_for_protocol_role set.
- Case 4 (alias drift): 'Glufomin' is NOT in the alias whitelist.

Cases 2, 3, 5 are deferred to Day 2 (evidence_cards) and Day 3 (citation_trace);
their fixtures still load successfully and are structurally validated here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.topic_pack import load_topic_pack

FIXTURE_DIR = Path(__file__).parent / "planted_failures" / "metformin"
TOPIC_PACK_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


def _load(case_filename: str) -> dict:
    with (FIXTURE_DIR / case_filename).open() as fh:
        return json.load(fh)


# --- Structural integrity of the fixture corpus ---------------------------


@pytest.fixture(scope="module")
def all_cases() -> list[dict]:
    cases = []
    for path in sorted(FIXTURE_DIR.glob("case_*.json")):
        with path.open() as fh:
            cases.append(json.load(fh))
    return cases


def test_five_planted_cases_present(all_cases: list[dict]) -> None:
    """Per DESIGN-001 §14, the corpus is exactly 5 cases."""
    assert len(all_cases) == 5
    case_ids = {c["case_id"] for c in all_cases}
    assert case_ids == {"C1", "C2", "C3", "C4", "C5"}


def test_each_case_has_required_fields(all_cases: list[dict]) -> None:
    required = {"case_id", "name", "description", "synthetic_source",
                "synthetic_claim_text", "expected_catch"}
    for case in all_cases:
        missing = required - case.keys()
        assert not missing, f"case {case.get('case_id')} missing fields: {missing}"


def test_each_synthetic_source_has_minimum_shape(all_cases: list[dict]) -> None:
    """Synthetic sources mimic agent.types.Source so Day 2 evidence_cards
    can consume them directly via from-dict construction.
    """
    required = {"ref", "title", "abstract", "year", "url", "source"}
    for case in all_cases:
        src = case["synthetic_source"]
        missing = required - src.keys()
        assert not missing, f"case {case['case_id']} source missing: {missing}"
        assert isinstance(src["ref"], int)


# --- Case 1 (Day 1 catchable at topic_pack layer) -------------------------


def test_case_1_tame_pinned_to_registered_pending() -> None:
    """The TAME (NCT04264897) protocol-as-results submission must be rejected.

    Topic-pack registry override is the FIRST gate. If a future change
    weakens or bypasses the override, this test fails.
    """
    case = _load("case_1_protocol_as_results.json")
    pack = load_topic_pack(TOPIC_PACK_PATH)
    nct = case["synthetic_source"]["nct"]
    assert nct == "NCT04264897"

    override = pack.lookup_role_override(nct)
    assert override is not None, "TAME must be in known_role_overrides"
    assert override.role == "registered_pending", (
        f"TAME override role is {override.role!r}; submission claims "
        f"'demonstrated CV benefit' which would only be valid for "
        f"published_results"
    )


def test_case_1_verb_demonstrated_is_banned_for_protocol_role() -> None:
    """The verb in the synthetic claim is in forbidden_verbs_for_protocol_role.

    Validators.py (Day 2) consumes this set; the topic_pack already exposes
    the lookup so this guard is provable at Day 1.
    """
    case = _load("case_1_protocol_as_results.json")
    pack = load_topic_pack(TOPIC_PACK_PATH)
    verb = case["synthetic_claim_verb"]
    assert verb == "demonstrated"
    assert pack.is_protocol_verb_forbidden(verb), (
        f"verb {verb!r} must be in forbidden_verbs_for_protocol_role "
        f"so validators.py rejects 'TAME demonstrated...' on Day 2"
    )


# --- Case 4 (Day 1 catchable at topic_pack layer) -------------------------


def test_case_4_glufomin_not_in_alias_whitelist() -> None:
    """The fake alias 'Glufomin' must be rejected by the case-insensitive
    whitelist. DrugAliasClient (Day 3) provides a second layer of defense.
    """
    case = _load("case_4_alias_drift.json")
    pack = load_topic_pack(TOPIC_PACK_PATH)
    fake_alias = "Glufomin"
    assert fake_alias in case["synthetic_claim_text"]
    assert not pack.has_alias(fake_alias), (
        f"alias whitelist must reject {fake_alias!r}"
    )
    # Case-variants should also be rejected (whitelist is case-insensitive
    # but only on the alias values, not by adding variants).
    for variant in ("glufomin", "GLUFOMIN", "  Glufomin  "):
        assert not pack.has_alias(variant)


# --- Cases 2, 3, 5 — fixtures load + structure check; full check in later Days


@pytest.mark.parametrize("case_filename,future_layer", [
    ("case_2_fabricated_nct.json", "citation_trace"),
    ("case_3_inflated_pvalue.json", "citation_trace"),
    ("case_5_off_domain.json", "evidence_cards"),
])
def test_deferred_cases_fixtures_well_formed(
    case_filename: str, future_layer: str,
) -> None:
    """Fixtures for Day 2/3 layers exist and have the right `gate_primary`."""
    case = _load(case_filename)
    assert case["expected_catch"]["gate_primary"] == future_layer, (
        f"{case_filename} expects catch at {future_layer}, found "
        f"{case['expected_catch']['gate_primary']}"
    )


# --- Discriminating test: forbidden-verb completeness ---------------------


def test_all_protocol_verbs_in_topic_pack_match_design_doc() -> None:
    """Sync between DESIGN-001 §14 and metformin.toml — if either drifts,
    fail loud here rather than during a planted-failure regression hunt.
    """
    pack = load_topic_pack(TOPIC_PACK_PATH)
    expected = {"found", "showed", "improved", "reduced",
                "demonstrated", "established", "proved"}
    assert pack.forbidden_verbs_for_protocol_role == expected
