"""Day 2.5 — End-to-end metformin retrieval smoke.

Replays the captured metformin fixtures (real PubMed / OpenAlex / EuropePMC /
ClinicalTrials.gov responses, captured during V1.1) through the full Day 2
pipeline:

    raw_hits → retrieve.normalize_and_dedup → bundle(topic_pack=metformin_pack)

Closes the last Day 2 done-when criterion (DESIGN-001 §19):
- ≥12 sources retrieved after dedup
- Cards classify correctly (MASTERS NCT02308228 → published_results / rct / A1)
- Topic-pack registry override is wired through bundle() and consulted
- Performance baseline recorded as test telemetry (v4 Rule 16 — captured for
  Day 3+ comparison)

Why fixture-replay rather than real APIs in pytest:
- Determinism: real API responses change as papers retract / re-classify
- CI-friendliness: no network dependency, sub-second runtime
- The fixtures ARE real captured responses — same wire format the live APIs
  produce, so the pipeline path is identical. The only difference is the
  transport.

For a fresh real-API smoke, run
`scripts/e2e_metformin_proof_001.py --live --retrieve-only`
deliverable; opt-in network call) which captures a new baseline and
optionally refreshes the fixtures.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import pytest

from agent.evidence_cards import bundle
from agent.retrieve import normalize_and_dedup
from agent.topic_pack import TopicPack, load_topic_pack
from agent.types import EvidenceItem, RawHit

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "metformin"
TOPIC_PACK_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"

# Adapter priority order — preserved from V1.1; PMIDs survive cross-source dedup
# only if PubMed comes first.
ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(TOPIC_PACK_PATH)


@pytest.fixture(scope="module")
def metformin_raw_hits() -> list[RawHit]:
    """Load all captured-fixture raw hits in adapter priority order."""
    hits: list[RawHit] = []
    for adapter_name in ADAPTER_PRIORITY:
        path = FIXTURES_ROOT / f"{adapter_name}.json"
        if not path.exists():
            pytest.fail(f"missing metformin fixture: {path}")
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    return hits


@pytest.fixture(scope="module")
def metformin_e2e(
    metformin_raw_hits: list[RawHit],
    metformin_pack: TopicPack,
) -> dict:
    """Run the full Day 2 pipeline once, return everything for inspection."""
    t0 = time.perf_counter()
    sources, abstracts, raw_signals = normalize_and_dedup(metformin_raw_hits)
    t_normalize = time.perf_counter() - t0

    t1 = time.perf_counter()
    items = bundle(
        sources, abstracts,
        topic="metformin",
        domain="longevity older adults",
        raw_signals=raw_signals,
        topic_pack=metformin_pack,
    )
    t_bundle = time.perf_counter() - t1

    return {
        "sources": sources,
        "abstracts": abstracts,
        "raw_signals": raw_signals,
        "items": items,
        "n_raw_hits": len(metformin_raw_hits),
        "t_normalize_sec": t_normalize,
        "t_bundle_sec": t_bundle,
    }


# --- Day 2.5 done-when criteria ------------------------------------------


def test_at_least_twelve_sources_retrieved(metformin_e2e: dict) -> None:
    """DESIGN-001 §19 Day 2 done-when criterion #1: ≥12 sources after dedup."""
    n_sources = len(metformin_e2e["sources"])
    assert n_sources >= 12, (
        f"only {n_sources} sources after dedup; need ≥12 for Day 2 ship. "
        f"Raw hits: {metformin_e2e['n_raw_hits']} — dedup may be too aggressive."
    )


def test_canonical_nct_masters_surfaces() -> None:
    """The MASTERS trial (NCT02308228, Walton 2019) is the canonical
    deterministic-result test. It must appear in the captured corpus —
    via OpenAlex with the NCT in its abstract."""
    raw_path = FIXTURES_ROOT / "openalex.json"
    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
    has_masters = any(
        "NCT02308228" in (h.get("abstract") or "")
        for h in raw_data
    )
    assert has_masters, "MASTERS NCT02308228 not surfaced in OpenAlex fixture"


def test_masters_classified_as_published_results_rct(
    metformin_e2e: dict,
) -> None:
    """MASTERS in the bundled output: role=published_results, design=rct.
    Triggered via NCT-in-abstract dedup (OpenAlex paper merges with the
    CT.gov registry entry that has has_results=True).
    """
    items: list[EvidenceItem] = metformin_e2e["items"]
    masters_items = [
        it for it in items
        if it.source.nct == "NCT02308228"
        or "NCT02308228" in (it.abstract or "")
    ]
    assert masters_items, "MASTERS not in bundled items"
    masters = masters_items[0]
    assert masters.role == "published_results", (
        f"MASTERS role={masters.role!r}; expected published_results"
    )
    assert masters.design == "rct", f"MASTERS design={masters.design!r}; expected rct"


def test_topic_pack_override_wired_through_bundle(
    metformin_e2e: dict,
    metformin_pack: TopicPack,
) -> None:
    """Verify the topic_pack kwarg is being honored: any fixture source
    whose NCT has a registry override should carry the overridden role,
    not whatever the abstract classifier would assign.

    Among the 4 canonical NCTs in metformin_pack, MASTERS (NCT02308228) is
    the one most likely to appear in the captured corpus. Test that its
    role matches the override (published_results / rct / A1)."""
    items: list[EvidenceItem] = metformin_e2e["items"]
    override = metformin_pack.lookup_role_override("NCT02308228")
    assert override is not None
    masters_items = [
        it for it in items
        if it.source.nct == "NCT02308228"
        or "NCT02308228" in (it.abstract or "")
    ]
    if masters_items:
        masters = masters_items[0]
        assert masters.role == override.role
        assert masters.design == override.design
        assert masters.tier == override.tier


def test_role_distribution_includes_real_results(
    metformin_e2e: dict,
) -> None:
    """The metformin corpus should yield a mix of roles. At minimum:
    >=1 published_results (real RCT), and >=1 registered_pending (CT.gov
    with no results yet) — confirming the classifier and the CT.gov
    has_results signal both function in the E2E pipeline."""
    items: list[EvidenceItem] = metformin_e2e["items"]
    role_counts = Counter(it.role for it in items)
    assert role_counts["published_results"] >= 1, (
        f"no published_results in bundle. roles: {role_counts}"
    )
    assert role_counts["registered_pending"] >= 1, (
        f"no registered_pending in bundle. roles: {role_counts}"
    )


def test_direct_evidence_present(metformin_e2e: dict) -> None:
    """At least one item must be `direct=True` — the topic-anchor +
    population-fit gate must be passing for the canonical metformin
    aging RCTs."""
    items: list[EvidenceItem] = metformin_e2e["items"]
    direct = [it for it in items if it.direct]
    assert direct, (
        "no direct=True items in bundle. The topic-anchor or aging-relevance "
        "gate may be over-rejecting metformin papers."
    )


# --- Performance baseline (v4 Rule 16) -----------------------------------


def test_pipeline_performance_baseline(metformin_e2e: dict) -> None:
    """Record performance baseline as a test telemetry assertion. Not a
    blocking gate — values come from fixture-replay so they're CPU-bound
    only. Real-API runtime will dominate when network is involved.

    Captured baseline (fixture-replay only — no network):
        normalize_and_dedup: < 0.05 s on 40 raw hits
        bundle:              < 0.10 s on 12+ sources
    These bounds are intentionally generous. If they trip, something has
    regressed in the deterministic pipeline (regex, dict lookup, etc.).
    """
    t_norm = metformin_e2e["t_normalize_sec"]
    t_bundle = metformin_e2e["t_bundle_sec"]
    assert t_norm < 0.5, f"normalize_and_dedup took {t_norm:.3f}s; baseline < 0.5s"
    assert t_bundle < 1.0, f"bundle took {t_bundle:.3f}s; baseline < 1.0s"


# --- Telemetry summary ---------------------------------------------------


def test_e2e_summary(metformin_e2e: dict, metformin_pack: TopicPack) -> None:
    """Pretty-print E2E summary — running pytest -s shows the telemetry.
    The body of this test is sanity assertions; the print is the
    Day 2.5 deliverable as a snapshot of what the pipeline produced."""
    items: list[EvidenceItem] = metformin_e2e["items"]
    role_counts = Counter(it.role for it in items)
    tier_counts = Counter(it.tier for it in items)
    direct_count = sum(1 for it in items if it.direct)
    strict_count = sum(1 for it in items if it.strict)

    print()
    print("=" * 60)
    print("Day 2.5 — Metformin E2E Pipeline Summary")
    print("=" * 60)
    print(f"raw hits ingested:       {metformin_e2e['n_raw_hits']}")
    print(f"deduped sources:         {len(metformin_e2e['sources'])}")
    print(f"normalize_and_dedup:     {metformin_e2e['t_normalize_sec']*1000:.1f} ms")
    print(f"bundle (with topic_pack): {metformin_e2e['t_bundle_sec']*1000:.1f} ms")
    print(f"role distribution:       {dict(role_counts)}")
    print(f"tier distribution:       {dict(tier_counts)}")
    print(f"direct=True:             {direct_count}")
    print(f"strict=True:             {strict_count}")
    override = metformin_pack.lookup_role_override("NCT02308228")
    assert override is not None
    print(f"topic_pack override hits: NCT02308228 (MASTERS) — pinned to {override.role}")
    print("=" * 60)

    assert len(items) == len(metformin_e2e["sources"])
    assert direct_count <= len(items)
