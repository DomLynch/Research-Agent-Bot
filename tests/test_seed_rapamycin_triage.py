"""Proof 002 Workstream C — rapamycin corpus triage smoke tests.

The triage step is pure-Python (no LLM cost) and reads from the
prior pipeline's evidence_cards.json (67 cards). Tests cover the
selection contract: pinning, off-topic exclusion, scoring rank.

Note: the seed cards file lives under runs/ which is gitignored,
so it's local-only on the developer's MacBook. CI/VPS won't have
the file → the data-dependent tests skip gracefully. The pure
function tests (score monotonicity) always run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_rapamycin_corpus as seed  # noqa: E402


# Module-level skip marker for tests that require the local seed pool.
_SEED_AVAILABLE = seed.SEED_CARDS.exists()
_skip_no_seed = pytest.mark.skipif(
    not _SEED_AVAILABLE,
    reason=(
        f"seed cards not found at {seed.SEED_CARDS} — runs/ is "
        "gitignored, this test runs only on dev machines with the "
        "prior pipeline's local artifacts"
    ),
)


@_skip_no_seed
def test_triage_excludes_off_topic_ncts() -> None:
    """Cards on EXCLUDE_NCTS list never appear in the selection,
    regardless of tier — alpha-ketoglutarate trial isn't a rapamycin
    paper even if our retrieval grabbed it."""
    result = seed.triage(top_n=15)
    selected_ncts = {
        p["source"].get("nct") for p in result["selected"]
    }
    for excluded in seed.EXCLUDE_NCTS:
        assert excluded not in selected_ncts, (
            f"Triage selected EXCLUDE_NCTS entry {excluded}"
        )


@_skip_no_seed
def test_triage_filters_off_topic_abstracts() -> None:
    """Cards whose abstract+title don't mention rapamycin/sirolimus
    are excluded. The prior pipeline pulled some mTOR-adjacent
    papers; this filter keeps the corpus topic-pure."""
    result = seed.triage(top_n=15)
    assert result["n_off_topic"] > 0, (
        "expected SOME off-topic exclusions from the 67 seed cards"
    )
    for p in result["selected"]:
        blob = (
            p["abstract"].lower() + " "
            + (p["source"].get("title") or "").lower()
        )
        assert any(kw in blob for kw in seed.TOPIC_KEYWORDS), (
            f"Selected paper {p['paper_id']} has no rapamycin/"
            f"sirolimus keyword in abstract+title"
        )


@_skip_no_seed
def test_triage_pins_canonical_ncts_when_present() -> None:
    """Pinned NCTs are guaranteed slots — the moat per
    topic_packs/rapamycin.toml. They go in even if their score is
    low (e.g. registered_pending RCTs without published results)."""
    result = seed.triage(top_n=15)
    pinned_in_selection = {
        p["source"].get("nct")
        for p in result["selected"]
        if p["pinned"]
    }
    # At least 3 pinned NCTs should make it (the seed pool has
    # PEARL/RAP-CAD/RAP-AD/VIAging/etc.)
    assert len(pinned_in_selection) >= 3, (
        f"Triage pinned only {len(pinned_in_selection)} canonical "
        "NCTs — expected ≥3"
    )


@_skip_no_seed
def test_triage_returns_target_count_or_less() -> None:
    """top_n is a ceiling; selection ≤ top_n. If filtered candidate
    pool is smaller than top_n, return the full pool."""
    result = seed.triage(top_n=15)
    assert result["n_selected"] <= 15
    assert result["n_selected"] <= result["n_after_filter"]


@_skip_no_seed
def test_triage_writes_output_json() -> None:
    """Triage writes _triage.json to the corpus directory for
    downstream --extract to consume."""
    result = seed.triage(top_n=15)
    out_path = seed.OUT_DIR / "_triage.json"
    assert out_path.exists(), f"Triage did not write {out_path}"
    # Round-trip: the file's JSON should match the returned dict
    import json as _json
    on_disk = _json.loads(out_path.read_text())
    assert on_disk["n_selected"] == result["n_selected"]
    assert on_disk["topic"] == "rapamycin"


def test_triage_score_function_monotonic() -> None:
    """A1+direct=True+published_results+rct must score higher than
    C+mechanistic+direct=False (sanity check on weights)."""
    a1_card = {
        "tier": "A1", "direct": True, "role": "published_results",
        "design": "rct", "source": {"year": 2025},
    }
    c_card = {
        "tier": "C", "direct": False, "role": "mechanistic",
        "design": "mechanistic", "source": {"year": 2024},
    }
    assert seed._score(a1_card) > seed._score(c_card)


@_skip_no_seed
def test_triage_pearl_bubbles_to_top() -> None:
    """PEARL is the load-bearing human RCT for rapamycin/aging.
    Even without canonical-NCT pinning (the seed card lacks an NCT
    field), it should bubble to the top of the unpinned ranking."""
    result = seed.triage(top_n=15)
    pearl_in_selection = any(
        "pearl" in (p["source"].get("title") or "").lower()
        for p in result["selected"]
    )
    assert pearl_in_selection, (
        "PEARL trial paper missing from triage selection"
    )


@_skip_no_seed
def test_triage_pinned_ncts_appear_first() -> None:
    """Pinned cards come before unpinned in the selection list — so
    --extract processes the canonical trials first and burns its LLM
    budget on the most important papers."""
    result = seed.triage(top_n=15)
    pin_states = [p["pinned"] for p in result["selected"]]
    if True in pin_states and False in pin_states:
        last_true = max(
            i for i, v in enumerate(pin_states) if v
        )
        first_false = min(
            i for i, v in enumerate(pin_states) if not v
        )
        assert last_true < first_false, (
            "Pinned cards must precede unpinned in selection"
        )
