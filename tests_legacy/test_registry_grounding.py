"""Registry-vs-results grounding tests.

Each test is xfail — pending GPT Tier 1.6 Cycle 1 which will ship the
registry-vs-results distinction in drafter.py / planner.py.
"""

import pytest

REASON = "pending GPT Tier 1.6 Cycle 1: registry-vs-results distinction"


@pytest.mark.xfail(reason=REASON, strict=False)
def test_registry_only_entry_does_not_claim_outcomes() -> None:
    pytest.fail("placeholder — implement when GPT ships Cycle 1")


@pytest.mark.xfail(reason=REASON, strict=False)
def test_results_bearing_entry_receives_numeric_citation() -> None:
    pytest.fail("placeholder — implement when GPT ships Cycle 1")


@pytest.mark.xfail(reason=REASON, strict=False)
def test_all_registrations_bundle_triggers_design_only_language() -> None:
    pytest.fail("placeholder — implement when GPT ships Cycle 1")


@pytest.mark.xfail(reason=REASON, strict=False)
def test_mixed_bundle_distinguishes_published_from_registered() -> None:
    pytest.fail("placeholder — implement when GPT ships Cycle 1")


@pytest.mark.xfail(reason=REASON, strict=False)
def test_drafter_prompt_splits_published_and_registered() -> None:
    pytest.fail("placeholder — implement when GPT ships Cycle 1")
