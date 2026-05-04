"""Unit tests for the OpenCitations + openFDA enrichment clients
added 2026-05-04 (second wave of enrichment-layer adapters).

Same fail-soft contract as the main source layer: every failure mode
returns an empty result (not an exception). Network IO mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from agent.enrichment.opencitations import (
    OpenCitationsMetaClient,
    OpenCitationsRecord,
)
from agent.enrichment.openfda import (
    AdverseReactionCount,
    AdverseReport,
    OpenFDAClient,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


# ---------- OpenCitations Meta -------------------------------------

def test_opencitations_parses_id_field():
    """Real shape: 'doi:X omid:br/Y' space-separated tokens."""
    record = {
        "id": "doi:10.1093/ageing/afaf271 omid:br/06702489437",
        "title": "Test Title",
        "author": "Smith, A [orcid:0000-0001]; Jones, B",
        "pub_date": "2025-08-29",
        "venue": "Age and Ageing [issn:0002-0729]",
        "publisher": "Oxford UP",
        "type": "journal article",
    }
    rec = OpenCitationsMetaClient._parse(record)
    assert rec is not None
    assert rec.doi == "10.1093/ageing/afaf271"
    assert rec.omid == "br/06702489437"
    assert rec.title == "Test Title"
    assert rec.authors == ("Smith, A", "Jones, B")
    assert rec.pub_date == "2025-08-29"
    assert "Age and Ageing" in rec.venue
    assert rec.work_type == "journal article"


def test_opencitations_drops_record_without_doi():
    """Records lacking a doi: token in the id field → None."""
    record = {"id": "omid:br/123 pmid:456", "title": "X"}
    assert OpenCitationsMetaClient._parse(record) is None


def test_opencitations_drops_empty_id_field():
    assert OpenCitationsMetaClient._parse({"title": "X"}) is None


def test_opencitations_drugconcept_immutable():
    """Frozen dataclass — assignment raises FrozenInstanceError."""
    from dataclasses import FrozenInstanceError
    rec = OpenCitationsRecord(doi="x", omid="y", title="T")
    with pytest.raises(FrozenInstanceError):
        rec.doi = "z"  # type: ignore[misc]


def test_opencitations_handles_missing_authors():
    """No author field → empty tuple, not crash."""
    record = {"id": "doi:10.1/x", "title": "T"}
    rec = OpenCitationsMetaClient._parse(record)
    assert rec is not None
    assert rec.authors == ()


@pytest.mark.asyncio
async def test_opencitations_fail_soft_on_429():
    cli = OpenCitationsMetaClient()
    fake = AsyncMock()
    fake.get.return_value = _FakeResponse(429)
    out = await cli.fetch(fake, ["10.1/x"])
    assert out == {}


@pytest.mark.asyncio
async def test_opencitations_fail_soft_on_network_error():
    cli = OpenCitationsMetaClient()
    fake = AsyncMock()
    fake.get.side_effect = httpx.ConnectError("boom")
    out = await cli.fetch(fake, ["10.1/x"])
    assert out == {}


@pytest.mark.asyncio
async def test_opencitations_dedupes_input_dois():
    """Same DOI twice → one batch, one entry."""
    cli = OpenCitationsMetaClient()
    fake = AsyncMock()
    fake.get.return_value = _FakeResponse(
        200,
        json_data=[{
            "id": "doi:10.1/x omid:br/1",
            "title": "T",
            "author": "",
        }],
    )
    out = await cli.fetch(fake, ["10.1/X", "10.1/x", "10.1/x"])  # case + dup
    assert len(out) == 1
    assert "10.1/x" in out
    # Only one HTTP call despite 3 inputs (after dedup)
    assert fake.get.call_count == 1


# ---------- openFDA -------------------------------------------------

def test_openfda_parses_adverse_report():
    """Realistic FAERS record shape → AdverseReport."""
    record = {
        "receivedate": "20251231",
        "serious": "1",
        "primarysource": {
            "reportercountry": "US", "qualification": "1",
        },
        "patient": {
            "reaction": [
                {"reactionmeddrapt": "Tooth abscess",
                 "reactionoutcome": "1"},
                {"reactionmeddrapt": "Toothache"},
            ],
        },
    }
    r = OpenFDAClient._parse_report(record)
    assert r.receive_date == "20251231"
    assert r.serious is True
    assert r.primary_source_country == "US"
    assert r.reactions == ("Tooth abscess", "Toothache")


def test_openfda_serious_false_when_zero():
    """serious=0 → False."""
    record = {"serious": 0, "primarysource": {}, "patient": {}}
    r = OpenFDAClient._parse_report(record)
    assert r.serious is False


def test_openfda_serious_handles_string():
    """FAERS sends serious as string '1' or '2' — both truthy."""
    record = {"serious": "2", "primarysource": {}, "patient": {}}
    r = OpenFDAClient._parse_report(record)
    assert r.serious is True


def test_openfda_dataclasses_immutable():
    from dataclasses import FrozenInstanceError
    r = AdverseReport(receive_date="x", serious=True, primary_source_country="x")
    rxn = AdverseReactionCount(reaction="X", count=1)
    with pytest.raises(FrozenInstanceError):
        r.serious = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        rxn.count = 99  # type: ignore[misc]


@pytest.mark.asyncio
async def test_openfda_top_reactions_fail_soft_on_429():
    cli = OpenFDAClient()
    fake = AsyncMock()
    fake.get.return_value = _FakeResponse(429)
    out = await cli.top_reactions(fake, "aspirin", limit=5)
    assert out == []


@pytest.mark.asyncio
async def test_openfda_top_reactions_fail_soft_on_5xx():
    cli = OpenFDAClient()
    fake = AsyncMock()
    fake.get.return_value = _FakeResponse(503)
    out = await cli.top_reactions(fake, "aspirin", limit=5)
    assert out == []


@pytest.mark.asyncio
async def test_openfda_top_reactions_fail_soft_on_network_error():
    cli = OpenFDAClient()
    fake = AsyncMock()
    fake.get.side_effect = httpx.ReadTimeout("slow")
    out = await cli.top_reactions(fake, "aspirin", limit=5)
    assert out == []


@pytest.mark.asyncio
async def test_openfda_top_reactions_drops_malformed_count_records():
    """Records missing term or count are skipped, not crash."""
    cli = OpenFDAClient()
    fake = AsyncMock()
    fake.get.return_value = _FakeResponse(
        200,
        json_data={
            "results": [
                {"term": "FATIGUE", "count": 100},   # OK
                {"term": "", "count": 50},            # empty term → skip
                {"term": "NAUSEA"},                   # no count → skip
                {"term": "X", "count": "not_a_number"},  # bad cast → skip
                {"term": "DIZZINESS", "count": 25},  # OK
            ],
        },
    )
    out = await cli.top_reactions(fake, "aspirin", limit=10)
    assert len(out) == 2
    assert out[0].reaction == "FATIGUE"
    assert out[1].reaction == "DIZZINESS"
