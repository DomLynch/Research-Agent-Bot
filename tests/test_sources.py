"""Adapter parser regression tests against real captured fixtures.

Asserts that every adapter's saved fixture is a non-empty list of well-shaped
RawHit objects. If a parser regresses (silently drops fields, breaks on a
shape change), this fails before we ever hit the network in CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.types import RawHit

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOPICS = ["rapamycin", "metformin", "senolytics", "semaglutide_weight", "vitamin_d_mortality"]
SOURCES = ["pubmed", "openalex", "europepmc", "clinicaltrials"]


def _load(topic: str, source: str) -> list[RawHit]:
    path = FIXTURES / topic / f"{source}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [RawHit(**entry) for entry in raw]


@pytest.mark.parametrize("topic", TOPICS)
@pytest.mark.parametrize("source", SOURCES)
def test_fixture_loads_as_raw_hits(topic: str, source: str):
    """Every captured fixture must round-trip into typed RawHit objects with
    non-empty title and abstract. Per-adapter identifier guarantees live in
    the dedicated tests below."""
    hits = _load(topic, source)
    assert hits, f"{topic}/{source}.json captured 0 hits — capture probably failed"
    for hit in hits:
        assert hit.source == source
        assert hit.title.strip(), f"empty title in {topic}/{source}"
        assert hit.abstract.strip(), f"empty abstract in {topic}/{source}"


@pytest.mark.parametrize("topic", TOPICS)
def test_clinicaltrials_carries_has_results_signal(topic: str):
    """CT.gov adapter MUST flow has_results into raw — bundle.py reads it
    to assign role={published_results, registered_pending}."""
    hits = _load(topic, "clinicaltrials")
    for hit in hits:
        assert "has_results" in hit.raw, (
            f"{topic}/clinicaltrials: ref to NCT {hit.nct} missing has_results signal"
        )
        assert isinstance(hit.raw["has_results"], bool)


@pytest.mark.parametrize("topic", TOPICS)
def test_pubmed_provides_pmid(topic: str):
    """Every PubMed hit must carry a PMID; bundle dedup keys on it."""
    for hit in _load(topic, "pubmed"):
        assert hit.pmid and hit.pmid.isdigit(), (
            f"{topic}/pubmed: hit missing or malformed PMID: {hit.pmid!r}"
        )


@pytest.mark.parametrize("topic", TOPICS)
def test_openalex_doi_is_normalized(topic: str):
    """OpenAlex DOIs must be lowercase, no protocol prefix."""
    for hit in _load(topic, "openalex"):
        if hit.doi is None:
            continue
        assert hit.doi == hit.doi.lower()
        assert not hit.doi.startswith(("https://", "http://", "doi:"))


@pytest.mark.parametrize("topic", TOPICS)
def test_europepmc_provides_abstract(topic: str):
    """resultType=core MUST yield abstractText; resultType=lite would silently
    drop everything (the bug we shipped on first capture)."""
    hits = _load(topic, "europepmc")
    assert hits, f"{topic}/europepmc empty — resultType regression?"
