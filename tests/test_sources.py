"""Adapter parser regression tests against real captured fixtures.

Asserts that every adapter's saved fixture is a non-empty list of well-shaped
RawHit objects. If a parser regresses (silently drops fields, breaks on a
shape change), this fails before we ever hit the network in CI.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.sources.pubmed import pmid_audit_is_current, pmid_rows_fingerprint, verify_pmid_rows
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


def test_pubmed_identity_verification_rejects_wrong_pmid() -> None:
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article>
    <ArticleTitle>Correct trial title: A Randomized Clinical Trial</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList>
    <ArticleId IdType="doi">10.1000/correct</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId>
    </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

    class Response:
        text = xml

        @staticmethod
        def raise_for_status() -> None:
            return None

    passed = verify_pmid_rows([{"receipt_id": "PMC123_source", "source_pmid": "12345678",
                                "source_title": "Correct trial title", "source_doi": "10.1000/correct"}],
                              get=lambda *_a, **_k: Response())
    failed = verify_pmid_rows([{"receipt_id": "PMC999_source", "source_pmid": "12345678",
                                "source_title": "Different paper", "source_doi": "10.1000/wrong"}],
                              get=lambda *_a, **_k: Response())
    contradictory = verify_pmid_rows([{"receipt_id": "PMC999_source", "source_pmid": "12345678",
                                       "source_title": "Correct trial title", "source_doi": "10.1000/wrong"}],
                                     get=lambda *_a, **_k: Response())

    assert passed["passed"] is True and passed["verified"] == 1
    assert failed["passed"] is False and failed["status"] == "identity_mismatch"
    assert contradictory["passed"] is False


@pytest.mark.parametrize("row, mismatch", [
    ({"source_pmid": "12345678", "pmid": "99999999"}, "conflicting_pmid"),
    ({"source_pmid": "12345678", "source_doi": "10.1000/a", "doi": "10.1000/b"},
     "conflicting_doi"),
    ({"source_pmid": "12345678", "source_pmcid": "PMC123", "receipt_id": "PMC999_row"},
     "conflicting_pmcid"),
])
def test_pubmed_identity_verification_rejects_conflicting_aliases(
    row: dict[str, str], mismatch: str,
) -> None:
    def unexpected_get(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("conflicting aliases must fail before the PubMed request")

    audit = verify_pmid_rows([row], get=unexpected_get)

    assert audit["passed"] is False and audit["status"] == "identity_mismatch"
    assert audit["issues"][0]["mismatch"] == mismatch


def test_pubmed_audit_cache_is_bound_to_inputs_and_throttles_outages() -> None:
    rows = [{"source_pmid": "12345678", "source_title": "Trial A"}]
    current = {"provider": "ncbi_pubmed", "input_fingerprint": pmid_rows_fingerprint(rows),
               "status": "verified", "passed": True,
               "entries": 1, "declared": 1, "verified": 1, "without_pmid": 0, "issues": []}
    outage = {**current, "status": "provider_unavailable", "passed": False,
              "checked_at": time.time()}

    assert pmid_audit_is_current(current, rows) is True
    assert pmid_audit_is_current(current, rows + [{"source_pmid": "2"}]) is False
    assert pmid_audit_is_current({**current, "declared": 0, "verified": 0,
                                  "without_pmid": 1}, rows) is False
    assert pmid_audit_is_current(outage, rows) is True
    assert pmid_audit_is_current({**outage, "checked_at": "bad"}, rows) is False
    assert pmid_audit_is_current({"input_fingerprint": current["input_fingerprint"],
                                  "status": "verified"}, rows) is False
    malformed = dict(current)
    malformed.pop("issues")
    assert pmid_audit_is_current(malformed, rows) is False
    conflicting_rows = [{"source_pmid": "12345678", "pmid": "99999999"}]
    conflicting_audit = {**current, "input_fingerprint": pmid_rows_fingerprint(conflicting_rows)}
    assert pmid_audit_is_current(conflicting_audit, conflicting_rows) is False
    assert pmid_audit_is_current({**current, "provider": "fake"}, rows) is False


@pytest.mark.parametrize("source_title, actual_title", [
    ("Trial", "Trial: unrelated oncology study"),
    ("Randomized clinical trial", "Randomized clinical trial of an unrelated cancer therapy"),
])
def test_pubmed_identity_verification_rejects_under_specified_title_only(
    source_title: str, actual_title: str,
) -> None:
    xml = ("<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article>"
           f"<ArticleTitle>{actual_title}</ArticleTitle></Article></MedlineCitation>"
           "<PubmedData><ArticleIdList/></PubmedData></PubmedArticle></PubmedArticleSet>")

    class Response:
        text = xml

        @staticmethod
        def raise_for_status() -> None:
            return None

    audit = verify_pmid_rows([{"source_pmid": "12345678", "source_title": source_title}],
                             get=lambda *_a, **_k: Response())

    assert audit["passed"] is False
    assert audit["issues"][0]["mismatch"] == "title_under_specified"


@pytest.mark.parametrize("xml", [
    "<eFetchResult><ERROR>API rate limit exceeded</ERROR></eFetchResult>",
    "<ERROR>API rate limit exceeded</ERROR>",
])
def test_pubmed_http_200_error_payload_is_retryable(xml: str) -> None:
    class Response:
        text = xml

        @staticmethod
        def raise_for_status() -> None:
            return None

    audit = verify_pmid_rows([{"source_pmid": "12345678", "source_title": "Trial"}],
                             get=lambda *_a, **_k: Response())
    assert audit["status"] == "provider_unavailable" and audit["passed"] is False


def test_pubmed_partial_http_200_response_is_retryable() -> None:
    class Response:
        text = "<PubmedArticleSet/>"

        @staticmethod
        def raise_for_status() -> None:
            return None

    rows = [{"source_pmid": "12345678", "source_title": "Distinct intervention outcome trial"}]
    audit = verify_pmid_rows(rows, get=lambda *_a, **_k: Response())

    assert audit["status"] == "provider_unavailable" and audit["passed"] is False
    assert audit["error"] == "partial_provider_response"
    assert pmid_audit_is_current(audit, rows) is True
    assert pmid_audit_is_current({**audit, "checked_at": 0}, rows) is False
